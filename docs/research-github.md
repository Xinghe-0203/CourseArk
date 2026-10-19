# 学习通「独立作业」提交失败调研（公开实现对照）

> 调研方式：只读阅读本仓库代码 + `scratch/real-page/` 本机抓包 + GitHub 公开源码（`gh api` / `gh search code`）。
> 结论分级：**已由源码/抓包证实** / **本地推断** / **未验证**。所有外部代码均给出仓库与文件路径，可复核。
> 调研时间：2026-10-18。本文件为调研报告，不改动任何代码。
>
> 说明（v2.2.2 清理）：本文引用的 `scratch/real-page/…`、`tools/_dump_events.txt` 等是调研期间的**本机抓包文件**，
> 从未纳入版本库，现已随本地缓存清理删除。引用行号保留原样以便对照当时证据；结论已并入
> [`docs/CHANGELOG.md`](CHANGELOG.md) 与 [`docs/architecture.md`](architecture.md)。

---

## 1. TL;DR（可执行修复结论）

1. **code-2 的根因是「提交端点/URL 形态错了」，不是 enc 算错**：2026 版 Vue3 答题页的真实表单是
   `<form id="submitForm" action="/mooc-ans/work/addStudentWorkNewWeb?_classId=..&courseid=..&token=<enc_work>&totalQuestionNum=<32hex>&wMicroNodeId=">`，
   页面 JS 还会用 `version(action)` 追加 `ua/formType/saveStatus/version` 后才 `serialize()` 提交（`scratch/real-page/0_第4章组件_list.html:657-682`、`:2171-2205`）。
2. 失败请求打的是**旧端点** `POST /mooc-ans/work/addStudentWorkNew`（无 query，令牌塞 body）——`tools/_dump_events.txt:120-124` 的失败体正是这种形态；旧端点对 2026 页面返回 `无效的参数：code-2！`。
3. **最低风险修法**：取答题页 → 解析 `form#submitForm` 的 `action` 与**全部** `input/textarea/select`（不限 `type=hidden`）→ 按页面 JS 规则扩展 URL → 回放 `serialize()` 后的 body。**不要自己拼端点、不要自己造 `token/jobid/totalQuestionNum`**。
4. 仓库里其实已有该修法的未跟踪实现 `cli_copy/core/work_form.py`（`build_submit_url`/`build_submission`），但 `tools/_dump_events.txt` 的失败仍是旧路径，说明失败发生时走的是 `_legacy_submission`（或该文件未合入/未生效）。**优先核对独立作业是否真的走了 page-form 分支。**
5. `totalQuestionNum` 是页面隐藏域里的 **32 位 hex 令牌**（如实测 `6eaca1bf84b6b650bc4b09d8f8805f1e`），**不是题目数量**；本地 `_legacy_submission` 在缺失时回退成题数，必须删掉。
6. 解析必须换容器：用 `div.singleQuesId[data]`；题干兼容 `h3.mark_name`（2026 变体 A）与 `.Zy_TItle > div.fontLabel`（2026 变体 B）。**禁用 `//div[contains(@class,'TiMu')]`**：它命中的是外层 `div.fanyaMarking.TiMu#fanyaMarking`，里面第一段文字就是「举报」+ 作业标题，正是日志里题干变「举报\r\n…第4章组件」的原因。
7. 更稳的取题入口是答题页接口 `GET /mooc-ans/api/work?api=1&workId=..&jobid=..&enc=..`（返回含表单与题目的 HTML），而不是从作业列表页/壳页解析。
8. 字体：`font-cxsecret` 映射**每页随机**，静态对照表不可行；用「字形字节哈希 → 汉字」表离线反查（社区已验证 83/83、154/154）。
9. AI 侧：统一 JSON 契约（`{"answers":[{"index":1,"answer":"B"}]}`），答案解析必须过题型/选项校验；**禁止「LLM 空结果 → 静默随机提交」**，默认改为跳过并汇总告警。
10. 外部实现中，2026 年仍在维护且直接打「新端点」的证据是 Dainoar/SuperAutoStudy（Java，2026-07 仍有提交）：`addStudentWorkNewWeb` + 表单体，`status=true && msg=success` 判成功。

---

## 2. 提交协议对照表 + 最小可行请求

### 2.1 对照表（全部来自源码）

