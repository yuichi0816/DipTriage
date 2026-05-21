"""add_market_segment_flags

Revision ID: f5a6b7c8d9e0
Revises: e3f4a5b6c7d8
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("include_nikkei225", sa.Integer(), nullable=True))
    op.add_column("app_settings", sa.Column("include_standard",  sa.Integer(), nullable=True))
    op.add_column("app_settings", sa.Column("include_growth",    sa.Integer(), nullable=True))
    op.add_column("app_settings", sa.Column("include_sp500",     sa.Integer(), nullable=True))

    # 既存レコードを market_scope の値から移行
    op.execute("UPDATE app_settings SET include_nikkei225 = 1 WHERE include_nikkei225 IS NULL")
    op.execute("UPDATE app_settings SET include_standard  = 0 WHERE include_standard  IS NULL")
    op.execute("UPDATE app_settings SET include_growth    = 0 WHERE include_growth    IS NULL")
    op.execute("""
        UPDATE app_settings
        SET include_sp500 = CASE
            WHEN market_scope = 'japan_only' THEN 0
            ELSE 1
        END
        WHERE include_sp500 IS NULL
    """)


def downgrade() -> None:
    op.drop_column("app_settings", "include_sp500")
    op.drop_column("app_settings", "include_growth")
    op.drop_column("app_settings", "include_standard")
    op.drop_column("app_settings", "include_nikkei225")
