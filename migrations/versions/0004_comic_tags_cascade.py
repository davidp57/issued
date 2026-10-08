"""Rebuild comic_tags with ON DELETE CASCADE

Databases initialised with ``SQLModel.metadata.create_all`` before 0003 got a
``comic_tags`` table whose foreign keys have no ``ON DELETE CASCADE`` (0003
skips tables that already exist).  Deleting a tagged comic then fails with
``FOREIGN KEY constraint failed`` and aborts the library scan.

SQLite cannot alter a foreign key in place, so the table is rebuilt when its
definition lacks the cascade.  Orphan rows, if any, are dropped on the way.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _comic_tags_sql() -> str | None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='comic_tags'")
    ).fetchone()
    return row[0] if row else None


def upgrade() -> None:
    sql = _comic_tags_sql()
    if sql is None or "ON DELETE CASCADE" in sql.upper():
        return

    op.execute(
        """
        CREATE TABLE comic_tags_new (
            comic_id INTEGER NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
            tag_id   INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
            PRIMARY KEY (comic_id, tag_id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO comic_tags_new (comic_id, tag_id)
        SELECT comic_id, tag_id FROM comic_tags
        WHERE comic_id IN (SELECT id FROM comics)
          AND tag_id IN (SELECT id FROM tags)
        """
    )
    op.execute("DROP TABLE comic_tags")
    op.execute("ALTER TABLE comic_tags_new RENAME TO comic_tags")


def downgrade() -> None:
    # The cascade is a strict improvement; nothing to undo.
    pass