| 项目 | 提交 URL（是否带 query） | Body 编码 | 关键字段 | 关键头 | 成功判定 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| **Dainoar/SuperAutoStudy**（Java，2026-07 仍更新） | `https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb`，**无 query** | `application/x-www-form-urlencoded`（OkHttp `FormBody`） | 页面表单字段 + `answer<qid>`/`answertype<qid>` + `answerwqbid`（qid 逗号拼接、**尾逗号**） | Host、`X-Requested-With: XMLHttpRequest`、`Accept: application/json, text/javascript, */*; q=0.01`、`Content-Type: application/x-www-form-urlencoded; charset=UTF-8`、Origin、Sec-Fetch-*、Chrome/129 UA | JSON `status=="true" && msg=="success"` | `src/main/java/com/tihai/utils/CourseUtil.java` 约 857-889 行（注释 `//2025/4/26发现学习通提交题目接口已改变`）；`Decode.java:283-336` |
| **lskzsy/EryaKiller**（老脚本，走 Web 端点） | `https://mooc1-2.chaoxing.com/work/addStudentWorkNewWeb?_classId=<clazzid>&courseid=<courseid>&token=<enc_work>`（query 3 参） | form-urlencoded | `pyFlag=""`、courseId、classId、`api=1`、workAnswerId、`totalQuestionNum`（隐藏域令牌）、fullScore=100.0、knowledgeid、oldSchoolId、`oldWorkId`、jobid、workRelationId、enc、`enc_work`、answer/answertype、`answerwqbid`（无尾逗号） | 默认 | 仅 `code==200`（不解析 JSON） | `Eryakill-3.0.py`（`SplitStr(inner,'enc_work"value="','"')` 取令牌） |
| **chettoy/FxxkStar**（Python，旧端点路线） | `/work/addStudentWorkNew?_classId=&courseid=&token={enc_work}&totalQuestionNum={隐藏域}&ua={client}&formType=post&saveStatus=1&version=1` | form-urlencoded（提交整张 `form#form1`） | 表单全部字段；`answerwqbid` 由 `answertype*` 字段名后缀拼出；先 `GET /work/validate?courseId=&classId=&cpi=`（3 正常 / 2 验证码 / 1 失败） | `Accept: application/json`、`Referer: /ananas/modules/work/index.html?v=2022-0714-1515&castscreen=0` | `result['status'] == True`（msg「保存成功！」） | `fxxkstar.py` `module_work_submit` 约 2450-2510 行 |
| **yatori-dev/yatori-go-core**（Go，旧端点路线） | `.../work/addStudentWorkNew?_classId&courseid&token=<enc_work>&totalQuestionNum&ua=pc&formType=post&saveStatus=1&version=1&tempsave=1` | `multipart/form-data` | `pyFlag`（暂存"1"/交卷""）、courseId、classId、api=1、workAnswerId、answerId、totalQuestionNum、fullScore、knowledgeid、oldSchoolId、oldWorkId、jobid、workRelationId、enc、enc_work、userId、cpi、workTimesEnc、randomOptions=false、isAccessibleCustomFid=0、answerwqbid；题型码 0 单选 / 1 多选 / 2 填空 / 3 判断(true/false) / 4 简答 / 11 连线 / 8 其他 | 见源码 | 解析 JSON（含验证码文案判断） | `api/xuexitong/XueXiTongChapterTestApi.go` `WorkNewSubmitAnswer` 30-235 行；`examples/XueXiToWorkAddBody.json` |
| **sweetcornna/university-helper**（Python，维护中） | `https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew`，**无 query** | form-urlencoded，`data=questions`（即页面解析出的整张表单） | 先 GET `/mooc-ans/api/work` 拿答题页；`pyFlag=""` 交卷 / `"1"` 暂存；`cover_rate` 阈值 | Host、X-Requested-With、Chrome/129 UA、Accept、Origin、Sec-Fetch-* | `res.json()["status"]`；msg 含「已过期」→ 跳过 | `backend/app/services/course/chaoxing/work_legacy_service.py`（`WORK_API_URL`/`SUBMIT_WORK_URL`）、`quiz_service.py:342`、`decode.py` |
| **kuizuo/blog 抓包**（2021，Web 端点） | `https://mooc1-2.chaoxing.com/work/addStudentWorkNewWeb?_classId=..&courseid=..&token=..&totalQuestionNum=..&ua=pc&formType=post&saveStatus=1&pos=..&rd=..&value=..&wid=..&_edt=..&version=1` | form-urlencoded | pyFlag、courseId、classId、api=1、workAnswerId、totalQuestionNum、fullScore、knowledgeid、oldSchoolId、oldWorkId、jobid=`work-<oldWorkId>`、workRelationId、enc、enc_work、userId、answercheck*/answer*/answertype*、`answerwqbid=...`（尾逗号） | 浏览器默认 | 响应 `{"msg":"success!","stuStatus":4,...,"status":true}` | `blog/project/某习通小助手.md` |
| **ocsjs/ocsjs 5.0**（TS，主流刷课脚本） | **不直连提交**：DOM 驱动点击 `submitBtn()`/`saveQuestion` | — | 题目 `domSearchAll({TiMu:'.TiMu'})`、题干 `.Zy_TItle .clearfix`、选项 `.answerBg .answer_p` | — | 以页面跳转/提示为准 | `packages/scripts/src/projects/cx.ts:880/889/1845/1968/2012` |
| **本仓库旧路径**（失败现场） | `SUBMIT_URL=https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew`（无 query） | form-urlencoded | 隐藏域 + 自造 `jobid=work-<id>`、`workid=workRelationId`、`token=enc_work`、缺失时 `totalQuestionNum=题数` | Referer、X-Requested-With、form-urlencoded | `accepted_response(status in true/1/"true")` | `cli_copy/functions/deal_exam.py` `_legacy_submission`；`cli_copy/core/answer_validation.py:39-43` |

