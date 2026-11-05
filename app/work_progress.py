"""按稳定工作单元合并真实进度，与日志和答题统计独立。"""
import math


def reduce_progress(state: dict, event: str, payload: dict) -> dict:
    """合并一条进度事件，返回新 state（写时复制，不修改传入对象）。

    v2.4.0 T4：原来每个事件 deepcopy 整个 state（含全部 units）——每任务几百个
    单元 × 每秒多条播放事件时开销显著。改为单层复制：state/units 两个容器每次
    新建，但未被本事件触及的 unit dict 原样共享（它们在原 state 里也不会再被
    修改——本函数的所有写入都落在新建容器或复制后的 unit 上）。
    """
    src = state if isinstance(state, dict) else None
    result = {
        'units': dict(src.get('units') or {}) if src else {},
        'sealed': bool(src.get('sealed')) if src else False,
    }
    units = result['units']
    if event == 'work_plan':
        for item in payload.get('units', []):
            if isinstance(item, dict) and item.get('id'):
                key = str(item['id'])
                # payload 先展开、旧 unit 后展开：与 deepcopy 版语义一致（旧值优先）
                units[key] = {**item, **units.get(key, {}), 'id': key}
        if 'sealed' in payload:
            result['sealed'] = bool(payload['sealed'])
    elif payload.get('id'):
        key = str(payload['id'])
        old = units.get(key) or {'id': key}
        # 重复/晚到的播放事件不能把终态工作回退为运行中。
        if old.get('status') not in ('succeeded', 'failed', 'skipped', 'blocked'):
            units[key] = {**old, **payload, 'id': key}
            if event == 'work_progress':
                units[key]['status'] = 'running'
        else:
            units[key] = old
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
