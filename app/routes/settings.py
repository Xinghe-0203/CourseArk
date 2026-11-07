"""设置与预设路由。"""

import time

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .. import settings
from ..task_model import FEATURE_LABELS
from .. import main

router = APIRouter()


@router.get("/api/settings")
def get_settings():
    data = settings.masked()
    data["features"] = [{"key": key, "label": FEATURE_LABELS[key]}
                        for key in FEATURE_LABELS]
    data["storage"] = {**data.get('storage', {}), **settings.storage_info()}
    data["source_config"] = settings.source_config_info()
    return data


@router.patch("/api/settings")
def patch_settings(payload: dict = Body(default={})):
    return settings.apply_updates(payload)


@router.post("/api/settings/import-source")
def import_settings_from_source(payload: dict = Body(default={})):
    """从源 CLI 的 config.yml 导入 LLM/题库/请求参数并持久化到本地数据库"""
    only_empty = payload.get("only_empty", True)
    return settings.import_from_source_config(only_empty=bool(only_empty))


@router.get("/api/settings/export")
def export_settings():
    return Response(
        content=settings.export_json(),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="webui-settings.json"'},
    )


@router.post("/api/settings/import")
def import_settings(payload: dict = Body(default={})):
    content = payload.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="缺少 content 字段")
    try:
        return settings.import_json(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/presets")
def list_presets():
    return {"items": [main._preset_view(row) for row in main.db.list_presets()]}


@router.post("/api/presets", status_code=201)
def create_preset(payload: main.PresetCreate):
    preset_id = payload.id or ("preset-" + str(int(time.time() * 1000)))
    row = main.db.upsert_preset(preset_id, payload.name, payload.params)
    return main._preset_view(row)


@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str):
    if not main.db.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"ok": True}