> 结论：**同一个业务动作存在两代端点**。旧端点 `addStudentWorkNew`（FxxkStar/yatori/uh 在用）在旧页面可用；2026 页面的表单 action 已改为 `addStudentWorkNewWeb` 并带 query 令牌（本机抓包、SuperAutoStudy、EryaKiller、kuizuo 抓包一致）。

### 2.2 最小可行请求（2026 Vue3 作业页）

**前置**：已登录会话；先 GET 答题页拿表单（见 §4.4）。不要复用列表页里的旧 `workAnswerId`（列表页 `works.json` 的 `answer_id` 与答题页一致时才可用，见 §3.3）。

| 项 | 取值 / 来源 | 必填 | 证据 |
| --- | --- | --- | --- |
| Method | `POST` | 是 | 页面 `method="post"`（抓包 :657） |
| URL | `https://mooc1.chaoxing.com` + `form#submitForm` 的 `action` 原样，再按页面 `version(url)` 追加：`&ua=pc&formType=post&saveStatus=1`，已有 `version=N` → `N+1`，否则 `&version=1` | 是 | 抓包 :657-682（action 已含 `_classId/courseid/token/totalQuestionNum/wMicroNodeId=`）+ :2171-2205 |
| `_classId` / `courseid` | action query，来自 `classId`/`courseId` 隐藏域 | 是（query） | 抓包 :658 |
| `token` | action query = 隐藏域 `enc_work`（**不是** `standardEnc`） | 是（query） | 抓包 :658/:672；FxxkStar/EryaKiller 同取 `enc_work` |
| `totalQuestionNum` | action query = 隐藏域 `totalQuestionNum`（32-hex 令牌） | 是（query） | 抓包 :658/:673；yatori `examples/XueXiToWorkAddBody.json` |
| `wMicroNodeId` | action query，保留（可空） | 建议原样 | 抓包 :658 |
| `ua` / `formType` / `saveStatus` / `version` | 页面 `version()` 追加：`ua=pc`、`formType=post`、`saveStatus=1`、`version` 递增 | 是（页面行为） | 抓包 :2171-2205；kuizuo 抓包同款 |
| Body | 把 `form#submitForm` 内**所有**带 `name` 的 `input/textarea/select` 原样序列化（含 `courseId/classId/knowledgeid/cpi/workRelationId/workAnswerId/jobid/standardEnc/enc_work/totalQuestionNum/pyFlag/answerwqbid/mooc2/randomOptions/workTimesEnc`），再逐题写入 `answer<qid>`、`answertype<qid>`、填空 `answerEditor<qid>N` + `tiankongsize<qid>` | 是 | 抓包 :657-682；`cli_copy/core/work_form.py` |
| `answerwqbid` | 全部 qid 以 `,` 连接 + **尾部逗号**（页面 `ready2Submit()` 即 `"404552708,...,404552712,"`） | 是 | 抓包 :1891；SuperAutoStudy `Decode.java:331-336` |
| `pyFlag` | 交卷 `""`；暂存 `"1"` | 是 | 抓包 :657+页面 `saveAnswer()` :2284；uh/yatori |
| Headers | `X-Requested-With: XMLHttpRequest`、`Accept: application/json`、`Content-Type: application/x-www-form-urlencoded; charset=UTF-8`、`Origin: https://mooc1.chaoxing.com`、`Referer`=答题页 URL | 是 | SuperAutoStudy、uh、FxxkStar |
| 预检（可选但建议） | `GET /mooc-ans/work/validate?courseId=&classId=&cpi=`：`3` 正常、`2` 需验证码、`1` 账号异常 | 建议 | 抓包 :1835-1891；FxxkStar |
| 成功判定 | 响应 JSON `status: true`（msg 常见 `success`/`保存成功！`）；若 `status != true` 直接把 `msg` 回显到日志 | 是 | SuperAutoStudy、FxxkStar、uh、kuizuo |

> 若想先「最小改动」验证：只把旧 `SUBMIT_URL` 换成 `addStudentWorkNewWeb` 并带 action 的 query 串（至少 `_classId/courseid/token/totalQuestionNum`），body 保持现有隐藏域 + 答案，仍失败再补 `version/ua/formType/saveStatus` 与页面其余控件。

---

## 3. `无效的参数：code-2！` 成因与修复

### 3.1 证据链（按强度排序）

1. **本机真实页面表单 action 已换端点**（最强）：
   `scratch/real-page/0_第4章组件_list.html:657-682` —— `action="/mooc-ans/work/addStudentWorkNewWeb?_classId=151670988&courseid=244694077&token=9f9951332b375cf4f4e377e4e2328da9&totalQuestionNum=6eaca1bf84b6b650bc4b09d8f8805f1e&wMicroNodeId="`；隐藏域里 `enc_work=9f995133...`、`standardEnc=bf71ae150c...`、`jobid=""`（**没有** `oldWorkId/fullScore/api` 字段，`userId` 只有 `id` 没有 `name`）。
