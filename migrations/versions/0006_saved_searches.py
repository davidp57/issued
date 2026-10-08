"""Saved tag searches

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
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
    if _table_exists("saved_searches"):
        return
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("criteria", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_saved_searches_name", "saved_searches", ["name"], unique=True)


def downgrade() -> None:
    if _table_exists("saved_searches"):
        op.drop_table("saved_searches")
