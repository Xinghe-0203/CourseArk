"""
AutoChaoxingCLI - 字体解密模块

处理超星学习通的字体反爬虫加密（font-cxsecret）。
支持两种解密方式：
1. 精确轮廓比对 — 将字形轮廓哈希与参考映射表比对
2. 两级位图匹配 — 针对轮廓微扰，拒绝低置信度映射
"""

import base64
import hashlib
import io
import json
import os
import re

from fontTools.ttLib import TTFont
from lxml import etree
from loguru import logger

from core.paths import get_resource_path

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


# 解码器与题目解析器共享判定，防止字体别名/大小写漏过未识别检查。
SECRET_FONT_PREDICATE = (
    'contains(concat(" ", translate(normalize-space(@class), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), " "), " font-cxsecret ")'
    ' or contains(translate(@style, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "cxsecret")'
)


class FontDecoder:
    """字体解密器 - 解密超星学习通页面中的font-cxsecret加密"""

    def __init__(self):
        self._ref_map = _load_reference_map()

    def extract_font_data(self, html: str) -> bytes | None:
        """从加密字体声明提取数据，支持字体别名、大小写和 Base64 换行。"""
        root = etree.HTML(html)
        candidates = re.findall(r'@font-face\s*\{.*?\}', html, re.DOTALL | re.I)
        candidates = [block for block in candidates if re.search(r'(?:font-)?cxsecret', block, re.I)]
        if root is not None:
            candidates.extend(''.join(node.itertext()) for node in root.xpath('//style[translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="cxsecretstyle"]'))
        for block in candidates:
            match = re.search(r"base64,([A-Za-z0-9+/=\s]+)[\"'\)]", block, re.I)
            if match:
                try:
                    return base64.b64decode(re.sub(r'\s+', '', match.group(1)), validate=True)
                except (ValueError, TypeError):
                    logger.warning('字体 Base64 数据无效，保留待处理标记')
        return None

    @staticmethod
    def _clear_secret_marker(node):
        node.set('class', ' '.join(c for c in node.get('class', '').split() if c.lower() != 'font-cxsecret'))
        node.attrib.pop('data-font-unresolved', None)
        node.attrib.pop('data-font-reason', None)
        if 'cxsecret' in node.get('style', '').lower():
            node.set('style', re.sub(r'font-family\s*:\s*[^;]*(?:font-)?cxsecret[^;]*;?', '', node.get('style', ''), flags=re.I))

    def decode_page(self, html: str) -> str:
        """解密整个页面的字体加密内容"""
        font_data = self.extract_font_data(html)
        if font_data is None:
            root = etree.HTML(html)
            if root is None:
                return html
            nodes = root.xpath(f'//*[{SECRET_FONT_PREDICATE}]')
            declared = bool(root.xpath('//style[translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="cxsecretstyle"] | //link[contains(translate(@href,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"cxsecret")]')) or bool(re.search(r'@font-face\s*\{[^}]*cxsecret', html, re.I | re.S))
            for node in nodes:
                private_glyphs = any(0xE000 <= ord(char) <= 0xF8FF or 0xF0000 <= ord(char) <= 0x10FFFD for char in ''.join(node.itertext()))
                if declared or private_glyphs or node.get('data-font-unresolved') == 'true':
                    node.set('data-font-unresolved', 'true')
                    node.set('data-font-reason', '存在加密字体声明或私用字形，但字体数据缺失或无效')
                else:
                    # 页面模板会给普通题目也加此类名；类名本身不是加密证据。
                    self._clear_secret_marker(node)
            logger.debug('页面未包含可读取的加密字体，已区分普通题目和缺失字体')
            return etree.tostring(root, encoding='unicode', method='html')
        root = etree.HTML(html)
        if root is None:
            return html
        char_map = self._build_mapping_via_contour(font_data)
        try:
            with TTFont(io.BytesIO(font_data)) as font:
                codes = {chr(c) for c in (font.getBestCmap() or {})}
            nodes = root.xpath(f'//*[{SECRET_FONT_PREDICATE}]')
            used = set(''.join(''.join(n.itertext()) for n in nodes)) & codes
            missing = used - set(char_map)
            if missing:
                from core.font_bitmap import decode_characters
                char_map.update(decode_characters(font_data, missing))
        except Exception as exc:
            logger.debug(f'字体补充识别不可用: {type(exc).__name__}')
        trusted = bool(char_map)
        if not char_map:
            logger.warning("字体解密映射为空，保留待处理标记")
            for node in root.xpath(f'//*[{SECRET_FONT_PREDICATE}]'):
                node.set('data-font-unresolved', 'true')
                node.set('data-font-reason', '字体数据无法解析或未获得可靠字形映射')
            return etree.tostring(root, encoding='unicode', method='html')

        root = etree.HTML(html)
        if root is None:
            return html
        try:
            with TTFont(io.BytesIO(font_data)) as font:
                encrypted = {chr(c) for c in (font.getBestCmap() or {})}
        except Exception:
            encrypted = set(char_map)
        def replace(text):
            return ''.join(char_map.get(c, c) for c in text or '')
        processed = set()
        def walk(node):
            processed.add(node)
            if node.tag in ('script', 'style'):
                return
            if node.text:
                node.text = replace(node.text)
            for child in node:
                walk(child)
                if child.tail:
                    child.tail = replace(child.tail)
        secret_nodes = root.xpath(f'//*[{SECRET_FONT_PREDICATE}]')
        originals = {node: ''.join(node.itertext()) for node in secret_nodes}
        for node in secret_nodes:
            original = originals[node]
            unresolved = (set(original) & encrypted) - set(char_map)
            if node not in processed:
                walk(node)
            if unresolved or not trusted:
                node.set('data-font-unresolved', 'true')
                node.set('data-font-reason', '部分加密字形未获得可靠映射')
            else:
                self._clear_secret_marker(node)
        return etree.tostring(root, encoding='unicode', method='html')

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
