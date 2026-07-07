import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock

from app.models.stock import Base
from app.models.settings import AppSettings
from app.models.pipeline_run import PipelineRun
from app.main import app
from app.database import get_db
from app.scheduler import PipelineStatus


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSettings(id=1))
        s.add(PipelineRun(
            trigger="schedule", status="done", target_date="2026-07-06",
            stats_json='{"date": "2026-07-06", "dips_detected": 2}',
            started_at="2026-07-06T22:00:00+00:00",
            finished_at="2026-07-06T22:15:00+00:00",
        ))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.state.pipeline_status = PipelineStatus()
    app.state.news_status = PipelineStatus()
    app.state.scheduler = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_dashboard_shows_last_run_summary(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "最終実行" in response.text
    assert "検知 2 件" in response.text
