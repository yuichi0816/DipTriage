"""起動時スキーマ初期化の判定ロジックのテスト"""
from app.database import choose_init_action


class TestChooseInitAction:
    def test_empty_db_creates_and_stamps(self):
        assert choose_init_action([]) == "create_and_stamp"

    def test_legacy_db_without_version_creates_and_stamps(self):
        # create_all 時代の DB（テーブルはあるが alembic_version が無い）
        assert choose_init_action(["dip_events", "briefings"]) == "create_and_stamp"

    def test_alembic_managed_db_upgrades(self):
        assert choose_init_action(["alembic_version", "dip_events"]) == "upgrade"
