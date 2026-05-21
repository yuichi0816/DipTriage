"""add_briefing_latest_unique_index

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # is_latest=1 の行に対して (dip_event_id, briefing_type) の一意性をDBレベルで保証する
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_briefings_latest "
        "ON briefings(dip_event_id, briefing_type) WHERE is_latest = 1"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_briefings_latest")
