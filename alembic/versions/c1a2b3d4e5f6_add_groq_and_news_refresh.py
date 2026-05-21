"""add_groq_and_news_refresh

Revision ID: c1a2b3d4e5f6
Revises: 832fe6a5eae8
Create Date: 2026-05-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = '832fe6a5eae8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_settings ADD COLUMN llm_provider VARCHAR NOT NULL DEFAULT 'ollama'")
    op.execute("ALTER TABLE app_settings ADD COLUMN groq_api_key VARCHAR")
    op.execute("ALTER TABLE app_settings ADD COLUMN groq_model_interview VARCHAR NOT NULL DEFAULT 'llama-3.1-8b-instant'")
    op.execute("ALTER TABLE app_settings ADD COLUMN groq_model_diagnosis VARCHAR NOT NULL DEFAULT 'llama-3.3-70b-versatile'")
    op.execute("ALTER TABLE app_settings ADD COLUMN news_refresh_days INTEGER NOT NULL DEFAULT 5")


def downgrade() -> None:
    pass
