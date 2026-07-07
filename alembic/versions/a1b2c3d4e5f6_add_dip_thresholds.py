"""add_dip_thresholds

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("threshold_dip_pct", sa.Float(), nullable=True))
    op.add_column("app_settings", sa.Column("macro_filter_pct",  sa.Float(), nullable=True))
    op.execute("UPDATE app_settings SET threshold_dip_pct = -5.0 WHERE threshold_dip_pct IS NULL")
    op.execute("UPDATE app_settings SET macro_filter_pct  = -2.0 WHERE macro_filter_pct  IS NULL")


def downgrade() -> None:
    op.drop_column("app_settings", "macro_filter_pct")
    op.drop_column("app_settings", "threshold_dip_pct")
