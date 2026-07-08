"""news_unique_per_event

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-07-08 00:00:00.000000

news_articles の一意制約を url 単独から (dip_event_id, url) へ変更（監査 2-2）。
既存データは url 一意 ⊂ (dip_event_id, url) 一意なのでデータ移行は不要。
SQLite は制約変更に非対応のため batch モード（テーブル再作成）で行う。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("news_articles", recreate="always") as batch:
        batch.drop_constraint("uq_news_articles_url", type_="unique")
        batch.create_unique_constraint("uq_news_articles_event_url", ["dip_event_id", "url"])


def downgrade() -> None:
    # 複数イベントに同一 URL が付与された後は url 単独一意に戻すと制約違反になりうる。
    # その場合は手動で重複を解消してから実行すること。
    with op.batch_alter_table("news_articles", recreate="always") as batch:
        batch.drop_constraint("uq_news_articles_event_url", type_="unique")
        batch.create_unique_constraint("uq_news_articles_url", ["url"])
