# 学习通「独立考试」协议 + AI 答题提示词调研（v2.2 前置）

> 调研时间：2026-10-18。本文件为调研报告，不改动任何代码。
> 证据分级：**【已验证】** = 本机抓包或上游源码可直接复核；**【社区代码】** = 仅见于公开项目源码，未在本机复现；**【未验证】** = 推测/待真机确认。
> 网络限制：本机 GitHub / raw.githubusercontent 全链路不可用（198.18.x 劫持、TLS 失败），本轮上游源码经 **gitcode 镜像 `git clone`** 获取（`https://gitcode.com/gh_mirrors/cx/CxKitty.git` = `SocialSisterYi/CxKitty`），文件行号与原文均来自克隆副本。
>
> 说明（v2.2.2 清理）：文中引用的 `scratch/exam/…`、`tools/_recon_exam*.py` 是调研期间的**本机抓包/探针文件**，
> 从未纳入版本库，现已随本地缓存清理删除；v2.2.2 已按本文 §6 的协议结论完成落地，正式实现见
> [`docs/architecture.md`](architecture.md) 的「考试答题页直连」小节与 [`docs/release-2.2.2.md`](release-2.2.2.md)。

---

## 1. TL;DR（可直接执行的结论）

1. **考试没有作业式的 `addStudentWorkNew` 链路**：公开实现里考试的提交全部走 `exam-ans` 协议族。作业的 `code-2` 结论（回放页面表单 action）不能平移到考试。
2. **手机客户端考试协议已完整拿到（最可靠证据）**：`task-exam`（封面/跳过承诺书）→ `phone/start`（开始，302 后 Location query 取 `enc`）→ `reVersionTestStartNew`（逐题取题，`start` 为**0 基**索引）→ **`POST reVersionSubmitTestNew`（逐题保存/交卷）**。端点与字段见 §2.1、§3。
3. **端点名纠错**：本仓库 `cli_copy/core/exam_form.py` 猜测的 `reVersionTestSubmitNew` / `addStudentExam` / `saveExamAnswer` / `reVersionTestSaveNew` 在 CxKitty 与 OCSJS 源码中**均未出现**；手机端真名是 `reVersionSubmitTestNew`（注意是 `SubmitTest`，不是 `TestSubmit`）。PC 端端点名**未验证**，必须运行时探测，禁止写死。
4. **提交签名是四个 query 参数 `pos / rd / value / _edt`**，算法见 `cxapi/utils.py:71-108`（§3.3，可逐行移植）；`x,y` 只是随机点击坐标（100..1000），不涉及屏幕采集。
5. **动态令牌会滚动**：非交卷提交成功后，响应 `data` 为 `"<encLastUpdateTime>|<encRemainTime>|<enc>"`，**必须解析并更新下一题的参数**；沿用旧值会触发「无效参数！」或提交失败（CxKitty `exam.py:793-799`）。
6. **逐题模式确实存在**：OCSJS 注释「由于当前考试禁止整卷预览，各题为独立新页面，只能一个个答题」，逐题页靠 `[onclick="getTheNextQuestion(1)"]` 翻页；本仓库检测到逐题/单题限时必须以「整卷预览接口」或**安全中止**收场，不能提交半份。
7. **超时自动交卷已确认**：考试列表页 `TestRelationInfo[examId].expiredAutoSubmit = 1`，且页面考试说明写明「考试时间截止或答题时间结束，如果处于答题页面，将自动提交试卷」（`scratch/exam/exam_test.html:66`）；超时后提交会返回「考试时间已用完,不允许提交答案!」。
8. **考试没有「整卷回退保存」**：CxKitty 考试固定 `fallback_save=False`，注释「考试不存在临时保存特性」；逐题的 `tempSave=true` 就是保存动作。因此默认 `auto_submit=false`、有未答/答案无效时**不交卷**、留给用户/日志，是最小风险策略。
9. **AI 侧**：保留本仓库批量 JSON 契约，但必须加「题型硬约束 + 校验层 + 禁止空结果静默随机」；考试场景建议单题独立调用、temperature≤0.3、两段式（先推理后结构化）只用于疑难/多选。
10. **风险前置**：人脸比对（`face-compare` + 构造 `faceDetectionResult`）、人机验证码、IP 限制、仅电脑客户端、考试码、章节任务点未完成、重复交卷间隔限制（「X 分钟内不允许提交考试」）——任一命中都应中止本次自动考试并提示用户。

---

## 2. 考试全流程与端点

### 2.1 协议 A：手机客户端协议（CxKitty，**【已验证】** 源码）

仓库：`SocialSisterYi/CxKitty`（GitHub 原仓库，本机经 gitcode 镜像克隆）。核心文件 `cxapi/exam.py`（861 行）、`cxapi/utils.py`、`cxapi/session.py`、`cxapi/face_detection.py`、`resolver/question.py`、`cxapi/classes.py`。