2. **页面提交 JS 会改写 URL**：`version()`（:2171-2205）追加 `ua/formType/saveStatus/version`；`ready2Submit()`（:1891）先把 `#questionIds`（即 `answerwqbid`）填成「全部 qid + 尾逗号」；`confirmSubmitWork()`（:2187）才 `serialize()` POST。也就是说真实浏览器提交的 URL 一定带 query，且 `version` 每次递增。
3. **失败现场是旧端点、无 query**：`tools/_dump_events.txt:120-124`，`SUBMIT_URL=.../work/addStudentWorkNew`，body 含 `standardEnc=bf71ae150c…`（说明隐藏域解析其实成功过），返回 `提交失败! 无效的参数：code-2！`。
4. **维护中的外部实现已改新端点**：SuperAutoStudy `CourseUtil.java` 注释「2025/4/26发现学习通提交题目接口已改变」，改为 `addStudentWorkNewWeb`；EryaKiller、kuizuo 2021 抓包同端点。反过来，FxxkStar/yatori/uh 仍打旧端点，说明旧端点对**旧页面**仍有效——不是全站 404，而是「对 2026 页面参数校验失败」。
5. **本仓库作者自己的注释**：`cli_copy/tests/test_core_behaviors.py:324-355` docstring 称「忽略页面表单（改打别处或丢掉查询串里的令牌）会得到『无效的参数：code-2』」——**这是本地推断，不是外部证据**，但与上面 1-4 吻合。
6. **社区检索为空**：`gh search issues`（"无效的参数"、"code-2 chaoxing"、"addStudentWorkNew"）与 web_search 精确短语均无公开解释。→ **code-2 的确切服务端判定条件未验证**，只能按「参数集合/端点不匹配」处理。

### 3.2 结论与修复优先级

| 优先级 | 假设 | 证据强度 | 修复 |
| --- | --- | --- | --- |
| **P0** | 打错端点：新页面必须用 `addStudentWorkNewWeb` + 页面 action 的 query 令牌；旧端点 `addStudentWorkNew` 对 2026 页面返回 code-2 | 强（抓包 + 两个外部实现） | 直接回放 action；删除 `_legacy_submission` 作为默认路径 |
| **P0** | 丢了 query：`_classId/courseid/token/totalQuestionNum` 只在 query 里被新版服务端读取，body 里的 `enc_work` 不等价 | 中强（页面 JS 只用 action + serialize；但 SuperAutoStudy 无 query 也声称成功 → **query 是否强制未验证**） | 保留 action query，至少带这 4 个 |
| P1 | 页面表单解析失败 → 回落到 legacy（旧 URL） | 中（失败体有 `standardEnc` 说明解析过一次；但 `jobid=work-57096674` 与页面 `jobid=""` 不一致，疑似又经过自造逻辑） | 同一页面只解析一次；`found=False` 时**不提交**并明确报错 |
| P1 | `totalQuestionNum` 被回退成题数 | 强（代码事实；yatori/抓包证明是 32-hex 令牌） | 删回退；缺失则中止提交 |
| P2 | `jobid/workid` 自造（`jobid=work-<workId>` 覆盖页面空值；`workid=workRelationId`） | 中（页面真实 `jobid=""`；旧抓包 `jobid=work-<hex oldWorkId>`） | 一律用页面控件值，不覆盖 |
| P2 | `workAnswerId` 过期（列表页拿的 `answer_id` 需先 GET 答题页刷新） | 未验证 | 每次提交前从答题页表单取 `workAnswerId` |
| P2 | 未先 `GET /work/validate`、未处理验证码 status=2 | 中（FxxkStar 必做；页面 `submitValidate` 必做） | 提交前 validate，非 3 中止并提示 |
| P3 | 会话/`pageHeader`/列表页预热不足 | 未验证 | 保持「同 session 先列表→答题页→提交」顺序即可 |

### 3.3 附：`workAnswerId` 与列表页

`scratch/real-page/works.json` 里列表项：`work_id=57096674, answer_id=54986493, enc=b0ed95f0db07e80f43303aba56ecf1b2`，而答题页表单 `workAnswerId=54986493`、`enc_work=9f9951332b375cf4f4e377e4e2328da9`、`standardEnc=bf71ae150c9a59f7fa4408c5e2243f5c`。
→ **列表页的 `enc` 可以进 URL 取卷，但它不是提交用的 `token`**；三个值互不相同，不能互相替代（这是「token=enc」假设错误的直接证据）。

---

## 4. 新型页面（Vue3 / 2026）解析方案

### 4.1 两代 2026 页面结构（都必须兼容）

**变体 A（本机抓包，`scratch/real-page/0_第4章组件_list.html:688-710`）**

