"""
AutoChaoxingCLI - 学习次数刷取功能模块

超星"章节学习次数"由服务端在访问章节页面时下发 setlog 打点脚本记录。
本模块按真实前端行为复现计次流程：
1. 访问章节 studentstudyAjax 页面获取 HTML
2. 解析并执行其中的 setlog 脚本（真正计次的接口）
3. 发送 detect.chaoxing.com monitor 心跳包（佐证真人访问）
4. 停留一段时间后再次发送心跳（模拟前端 30 秒定时器）
5. 循环切换章节直到达到目标次数
"""

import random
import re
import time
from urllib.parse import urlencode

from loguru import logger

from core import runtime
from core.config import Config
from core.exceptions import AntispiderException
from core.request_client import get as doGet, get_session

# 连续失败上限，超过则终止避免死循环
MAX_CONSECUTIVE_FAILURES = 10


def _get_fid() -> str:
    """从Session Cookie中读取fid，monitor心跳需要该参数"""
    try:
        for cookie in get_session().cookies:
            if cookie.name == "fid" and cookie.value:
                return cookie.value
    except Exception:
        pass
    return ""


def _send_monitor_heartbeat(user, course, point, fid: str):
    """发送章节监控心跳包，模拟真实浏览器 JSONP 打点"""
    now = str(int(time.time() * 1000))
    callback = "jsonp" + str(random.randint(10 ** 20, 10 ** 21 - 1))
    params = {
        "version": now,
        "refer": "http://i.mooc.chaoxing.com",
        "from": "",
        "fid": fid,
        "jsoncallback": callback,
        "t": now,
    }
    referer_url = (
        f"https://mooc1.chaoxing.com/mycourse/studentstudy?"
        f"chapterId={point.get('knowledge_id')}&courseId={course.course_id}"
        f"&clazzid={course.class_id}&cpi={course.cpi}&mooc2=1"
    )
    headers = dict(user.headers or {})
    headers["Referer"] = referer_url
    try:
        doGet(url="https://detect.chaoxing.com/api/monitor?" + urlencode(params), headers=headers)
    except Exception as e:
        logger.debug(f"monitor心跳发送失败(非关键): {e}")


def _increase_once(user, course, point, fid: str, dwell: float) -> bool:
    """对单个章节执行一次学习次数增加，返回是否成功"""
    chapter_id = point.get("knowledge_id")
    if not chapter_id:
        return False

    params = {
        "courseId": course.course_id,
        "clazzid": course.class_id,
        "chapterId": chapter_id,
        "cpi": course.cpi,
        "verificationcode": "",
        "mooc2": 1,
        "microTopicId": 0,
        "editorPreview": 0,
    }
    try:
        html = doGet(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax?" + urlencode(params),
            headers=user.headers,
        )
    except AntispiderException:
        # 冷却期由RequestClient在下次请求时自动等待
        logger.warning(f"章节'{point.get('name')}'访问被拦截，等待冷却后重试")
        return False

    if not html:
        return False

    # 第1步：提取并执行 setlog 计次脚本
    match = re.search(
        r'<script[^>]+src="(https://fystat-ans\.chaoxing\.com/log/setlog[^"]+)"',
        html,
    )
    if match:
        try:
            doGet(url=match.group(1), headers=user.headers)
        except Exception as e:
            logger.debug(f"setlog计次请求失败(非关键): {e}")
    else:
        logger.debug(f"章节'{point.get('name')}'响应中未找到setlog脚本")

    # 第2步：立即发送心跳
    _send_monitor_heartbeat(user, course, point, fid)

    # 第3步：停留模拟前端 setInterval 间隔（可暂停、可停止）
    if dwell > 0:
        runtime.sleep(dwell)

    # 第4步：再次发送心跳
    _send_monitor_heartbeat(user, course, point, fid)
    return True


def _run_legacy(user, course, log, times: int, delay: float) -> int:
    """回退方案：使用课程学习记录链接直接刷取"""
    _url = course.get_url_log()
    if not _url:
        log.error("未获取到学习记录URL，已取消刷取")
        return 0
    added = 0
    for i in range(1, times + 1):
        try:
            _rsp = doGet(url=_url, headers=user.headers)
            logger.debug(_rsp)
            added += 1
            log.info(f"[刷取次数 {i}/{times}]")
        except AntispiderException:
            log.warning("刷取被拦截，等待冷却后继续")
            continue
        if delay > 0:
            runtime.sleep(delay)
    return added


def run(user, course, log, ui=None, times: int = 0, params: dict = None):
    """学习次数刷取功能入口（WebUI 下由任务快照传参，不读取终端输入）"""
    if not course:
        log.error("未指定课程，无法刷取学习次数")
        return

    # 显示当前学习次数
    current_count = course.get_count_log()
    log.info(f"课程'{course.course_name}'学习次数共{current_count}")

    if times <= 0:
        log.warning("刷取次数必须大于0")
        return

    params = params or {}
    delay = float(params.get("request_delay", Config.get("advanced.request_delay", 30)))
    dwell = float(params.get("dwell", Config.get("advanced.learn_count_dwell", 30)))

    # 获取章节列表用于循环计次
    if not course.chapter_list:
        try:
            course.get_chapter()
        except Exception as e:
            log.error(f"获取章节列表失败: {e}")

    points = []
    for catalog in course.chapter_list or []:
        for chapter in catalog.get("child_chapter", []):
            if chapter.get("available") and chapter.get("knowledge_id"):
                points.append(chapter)

    if not points:
        log.warning("未获取到可访问章节，回退到旧版学习记录链接刷取方式")
        added = _run_legacy(user, course, log, times, delay)
    else:
        added = _increase_via_chapters(user, course, log, points, times, dwell)

    # 显示刷取结果
    final_count = course.get_count_log()
    log.success(
        f"课程学习次数刷取完毕: {current_count} -> {final_count} "
        f"(增加 {final_count - current_count} 次, 本轮完成 {added} 次)"
    )
    return added


def _increase_via_chapters(user, course, log, points, times: int, dwell: float) -> int:
    """通过循环访问章节增加学习次数"""
    fid = _get_fid()
    if not fid:
        logger.debug("未从Cookie中读取到fid，monitor心跳可能无法计次")

    added = 0
    consecutive_failures = 0
    log.info(f"开始刷取学习次数，共{len(points)}个可访问章节，目标 {times} 次")

    while added < times:
        for point in points:
            runtime.checkpoint()
            if added >= times:
                break
            try:
                ok = _increase_once(user, course, point, fid, dwell)
            except AntispiderException:
                logger.warning("刷取被反爬虫拦截，等待冷却后继续")
                ok = False

            if ok:
                consecutive_failures = 0
                added += 1
                runtime.emit('work_result', '学习访问已记录', stage='progress',
                             payload={'id': 'visit:'+str(added-1), 'status': 'succeeded', 'name': point.get('name')})
                log.info(f"[刷取次数 {added}/{times}] 章节: {point.get('name')}")
            else:
                consecutive_failures += 1
                logger.warning(f"章节'{point.get('name')}'刷取失败 ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.error(f"连续失败{MAX_CONSECUTIVE_FAILURES}次，终止刷取")
                    return added

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            break

    return added