| # | 动作 | 方法 / URL | 关键参数 | 成功特征 | 失败特征 |
|---|---|---|---|---|---|
| 1 | 考试列表（手机端替代入口） | `GET https://mooc1-api.chaoxing.com/exam/phone/task-list` | `courseId, classId, cpi` | `ul.nav > li`：`li["data"]` query 含 `taskrefId`(exam_id)、`enc_task`；`li.p`=标题；`li.span`=状态（未开始/未交/已完成）；`span.fr`=剩余时间 | 无 `ul.nav` → 空列表 |
| 2 | 封面/元数据（**顺带跳过承诺书**） | `GET https://mooc1-api.chaoxing.com/exam-ans/exam/phone/task-exam` | `redo=1, taskrefId=<examId>, courseId, classId, userId=<puid>, role="", source=0, enc_task, cpi, vx=0, examsignal=1` | HTTP 200；`input#testUserRelationId`=exam_answer_id、`input#monitorEnc`、`span.overHidden2`=标题、`input#faceRecognitionCompare`、`input#captchaCheck`、`input#captchaCaptchaId`、JS `var needcode = <n>;` | 302 且 Location path=`/exam-ans/exam/phone/look` → 已完成；`h2.color6…` 文案：考试尚未开始 / 章节任务点未完成… / 请使用指定的IP环境进行考试。 / 该试卷只允许在电脑考试客户端考试… |
| 3 | 开始考试（计时开始，**不可逆**） | `GET https://mooc1-api.chaoxing.com/exam-ans/exam/phone/start` | `courseId, classId, examId, source=0, examAnswerId, cpi, keyboardDisplayRequiresUserAction=1, imei, faceDetection=0\|1, facekey, faceDetectionResult(JSON), captchavalidate, jt=0, code=<考试码>` | HTTP **302**，`Location` query 中取 `enc` | 200 + `p.blankTips/li.msg`：验证码错误！ / 人脸识别对比不通过，不允许进入考试 |
| 4 | 逐题取题（单题页） | `GET https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew` | `courseId, classId, tId=<examId>, id=<exam_answer_id>, source=0, p=1, isphone=true, tag=<int(enc_remain_time==0)>, cpi, imei, start=<0基题号>, enc, keyboardDisplayRequiresUserAction=1, monitorStatus=0, monitorOp=-1, remainTimeParam=<enc_remain_time>, relationAnswerLastUpdateTime=<last_update_time>` | `form#submitTest` 内 `input#enc/#encRemainTime/#remainTime/#encLastUpdateTime`；题目节点 `div.questionWrap.singleQuesId.ans-cc-exam`（整卷 `allAnswerList`，单题 `answerMain`） | `p.blankTips`：考试已经提交 / 无权限访问！ / 当前用户账号发生异常，无法进行考试 / 当前班级发生异常，无法进行考试 / 无效参数！ |
| 5 | 整卷预览（一次拿全部题） | `GET https://mooc1-api.chaoxing.com/exam-ans/exam/phone/preview` | `courseId, classId, source=0, imei, start=0, cpi, examRelationId=<examId>, examRelationAnswerId, monitorStatus=0, monitorOp=-1, remainTimeParam, relationAnswerLastUpdateTime, enc` | 同样是 `form#submitTest` + 多个 `questionWrap.singleQuesId` | 同上 `p.blankTips` |
| 6 | 答题卡状态 | `GET https://mooc1-api.chaoxing.com/exam-ans/exam/phone/loadAnswerStatic` | `courseId, classId, source=0, start=0, cpi, examRelationId, imei, examRelationAnswerId, remainTimeParam, relationAnswerLastUpdateTime, enc` | `ul` 下 `h4.cardTit`（题型）+ `li[data=<index>]`，class 含 `complated` 即已保存 | — |
| 7 | **逐题保存 / 交卷** | `POST https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew` | query/body 见 §3；`tempSave=true` 逐题保存，`tempSave=false` 交卷 | JSON `status == "success"` | 「考试时间已用完,不允许提交答案!」/「…分钟内不允许提交考试」/ 其他 msg |

**注意主机差异**：取题/预览/答题卡在 `mooc1-api.chaoxing.com`，**提交在 `mooc1.chaoxing.com`**（`exam.py:63`）。这是源码常量，不要混用。

### 2.2 协议 B：PC 网页（OCSJS + 本机列表抓包，**【社区代码】/部分【已验证】**）

