"""Comic deletion, trash page and trash API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.config import get_config
from server.deletion import DeletionError, delete_comic, forget, list_deleted, restore
from server.scanner import scan_file
from ._common import templates, _library_title, _reader_auth_enabled

router = APIRouter(tags=["reader"])


def _require_deletion():
    config = get_config()
    if not config.deletion.enabled:
        raise HTTPException(status_code=403, detail="Deletion is disabled")
    return config


@router.delete("/api/comic/{comic_uuid}")
def api_comic_delete(comic_uuid: str):
    """Delete or trash a comic, depending on ``[deletion] mode``."""
    config = _require_deletion()
    try:
        info = delete_comic(comic_uuid, config)
    except DeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, "filename": info.filename, "mode": info.mode}


@router.get("/trash")
def browse_trash(request: Request):
    """Deleted comics: restore from the trash, or forget the trace."""
    _require_deletion()
    return templates.TemplateResponse(
        request,
        "trash.html",
        {
            "title": f"Trash — {_library_title()}",
            "deleted_comics": list_deleted(),
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


@router.post("/api/trash/{trace_id:int}/restore")
def api_trash_restore(trace_id: int):
    """Move a trashed comic back into the library and scan it."""
    config = _require_deletion()
    try:
        path = restore(trace_id, config)
    except DeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    scan_file(path, config)
    return {"ok": True}


@router.delete("/api/trash/{trace_id:int}")
def api_trash_forget(trace_id: int):
    """Drop a trace, so a file with that name is imported again."""
    _require_deletion()
    try:
        forget(trace_id)
    except DeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True}
