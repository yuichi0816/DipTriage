"""run_daily_pipeline の実行履歴記録（pipeline_runs）のテスト"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Briefing, DipEvent, PipelineRun


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


async def test_news_refresh_skips_interview_when_no_new_articles():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    async with Session() as s:
        event = DipEvent(
            symbol="CRWD", detected_date=today, trigger_date=today,
            change_pct_1d=-8.0, macro_flag=0, status="interviewed",
            created_at=now, updated_at=now,
        )
        s.add(event)
        await s.commit()
        await s.refresh(event)
        s.add(Briefing(dip_event_id=event.id, briefing_type="interview",
                       initial_class="accident", created_at=now, is_latest=1))
        await s.commit()

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner.fetch_and_save_news", new=AsyncMock(return_value=[])), \
         patch("app.pipeline.runner.run_interview", new=AsyncMock()) as mock_interview:
        from app.pipeline.runner import run_news_refresh
        stats = await run_news_refresh(days=5)

    mock_interview.assert_not_called()  # 新着ゼロ + 問診済み → スキップ（監査 7-1）
    assert stats["skipped_no_new_news"] == 1
    await engine.dispose()