```html
<div class="padBom50 questionLi fontLabel singleQuesId" typeName="单选题"
     id="question404552708" data="404552708">
  <h3 class="mark_name colorDeep fontLabel workTextWrap">
    1.<span class="colorShallow">(单选题)</span>在 Vue 组件中…?
  </h3>
  <input type="hidden" name="answertype404552708" value="0">
  <input type="hidden" name="answer404552708" value="">
  <div class="stem_answer qtDetail">
    <div class="clearfix answerBg workTextWrap" onclick="addChoice(this)" qid qtype role="radio"
         aria-label="A props选择">
      <span class="num_option choice404552708" data="A">A</span>
      <div class="fl answer_p"><p>props</p></div>
    </div>
  </div>
</div>
```

**变体 B（chenhuilin2/chaoxing-work-export 的真实快照，`docs/chapter-quiz-diagnosis.md:38-65`）**

```html
<div class="singleQuesId" id="question405842140" data="405842140">
  <div class="TiMu newTiMu" data="0">
    <div class="Zy_TItle clearfix"><i class="fl">1</i>
      <div class="clearfix font-cxsecret fontLabel">
        <span class="newZy_TItle">【单选题】</span>题干正文…
      </div>
    </div>
    <ul class="Zy_ulTop w-top fl">
      <li class="font-cxsecret before-after" qid="405842140" qtype="0" role="radio"
          aria-label="A 毛泽东选择">
        <span class="num_option choice405842140" data="A">A</span>
        <a href="javascript:void(0);" class="fl after">毛泽东</a>
      </li>
    </ul>
    <input type="hidden" name="answer405842140" value="">
    <input type="hidden" id="answertype405842140" name="answertype405842140" value="0">
  </div>
</div>
```

### 4.2 选择器建议（按优先级回退）

| 目标 | 首选 | 回退 | 说明 |
| --- | --- | --- | --- |
| 题目容器 | `//div[contains(@class,'singleQuesId')]` | `//div[contains(@class,'questionLi')]`、`//div[contains(@class,'mark_item')]` | 容器带 `data="<qid>"`（变体 A/B 都有） |
| qid | `data` 属性 | `id="question<qid>"` 中 6+ 位数字 | 不要从 `answertype<qid>` 名字猜（填空/简答可能没有） |
| 题干 | 变体 A：`./h3[contains(@class,'mark_name')]`；变体 B：`.//div[contains(@class,'Zy_TItle')]//div[contains(@class,'fontLabel')]` | `.//div[contains(@class,'Zy_TItle')]`（整块取文本） | **不要**用 `TiMu` 定位题干（见 4.3） |
| 题型码 | `input[@name='answertype<qid>']/@value` | `div[contains(@class,'TiMu')]/@data`（变体 B）、容器 `@typeName`、`.newZy_TItle` 文本 | 码值：0 单选、1 多选、2 填空、3 判断、4 简答（SuperAutoStudy/yatori 一致） |
| 选项 | 变体 A：`.//div[contains(@class,'answerBg')]`；变体 B：`.//ul[contains(@class,'Zy_ulTop')]/li` | `li[contains(@class,'option')]` | 字母取 `span[contains(@class,'num_option')]/@data`；正文取 `.//div[contains(@class,'answer_p')]` 或 `a.after`；无结构时用 `aria-label` 去掉末尾「选择」 |
| 填空 | `textarea[name^='answerEditor']` + `input[name='tiankongsize<qid>']` | `textarea[name='answer<qid>']` | 空数从 `tiankongsize` 取，别按分号猜 |
| 提交表单 | `//form[contains(@id,'submitForm')]` | `//form[contains(@action,'addStudentWork') or contains(@action,'work') or contains(@action,'submit')]` | 收控件时用 `input[@name] | textarea[@name] | select[@name]`，**不要只取 `type=hidden`**（`questionIds` 等可能是普通 input） |
| 整页题干文本 | 取容器内**直接**题干节点 | 不要「容器 //text()」 | 后者会把「举报/收藏/题量」等杂项拼进题干 |

### 4.3 「举报」混入题干的根因（本机证据）

外层容器：

```html
<div class="fanyaMarking TiMu" id="fanyaMarking">
  <p onclick="reportTask('151670988','57096674','269409830','work')">举报</p>
  <h2 class="mark_title">第4章组件</h2>
  … 题量 / 满分 …
  <div class="padBom50 questionLi fontLabel singleQuesId" …>题目…</div>
</div>
```

- 各题的 class 是 `questionLi … singleQuesId`，**不含 `TiMu`**；
- 因此 `//div[contains(@class,'TiMu')]` 只命中外层 wrapper，`//text()` 拿到的第一段就是「举报」+ 标题 → 日志症状完全复现；
- 修复：容器改 `singleQuesId`，题干只取 `h3.mark_name` / `.Zy_TItle > .fontLabel`，并把 `(单选题)`、`【单选题】`、`1.` 从题干正文剥离（题型单独存）。

### 4.4 更稳的接口：先取答题页 HTML

`GET https://mooc1.chaoxing.com/mooc-ans/api/work`（university-helper `work_legacy_service.py:_fetch_response`）

