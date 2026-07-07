"""run_daily_pipeline の実行履歴記録（pipeline_runs）のテスト"""
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, PipelineRun


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_run_recorded_on_success():
    engine, Session = await _setup_db()
    fake_stats = {"date": "2026-07-06", "dips_detected": 3}

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner._run_pipeline_stages", new=AsyncMock(return_value=fake_stats)):
        from app.pipeline.runner import run_daily_pipeline
        stats = await run_daily_pipeline(trigger="schedule")

    assert stats == fake_stats
    async with Session() as s:
        run = (await s.execute(select(PipelineRun))).scalar_one()
    assert run.status == "done"
    assert run.trigger == "schedule"
    assert run.target_date == "2026-07-06"
    assert '"dips_detected": 3' in run.stats_json
    assert run.finished_at is not None
    await engine.dispose()


async def test_run_recorded_on_failure():
    engine, Session = await _setup_db()

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner._run_pipeline_stages", new=AsyncMock(side_effect=RuntimeError("boom"))):
        from app.pipeline.runner import run_daily_pipeline
        with pytest.raises(RuntimeError):
            await run_daily_pipeline()

    async with Session() as s:
        run = (await s.execute(select(PipelineRun))).scalar_one()
    assert run.status == "error"
    assert run.trigger == "manual"
    assert "boom" in run.error
    await engine.dispose()
