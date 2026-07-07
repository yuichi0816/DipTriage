"""add_pipeline_runs

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("target_date", sa.String(), nullable=True),
        sa.Column("stats_json", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pipeline_runs")
