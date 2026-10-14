"""终端序号选择：明确拒绝越界，重复序号只处理一次。"""
import re


def parse_selection(text, count):
    text = text.strip().lower()
    if text == 'q':
        return []
    if text in ('', 'all', '全部'):
        return list(range(count))
    parts = re.split('[,，]', text)
    if not parts or any(not p.strip().isdigit() for p in parts):
        raise ValueError('请输入有效序号，用逗号分隔')
    indices = list(dict.fromkeys(int(p.strip()) - 1 for p in parts))
    if any(i < 0 or i >= count for i in indices):
        raise ValueError('序号超出范围')
    return indices
