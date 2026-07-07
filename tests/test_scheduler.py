"""スケジュール実行の失敗リトライと misfire 設定のテスト"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app import scheduler as sched_mod


@pytest.fixture(autouse=True)
def _restore_scheduler_ref():
    """モジュールグローバル _scheduler_ref をテスト間で汚染させない。"""
    original = sched_mod._scheduler_ref
    yield
    sched_mod._scheduler_ref = original


async def test_scheduled_run_success_does_not_schedule_retry():
    fake_scheduler = MagicMock()
    sched_mod._scheduler_ref = fake_scheduler
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(return_value={})):
        await sched_mod.scheduled_pipeline_run()
    fake_scheduler.add_job.assert_not_called()


async def test_scheduled_run_failure_schedules_one_retry():
    fake_scheduler = MagicMock()
    fake_scheduler.get_job.return_value = None
    sched_mod._scheduler_ref = fake_scheduler
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await sched_mod.scheduled_pipeline_run()  # 例外を外に漏らさない
    assert fake_scheduler.add_job.called
    assert fake_scheduler.add_job.call_args.kwargs["id"] == "daily_pipeline_retry"


async def test_retry_run_swallows_exception():
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await sched_mod.retry_pipeline_run()  # raise しないこと


async def test_reschedule_sets_misfire_grace_and_coalesce():
    fake_scheduler = MagicMock()
    fake_scheduler.get_job.return_value = None
    settings = MagicMock(auto_fetch_enabled=1, pipeline_hour=7, pipeline_minute=0)
    await sched_mod.reschedule_pipeline(fake_scheduler, settings)
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["misfire_grace_time"] == 3600
    assert kwargs["coalesce"] is True
    assert fake_scheduler.add_job.call_args.args[0] is sched_mod.scheduled_pipeline_run
