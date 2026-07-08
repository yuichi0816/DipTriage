"""llm_client の APIキー優先順位のテスト（監査 4-3）"""
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base
from app.models.settings import AppSettings


async def _setup_settings():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(AppSettings(id=1, llm_provider="groq", groq_api_key="db-key"))
        await s.commit()
    return engine, Session


async def test_env_api_key_takes_precedence_over_db():
    engine, Session = await _setup_settings()
    with patch("app.intelligence.llm_client.AsyncSessionLocal", Session), \
         patch("app.intelligence.llm_client.GROQ_API_KEY", "env-key"), \
         patch("app.intelligence.llm_client.groq_client.generate",
               new=AsyncMock(return_value=("ok", 0.1))) as mock_gen:
        from app.intelligence.llm_client import generate
        await generate("p", model="m")
    assert mock_gen.call_args.kwargs["api_key"] == "env-key"
    await engine.dispose()


async def test_db_api_key_used_when_env_empty():
    engine, Session = await _setup_settings()
    with patch("app.intelligence.llm_client.AsyncSessionLocal", Session), \
         patch("app.intelligence.llm_client.GROQ_API_KEY", ""), \
         patch("app.intelligence.llm_client.groq_client.generate",
               new=AsyncMock(return_value=("ok", 0.1))) as mock_gen:
        from app.intelligence.llm_client import generate
        await generate("p", model="m")
    assert mock_gen.call_args.kwargs["api_key"] == "db-key"
    await engine.dispose()
