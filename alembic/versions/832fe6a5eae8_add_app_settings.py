"""add_app_settings

Revision ID: 832fe6a5eae8
Revises: 23b2a53ff851
Create Date: 2026-05-19 08:39:51.005575

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '832fe6a5eae8'
down_revision: Union[str, None] = '23b2a53ff851'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "  id INTEGER NOT NULL PRIMARY KEY,"
        "  auto_fetch_enabled INTEGER NOT NULL DEFAULT 1,"
        "  market_scope VARCHAR NOT NULL DEFAULT 'japan_and_sp500',"
        "  pipeline_hour INTEGER NOT NULL DEFAULT 7,"
        "  pipeline_minute INTEGER NOT NULL DEFAULT 0,"
        "  updated_at VARCHAR"
        ")"
    )
    op.execute(
        "INSERT OR IGNORE INTO app_settings"
        " (id, auto_fetch_enabled, market_scope, pipeline_hour, pipeline_minute)"
        " VALUES (1, 1, 'japan_and_sp500', 7, 0)"
    )


def downgrade() -> None:
    op.drop_table("app_settings")