| 参数 | 值 |
| --- | --- |
| `api` | `1` |
| `workId` | `jobid` 去掉 `work-` 前缀 |
| `jobid` | `work-<oldWorkId/hex>`（列表页/卡片页给） |
| `originJobId` | 同 `jobid` |
| `needRedirect` | `true` |
| `skipHeader` | `true` |
| `knowledgeid` | 列表项 knowledgeid（独立作业常见 0） |
| `ktoken` | 列表页提供（无则空） |
| `cpi` | 班级 cpi |
| `ut` | `s`（学生） |
| `clazzId` / `courseid` | classId / courseId |
| `type` | 空串 |
| `enc` | 列表项 enc（如 `b0ed95f0…`） |
| `mooc2` | `1` |

响应是**含 `form#submitForm` 与题目的 HTML**（不是 JSON），直接交给 §4.2 解析；`/mooc-ans/api/work` 也是四层 iframe 链的最后一层（`docs/chapter-quiz-diagnosis.md:29-32`：L3 `/ananas/modules/work/index.html?...jobid=` → L4 `api/work` 答题页）。
另：已批阅页 URL 特征为 `selectWorkQuestionYiPiYue`（FxxkStar `is_marked` 判断），提交前可用它区分「待做/已完成」。

### 4.5 字体加密

- 检测：`<style id="cxSecretStyle">`（uh `decode.py`）或 `div.font-cxsecret` / `.fontLabel.font-cxsecret`（FxxkStar、cwe）；命中即整段可能乱码。
- 机制：内联 `@font-face` 的 TTF 子集把「备用码位」的字形轮廓换成真字，`textContent` 是乱码；**同一码位在不同页面映射不同**（cwe 实测 46 个重叠码位一致率 0/46）。
- 可行解：离线建 `sha1(glyf 原始字节)→汉字` 表，运行时解析页面 TTF 的 `loca/glyf` 反查；cwe 用全量 20902 字（裸 122.5KB / base64 163.3KB）验证 83/83、154/154。静态「混淆字→真字」表不可行。
- 无法解码时不要把乱码送去 LLM：标记 `unreadable`，人工核对（本仓库已有 `question['unreadable']` 分支）。

---

## 5. AI 答题链路建议

### 5.1 提示词与输出契约（外部实现现状）

- **university-helper**（`backend/app/services/course/chaoxing/answer_providers/ai.py` 约 88-106 行）按题型给 system prompt，统一 JSON：
  - 单选：`格式：{"Answer": ["B"]}`；多选：`{"Answer": ["A", "C"]}`；填空：`{"Answer": ["答案1", "答案2"]}`；判断：`{"Answer": ["正确"]}` 或 `{"Answer": ["错误"]}`；
  - 每条形如「XX题答题。直接输出JSON，禁止解释、思考过程或Markdown。」；user 消息追加 `选项：` + 每行一个选项；
  - 并发信号量（`max_active_requests=3`）+ 最小请求间隔（3s），失败重试。
