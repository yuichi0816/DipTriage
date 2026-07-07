import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.config import BASE_DIR, DATABASE_URL
from app.models import Base

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def choose_init_action(existing_tables: list[str]) -> str:
    """起動時のスキーマ初期化方法を決める（監査 5-1: Alembic を単一情報源に）。

    - alembic_version がある → "upgrade"（以後は Alembic が管理）
    - それ以外（新規 DB / create_all 時代の DB）→ "create_and_stamp"
    """
    return "upgrade" if "alembic_version" in existing_tables else "create_and_stamp"


def _run_alembic(action: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    if action == "create_and_stamp":
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


async def init_db() -> None:
    def _table_names(sync_conn) -> list[str]:
        from sqlalchemy import inspect
        return inspect(sync_conn).get_table_names()

    async with engine.begin() as conn:
        action = choose_init_action(await conn.run_sync(_table_names))
        if action == "create_and_stamp":
            await conn.run_sync(Base.metadata.create_all)
    # Alembic は同期 API（env.py が内部で asyncio.run する）のでスレッドで実行
    await asyncio.to_thread(_run_alembic, action)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
