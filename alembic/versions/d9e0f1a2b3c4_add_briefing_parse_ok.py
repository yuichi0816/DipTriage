"""add_briefing_parse_ok

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("briefings", sa.Column("parse_ok", sa.Integer(), nullable=True))
    op.add_column("briefings", sa.Column("raw_response", sa.String(), nullable=True))
    op.execute("UPDATE briefings SET parse_ok = 1 WHERE parse_ok IS NULL")


def downgrade() -> None:
    op.drop_column("briefings", "raw_response")
    op.drop_column("briefings", "parse_ok")