| 环节 | 证据 | 内容 |
|---|---|---|
| 列表页 | 本机 `scratch/exam/exam_test.html` | `GET /exam-ans/exam/test?courseId&classId&ut=s&cpi&openc&enc&examsystem=0`；条目 `onclick="goTest('244694077',11021171,171477623,'2026-10-31 20:00:51.0',471087489,false,'4533db7e…')"`（7 参：courseId, examId, examRelationId, endTime, paperId, isRetest, examEnc）；另有 6 参无 examEnc 的旧条目（`:344`、`:359`）。页内 `TestRelationInfo = {"11021171":{"limitTime":100,"pcExamNotes":"…3、考试时间截止或答题时间结束，如果处于答题页面，将自动提交试卷。…","expiredAutoSubmit":1}}`（`:66`） |
| 启动考试 | Lead 实测 + OCSJS | `GET /exam/test/reVersionTestStartNew?courseId&classId&tId=<examId>&id=0&p=1&tag=1&enc=<examEnc>&examsystem=0&cpi=&openc=`。OCSJS 把 `exam-ans/exam/test/reVersionTestStartNew` 与 `mooc-ans/exam/test/reVersionTestStartNew` 都识别为「新版考试页面」 |
| 答题页 DOM | OCSJS `packages/scripts/src/projects/cx.ts`（5.0） | 容器 `.questionLi`；题干 `.splitS-left .mark_name` / `.line_wid_half.fl,.line_wid_half.fr`；选项 `.answerBg .answer_p, .textDIV, .eidtDiv`；题型 `input[name^="type"]`（**考试与作业不同**：作业是 `input[id^="answertype"]`；且会出现多个干扰 `type`，需过滤 `name` 匹配 `/type\d+/`）；填空 `textarea` 或同域 iframe；翻页按钮 `[onclick="getTheNextQuestion(1)"]` |
| 整卷预览 | OCSJS `cx.ts:452,629-660` | 考试整卷预览页 `/mooc2/exam/preview`；若考试禁止整卷预览，则「各题为独立新页面，只能一个个答题」（源码注释原文） |
| 提交 | OCSJS | **脚本不自动交卷**：答完提示「作业/考试完成，请自行检查后保存或提交。」（`cx.ts:1034,1055`）。PC 端提交端点/参数在本机无证据 → **【未验证】** |

> 结论：PC 端可做「解析 + 填答」，但**提交动作不要自创**。两条可行路线：① 回放答题页真实表单（若抓到 `form`，沿用 v2.1 作业的 page-form 回放思路）；② 若页面无表单/只有按钮，则只能「填完不交卷」或走手机协议（需接受 §4 的风险）。**禁止**凭空拼 `addStudentExam`/`saveExamAnswer` 之类端点。

---

## 3. 提交协议细节（手机端，【已验证】CxKitty `cxapi/exam.py:699-809`）

### 3.1 请求骨架

```
POST https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew
     ?classId=<classId>
     &courseId=<courseId>
     &cpi=<cpi>
     &testPaperId=<examId>
     &testUserRelationId=<exam_answer_id>
     &tempSave=true|false
     &pos=<签名> &rd=<签名> &value=<签名> &_edt=<签名>
     &qid=<当前题 qid | 交卷时为空>
     &version=1
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
```

### 3.2 body 字段

公共字段（每次提交都带）：

| 字段 | 取值来源 | 说明 |
|---|---|---|
| `courseId` / `classId` / `cpi` | 列表/封面 | 与 query 重复，保留 |
| `testPaperId` | examId | 考试 id |
| `testUserRelationId` | `input#testUserRelationId` | 考试作答关系 id（exam_answer_id） |
| `type` | 固定 `0` | — |
| `isphone` | `true` | 手机协议标志 |
| `imei` | 随机 16 字节 hex（CxKitty `get_imei()`） | 客户端设备号 |
| `subCount` | `""` | — |
| `remainTime` | `input#remainTime` | 裸秒数 |
| `tempSave` | 与 query 一致 | true=保存，false=交卷 |
| `timeOver` | `"false"` | 超时提交才为 true |
| `encRemainTime` | `input#encRemainTime` | 加密剩余时间 |
| `encLastUpdateTime` | `input#encLastUpdateTime` | 最近操作时间（加密） |
| `enc` | `input#enc`（来自 start 302 的 Location query，之后每次提交回传新值） | 动态行为校验 |
| `userId` | puid | — |
| `source` | `0` | — |
| `start` | 当前题索引（0 基） | 交卷可不传 |
| `enterPageTime` | `encLastUpdateTime` | — |
| `monitorforcesubmit` | `0` | — |
| `answeredView` | `0` | — |
| `exitdtime` | `0` | — |

逐题字段（每题一套，`<qid>` 为题目 id）：

| 题型 | 字段 |
|---|---|
| 单选 | `type<qid>=0`、`questionId=<qid>`、`typeName<qid>="单选题"`、`hidetext=""`、`answer<qid>=字母` |
| 多选 | `type<qid>=1`、`...`、`answers<qid>=字母串（升序）` |
| 填空 | `type<qid>=2`、`answer<qid>1..N=每空答案`、`blankNum<qid>= "1,2,"`（1 基序号+尾逗号） |
| 判断 | `type<qid>=3`、`answer<qid>= "true" / "false"` |

题型枚举（`cxapi/schema.py`，与作业同一套）：单选 0、多选 1、填空 2、判断 3、简答 4、名词解释 5、论述 6、计算 7、其他 8、分录 9、资料 10、连线 11、排序 13、完型填空 14、阅读理解 15、口语 18、听力 19、共用选项 20、测评 21。

