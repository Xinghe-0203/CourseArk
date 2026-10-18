"""任务点进度解析（models.course.parse_mission_progress）的单元测试。

真实页面把「已完成任务点: 109/125」放在 h2 的文本节点里、只把 109 放进 span，
旧实现只读 span 得到 109/0，前端因此显示 0/0。这里用合成 HTML 覆盖几种布局。
"""

from models.course import Course


def test_span_only_number_with_ratio_in_h2_text():
    html = """
    <div class="fanyaChapterWhite">
      <div class="chapter_head">
        <h2>已完成任务点: <span>109</span>/<span>125</span></h2>
      </div>
    </div>
    """
    assert Course.parse_mission_progress(html) == (109, 125)


def test_ratio_in_single_text_node():
    html = "<div class='chapter_head'><h2>已完成任务点: 27/27</h2></div>"
    assert Course.parse_mission_progress(html) == (27, 27)


def test_fullwidth_colon_and_spaces():
    html = "<h2>已完成任务点： 3/ 9</h2>"
    assert Course.parse_mission_progress(html) == (3, 9)


def test_page_text_fallback_when_no_chapter_head():
    html = "<html><body><div>学习进度 · 已完成任务点 12/20</div></body></html>"
    assert Course.parse_mission_progress(html) == (12, 20)


def test_ratio_without_mission_keyword_is_ignored():
    html = "<div class='x'>本章 1/2 个视频</div>"
    assert Course.parse_mission_progress(html) == (0, 0)


def test_empty_page_returns_zero():
    for html in ("", None, "<html><body>参数传递不正确</body></html>"):
        assert Course.parse_mission_progress(html) == (0, 0)
