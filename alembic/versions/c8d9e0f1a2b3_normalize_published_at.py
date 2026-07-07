"""normalize_published_at

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-07 00:00:00.000000

既存 news_articles.published_at（RFC 2822 文字列）を UTC ISO 8601 に変換する。
"""
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, published_at FROM news_articles WHERE published_at IS NOT NULL")
    ).fetchall()
    for row_id, published in rows:
        try:
            dt = parsedate_to_datetime(published)
        except Exception:
            continue  # 既に ISO 形式など、RFC 2822 でないものはそのまま
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        conn.execute(
            sa.text("UPDATE news_articles SET published_at = :p WHERE id = :i"),
            {"p": dt.astimezone(timezone.utc).isoformat(), "i": row_id},
        )


def downgrade() -> None:
    pass  # 表記の正規化のため不可逆（実害なし）