### 3.3 签名算法（`cxapi/utils.py:71-108`，可逐行移植）

```python
def get_exam_signature(uid: int, qid: int, x: int, y: int):
    ts = get_ts()                                  # 毫秒时间戳
    r1 = random.randrange(0, 9); r2 = random.randrange(0, 9)
    a = f"{secrets.token_hex(16)}{ts[4:]}{r1}{r2}{qid or ''}"
    temp = 0
    for ch in a:
        temp = (temp << 5) - temp + ord(ch)
    salt = f"{r1}{r2}{(0x7fffffff & temp) % 10}"
    encVal = f"{uid}" + (f"_{qid}" if qid else "") + f"|{salt}"
    encVal2 = "".join(str(ord(c)) for c in encVal)
    b = len(encVal2) // 5
    c = int(encVal2[b] + encVal2[2 * b] + encVal2[3 * b] + encVal2[4 * b])
    d = len(encVal) // 2 + 1
    e = (c * int(encVal2[:10]) + d) % 0x7FFFFFFF
    pos = f"({x}|{y})"
    result = ""
    for ch in pos:
        temp = ord(ch) ^ floor(e / 0x7FFFFFFF * 0xFF)
        result += f"{temp:02x}"
        e = (c * e + d) % 0x7FFFFFFF
    return {"pos": f"{result}{secrets.token_hex(4)}",
            "rd": random.random(),
            "value": pos,
            "_edt": f"{ts}{salt}"}
```

关键点：`qid` 为空时 `encVal` 不含 `_qid` 段；`pos` 是点击坐标的逐字符 XOR 十六进制 + 4 字节随机尾巴；`rd` 直接返回随机浮点（原样作为 query 参数，requests 会 float→str）。

### 3.4 响应与成功判定

```json
{"status": "success", "msg": "...", "data": "<encLastUpdateTime>|<encRemainTime>|<enc>"}
```

- 成功：`resp.json()["status"] == "success"`（注意是**字符串** success，不是布尔 true）。
- 逐题 `tempSave=true` 成功后：解析 `data` 三段，更新 `last_update_time / enc_remain_time / enc`，再取下一题。
- 失败分支（源码显式处理）：`msg == "考试时间已用完,不允许提交答案!"` → 超时（停止）；`msg.endswith("分钟内不允许提交考试")` → 提交过频（等待/停止）；其他 → 直接报错并中止。

### 3.5 会话与风控（`cxapi/session.py:122-128`，【已验证】）

- 默认头：`User-Agent` = 学习通手机客户端 UA（`Dalvik/2.1.0 … com.chaoxing.mobile/ChaoXingStudy_3_5.1.4_…_{IMEI}`）、`X-Requested-With: com.chaoxing.mobile`。
- `IMEI` 每次运行随机：`secrets.token_hex(16)`。
- 风控验证码：响应跳到 `antispiderShowVerify.ac` 即触发；流程 `processVerifyPng.ac` 取图 → DdddOcr/OpenCV 识别 → `processVerify.ac` 提交。
- 人脸：`pan-yz.chaoxing.com/api/token/uservalid` 取 token → `pan-yz.chaoxing.com/upload?uploadtype=face` 上传（先做 LSB 扰动"破坏 hash 风控"）→ `exam-ans/exam/phone/face-compare` 得 `facekey` 与比对结果 → 拼 `faceDetectionResult` JSON 供 `phone/start`。

---

## 4. 错误对照、code-2 类比与风险

### 4.1 错误文案 → 语义 → 建议动作

| 文案（原文） | 出处 | 语义 | 建议动作 |
|---|---|---|---|
| `无效的参数：code-2！` | 本机作业日志 | 作业旧端点/令牌错（v2.1 结论） | 作业问题，不适用考试 |
| `无效参数！` | CxKitty `fetch()` `p.blankTips` | 会话/签名/题号越界（按迭代结束处理） | **不要重试**；视为逐题循环终止 |
| `考试已经提交` | 同上 | 已交卷/重复进入 | 中止并提示 |
| `无权限访问！` / `当前用户账号发生异常…` / `当前班级发生异常…` | 同上 | 权限/风控 | 中止 |
| `考试时间已用完,不允许提交答案!` | submit 响应 | 超时 | 立即停止，不本地硬交卷 |
| `…分钟内不允许提交考试` | submit 响应 | 交卷过频 | 停止，等提示时间 |
| `验证码错误！` / `人脸识别对比不通过…` | `start()` | 考试码/验证失败 | 中止，交人工 |
| `请使用指定的IP环境进行考试。` | 封面 | IP 白名单 | 中止 |
| `该试卷只允许在电脑考试客户端考试…` | 封面 | 禁止手机协议 | 降级到 PC 路线或中止 |
| `章节任务点未完成…` | 封面 | 未满足前置 | 中止并提示 |

