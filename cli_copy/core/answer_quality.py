# -*- coding: utf-8 -*-
"""答案/题干的乱码残留检测。

学习通的加密字体有两层风险：

1. 轮廓反查失败时，文本里会留下康熙部首、部首补充区、私用区或替换符；
2. 字体数据缺失/轮廓微扰时，文本里会留下一批「能正常显示、但不是原字」的
   汉字（例如 `忑速忝忔忞忟热处忕为`、`慪憮怇忿的愴法悵`）。模型会照着这些字
   作答，提交后在学习通页面上就是不折不扣的乱码答案。

第 1 类靠 Unicode 区段就能识别，无需猜测。第 2 类没有码位特征，需要用统计特征：
这类残留绝大多数落在 **GB2312（大陆常用字表）之外**，且在一段短文本里占比很高。
判定需要同时满足三个条件：

- ``uncommon``：不在 GB2312 内的汉字，个数 ≥3、占全句汉字 ≥30%；
- 其中至少有一个 ``exotic``：GB2312 **和** Big5 都装不下的生僻码位（强证据）。

最后一条是防误杀的关键：纯繁体文本（`社會主義核心價值觀`、`液壓傳動系統`）虽然
uncommon 占比很高，但两套字符集都能覆盖、exotic 为 0，不会被误判；
`饕餮`、`魑魅魍魉` 这类正常生僻词本身就在 GB2312 内，也不会命中。

检测结果只用于拦截/标记，不改写题干或答案。
"""

import re
import unicodedata
from functools import lru_cache

# 加密字体残留的码位区段：私用区、替换符、康熙部首、部首补充、兼容表意
_RESIDUE_RANGES = (
    (0xE000, 0xF8FF),
    (0xFFFD, 0xFFFD),
    (0xF0000, 0x10FFFF),
    (0x2E80, 0x2EFF),
    (0x2F00, 0x2FDF),
    (0xF900, 0xFAFF),
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
# 常见 mojibake 片段（UTF-8 被按单字节解码后的典型残片）
_MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â€|ï¼|ï»¿)")

# 生僻残留判定阈值（见模块文档）：GB2312 之外的字数、占比，且至少一个
# 「两套字符集都装不下」的强证据字
_UNCOMMON_MIN = 3
_RATIO_MIN = 0.3
_EXOTIC_MIN = 1


def _is_han(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF      # CJK 扩展 A
        or 0x4E00 <= code <= 0x9FFF   # CJK 基本区
        or 0xF900 <= code <= 0xFAFF   # 兼容表意
        or 0x20000 <= code <= 0x2FA1F # 扩展 B-F
    )


def _is_residue(char: str) -> bool:
    """字体加密残留码位（逐字符判，比正则快一个量级）。"""
    code = ord(char)
    for low, high in _RESIDUE_RANGES:
        if low <= code <= high:
            return True
    return False


def _encodable(char: str, encoding: str) -> bool:
    try:
        char.encode(encoding)
    except (UnicodeEncodeError, TypeError):
        return False
    return True


def _is_common(char: str) -> bool:
    """是否属于 GB2312（大陆常用字表）。"""
    return _encodable(char, "gb2312")


def _is_exotic(char: str) -> bool:
    """既不在 GB2312 也不在 Big5：字体残留的强证据。"""
    return not _encodable(char, "gb2312") and not _encodable(char, "big5")


def _rare_issue(text: str, label: str) -> str:
    """生僻字残留判定；不满足阈值返回空串。

    字体残留的典型形状是「一句里混进一批 GB2312 装不下的字」，而且这批字里
    至少有部分是两套常用字符集都装不下的生僻码位。纯繁体文本（`社會主義核心
    價值觀`、`液壓傳動系統`）虽然同样不在 GB2312 内，但两套字符集都能覆盖，
    不会命中 `_EXOTIC_MIN` 这条强证据，因此不会被误杀。
    """
    han = [char for char in text if _is_han(char)]
    if not han:
        return ""
    uncommon = [char for char in han if not _is_common(char)]
    exotic = [char for char in uncommon if _is_exotic(char)]
    ratio = len(uncommon) / len(han)
    if (
        len(uncommon) < _UNCOMMON_MIN
        or ratio < _RATIO_MIN
        or len(exotic) < _EXOTIC_MIN
    ):
        return ""
    sample = "".join(uncommon[:6])
    return (
        f"{label}里有 {len(uncommon)}/{len(han)} 个生僻字（{sample}…），"
        "疑似字体加密未完全解出"
    )


def encoding_issues(text: str, label: str = "答案") -> list[str]:
    """返回文本里的乱码风险原因列表（空列表 = 未发现异常）。

    同一段文本会在「搜索列表 / 统计 / 命中校验」里被反复检查，所以缓存分析结果；
    缓存里放的是不可变 tuple，每次调用再复制成 list，调用方随便改也不会污染缓存。
    """
    return list(_analyze_cached(str(text or ""), label))


@lru_cache(maxsize=4096)
def _analyze_cached(value: str, label: str) -> tuple[str, ...]:
    return _analyze(value, label)


def _analyze(value: str, label: str) -> tuple[str, ...]:
    if not value.strip():
        return ()

    issues = []
    residue = [char for char in value if _is_residue(char)]
    if residue:
        names = [f"{char}(U+{ord(char):04X})" for char in residue[:4]]
        issues.append(f"{label}含字体解密残留码位：{'、'.join(names)}")

    if _CONTROL_RE.search(value):
        issues.append(f"{label}含不可见控制字符")

    if _MOJIBAKE_RE.search(value):
        issues.append(f"{label}含常见乱码片段（Ã/Â/â€/ï¼）")

    # 部首/兼容区先归位再判断生僻字，避免同一段文字被重复计数。
    normalized = value
    if residue:
        normalized = "".join(
            unicodedata.normalize("NFKC", char)
            if _is_residue(char) else char
            for char in value
        )
    rare = _rare_issue(normalized, label)
    if rare:
        issues.append(rare)
    return tuple(issues)


def question_encoding_issues(text: str) -> list[str]:
    """题干/选项的乱码检测（阈值与答案一致，标签改成「题干」）。"""
    return encoding_issues(text, label="题干")


def is_suspicious_answer(text: str) -> bool:
    return bool(encoding_issues(text, label="答案"))
