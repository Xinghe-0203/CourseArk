"""只读自检：核对「作业/考试页面抓取 → 题目解析 → 提交报文构造」是否正常。

用途：当某个作业执行失败（例如提交返回 `code-2`、题干识别成课程标题、
题目数明显偏少）时，先在本机跑一遍这个脚本，确认解析与表单是否与浏览器一致。

安全边界：
- 默认只发送 GET 请求读取作业页面，**不会提交答案**，也不会调用 AI 或在线题库；
- 会构造一份占位答案来展示将要提交的表单字段，便于与浏览器的
  `$("#submitForm").serialize()` 对照；
- 考试默认只读取考试列表并打印将要请求的「开始考试」地址，**不会发起该请求**
  （发起即开始计时、占用考试机会）；只有显式加 `--fetch-start` 才会读取答题页；
- 不读取、不打印任何密钥（LLM api_key 置空）。

用法：
    python tools/check_work_page.py --list
    python tools/check_work_page.py --course-id 244694077
    python tools/check_work_page.py --course-id 244694077 --class-id 151670988 --cpi 518380181
    python tools/check_work_page.py --course-id 244694077 --kind exam
    python tools/check_work_page.py --course-id 244694077 --kind exam --fetch-start --limit 1
    python tools/check_work_page.py --course-id 244694077 --data-dir D:\\path\\to\\data
"""

import argparse
import json
import os
import sys
import tempfile

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (WEBUI_ROOT, CLI_COPY):
    if path not in sys.path:
        sys.path.insert(0, path)

from loguru import logger  # noqa: E402

from core import exam_form, work_form  # noqa: E402
from core.config import Config  # noqa: E402
from functions.deal_exam import DealExam  # noqa: E402
from models.user import User  # noqa: E402


def quiet_logging():
    """探针只关心结果，把 loguru 压到 WARNING 以上。"""
    logger.remove()
    logger.add(sys.stderr, level="ERROR")


class _Log:
    """只打印关键日志，避免探针输出淹没结果。"""

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            if args and name in ("warning", "error", "success"):
                print(f"[{name}] {args[0]}")
        return _noop


def default_data_dir():
    env = os.environ.get("AUTOCXWEBUI_DATA")
    if env:
        return env
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = os.path.join(appdata, "AutoCxWebUI")
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(WEBUI_ROOT, "data")


def load_accounts(data_dir):
    path = os.path.join(data_dir, "accounts.json")
    if not os.path.isfile(path):
        raise SystemExit(f"找不到账号文件：{path}（可用 --data-dir 指定数据目录）")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    items = raw.get("accounts") if isinstance(raw, dict) else raw
    return [item for item in (items or []) if item.get("username")]


