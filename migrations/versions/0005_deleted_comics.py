"""Traces of comics deleted from the web reader

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # SQLModel.metadata.create_all() may already have built the table.
    if _table_exists("deleted_comics"):
        return
    op.create_table(
        "deleted_comics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("trash_path", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("conflict_path", sa.String(), nullable=True),
        sa.Column("conflict_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_deleted_comics_filename", "deleted_comics", ["filename"])


def downgrade() -> None:
    if _table_exists("deleted_comics"):
        op.drop_table("deleted_comics")
