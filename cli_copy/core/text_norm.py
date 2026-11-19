# -*- coding: utf-8 -*-
"""字体解密残留的部首码位归位。

学习通的加密字体里，被替换的汉字常常以「部首」字形出现：字体文件把真实汉字的
字形轮廓改写成某个部首的形状，解码时按轮廓反查，就只能查到部首码位。于是题干
与选项里会出现 ⽤（U+2F64）、⻚（U+2EDA）这类字符 —— 字形和「用」「页」几乎一样，
但码位不同，模型读起来像乱码，答题缓存的 key 也对不上。

本模块负责把这两个部首区段归位成常规汉字：

- U+2F00–U+2FDF（康熙部首）：NFKC 能映射 214 个，直接用 unicodedata。
- U+2E80–U+2EFF（CJK 部首补充）：NFKC 只映射 2 个，其余靠 _SUPPLEMENTAL 手工表。
- U+F900–U+FAD9（兼容表意）：NFKC 归位，顺带处理。

归一化是幂等的：常规汉字不在这些区段里，重复调用不会再变。
"""

import re
import unicodedata

# 需要归位的三个区段
_RADICAL_RE = re.compile(r"[\u2E80-\u2EFF\u2F00-\u2FDF\uF900-\uFAD9]")

# CJK 部首补充区（U+2E80–U+2EFF）→ 常规汉字。
# NFKC 对这一段基本无效，只能逐字给出目标字形；简体优先，宁可选「部首对应的
# 常规写法」也不留下部首码位。
_SUPPLEMENTAL = {
    0x2E80: "\u4E36",  # ⺀ CJK RADICAL REPEAT            → 丶
    0x2E81: "\u5382",  # ⺁ CJK RADICAL CLIFF             → 厂
    0x2E82: "\u4E59",  # ⺂ CJK RADICAL SECOND ONE        → 乙
    0x2E83: "\u4E59",  # ⺃ CJK RADICAL SECOND TWO        → 乙
    0x2E84: "\u4E59",  # ⺄ CJK RADICAL SECOND THREE      → 乙
    0x2E85: "\u4EBA",  # ⺅ CJK RADICAL PERSON            → 人
    0x2E86: "\u5182",  # ⺆ CJK RADICAL BOX               → 冂
    0x2E87: "\u51E0",  # ⺇ CJK RADICAL TABLE             → 几
    0x2E88: "\u5200",  # ⺈ CJK RADICAL KNIFE ONE         → 刀
    0x2E89: "\u5200",  # ⺉ CJK RADICAL KNIFE TWO         → 刀
    0x2E8A: "\u535C",  # ⺊ CJK RADICAL DIVINATION        → 卜
    0x2E8B: "\u5369",  # ⺋ CJK RADICAL SEAL              → 卩
    0x2E8C: "\u5C0F",  # ⺌ CJK RADICAL SMALL ONE         → 小
    0x2E8D: "\u5C0F",  # ⺍ CJK RADICAL SMALL TWO         → 小
    0x2E8E: "\u5C22",  # ⺎ CJK RADICAL LAME ONE          → 尢
    0x2E8F: "\u5C22",  # ⺏ CJK RADICAL LAME TWO          → 尢
    0x2E90: "\u5C22",  # ⺐ CJK RADICAL LAME THREE        → 尢
    0x2E91: "\u5C22",  # ⺑ CJK RADICAL LAME FOUR         → 尢
    0x2E92: "\u5DF3",  # ⺒ CJK RADICAL SNAKE             → 巳
    0x2E93: "\u5E7A",  # ⺓ CJK RADICAL THREAD            → 幺
    0x2E94: "\u5F50",  # ⺔ CJK RADICAL SNOUT ONE         → 彐
    0x2E95: "\u5F50",  # ⺕ CJK RADICAL SNOUT TWO         → 彐
    0x2E96: "\u5FC4",  # ⺖ CJK RADICAL HEART ONE         → 忄
    0x2E97: "\u5FC3",  # ⺗ CJK RADICAL HEART TWO         → 心
    0x2E98: "\u624C",  # ⺘ CJK RADICAL HAND              → 扌
    0x2E99: "\u6534",  # ⺙ CJK RADICAL RAP               → 攴
    0x2E9B: "\u65E1",  # ⺛ CJK RADICAL CHOKE             → 旡
    0x2E9C: "\u65E5",  # ⺜ CJK RADICAL SUN               → 日
    0x2E9D: "\u6708",  # ⺝ CJK RADICAL MOON              → 月
    0x2E9E: "\u6B79",  # ⺞ CJK RADICAL DEATH             → 歹
    0x2E9F: "\u6BCD",  # ⺟ CJK RADICAL MOTHER            → 母
    0x2EA0: "\u6C11",  # ⺠ CJK RADICAL CIVILIAN          → 民
    0x2EA1: "\u6C35",  # ⺡ CJK RADICAL WATER ONE         → 氵
    0x2EA2: "\u6C3A",  # ⺢ CJK RADICAL WATER TWO         → 氺
    0x2EA3: "\u706C",  # ⺣ CJK RADICAL FIRE              → 灬
    0x2EA4: "\u722B",  # ⺤ CJK RADICAL PAW ONE           → 爫
    0x2EA5: "\u722B",  # ⺥ CJK RADICAL PAW TWO           → 爫
    0x2EA6: "\u4E2C",  # ⺦ CJK RADICAL SIMPLIFIED HALF TREE TRUNK → 丬
    0x2EA7: "\u725B",  # ⺧ CJK RADICAL COW               → 牛
    0x2EA8: "\u72AD",  # ⺨ CJK RADICAL DOG               → 犭
    0x2EA9: "\u738B",  # ⺩ CJK RADICAL JADE              → 王
    0x2EAA: "\u758B",  # ⺪ CJK RADICAL BOLT OF CLOTH     → 疋
    0x2EAB: "\u76EE",  # ⺫ CJK RADICAL EYE               → 目
    0x2EAC: "\u793A",  # ⺬ CJK RADICAL SPIRIT ONE        → 示
    0x2EAD: "\u793A",  # ⺭ CJK RADICAL SPIRIT TWO        → 示
    0x2EAE: "\u7AF9",  # ⺮ CJK RADICAL BAMBOO            → 竹
    0x2EAF: "\u7CF8",  # ⺯ CJK RADICAL SILK              → 糸
    0x2EB0: "\u7E9F",  # ⺰ CJK RADICAL C-SIMPLIFIED SILK → 纟
    0x2EB1: "\u7F52",  # ⺱ CJK RADICAL NET ONE           → 罒
    0x2EB2: "\u7F52",  # ⺲ CJK RADICAL NET TWO           → 罒
    0x2EB3: "\u7F52",  # ⺳ CJK RADICAL NET THREE         → 罒
    0x2EB4: "\u7F52",  # ⺴ CJK RADICAL NET FOUR          → 罒
    0x2EB5: "\u7F52",  # ⺵ CJK RADICAL MESH              → 罒
    0x2EB6: "\u7F8A",  # ⺶ CJK RADICAL SHEEP             → 羊
    0x2EB7: "\u7F8A",  # ⺷ CJK RADICAL RAM               → 羊
    0x2EB8: "\u7F8A",  # ⺸ CJK RADICAL EWE               → 羊
    0x2EB9: "\u8001",  # ⺹ CJK RADICAL OLD               → 老
    0x2EBA: "\u807F",  # ⺺ CJK RADICAL BRUSH ONE         → 聿
    0x2EBB: "\u807F",  # ⺻ CJK RADICAL BRUSH TWO         → 聿
    0x2EBC: "\u6708",  # ⺼ CJK RADICAL MEAT              → 月
    0x2EBD: "\u81FC",  # ⺽ CJK RADICAL MORTAR            → 臼
    0x2EBE: "\u8279",  # ⺾ CJK RADICAL GRASS ONE         → 艹
    0x2EBF: "\u8279",  # ⺿ CJK RADICAL GRASS TWO         → 艹
    0x2EC0: "\u8279",  # ⻀ CJK RADICAL GRASS THREE       → 艹
    0x2EC1: "\u864E",  # ⻁ CJK RADICAL TIGER             → 虎
    0x2EC2: "\u8864",  # ⻂ CJK RADICAL CLOTHES           → 衤
    0x2EC3: "\u897F",  # ⻃ CJK RADICAL WEST ONE          → 西
    0x2EC4: "\u897F",  # ⻄ CJK RADICAL WEST TWO          → 西
    0x2EC5: "\u89C1",  # ⻅ CJK RADICAL C-SIMPLIFIED SEE  → 见
    0x2EC6: "\u89D2",  # ⻆ CJK RADICAL SIMPLIFIED HORN   → 角
    0x2EC7: "\u89D2",  # ⻇ CJK RADICAL HORN              → 角
    0x2EC8: "\u8BA0",  # ⻈ CJK RADICAL C-SIMPLIFIED SPEECH → 讠
    0x2EC9: "\u8D1D",  # ⻉ CJK RADICAL C-SIMPLIFIED SHELL  → 贝
    0x2ECA: "\u8DB3",  # ⻊ CJK RADICAL FOOT              → 足
    0x2ECB: "\u8F66",  # ⻋ CJK RADICAL C-SIMPLIFIED CART → 车
    0x2ECC: "\u8FB6",  # ⻌ CJK RADICAL SIMPLIFIED WALK   → 辶
    0x2ECD: "\u8FB6",  # ⻍ CJK RADICAL WALK ONE          → 辶
    0x2ECE: "\u8FB6",  # ⻎ CJK RADICAL WALK TWO          → 辶
    0x2ECF: "\u961D",  # ⻏ CJK RADICAL CITY              → 阝
    0x2ED0: "\u9485",  # ⻐ CJK RADICAL C-SIMPLIFIED GOLD → 钅
    0x2ED1: "\u9577",  # ⻑ CJK RADICAL LONG ONE          → 長
    0x2ED2: "\u9577",  # ⻒ CJK RADICAL LONG TWO          → 長
    0x2ED3: "\u957F",  # ⻓ CJK RADICAL C-SIMPLIFIED LONG → 长
    0x2ED4: "\u95E8",  # ⻔ CJK RADICAL C-SIMPLIFIED GATE → 门
    0x2ED5: "\u961D",  # ⻕ CJK RADICAL MOUND ONE         → 阝
    0x2ED6: "\u961D",  # ⻖ CJK RADICAL MOUND TWO         → 阝
    0x2ED7: "\u96E8",  # ⻗ CJK RADICAL RAIN              → 雨
    0x2ED8: "\u9752",  # ⻘ CJK RADICAL BLUE              → 青
    0x2ED9: "\u97E6",  # ⻙ CJK RADICAL C-SIMPLIFIED TANNED LEATHER → 韦
    0x2EDA: "\u9875",  # ⻚ CJK RADICAL C-SIMPLIFIED LEAF → 页
    0x2EDB: "\u98CE",  # ⻛ CJK RADICAL C-SIMPLIFIED WIND → 风
    0x2EDC: "\u98DE",  # ⻜ CJK RADICAL C-SIMPLIFIED FLY  → 飞
    0x2EDD: "\u98DF",  # ⻝ CJK RADICAL EAT ONE           → 食
    0x2EDE: "\u98DF",  # ⻞ CJK RADICAL EAT TWO           → 食
    0x2EDF: "\u98DF",  # ⻟ CJK RADICAL EAT THREE         → 食
    0x2EE0: "\u9963",  # ⻠ CJK RADICAL C-SIMPLIFIED EAT  → 饣
    0x2EE1: "\u6597",  # ⻡ CJK RADICAL HEAD              → 斗
    0x2EE2: "\u9A6C",  # ⻢ CJK RADICAL C-SIMPLIFIED HORSE → 马
    0x2EE3: "\u9AA8",  # ⻣ CJK RADICAL BONE              → 骨
    0x2EE4: "\u9B3C",  # ⻤ CJK RADICAL GHOST             → 鬼
    0x2EE5: "\u9C7C",  # ⻥ CJK RADICAL C-SIMPLIFIED FISH → 鱼
    0x2EE6: "\u9E1F",  # ⻦ CJK RADICAL C-SIMPLIFIED BIRD → 鸟
    0x2EE7: "\u5364",  # ⻧ CJK RADICAL C-SIMPLIFIED SALT → 卤
    0x2EE8: "\u9EA6",  # ⻨ CJK RADICAL SIMPLIFIED WHEAT  → 麦
    0x2EE9: "\u9EC4",  # ⻩ CJK RADICAL SIMPLIFIED YELLOW → 黄
    0x2EEA: "\u9EFE",  # ⻪ CJK RADICAL C-SIMPLIFIED FROG → 黾
    0x2EEB: "\u9F50",  # ⻫ CJK RADICAL J-SIMPLIFIED EVEN → 齐
    0x2EEC: "\u9F50",  # ⻬ CJK RADICAL C-SIMPLIFIED EVEN → 齐
    0x2EED: "\u9F7F",  # ⻭ CJK RADICAL J-SIMPLIFIED TOOTH → 齿
    0x2EEE: "\u9F7F",  # ⻮ CJK RADICAL C-SIMPLIFIED TOOTH → 齿
    0x2EEF: "\u9F99",  # ⻯ CJK RADICAL J-SIMPLIFIED DRAGON → 龙
    0x2EF0: "\u9F99",  # ⻰ CJK RADICAL C-SIMPLIFIED DRAGON → 龙
    0x2EF1: "\u9F9F",  # ⻱ CJK RADICAL TURTLE            → 龟
    0x2EF2: "\u9F9F",  # ⻲ CJK RADICAL J-SIMPLIFIED TURTLE → 龟
    0x2EF3: "\u9F9F",  # ⻳ CJK RADICAL C-SIMPLIFIED TURTLE → 龟
}


def normalize_radicals(value: str) -> str:
    """把部首码位归位成常规汉字；不含部首的文本原样返回。"""
    if not value or not _RADICAL_RE.search(value):
        return value
    out = []
    for ch in value:
        code = ord(ch)
        if 0x2E80 <= code <= 0x2EFF:
            out.append(_SUPPLEMENTAL.get(code, ch))
        elif 0x2F00 <= code <= 0x2FDF or 0xF900 <= code <= 0xFAD9:
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)