"""总览聚合路由。"""

import time

from fastapi import APIRouter

from .. import accounts, question_bank_manager
from ..task_model import FEATURE_LABELS
from .. import main

router = APIRouter()


@router.get("/api/overview")
def overview(level: str = "all"):
    """总览聚合（v2.4.0 T7）；level=problem 时 recent_events 只含告警与错误。"""
    db = main.db
    day_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    stats = db.dashboard_stats(day_start)
    tasks_today = db.count_tasks({"since": day_start})
    active = db.list_tasks({"status": "running,starting,logging_in,loading_courses,pausing,stopping"}, limit=50)
    paused = db.list_tasks({"status": "paused"}, limit=50)
    pending = db.list_tasks({"status": "pending"}, limit=50)
    # level=problem：总览只关心需要处理的问题（warning/error），日志噪音不上屏
    recent = (db.problem_events(limit=60) if level == "problem"
              else db.recent_events(limit=60))
    bank = question_bank_manager.stats()
    account_summary = accounts.summary()
    queue_rows = []
    for row in (active + paused + pending)[:60]:
        queue_rows.append({
            "id": row["id"],
            "account_id": row["account_id"],
            "account_label": row["account_label"],
            "course_name": row["course_name"],
            "feature": row["feature"],
            "feature_label": FEATURE_LABELS.get(row["feature"], row["feature"]),
            "status": row["status"],
            "stage": row["stage"],
            "stats": main._json(row["stats_json"]),
            "created_at": row["created_at"],
        })
    return {
        "accounts": account_summary,
        "tasks": {
            "active": db.count_tasks({"status": "running,starting,logging_in,loading_courses,pausing,stopping"}),
            "paused": db.count_tasks({"status": "paused"}),
            "pending": db.count_tasks({"status": "pending"}),
            "today_total": tasks_today,
        },
        "today": stats,
        "workers": main.manager.snapshot(),
        "question_bank": {
            "total": bank["total"],
            "hits": bank["hits"],
            "hit_rate": bank["hit_rate"],
            "lookups": bank["lookups"],
        },
        "queue": queue_rows,
        "recent_events": [main._event_view(item) for item in recent],
    }
