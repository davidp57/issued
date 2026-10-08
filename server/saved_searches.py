"""Saved tag searches: named ``TagQuery`` rows in ``saved_searches``."""

from __future__ import annotations

from datetime import datetime, timezone

from .tag_query import TagQuery


def _row(row) -> dict:
    query = TagQuery.from_json(row["criteria"])
    return {
        "id": row["id"],
        "name": row["name"],
        "query": query,
        "description": query.describe(),
        "query_string": query.query_string(),
    }


def list_saved_searches(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT id, name, criteria FROM saved_searches ORDER BY name COLLATE NOCASE"
    )
    return [_row(row) for row in cur.fetchall()]


def has_saved_searches(conn) -> bool:
    return conn.execute("SELECT 1 FROM saved_searches LIMIT 1").fetchone() is not None


def get_saved_search(conn, search_id: int) -> dict | None:
    cur = conn.execute(
        "SELECT id, name, criteria FROM saved_searches WHERE id = ?", (search_id,)
    )
    row = cur.fetchone()
    return _row(row) if row else None


def save_search(conn, name: str, query: TagQuery) -> dict:
    """Create the search, or replace the criteria of the one with that name."""
    conn.execute(
        "INSERT INTO saved_searches (name, criteria, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET criteria = excluded.criteria",
        (name, query.to_json(), datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")),
    )
    conn.commit()
    cur = conn.execute(
        "SELECT id, name, criteria FROM saved_searches WHERE name = ?", (name,)
    )
    return _row(cur.fetchone())


def delete_saved_search(conn, search_id: int) -> bool:
    cur = conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
    conn.commit()
    return cur.rowcount > 0
