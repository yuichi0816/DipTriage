"""run_daily_pipeline の実行履歴記録（pipeline_runs）のテスト"""
import asyncio
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Briefing, DipEvent, PipelineRun, StockMeta
from app.pipeline.fetcher import StockInfo


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


async def test_concurrent_pipeline_second_run_skips():
    engine, Session = await _setup_db()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stages(**kwargs):
        started.set()
        await release.wait()
        return {"date": "2026-07-07", "dips_detected": 0}

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner._run_pipeline_stages", new=AsyncMock(side_effect=slow_stages)) as mock_stages:
        from app.pipeline.runner import run_daily_pipeline
        first_task = asyncio.create_task(run_daily_pipeline(trigger="schedule"))
        await started.wait()
        second = await run_daily_pipeline(trigger="manual")  # 実行中に再入
        release.set()
        first = await first_task

    assert second == {"skipped": "already_running", "trigger": "manual"}
    assert first["dips_detected"] == 0
    assert mock_stages.await_count == 1  # 2本目はステージ未実行
    await engine.dispose()


async def test_load_universe_prefers_fetched_symbols():
    engine, Session = await _setup_db()
    info = StockInfo(symbol="AAA", name="A Corp", market="US", exchange=None,
                     sector=None, sector_etf=None, index_name="S&P500")
    async with Session() as s:
        from app.pipeline.runner import _load_universe
        result = await _load_universe(s, lambda: [info], "S&P500")
    assert result == [info]
    await engine.dispose()


async def test_load_universe_falls_back_to_cached_meta():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()
    async with Session() as s:
        s.add(StockMeta(symbol="7203.T", name="Toyota", market="JP", exchange="TSE",
                        index_name="Nikkei225", is_active=1,
                        created_at=now, updated_at=now))
        await s.commit()
        from app.pipeline.runner import _load_universe
        result = await _load_universe(s, lambda: [], "Nikkei225")
    assert [x.symbol for x in result] == ["7203.T"]
    assert result[0].index_name == "Nikkei225"
    await engine.dispose()