### 4.2 风险清单（考试场景比作业严格得多）

| 风险 | 证据 | 处置 |
|---|---|---|
| 人脸识别 | CxKitty `cxapi/face_detection.py`（`face-compare` + `faceDetectionResult` 构造，含 `LiveDetectionStatus=1`、`ignoreLiveDetectionStatus=1`） | 默认**不支持自动人脸**；检测到 `input#faceRecognitionCompare` 非空即中止，交用户 |
| 人机验证码 | `processVerifyPng.ac`/`processVerify.ac`；考试封面 `input#captchaCheck`、`input#captchaCaptchaId` | 需要 OCR/打码依赖；未配置则中止 |
| 考试码 | `var needcode` + `start` 的 `code` 参数 | 让用户输入；空码会被判 `验证码错误！` |
| 超时自动交卷 | `expiredAutoSubmit:1`（`exam_test.html:66`）+ 考试说明第 3 条 | 本地倒计时；剩余 ≤30s 停止提交；不要与服务端抢交卷 |
| 逐题模式/单题限时 | OCSJS 注释（禁止整卷预览时各题独立页）；CxKitty 循环 `fetch(index)` | 先尝试 `phone/preview` 整卷；失败则**不提交**（只填/记录），避免半份交卷 |
| 切屏/离开页面 | 考试说明「离开或退出考试界面答题计时不停止」；教师端 JS 有 `exitexamForcesubmit`、`submitExitclientTime`（`scratch/exam/js/testPaper.js`，教师配置，学生端行为**未验证**） | 不复现"切屏检测"细节；建议无头流程不要模拟切屏事件，也不要在考试中重启会话 |
| IP 限制 / 仅电脑客户端 | 封面错误文案（§2.1 #2） | 命中即中止并提示用户 |
| 交卷即终局 | 手机协议无整卷回退保存（`main.py:298` 注释、`fallback_save()` 未实现） | 默认 `auto_submit=false`；有 invalid 题则不交卷 |
| 手机 UA 风控 | 手机协议依赖 `X-Requested-With: com.chaoxing.mobile` + 随机 IMEI | 与 PC 登录会话分开；同一账号并发/频繁切换端有风控风险（**未验证**具体阈值） |

---

## 5. 答题页 DOM 与逐题模式

### 5.1 手机端题目结构（【已验证】`cxapi/exam.py:69-193` 的解析依据）

```html
<div class="allAnswerList questionWrap singleQuesId ans-cc-exam" data="1234">   <!-- 整卷 -->
<div class="answerMain questionWrap singleQuesId ans-cc-exam" data="1234">      <!-- 单题 -->

  <div class="tit">
    <h3>单选题（共??题，??分）</h3>
    1.<span>（5.0分）</span>题干正文
  </div>

  <!-- 单选/多选 -->
  <input type="hidden" name="questionId" value="1234">
  <input type="hidden" name="type1234" value="0">
  <div class="answerList radioList" name="A"><cc>选项文本</cc></div>
  <input id="answer1234" value="">

  <!-- 填空 -->
  <div class="completionList objectAuswerList">
    <span class="grayTit">空1</span><textarea class="blanktextarea"></textarea>
  </div>

  <!-- 判断 -->
  <input id="answer1234" value="true|false">
</div>
```

解析要点：
- `questionId` 取自 `input[name='questionId']`；题型取自 `input[name^='type']` 的整数（考试页是 **`name` 前缀**，不是作业的 `answertype<qid>` id/name）。
- 题干来自 `div.tit`，且单题页前 4 个文本节点是「题型标题 + 题号 + 分值」，必须跳过（CxKitty 用 `children[4:]`，整卷页用 `children[2:]`）——这正是本仓库作业页「举报」混入题干的同构问题：**外壳/标题文本必须按固定偏移或显式节点剔除**。
- 选项 key 是 `div.answerList.radioList[name]` 的 `name` 属性（A/B/C/D），文本在子节点 `<cc>`。

### 5.2 PC 答题页（【社区代码】OCSJS `cx.ts:873-897,1042-1055`）

- 容器：`.questionLi`（整卷可能多个）。
- 题干：`.splitS-left .mark_name` 或 `.line_wid_half.fl,.line_wid_half.fr`；预览模式下为 `:scope > h3`、`:scope > div:not(.stem_answer,.mark_answer)`、`:scope > p`。
- 选项：`.answerBg .answer_p`、`.textDIV`、`.eidtDiv`。
- 题型：`input[name^="type"]`，过滤 `name` 命中 `/type\d+/` 的那个（干扰项很多）。
- 填空：`textarea` 或同域 `iframe`（富文本）；每题可能带 `[onclick*=saveQuestion]` 保存按钮。
- 翻页：`[onclick="getTheNextQuestion(1)"]`；逐题模式下脚本循环「答题 → sleep 3s → 点下一题 → sleep 1s」。
- 整卷预览页：`/mooc2/exam/preview`；不可预览时各题独立页面（源码注释原文）。

