"""章节卡片解析，不依赖脚本序号或 catch 包装格式。"""
import json
import re
from lxml import etree


def parse_cards(html: str) -> list[dict]:
    root = etree.HTML(html or '')
    if root is None:
        return []
    decoder, found, seen = json.JSONDecoder(), [], set()
    for script in root.xpath('//script/text()'):
        for match in re.finditer(r'\bmArg\s*=\s*', script):
            try:
                value, _ = decoder.raw_decode(script[match.end():].lstrip())
            except (ValueError, TypeError):
                continue
            if not isinstance(value, dict) or not isinstance(value.get('attachments', []), list):
                continue
            fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if fingerprint not in seen:
                found.append(value)
                seen.add(fingerprint)
    return found