- **chaoxing-fanya**（`api/answer.py` 847-1160 行）：同样的 `{"Answer": [...]}` 契约；`_strip_json_block` 去 ```json 围栏；`_ensure_answer_list` 兼容字符串/列表；判断题再用「正确选项/错误选项」两个列表做文本→布尔映射（映射不上时**随机**并打错误日志：`_ensure_boolean_answer` 约 389-402 行）。
- **Jianqing-Lin/xxt**（README「题库调用链与 AI 兜底」）：`local,TikuYanxi,AI` Provider 链；外部/AI 答案都要过「题型 + 选项匹配校验」，通过才回写本地题库；AI 要求 `{"Answer":["答案"]}`。
- **本仓库**（`cli_copy/utils/llm_client.py:20-24`）已有更好的契约：
  `{"answers":[{"index":1,"answer":"B"}]}`，并明确「不要编造缺失题干/图片/选项；信息不足返回空字符串；单选一个字母、多选按顺序、判断 true/false、填空中文分号、简答全文」。

### 5.2 建议（可直接落地）

1. **保留本仓库的批量 JSON 契约**（index 对齐，天然支持批处理/并发），把 `answer` 的题型约束写进 system prompt（已有），并在 user 消息里给「题号 + 题型 + 题干 + 选项字母.正文」。
2. **强制校验层**（拒绝静默）：
   - 单选：答案必须是存在的选项字母（1 个）；
   - 多选：字母去重、升序、必须 ⊆ 选项集合；
   - 判断：只接受 `true/false`（或 正确/错误/T/F/对/错）→ 统一转 `true/false`；
   - 填空：按 `tiankongsize` 校验空数，用中文分号连接；多空与空数不符 → 判失败；
   - 简答：非空文本即可；
   - 任何失败 → 该题标记 `source=llm_invalid`，**不提交**或按显式配置降级。
3. **禁止「空结果 → 随机」默认策略**：本仓库 `deal_exam._answer_question` 回退链是「缓存 → LLM → 随机/跳过」，`_random_answer` 在 `no_answer_action=="random"` 时会给随机字母；建议默认 `skip`，并在任务汇总里单列 `random_answers/invalid_answers`，提交前若异常率超阈值（参考 uh `cover_rate`）直接中止。
4. **题干/选项清洗**：题型标记、题号、「举报/收藏」、`\r\t\n` 全去掉；图片题干走 OCR（见 5.3）；字体乱码标记 `unreadable` 不下发。
5. **失败重试**：JSON 解析失败 → 重试一次（温度 0）；仍失败 → 该题跳过；HTTP 失败按指数退避（本仓库已有 3 次重试）。
6. **并发**：按 Provider 限流（uh 3 并发 + 3s 间隔；fanya 信号量）；同题不要重复调用。
7. **写回缓存的条件**：只在「服务器接受提交」后回写（本仓库 `_save_submitted_answers` 已如此；xxt 是校验通过即回写，二者取其一但不要缓存随机答案）。

### 5.3 图片/OCR

- 题干含 `<img>` 时：university-helper `decode.py:1301-1308` 会把图片转成 `[公式: <ocr文本>]`，OCR 失败则保留 `<img src="...">`；OCR 有三层开关（外部视觉模型 → 本地 PaddleOCR `CHAOXING_ENABLE_OCR=1` → HTTP OCR 服务）。
- 本仓库 `_extract_title` 也收集 `img`；若未开启 OCR，建议把 `<img>` 的 **绝对 URL** 传给多模态模型，而不是让文本模型瞎猜。
- 安全：只允许 `chaoxing.com` 域/HTTPS 的图片（uh 的 `_OCR_ALLOWED_IMG_HOSTS` 白名单可直接借鉴），避免 SSRF。

---

## 6. 下一版功能候选（来源 + 难度）

| 功能 | 价值 | 来源（可复核） | 难度 |
| --- | --- | --- | --- |
| 提交表单「原样回放」框架（action + 全控件 + 页面 JS URL 规则） | 修 code-2 的根 | 本机抓包；`cli_copy/core/work_form.py`；SuperAutoStudy | 低（已基本实现，需 review/合入） |
| 题库 Provider 链 + 答案校验 + 命中回写 | 降低 AI 成本、提升正确率 | Jianqing-Lin/xxt README「题库调用链与 AI 兜底」 | 中 |
| 本地 SQLite 题库（`cxtk.db`）+ 分页管理 | 离线命中、可积累 | xxt README | 中 |
| AI 兜底 + 统一 JSON 契约 + 严格校验 | 质量兜底 | uh `answer_providers/ai.py`；fanya `api/answer.py`；本仓库 `llm_client.py` | 低 |
| 覆盖率阈值（cover_rate）后再提交 | 防「大面积不会」被提交 | uh `work_legacy_service.py` | 低 |
| 断点续跑/断点续学 | 长任务稳定性 | SuperAutoStudy README「断点续学」 | 中 |
| 多 iframe 递归 + 章节练习批量遍历 | 扩功能面 | chenhuilin2/chaoxing-work-export README/`frame-bridge.ts` | 中 |
| 作业导出 Word/TXT/MD + 历史记录 | 复习/归档 | cwe README | 低-中 |
| 字体哈希解码（glyf→汉字表，按 `cxsecret` 作用域） | 解乱码 | cwe `docs/chapter-quiz-diagnosis.md` §3 | 中 |
| 题干图片 OCR（本地 PaddleOCR / 视觉模型） | 图片题可答 | uh `decode.py`、`_OCR_ALLOWED_IMG_HOSTS`；FxxkStar optional pytesseract | 中 |
| 验证码处理（validate status=2） | 提交成功率 | 本机抓包 `submitValidate`；FxxkStar `/work/validate` | 中-高 |
| WebUI 任务日志/状态/定时调度 | 可观测性 | xxt README（WebUI 日志、任务状态）；本仓库已有事件流 | 中 |
| 高并发调度 + Redis 缓存（微服务化） | 多账号吞吐 | SuperAutoStudy README | 高 |
| 已批阅/答案与解析提取（错题本） | 学习价值 | cwe（答案容器「新的答案开始/结束」；`selectWorkQuestionYiPiYue`） | 中 |

---

## 7. 参考链接

**提交协议 / 端点**

- chettoy/FxxkStar `fxxkstar.py`（旧端点 + `/work/validate` + 表单全量回放）：https://github.com/chettoy/FxxkStar/blob/main/fxxkstar.py
- yatori-dev/yatori-go-core `api/xuexitong/XueXiTongChapterTestApi.go`（旧端点 multipart 字段全集 + 题型码）：https://github.com/yatori-dev/yatori-go-core/blob/main/api/xuexitong/XueXiTongChapterTestApi.go
- yatori 提交体样例 `examples/XueXiToWorkAddBody.json`（证明 `totalQuestionNum` 是 32-hex 令牌）：https://github.com/yatori-dev/yatori-go-core/blob/main/examples/XueXiToWorkAddBody.json
- sweetcornna/university-helper `backend/app/services/course/chaoxing/work_legacy_service.py`（`/mooc-ans/api/work` 取卷 + 提交）：https://github.com/sweetcornna/university-helper/blob/main/backend/app/services/course/chaoxing/work_legacy_service.py
- university-helper `quiz_service.py`（提交与「已过期」判断）：https://github.com/sweetcornna/university-helper/blob/main/backend/app/services/course/chaoxing/quiz_service.py
- Dainoar/SuperAutoStudy `src/main/java/com/tihai/utils/CourseUtil.java`（2025/4/26 接口变更注释 + `addStudentWorkNewWeb` + 成功判定）：https://github.com/Dainoar/SuperAutoStudy/blob/master/src/main/java/com/tihai/utils/CourseUtil.java
- SuperAutoStudy `src/main/java/com/tihai/utils/Decode.java`（`div.singleQuesId` / `.Zy_TItle` / `TiMu@data` / `answerwqbid` 尾逗号）：https://github.com/Dainoar/SuperAutoStudy/blob/master/src/main/java/com/tihai/utils/Decode.java
- lskzsy/EryaKiller `Eryakill-3.0.py`（`enc_work` 取 token + Web 端点）：https://github.com/lskzsy/EryaKiller/blob/master/Eryakill-3.0.py
- kuizuo/blog `blog/project/某习通小助手.md`（2021 完整抓包：URL query + body + 成功响应）：https://github.com/kuizuo/blog/blob/main/blog/project/%E6%9F%90%E4%B9%A0%E9%80%9A%E5%B0%8F%E5%8A%A9%E6%89%8B.md

**新页面解析 / 字体**

- chenhuilin2/chaoxing-work-export `docs/chapter-quiz-diagnosis.md`（四层 iframe、L4 DOM、题干 `.fontLabel` 根因、字体哈希解码实测）：https://github.com/chenhuilin2/chaoxing-work-export/blob/main/docs/chapter-quiz-diagnosis.md
- cwe `docs/chapter-exercise-scan.md`（章节练习扫描与诊断）：https://github.com/chenhuilin2/chaoxing-work-export/blob/main/docs/chapter-exercise-scan.md
- cwe `src/extractors/question-stem.ts` / `cxsecret-font.ts` / `cxsecret-decoder.ts`：https://github.com/chenhuilin2/chaoxing-work-export/tree/main/src/extractors
- university-helper `backend/app/services/course/chaoxing/decode.py`（`div.singleQuesId` + `TiMu@data` + `answerwqbid` 尾逗号 + `[公式: ...]` OCR + 字体解码钩子）：https://github.com/sweetcornna/university-helper/blob/main/backend/app/services/course/chaoxing/decode.py
- ocsjs/ocsjs 5.0 `packages/scripts/src/projects/cx.ts`（`.TiMu`/`.Zy_TItle .clearfix`/`.answerBg .answer_p`、DOM 驱动提交）：https://github.com/ocsjs/ocsjs/blob/5.0/packages/scripts/src/projects/cx.ts
- TellMeYourWish/chaoxing_solution_of_font_confusion（字体混淆哈希反查参考实现，cwe 引用）：https://github.com/TellMeYourWish/chaoxing_solution_of_font_confusion

**AI 答题 / 题库**

- university-helper `answer_providers/ai.py`（按题型 JSON 提示词 + 并发/间隔 + 解析）：https://github.com/sweetcornna/university-helper/blob/main/backend/app/services/course/chaoxing/answer_providers/ai.py
- chaoxing-fanya `api/answer.py`（`{"Answer":[...]}` 契约、去围栏、判断题布尔映射）：https://github.com/sweetcornna/chaoxing-fanya/blob/main/api/answer.py
- Jianqing-Lin/xxt README（本地题库 `cxtk.db`、Provider 链 `local,TikuYanxi,AI`、答案校验回写、WebUI 日志）：https://github.com/Jianqing-Lin/xxt
- yatori-dev/yatori-go-core README（多平台 API 聚合）：https://github.com/yatori-dev/yatori-go-core
- ocsjs/ocsjs（脚本市场、多平台）：https://github.com/ocsjs/ocsjs
- 本仓库内部证据：`cli_copy/functions/deal_exam.py`（提交/回退链）、`cli_copy/core/work_form.py`（2026 表单解析与回放）、`cli_copy/core/answer_validation.py`、`cli_copy/tests/test_core_behaviors.py:316-355`、`scratch/real-page/0_第4章组件_list.html`、`tools/_dump_events.txt:120-124/1115`。

---

### 附：未验证 / 需真机确认

1. `code-2` 的确切服务端校验条件（无公开 issue；只能确认「旧端点 + 无 query」会触发）。
2. query 里的 `_classId/courseid/token/totalQuestionNum` 是否**强制**（SuperAutoStudy 无 query 声称成功，与本机页面行为相反）——建议按页面行为带全，最稳。
3. `workAnswerId` 是否必须每次从答题页刷新（列表页值是否过期）。
4. `/mooc-ans/api/work` 对「独立作业」列表项是否同样返回表单（当前抓包来自作业任务页；章节测验已证实）。
5. 字体解码表是否覆盖本课程用字（需用真实页面 TTF 跑一次哈希表校验）。