### 5.3 对本仓库解析器的建议（`cli_copy/core/exam_form.py`）

1. **容器回退顺序**：`div.questionWrap.singleQuesId` → `div.singleQuesId` → `.questionLi`（排除 `#fanyaMarking` 外壳，沿用 `_exclude_shell` 思路）。不要以 `div.TiMu` 作为主选择器。
2. **题干**：手机 `.tit`（按 class 区分 `answerMain`/`allAnswerList` 跳固定前缀）→ PC `h3.mark_name` / `.Zy_TItle .fontLabel` → `.splitS-left .mark_name`；统一清除题号、`(单选题)` 标记、「举报/收藏」、`\r\t\n`。
3. **题型**：考试页优先 `input[name^='type'][name~=/type\d+/]`，其次 `input[name='answertype<qid>']`、`typename` 文本；值映射用 §3.2 枚举。
4. **qid**：`input[name='questionId']`（手机）→ 容器 `data` → `id="question<qid>"` 数字 → 控件名尾部数字。
5. **选项**：手机 `div.answerList.radioList[name]`（取 name 与 `<cc>` 文本）；PC `.answerBg` 内 `span.num_option[data]` + `div.answer_p`。
6. **填空**：手机 `textarea.blanktextarea` 按顺序编号 `answer<qid>N`；PC `textarea[name=answerEditor<qid>N]`/`answer<qid>`。

### 5.4 逐题模式识别与安全中止

判定信号（任一命中即视为逐题/单题限时模式）：
- 页面/URL 含 `reVersionTestStartNew` 且带 `start=` 参数（每次只返回一题）；
- 存在 `[onclick="getTheNextQuestion(1)"]` 按钮；
- 只有 1 个题目容器且带 `answerMain` class；
- 页内出现「下一题」「上一题」「本题限时」等控件文本；
- 本仓库 `exam_form.is_single_question_mode()` 已覆盖 `nextQuestion`/「下一题」/`saveExamAnswer` 等启发式，但 `saveExamAnswer` 是**未证实的名字**，不应作为判据权重。

处置：
1. 若可调 `phone/preview`（需已开始考试）→ 一次取全卷；
2. 否则**只填不交**（若页面支持表单回放）或直接中止并提示「该考试为逐题模式，需人工完成交卷」；
3. **绝不**在部分题目未答/答案无效时提交（避免半份交卷）。

---

## 6. 对 v2.2 实现的调整建议（按优先级）

1. **修正端点清单**（`cli_copy/core/exam_form.py:36-41`）：加入已证实的 `reVersionSubmitTestNew`；把 `addStudentExam` / `saveExamAnswer` / `reVersionTestSubmitNew` / `reVersionTestSaveNew` 保留为「低置信候选」，只在页面 JS/HTML 中**实际出现**时才使用，不做默认。
2. **双协议探测**：答题页含 `form#submitTest` + `input#encRemainTime` + `questionWrap.singleQuesId.ans-cc-exam` → 手机协议；含 `.questionLi`/`input[name^=type]` → PC 页面协议；两者都没有 → 中止。
3. **优先页面表单回放**：沿用 v2.1 作业的 `work_form.build_submission()` 思路，任何 `action` 含 `exam/test` 的真实 form 都比自拼端点安全。
4. **手机协议实现要点**：`pos/rd/value/_edt` 签名、随机 `imei`、手机 UA/`X-Requested-With`、`isphone=true`、`tempSave` 区分保存/交卷、成功判 `status=="success"`、**解析 `data` 滚动 enc 三参数**。
5. **时间预算**：从 `encRemainTime` 计算剩余时间；提交前留 ≥30s；超时/「时间已用完」立即停。
6. **提交节奏**：沿用 CxKitty `persubmit_delay=15s`（可配置，默认 ≥5s），避免「分钟内不允许提交考试」。
7. **答案校验失败 → 不提交**：统计 `invalid/未答` 数量，按 `cover_rate` 阈值中止；`auto_submit` 默认 false，交卷前必须用户确认。
8. **日志字段**：每场考试记录 `exam_id / exam_answer_id / paper_id / relation_id / enc_task / 协议类型 / 每步 HTTP 状态 / 服务端 msg / 剩余时间 / 是否交卷`；这四项 id 是本轮唯一能稳定复现问题的抓手。
9. **不要复用作业的 `answerwqbid/totalQuestionNum` 语义**：考试协议没有 `answerwqbid`；`totalQuestionNum` 是作业页面 32hex 令牌，不要写入考试请求。
10. **单测**：为签名算法、`data` 三段解析、错误文案映射、逐题模式判定各加纯函数单测（不联网）。

---

## 7. AI 答题提示词：5 条可直接采用的规则 + 反例

### 7.1 现状（沿用 v2.1 调研，可复核）

