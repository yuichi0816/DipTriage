"""add_dip_lookback_days

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("dip_lookback_days", sa.Integer(), nullable=True))
    op.execute("UPDATE app_settings SET dip_lookback_days = 2 WHERE dip_lookback_days IS NULL")


def downgrade() -> None:
    op.drop_column("app_settings", "dip_lookback_days")
