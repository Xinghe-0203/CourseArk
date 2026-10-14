# 字体参考数据与来源

`font_ref_cx.bin` 下载自 [OCS CDN](https://cdn.ocsjs.com/resources/font/font_ref_cx.bin)（2026-10-11）。FRB2 格式、参考特征和坐标协议参考 [ocsjs 字体解码实现](https://github.com/ocsjs/ocsjs/tree/main/packages/scripts/src/utils/font-decrypt)。OCS 代码采用 MIT 许可证，版权为 Copyright (c) 2022 enncy；完整许可保存在 [`OCS-MIT-LICENSE.txt`](OCS-MIT-LICENSE.txt)。

匹配特征以 [Adobe Source Han Sans（思源黑体）](https://github.com/adobe-fonts/source-han-sans) 字形为参考；该字体采用 SIL Open Font License 1.1。此处保留完整许可 [`SourceHanSans-OFL-LICENSE.txt`](SourceHanSans-OFL-LICENSE.txt)，仅分发字形匹配特征数据，不捆绑完整字体。

CourseArk 的 Python 匹配代码由本项目实现。它使用固定基线和两级位图距离补充轮廓匹配；低置信度字符保持未解决状态，不自动猜测。启动和测试会校验 FRB2 数据长度及参数。
