"""答题缓存路由：统计、搜索、导入（内容/文件/源 CLI）、导出、删除与清空。"""

import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from .. import paths, question_bank_manager
from .. import main

router = APIRouter()


@router.get("/api/question-bank/stats")
def bank_stats(days: int = Query(default=7, ge=1, le=365)):
    return question_bank_manager.stats(days)


@router.delete("/api/question-bank")
def bank_clear():
    """清空全部本地答题缓存（只删 WebUI 自己的缓存，不动源 CLI 的题库文件）"""
    return {"deleted": question_bank_manager.clear_cache()}


@router.get("/api/question-bank/search")
def bank_search(q: str = "", question_type: str = "",
                limit: int = Query(default=50, ge=1, le=200),
                offset: int = Query(default=0, ge=0)):
    return question_bank_manager.search(q, question_type, limit, offset)


@router.get("/api/question-bank/source")
def bank_source():
    """源 CLI 题库信息：界面据此显示一键导入的数量"""
    return question_bank_manager.source_info()


@router.post("/api/question-bank/import-source")
def bank_import_source(payload: main.QuestionBankImportPath):
    """一键导入源 AutoChaoxingCLI 的题库（源文件只读）"""
    try:
        if payload.preview_only:
            info = question_bank_manager.source_info()
            if not info.get("exists"):
                raise HTTPException(status_code=404, detail="未找到源 CLI 的题库文件")
            if info.get("error"):
                raise HTTPException(status_code=400, detail=info["error"])
            records = question_bank_manager.read_db_records(paths.SOURCE_QUESTION_BANK)
            current = question_bank_manager._count_rows()
            preview = question_bank_manager.preview_records(records)
            preview["current_total"] = current
            return preview
        return question_bank_manager.import_from_source(overwrite=payload.overwrite)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未找到源 CLI 的题库文件")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/question-bank/import-db")
async def bank_import_db(request: Request):
    """
    导入题库 .db 文件：支持 multipart 上传，也支持 JSON 指定服务器本地路径
    """
    import tempfile

    overwrite = False
    preview_only = False
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploads = form.getlist("file")
        uploads = [item for item in uploads if getattr(item, "filename", "")]
        if not uploads:
            raise HTTPException(status_code=400, detail="缺少上传文件")
        overwrite = str(form.get("overwrite", "")).lower() in ("1", "true", "on", "yes")
        preview_only = str(form.get("preview_only", "")).lower() in ("1", "true", "on", "yes")

        # 允许同时选中 .db 与其 -wal / -shm 侧车文件：
        # 只上传 .db 会丢掉尚未回放（checkpoint）的数据，导致题目变少
        tmp_dir = tempfile.mkdtemp(prefix="cxbank-upload-")
        main_path = None
        try:
            for upload in uploads:
                # 只取文件名部分，避免路径穿越写入临时目录之外
                name = os.path.basename(str(upload.filename).replace("\\", "/"))
                if not name or name.startswith("."):
                    raise HTTPException(status_code=400, detail=f"非法的文件名: {upload.filename}")
                target = os.path.join(tmp_dir, name)
                with open(target, "wb") as handle:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                if not (name.endswith("-wal") or name.endswith("-shm")):
                    main_path = target
            if main_path is None:
                raise HTTPException(status_code=400,
                                    detail="未找到题库主文件（.db），仅收到 -wal/-shm 侧车文件")
            result = main._import_db_path(main_path, overwrite, preview_only)
            if len(uploads) == 1:
                result["wal_warning"] = (
                    "仅上传了 .db 文件。若该题库存在 .db-wal 侧车文件（CLI 未正常退出时常见），"
                    "其中的题目不会被导入。建议同时选中 .db、.db-wal、.db-shm 三个文件，"
                    "或直接使用“导入源题库”。"
                )
            return result
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    payload = main.QuestionBankImportPath(**await request.json())
    if not payload.path:
        raise HTTPException(status_code=400, detail="请提供题库文件路径或上传文件")
    return main._import_db_path(payload.path, payload.overwrite, payload.preview_only)


@router.get("/api/question-bank/export")
def bank_export(format: str = "json"):
    if format == "csv":
        content = question_bank_manager.export_csv()
        return Response(
            content="\ufeff" + content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="question_bank.csv"'},
        )
    return Response(
        content=question_bank_manager.export_json(),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="question_bank.json"'},
    )


@router.post("/api/question-bank/import")
def bank_import(payload: main.QuestionBankImport):
    if payload.format not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="format 必须是 json 或 csv")
    if payload.preview_only:
        return question_bank_manager.preview_import(payload.content, payload.format)
    return question_bank_manager.commit_import(payload.content, payload.format,
                                               payload.overwrite)


@router.delete("/api/question-bank/{question_hash}")
def bank_delete(question_hash: str):
    if not question_bank_manager.delete_by_hash(question_hash):
        raise HTTPException(status_code=404, detail="题目不存在")
    return {"ok": True}
