"""
AutoChaoxingCLI - 字体解密模块

处理超星学习通的字体反爬虫加密（font-cxsecret）。
支持两种解密方式：
1. 字形名称映射 — 利用字体文件中字形名称包含真实Unicode信息
2. 轮廓比对 — 将字形轮廓哈希与参考映射表比对
"""

import base64
import hashlib
import io
import json
import os
import re

from fontTools.ttLib import TTFont
from loguru import logger

from core.paths import get_resource_path

# 标准字体名称
STANDARD_FONT_NAME = "SourceHanSansCN-Normal"

# 模块级缓存
_cached_ref_map = None
_ref_map_loaded = False


def _load_reference_map() -> dict[str, str] | None:
    """加载参考映射表（模块级缓存）"""
    global _cached_ref_map, _ref_map_loaded
    if _ref_map_loaded:
        return _cached_ref_map
    ref_map_path = get_resource_path(os.path.join("resource", "font_map_table.json"))
    if not os.path.exists(ref_map_path):
        logger.warning(f"参考字体映射文件未找到: {ref_map_path}")
        _ref_map_loaded = True
        return None
    try:
        with open(ref_map_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not raw:
            _ref_map_loaded = True
            return None
        sample_key = next(iter(raw))
        sample_val = raw[sample_key]
        if len(str(sample_key)) == 32 and sample_val and not all(c in '0123456789abcdef' for c in str(sample_val)):
            _cached_ref_map = raw
        else:
            ref_map = {}
            for glyph_name, contour_hash in raw.items():
                glyph_name = str(glyph_name)
                contour_hash = str(contour_hash)
                if glyph_name.startswith("uni") and len(glyph_name) >= 7:
                    try:
                        real_char = chr(int(glyph_name[3:], 16))
                        if contour_hash not in ref_map:
                            ref_map[contour_hash] = real_char
                    except (ValueError, OverflowError):
                        continue
                elif len(glyph_name) == 1 and len(contour_hash) == 32:
                    if contour_hash not in ref_map:
                        ref_map[contour_hash] = glyph_name
            _cached_ref_map = ref_map if ref_map else None
        _ref_map_loaded = True
        if _cached_ref_map:
            logger.success(f"已加载 {len(_cached_ref_map)} 条轮廓映射")
        return _cached_ref_map
    except Exception as e:
        logger.error(f"加载参考映射文件失败: {e}")
        _ref_map_loaded = True
        return None


class FontDecoder:
    """字体解密器 - 解密超星学习通页面中的font-cxsecret加密"""

    def __init__(self):
        self._ref_map = _load_reference_map()

    def extract_font_data(self, html: str) -> bytes | None:
        """从HTML中提取加密字体数据（Base64编码的TTF字体）"""
        font_blocks = re.findall(r'@font-face\s*\{.*?\}', html, re.DOTALL)
        for block in font_blocks:
            if 'font-cxsecret' not in block:
                continue
            m = re.search(r'base64,([A-Za-z0-9+/=]+?)[\'"\)]', block)
            if m:
                try:
                    return base64.b64decode(m.group(1))
                except Exception as e:
                    logger.error(f"字体 Base64 解码失败: {e}")
                    return None
        m = re.search(r'font-family:\s*["\']?font-cxsecret["\']?.*?base64,([A-Za-z0-9+/=]+)', html, re.DOTALL)
        if m:
            try:
                return base64.b64decode(m.group(1))
            except Exception as e:
                logger.error(f"字体 Base64 解码失败: {e}")
        return None

    def decode_page(self, html: str) -> str:
        """解密整个页面的字体加密内容"""
        font_data = self.extract_font_data(html)
        if font_data is None:
            logger.debug("页面中未检测到 font-cxsecret 加密字体，跳过解密")
            return html
        char_map = self._build_mapping_via_glyph_name(font_data)
        if char_map is None:
            logger.debug("字形名称映射无结果，尝试轮廓比对...")
            char_map = self._build_mapping_via_contour(font_data)
        if not char_map:
            logger.warning("字体解密映射为空，返回原始HTML")
            return html

        def _replace(m):
            chars = list(m.group(0))
            for i, c in enumerate(chars):
                if c in char_map:
                    chars[i] = char_map[c]
            return "".join(chars)

        result = re.sub(r'>([^<]+)</', _replace, html)
        result = re.sub(r'class="[^"]*font-cxsecret[^"]*"', '', result)
        result = re.sub(r'style="[^"]*font-family:\s*font-cxsecret[^;]*;?"', '', result)
        return result

    def _build_mapping_via_glyph_name(self, font_data: bytes) -> dict[str, str] | None:
        """通过字形名称构建字符映射"""
        try:
            font = TTFont(io.BytesIO(font_data))
            name_to_glyph = {}
            for table in font.get("cmap").tables:
                for char_code, glyph_name in table.cmap.items():
                    name_to_glyph[glyph_name] = char_code
            char_map = {}
            for glyph_name, fake_codepoint in sorted(name_to_glyph.items(), key=lambda x: x[0]):
                if glyph_name.startswith("uni"):
                    real_codepoint_str = glyph_name[3:]
                    if real_codepoint_str and len(real_codepoint_str) <= 6:
                        try:
                            real_codepoint = int(real_codepoint_str, 16)
                            fake_char = chr(fake_codepoint)
                            real_char = chr(real_codepoint)
                            if fake_char != real_char:
                                char_map[fake_char] = real_char
                        except ValueError:
                            continue
            font.close()
            return char_map if char_map else None
        except Exception as e:
            logger.error(f"字形名称映射失败: {e}")
            return None

    def _build_mapping_via_contour(self, font_data: bytes) -> dict[str, str]:
        """通过字形轮廓哈希构建字符映射"""
        if not self._ref_map:
            logger.error("轮廓比对参考映射不可用")
            return {}
        try:
            font = TTFont(io.BytesIO(font_data))
            cmap = font.getBestCmap()
            char_map = {}
            glyf_table = font.get("glyf")
            for fake_codepoint in cmap:
                glyph_name = cmap[fake_codepoint]
                glyph = glyf_table[glyph_name]
                contour_hash = self._glyph_contour_hash(glyph)
                if contour_hash and contour_hash in self._ref_map:
                    fake_char = chr(fake_codepoint)
                    real_char = self._ref_map[contour_hash]
                    if fake_char != real_char:
                        char_map[fake_char] = real_char
            font.close()
            return char_map
        except Exception as e:
            logger.error(f"轮廓比对映射失败: {e}")
            return {}

    @staticmethod
    def _glyph_contour_hash(glyph) -> str | None:
        """计算字形轮廓的哈希值"""
        try:
            if glyph.numberOfContours <= 0:
                return None
            pos_data = []
            last_index = 0
            for i in range(glyph.numberOfContours):
                end_point = glyph.endPtsOfContours[i]
                for j in range(last_index, end_point + 1):
                    x, y = glyph.coordinates[j]
                    flag = glyph.flags[j] & 0x01
                    pos_data.append(f"{x}{y}{flag}")
                last_index = end_point + 1
            pos_bin = "".join(pos_data)
            return hashlib.md5(pos_bin.encode()).hexdigest()
        except Exception:
            return None
