# CourseArk 2.2.2 计划：独立考试「粘贴答题页地址」直连作答

> 状态：**已实施完成并真机验证**（2026-10-18，v2.2.2）。发布说明与验证数据见
> [`docs/release-2.2.2.md`](release-2.2.2.md)，协议证据见 [`docs/research-exam.md`](research-exam.md)。

## 背景

v2.2.1 把独立考试失败定位为平台安全验证（考试说明页 `examCheck=1` / `captchaCheck=1`），
程序按设计安全中止。但用户仍需要真正完成考试，而验证凭证只存在于浏览器会话中，
程序既拿不到也不应绕过。

真机实验（2026-10-18 晚，`vue3第一章测试题`，10 题）确认：**带 `enc` 的答题页地址本身就是
平台签发的本次考试授权凭证**。有了它，程序可以只读打开答题页、逐题提交（`tempSave=true`）、
按响应 `data` 前进、最后一题 `tempSave=false` 交卷，全程不需要再碰验证码。

## 目标

1. 新建「独立考试」任务时可粘贴答题页地址，程序在该页面逐题 AI 作答并交卷；
2. 不粘贴地址时保持 v2.2.1 行为（按考试列表处理，平台验证处安全中止）；
3. 逐题进度、AI 答案、交卷结果在现有「AI 做题」与进度小窗中可见；
4. 不伪造成功、不绕过风控、不做无证据的端点猜测。

## 实现要点

- `cli_copy/core/exam_answer_page.py`：纯解析/构造（URL、答题页、提交报文、下一题地址、答案规范化）；
- `cli_copy/functions/exam_room_url.py`：`ExamRoomByUrl.do_finish(url)` 复用 `DealExam` 的
  LLM/缓存/逐题上报，逐题 `tempSave=true` → 末题 `tempSave=false`；
- `app/task_model.py::ExamParams` + `worker/runner.py` 分发：`exam` 带 `url` 才走新执行器；
- `frontend/src/components/NewTask.vue`：考试地址输入框与前端校验；
- `tools/check_work_page.py --exam-url`：只读自检；
- 测试：`tests/test_exam_answer_page.py`（31）、`tests/test_exam_room_url.py`（11），
  并更新参数快照用例。

## 关键协议结论（真机验证）

- 提交端点 PC 端就是 `POST /exam-ans/exam/test/reVersionSubmitTestNew`，query 只带
  `classId/courseId/testPaperId/testUserRelationId` + `cpi/tempSave/version=1`；
  多带 `keyboardDisplayRequiresUserAction=1` → 「提交失败：无效操作」。
- 服务端**不校验** `pos` 签名（普通浏览器也不签）；`pos` 只在客户端签名脚本里生成。
- 响应 `data="lastUpdateTime|remainTime|enc"` 必须用于下一题地址，否则「无效参数」。
- 判断题答案写 `true`/`false`（页面选项显示「对/错」），选择题写字母。
- 交卷后考试说明页显示「交卷成功」，考试列表状态变「已完成」。

## 验证

- `pytest tests cli_copy/tests -q` → 406 passed；smoke 56；vue_check 48/48；ui_check 47/47；
  frontend 25；desktop 8；`frontend run build` 通过；
- 真实考试：10/10 题作答并交卷成功（`status=success`，用时 21 分钟），平台显示已完成。

## 未做/边界

- 未实现浏览器自动化接管（Playwright 等），继续沿用「用户验证 + 程序作答」分工；
- 多选/填空/简答已有实现与单测，但未在真实考试逐类验证；
- `pos` 签名不做逆向，依赖服务端当前的宽容行为；若平台收紧需重新评估。
