import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.stock import Base
from app.models.settings import AppSettings
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
        # 初期レコードを挿入
        s.add(AppSettings(id=1, auto_fetch_enabled=1,
                          include_nikkei225=1, include_sp500=1,
                          include_standard=0, include_growth=0,
                          pipeline_hour=7, pipeline_minute=0))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = None

    app.dependency_overrides[get_db] = override_get_db
    app.state.pipeline_status = PipelineStatus()
    app.state.scheduler = mock_scheduler

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── GET /settings ───────────────────────────────────────────────

async def test_get_settings_redirects(client):
    response = await client.get("/settings", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


# ── POST /settings ──────────────────────────────────────────────

async def test_save_settings_updates_db(client, db_session):
    response = await client.post("/settings", data={
        "auto_fetch_enabled": "on",
        "include_nikkei225": "on",
        "pipeline_hour": "8",
        "pipeline_minute": "30",
        "dip_lookback_days": "3",
    }, follow_redirects=False)
    assert response.status_code == 303

    result = await db_session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one()
    assert settings.auto_fetch_enabled == 1
    assert settings.include_nikkei225 == 1
    assert settings.include_sp500 == 0
    assert settings.pipeline_hour == 8
    assert settings.pipeline_minute == 30
    assert settings.dip_lookback_days == 3


async def test_save_settings_dip_lookback_days_clamped(client, db_session):
    response = await client.post("/settings", data={
        "include_nikkei225": "on", "include_sp500": "on",
        "pipeline_hour": "7",
        "pipeline_minute": "0",
        "dip_lookback_days": "99",
    }, follow_redirects=False)
    assert response.status_code == 303

    result = await db_session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one()
    assert settings.dip_lookback_days == 10


async def test_save_settings_auto_fetch_off(client, db_session):
    response = await client.post("/settings", data={
        "include_nikkei225": "on", "include_sp500": "on",
        "pipeline_hour": "7",
        "pipeline_minute": "0",
    }, follow_redirects=False)
    assert response.status_code == 303

    result = await db_session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one()
    assert settings.auto_fetch_enabled == 0


async def test_save_settings_reschedules(client):
    response = await client.post("/settings", data={
        "auto_fetch_enabled": "on",
        "include_nikkei225": "on", "include_sp500": "on",
        "pipeline_hour": "6",
        "pipeline_minute": "0",
    }, follow_redirects=False)
    assert response.status_code == 303
    # スケジューラーへの add_job 呼び出しを確認
    assert app.state.scheduler.add_job.called


# ── POST /settings/run-pipeline ────────────────────────────────

async def test_run_pipeline_returns_status_panel(client):
    response = await client.post("/settings/run-pipeline")
    assert response.status_code == 200
    assert "pipeline-status-panel" in response.text


async def test_run_pipeline_sets_running_status(client):
    await client.post("/settings/run-pipeline")
    # BackgroundTask がテスト中に完了する場合もあるため、idle 以外であることを確認
    assert app.state.pipeline_status.status in ("running", "done", "error")


async def test_run_pipeline_skips_if_already_running(client):
    app.state.pipeline_status.status = "running"
    response = await client.post("/settings/run-pipeline")
    assert response.status_code == 200
    assert "pipeline-status-panel" in response.text


# ── GET /settings/pipeline-status ──────────────────────────────

async def test_pipeline_status_idle(client):
    app.state.pipeline_status = PipelineStatus(status="idle")
    response = await client.get("/settings/pipeline-status")
    assert response.status_code == 200
    assert "待機中" in response.text


async def test_pipeline_status_running(client):
    from datetime import datetime
    app.state.pipeline_status = PipelineStatus(
        status="running", stage="Stage 3b: LLM インタビュー", progress="3 / 12",
        updated_at=datetime.now(),
    )
    response = await client.get("/settings/pipeline-status")
    assert response.status_code == 200
    assert "Stage 3b: LLM インタビュー" in response.text
    assert "3 / 12" in response.text
    assert "every 3s" in response.text  # ポーリング継続


async def test_pipeline_status_done(client):
    from datetime import datetime
    app.state.pipeline_status = PipelineStatus(status="done", updated_at=datetime.now())
    response = await client.get("/settings/pipeline-status")
    assert response.status_code == 200
    assert "完了" in response.text
    assert "every 3s" not in response.text  # ポーリング停止


async def test_pipeline_status_error(client):
    from datetime import datetime
    app.state.pipeline_status = PipelineStatus(
        status="error", message="Network timeout", updated_at=datetime.now()
    )
    response = await client.get("/settings/pipeline-status")
    assert response.status_code == 200
    assert "エラー" in response.text
    assert "Network timeout" in response.text


async def test_run_pipeline_forwards_max_stage(client):
    with patch('app.pipeline.runner.run_daily_pipeline', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {}
        response = await client.post("/settings/run-pipeline", data={"max_stage": "2"})
        assert response.status_code == 200
        await asyncio.sleep(0.1)
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get('max_stage') == 2
