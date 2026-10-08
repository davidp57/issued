"""Saved tag search API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.database import db_connection
from server.saved_searches import delete_saved_search, save_search
from server.tag_query import TagQuery

router = APIRouter(tags=["reader"])


class SavedSearchBody(BaseModel):
    name: str
    all: list[str] = []
    any: list[str] = []
    none: list[str] = []


@router.post("/api/saved-searches")
def api_saved_search_save(body: SavedSearchBody):
    """Save a tag combination under a name; an existing name gets the new criteria."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A saved search needs a name")
    query = TagQuery.build(all=body.all, any=body.any, none=body.none)
    if query.is_empty():
        raise HTTPException(status_code=422, detail="Select at least one tag")
    with db_connection() as conn:
        saved = save_search(conn, name, query)
    return {"ok": True, "id": saved["id"], "name": saved["name"]}


@router.delete("/api/saved-searches/{search_id:int}")
def api_saved_search_delete(search_id: int):
    """Delete a saved search. The tags themselves are untouched."""
    with db_connection() as conn:
        found = delete_saved_search(conn, search_id)
    if not found:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {"ok": True}