- university-helper `backend/app/services/course/chaoxing/answer_providers/ai.py:88-106`：按题型给 system prompt，统一 `{"Answer": ["B"]}` / `{"Answer": ["A","C"]}` / `{"Answer": ["正确"]}`，明确「直接输出JSON，禁止解释、思考过程或Markdown」；user 追加「选项：每行一个」。
- chaoxing-fanya `api/answer.py:847-1160`：同契约；`_strip_json_block` 去围栏；判断题用「正确选项/错误选项」列表做文本→布尔映射，映射失败会**随机**（`:389-402`）——这是反面教材。
- 本仓库 `cli_copy/utils/llm_client.py:20-24` 已是更好的批量契约：`{"answers":[{"index":1,"answer":"B"}]}` + 题型规则说明。

### 7.2 规则

**R1｜结构化输出契约（硬约束）**
system 里写死 JSON schema 与题型枚举；`temperature=0`（重试也用 0）；`max_tokens` 给足；**要求「只输出 JSON 对象，不要 Markdown、不要解释、不要思考过程」**；解析前先去掉 ```json 围栏，再用 `json.loads`，失败视为无效。
> 反例：`请一步步详细分析并解释你的思路` → 模型输出大段文字/代码块 → 解析失败 → 上层静默丢弃 → 随机作答。

**R2｜选项锚定（字母必须来自给定选项）**
user 消息里每个选项写成 `A. 正文`（字母+正文成对）；规则显式写：
- 单选：仅 1 个字母，必须是给定字母之一；
- 多选：去重 + **按字母升序**（如 `A,C`，不是 `C,A`），禁止输出正文；
- 判断：只允许 `true`/`false`（中文「正确/错误」由校验层转）；
- 填空：多个空用中文分号 `；` 连接，空数必须与 `tiankongsize` 一致；不确定就留空，不要编造。
> 反例：「多选题请按你认为重要程度排序输出」→ 输出 `C,A` → 服务端按 `A,C` 判错；或输出 `B. props` 整句 → 校验失败。

**R3｜先推理后结构化（难题两段式，默认单段）**
普通题单次调用直接出 JSON；多选/计算/阅读理解等难题可两段：① pass1（temperature 0，只要求「针对每题给出 1-2 行关键依据」）② pass2（temperature 0，输入原题+依据，仍只输出 JSON）。**最终答案只能来自 pass2 的 JSON**，不得把推理文本拼进 `answer`。
> 反例：把「先推理后答」写进同一次输出（`"reasoning": "...", "answer": "..."` 且 schema 未约束）→ 模型把推理塞进 `answer` 字段。

**R4｜上下文注入 + 题干清洗**
system 注入课程名/章节/媒体名（本仓库 `answer_single(context=...)` 已预留 `{"course","media","kind"}`），user 题干前加题型与题号；题干必须清洗：去题号、`(单选题)`、`举报/收藏`、字体乱码（`font-cxsecret` 未解码时不要下发乱码，标 `unreadable` 跳过）；图片题干：有 OCR 用 `[公式: ...]`，否则传图片绝对 URL 给多模态模型。
> 反例：把「举报\n第4章组件\n在 Vue 组件中…」整段当题干 → 模型答非所问；字体乱码当正文 → 模型胡编。

**R5｜校验层 + 禁止静默随机**
所有答案过题型校验（字母∈选项、多选升序、判断严格 true/false、填空空数匹配、简答非空）；失败重试 1 次（temperature 0），仍失败标 `source=llm_invalid` → **该题不提交**（或按显式配置 `skip`），并在任务汇总里单列 `invalid/未答` 数量；任何情况下 **不允许「空结果 → 随机字母」**。
> 反例：chaoxing-fanya 式「判断题映射失败就 random」（`api/answer.py:389-402`）；本仓库 `deal_exam._answer_question` 的 `no_answer_action=="random"` 回退默认值必须改为 `skip`。

### 7.3 可直接粘贴的 system prompt（考试版，建议保留本仓库批量契约）

```text
你是学习通考试答题助手。只输出一个 JSON 对象，不要 Markdown/解释/思考过程。
输出格式：{"answers":[{"index":<题号>,"answer":"<答案>"}]}

