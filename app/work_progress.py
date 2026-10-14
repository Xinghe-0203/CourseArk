"""按稳定工作单元合并真实进度，与日志和答题统计独立。"""
from copy import deepcopy
import math


def reduce_progress(state: dict, event: str, payload: dict) -> dict:
    result = deepcopy(state or {'units': {}, 'sealed': False})
    units = result.setdefault('units', {})
    if event == 'work_plan':
        for item in payload.get('units', []):
            if isinstance(item, dict) and item.get('id'):
                key = str(item['id'])
                units[key] = {**item, **units.get(key, {}), 'id': key}
        if 'sealed' in payload:
            result['sealed'] = bool(payload['sealed'])
    elif payload.get('id'):
        key = str(payload['id'])
        unit = units.setdefault(key, {'id': key})
        # 重复/晚到的播放事件不能把终态工作回退为运行中。
        if unit.get('status') not in ('succeeded', 'failed', 'skipped', 'blocked'):
            unit.update(payload)
            if event == 'work_progress':
                unit['status'] = 'running'
    return result


def summarize(state: dict) -> dict:
    units = list((state or {}).get('units', {}).values())
    counts = {s: sum(u.get('status') == s for u in units) for s in ('succeeded', 'failed', 'skipped', 'blocked')}
    done = counts['succeeded']
    fractional = 0.0
    for unit in units:
        if unit.get('status') != 'running':
            continue
        try:
            ratio = float(unit.get('current', 0)) / float(unit.get('total', 0))
            if math.isfinite(ratio):
                fractional += max(0, min(ratio, .99))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    known = bool((state or {}).get('sealed')) and bool(units)
    return {'total': len(units), 'completed': done, **counts,
            'sealed': bool((state or {}).get('sealed')),
            'percent': round((done + fractional) * 100 / len(units), 1) if known else None,
            'active': [{'id': u['id'], 'name': u.get('name', ''), 'kind': u.get('kind', ''),
                        'current': u.get('current'), 'total': u.get('total')}
                       for u in units if u.get('status') == 'running'][:20]}