def load_defaults(data_dir):
    for name in ("settings.backup.json", "settings.json"):
        path = os.path.join(data_dir, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("defaults", {})
    return {}


def build_config(data_dir, account, defaults):
    llm = dict(defaults.get("llm") or {})
    llm["api_key"] = ""  # 自检不使用 AI，也不打印密钥
    tmp_dir = tempfile.mkdtemp(prefix="check-work-")
    Config._data = Config._normalize_config({
        "account": {"phone": account["username"], "password": account.get("password", "")},
        "answer": {"mode": "manual", "no_answer_action": "skip",
                   "submit_delay": 0, "auto_submit": False},
        "llm": llm,
        "question_bank": {"enabled": False,
                          "db_path": os.path.join(tmp_dir, "qb.db"),
                          "auto_save": False},
        "advanced": {"request_delay": 0, "request_delay_jitter": 0, "max_retries": 1,
                     "retry_delay": 0, "learn_count_dwell": 0, "rotate_ua": False,
                     "log_level": "INFO", "log_file": ""},
    })


def print_courses(courses):
    for course in courses:
        print(f"  {course.course_id:<12} class={getattr(course, 'class_id', '') or '-':<10} "
              f"{course.course_name}")


def pick_course(courses, args):
    if args.course_id:
        for course in courses:
            if str(course.course_id) == str(args.course_id):
                return course
        raise SystemExit(f"账号下没有课程 {args.course_id}")
    return courses[0] if courses else None


def show_work(exam, work):
    print(f"\n=== {work.get('title')} workId={work.get('work_id')} ===")
    result = exam._fetch_independent_work_page(
        work.get("url") or "", str(work.get("work_id")), work.get("answer_id", ""))
    if not result:
        print("!! 未取到题目：页面结构可能又变了，请反馈该作业页面")
        return False
    questions, _hidden, form = result
    print(f"解析题目数: {len(questions)}")
    print(f"提交表单 found={form.get('found')} action={form.get('action')}")
    if not form.get("found"):
        print("!! 页面未找到 addStudentWork 表单，提交会走旧版兼容路径")
    unreadable = 0
    for idx, question in enumerate(questions, 1):
        if question["unreadable"]:
            unreadable += 1
        print(f"  [{idx}] {question['question_type']} id={question['question_id']} "
              f"kind={question['kind']} blank={question['blank_count']} "
              f"unreadable={question['unreadable']} opts={len(question['options'])}")
        print(f"       题干: {question['question_text'][:70]}")
        for option in question["options"][:6]:
            print(f"       - {option[:44]}")
        if question["unreadable"] and question["unreadable_reason"]:
            print(f"       ! {question['unreadable_reason']}")

    # 用占位答案检查报文结构；不会发送
    answered = []
    for question in questions:
        if question["kind"] == work_form.KIND_CHOICE and question["options"]:
            answer = "A"
        elif question["kind"] == work_form.KIND_BLANK:
            answer = "；".join(["示例"] * max(1, question["blank_count"]))
        else:
            answer = "示例答案"
        answered.append({**question, "answer": answer})
    url, body = work_form.build_submission(form, answered)
    print(f"\n提交URL: {url or '（无）'}")
    print(f"表单字段数: {len(body)}")
    for key in sorted(body):
        value = str(body[key])
        print(f"   {key} = {value[:70] + '…' if len(value) > 70 else value}")

    # 只读：提交前置校验（作业是否可提交 / 是否需要验证码）
    try:
        ready, reason = exam._check_submit_ready()
    except Exception as exc:  # 网格异常不影响结论
        ready, reason = True, f"校验请求失败：{exc}"
    print(f"\n提交前置校验: {'可提交' if ready else '不可提交'} {('· ' + reason) if reason else ''}")
    print(f"\n小结: 共 {len(questions)} 题，其中 {unreadable} 题无法识别")
    return bool(questions)


def show_exam(course, item, fetch_start=False):
    """打印一场考试的元信息与将要请求的地址；默认不发起「开始考试」请求。"""
    title = item.get("title") or "未命名考试"
    print(f"\n=== {title} examId={item.get('exam_id')} 状态={item.get('status')} ===")
    print(f"考试窗口: {item.get('start_time') or '-'} 至 {item.get('end_time') or '-'}")
    print(f"限时: {item.get('limit_time') or '未知'} 分钟 · "
          f"relationId={item.get('relation_id')} paperId={item.get('paper_id')}")

    params = {}
    try:
        params = course._get_work_enc_params() or {}
    except Exception as exc:
        print(f"!! 取课程 enc 参数失败：{exc}")
    openc = str(params.get("openc") or "")
    exam_enc = str(params.get("examEnc") or "")
    start_url = course.exam_start_url(
        course.course_id, getattr(course, "class_id", "") or "", getattr(course, "cpi", "") or "",
        openc, str(params.get("enc") or ""), item.get("paper_id") or "",
        item.get("relation_id") or "", exam_enc=exam_enc, is_retest=bool(item.get("is_retest")))
    print(f"开始考试地址（未请求）: {start_url[:150]}")

    if not fetch_start:
        print("（默认只读：不请求开始考试地址，因为它会启动计时。"
              "确需检查答题页请加 --fetch-start）")
        return True

    from core.request_client import get as http_get

    print("!! 正在请求「开始考试」地址：这会开始考试计时，请自行确认后果")
    try:
        html = http_get(start_url, headers={"Referer": "https://mooc1.chaoxing.com/exam/test"})
    except Exception as exc:
        print(f"!! 请求失败：{exc}")
        return False
    questions = exam_form.parse_questions(html)
    form = exam_form.parse_form(html)
    diag = exam_form.describe_diagnostics(html, questions, form)
    print(f"页面长度: {diag['html_length']} · 解析题目数: {len(questions)}")
    print(f"结构命中: {diag['class_hits']}")
    print(f"表单: found={diag['form_found']} action={diag['form_action']}")
    print(f"逐题模式: {diag['single_question_mode']} · 页面总题数: {diag['total_questions']}")
    if diag["submit_candidates"]:
        print("提交候选:", *[f"  - {u[:120]}" for u in diag["submit_candidates"]], sep="\n")
    for idx, question in enumerate(questions, 1):
        print(f"  [{idx}] {question['question_type']} id={question['question_id']} "
              f"opts={len(question['options'])} unreadable={question['unreadable']}")
        print(f"       题干: {question['question_text'][:70]}")
    if not questions:
        print("!! 未解析出题目：该考试可能是「一页一题」，或需要先在浏览器里点开始考试")
    return bool(questions)


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读核对作业页面解析与提交报文")
    parser.add_argument("--data-dir", default="", help="数据目录（默认桌面版 %APPDATA%\\AutoCxWebUI）")
    parser.add_argument("--account", default="", help="账号 id 或手机号，默认第一个可用账号")
    parser.add_argument("--course-id", default="", help="课程 id；留空则列出课程")
    parser.add_argument("--class-id", default="", help="班级 id，一般从课程列表自带")
    parser.add_argument("--cpi", default="", help="cpi，一般从课程列表自带")
    parser.add_argument("--limit", type=int, default=2, help="最多检查几个待处理作业/考试（默认 2）")
    parser.add_argument("--kind", choices=("work", "exam"), default="work",
                        help="检查作业（work，默认）还是考试（exam）")
    parser.add_argument("--fetch-start", action="store_true",
                        help="考试模式下允许请求「开始考试」地址（会开始计时，慎用）")
    parser.add_argument("--list", action="store_true", help="只列出账号下的课程")
    args = parser.parse_args(argv)

    quiet_logging()
    data_dir = args.data_dir or default_data_dir()
    print(f"数据目录: {data_dir}")
    accounts = load_accounts(data_dir)
    if not accounts:
        raise SystemExit("accounts.json 里没有可用账号")
    account = accounts[0]
    if args.account:
        matched = [a for a in accounts
                   if args.account in (a.get("id"), a.get("username"), a.get("label"))]
        if not matched:
            raise SystemExit(f"找不到账号 {args.account}")
        account = matched[0]
    build_config(data_dir, account, load_defaults(data_dir))

    print(f"登录账号: {account.get('label') or account.get('username')}")
    user = User(Config.get("account.phone"), Config.get("account.password"))
    courses = user.get_courses() or user.course_list
    print(f"课程数: {len(courses)}")

    if args.list or not args.course_id:
        print_courses(courses)
        if not args.course_id:
            print("\n用 --course-id 指定课程后重跑，即可检查该课程的待处理作业。")
            return 0

    course = pick_course(courses, args)
    if args.class_id:
        course.class_id = args.class_id
    if args.cpi:
        course.cpi = args.cpi
    print(f"目标课程: {course.course_name} ({course.course_id}) "
          f"class={getattr(course, 'class_id', '')} cpi={getattr(course, 'cpi', '')}")

    if args.kind == "exam":
        exams = course.get_exam_list()
        pending = [item for item in exams if item.get("valid") is not False]
        print(f"可作答考试 {len(pending)} 场: {[e.get('title') for e in pending]}")
        if not pending:
            print("没有可作答的考试，无需检查。")
            return 0
        ok = True
        for item in pending[:max(1, args.limit)]:
            ok = show_exam(course, item, fetch_start=args.fetch_start) and ok
        return 0 if ok else 1

    works = course.get_work_list()
    pending = [work for work in works if work.get("valid") is not False]
    print(f"待处理作业 {len(pending)} 个: {[w.get('title') for w in pending]}")
    if not pending:
        print("没有待处理作业，无需检查。")
        return 0

    exam = DealExam(user, course, _Log())
    ok = True
    for work in pending[:max(1, args.limit)]:
        ok = show_work(exam, work) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