规则：
1) 单选：1 个大写字母，必须来自题目给出的选项字母。
2) 多选：多个字母，去重并按字母升序，用英文逗号分隔（如 "A,C"）。
3) 判断：只输出 true 或 false。
4) 填空：按空格顺序，多空用中文分号"；"分隔；空数必须一致；不确定留空字符串。
5) 简答：输出简洁中文答案，不要展开分析。
6) 题干或选项不可读（乱码/缺图）时，answer 输出空字符串 ""，不要猜测。
课程上下文：{course}（{kind}）。请依据课程知识作答。
```

user 模板：

```text
第1题【单选】题干……
A. ……
B. ……
第2题【多选】题干……
A. ……  B. ……  C. ……  D. ……
（请对以上全部题目作答，返回 JSON）
```

### 7.4 参数与流程建议

- `temperature=0`（重试用 0）、`top_p` 默认；单题独立调用（考试不允许上下文串题导致错位）。
- 并发 ≤3 + 最小间隔 3s（参考 university-helper 限流），避免答题接口被风控。
- 先取整卷 → 本地排序题号 → 批量（如 5 题/批）请求 → 校验 → 汇总；批大小与 `max_tokens` 联动，避免截断 JSON。
- 提交前打印「题号 → 答案 → 校验结果」表，任何 invalid 都中止交卷（考试无回退保存）。

---

## 8. 结论状态表

| 结论 | 等级 |
|---|---|
| 考试提交端点为 `POST exam-ans/exam/test/reVersionSubmitTestNew`（手机协议），成功判定 `status=="success"` | 已验证（CxKitty 源码） |
| 签名 `pos/rd/value/_edt` 算法与随机坐标 | 已验证（源码，可移植） |
| 动态 `data` 三参数滚动 | 已验证（源码） |
| 逐题页 `reVersionTestStartNew` 参数集（`isphone/start/tag/remainTimeParam/relationAnswerLastUpdateTime/enc`） | 已验证（源码） |
| 考试列表 `goTest` 7 参数 + `TestRelationInfo.expiredAutoSubmit` | 已验证（本机抓包） |
| 超时自动交卷行为（服务端） | 页面说明 + 配置字段，**学生端实测未验证** |
| PC 考试页 DOM（`.questionLi`/`input[name^=type]`/`getTheNextQuestion`） | 社区代码（OCSJS） |
| PC 提交端点名（`addStudentExam` 等） | **未验证**，禁止写死 |
| 切屏检测具体实现/阈值 | **未验证** |
| 手机协议对「仅电脑客户端」考试的可用性 | **未验证**（封面错误文案表明会被拒） |
| 人脸/验证码自动处理的可合规性 | 技术可行但**不建议默认启用**；需用户显式授权 |

---

## 9. 参考链接（可复核）

上游源码（本机经镜像获取，GitHub 原链）：
- CxKitty（原仓库）：<https://github.com/SocialSisterYi/CxKitty>　镜像：<https://gitcode.com/gh_mirrors/cx/CxKitty>
  - `cxapi/exam.py`（考试协议全部端点/解析/提交，861 行；关键行 54-66、69-193、350-416、479-532、575-697、699-809）
  - `cxapi/utils.py:71-108`（提交签名）、`cxapi/session.py:25-28,122-128`（UA/验证码）、`cxapi/face_detection.py`（人脸链路）、`cxapi/classes.py:19,121-159`（手机端考试列表）、`resolver/question.py:313-491`（逐题节奏/交卷确认）、`config.yml:55-61`、`main.py:268-327`
- OCSJS：<https://github.com/ocsjs/ocsjs> → `packages/scripts/src/projects/cx.ts`（5.0）：考试页面识别 `:629-660`、`workOrExam` DOM `:873-897`、逐题翻页 `:1042-1055`、整卷预览 `/mooc2/exam/preview` `:452`
- university-helper：<https://github.com/sweetcornna/university-helper> → `backend/app/services/course/chaoxing/answer_providers/ai.py:88-106`（AI prompt 契约）
- chaoxing-fanya：<https://github.com/sweetcornna/chaoxing-fanya> → `api/answer.py:847-1160`（JSON 契约）、`:389-402`（判断题随机反例）

本仓库证据（只读）：
- 考试列表页 `goTest(...)` 的 7 参 / 6 参两种调用形态（列表页内联 JS，实测已确认第 2 参为考试 ID）
- 考试入口页 `examCheck` / `captchaCheck` / `needCode` 三个风控开关，以及未带验证参数时
  `/exam/test/examcheck` 返回 `{"msg":"安全验证不通过，请重新验证","type":"captchaVerify","status":false}`
- [cli_copy/core/exam_form.py](../cli_copy/core/exam_form.py#L36)（早期猜测的 SUBMIT_TOKENS；v2.2.2 起正式协议见
  [`cli_copy/core/exam_answer_page.py`](../cli_copy/core/exam_answer_page.py)）
- [cli_copy/functions/deal_exam_room.py](../cli_copy/functions/deal_exam_room.py)（列表入口流程：page-form 优先 + 猜测端点兜底）
- [docs/architecture.md](architecture.md)（v2.2.2 落地实现：`core/exam_answer_page.py` + `functions/exam_room_url.py`，见「考试答题页直连」小节）
- [docs/release-2.2.2.md](release-2.2.2.md)（v2.2.2 发布说明与真机验证数据）
- [docs/research-github.md](research-github.md)（v2.1 作业协议结论，作业/考试不可互相套用）

> 说明：GitHub 直链在本机不可访问，以上 GitHub URL 仅作引用标识；本文引用的行号/原文均来自 gitcode 镜像克隆副本（`CxKitty` HEAD：`SocialSisterYi/CxKitty` 镜像当前版本）。
