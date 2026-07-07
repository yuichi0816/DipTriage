"""起動時スキーマ初期化の判定ロジックのテスト"""
import sqlite3

from app.database import choose_init_action, set_sqlite_pragmas


class TestChooseInitAction:
    def test_empty_db_creates_and_stamps(self):
        assert choose_init_action([]) == "create_and_stamp"

    def test_legacy_db_without_version_creates_and_stamps(self):
        # create_all 時代の DB（テーブルはあるが alembic_version が無い）
        assert choose_init_action(["dip_events", "briefings"]) == "create_and_stamp"

    def test_alembic_managed_db_upgrades(self):
        assert choose_init_action(["alembic_version", "dip_events"]) == "upgrade"


def test_set_sqlite_pragmas_sets_busy_timeout():
    conn = sqlite3.connect(":memory:")
    set_sqlite_pragmas(conn)
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()
