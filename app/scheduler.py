import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

# reschedule_pipeline で保持し、失敗時のリトライ予約に使う
_scheduler_ref: AsyncIOScheduler | None = None

RETRY_DELAY_MINUTES = 30


@dataclass
class PipelineStatus:
    status: str = "idle"       # idle | running | done | error
    stage: str = ""
    progress: str = ""
    message: str = ""
    updated_at: datetime | None = None


async def scheduled_pipeline_run() -> None:
    """cron からの実行。失敗時は RETRY_DELAY_MINUTES 後に1回だけリトライを予約する（監査 3-1）。"""
    from app.pipeline.runner import run_daily_pipeline

    try:
        await run_daily_pipeline(trigger="schedule")
    except Exception:
        logger.exception("Scheduled pipeline failed; retrying once in %d min", RETRY_DELAY_MINUTES)
        if _scheduler_ref is not None and _scheduler_ref.get_job("daily_pipeline_retry") is None:
            _scheduler_ref.add_job(
                retry_pipeline_run,
                DateTrigger(run_date=datetime.now() + timedelta(minutes=RETRY_DELAY_MINUTES)),
                id="daily_pipeline_retry",
            )


async def retry_pipeline_run() -> None:
    """1回限りのリトライ。再失敗しても次のスケジュールまで諦める。"""
    from app.pipeline.runner import run_daily_pipeline

    try:
        await run_daily_pipeline(trigger="schedule-retry")
    except Exception:
        logger.exception("Pipeline retry failed; giving up until next schedule")


async def reschedule_pipeline(scheduler: AsyncIOScheduler, settings) -> None:
    """DB設定に基づいてスケジューラーを再設定する。"""
    global _scheduler_ref
    _scheduler_ref = scheduler

    if scheduler.get_job("daily_pipeline"):
        scheduler.remove_job("daily_pipeline")
    if settings.auto_fetch_enabled:
        scheduler.add_job(
            scheduled_pipeline_run,
            CronTrigger(hour=settings.pipeline_hour, minute=settings.pipeline_minute, timezone="Asia/Tokyo"),
            id="daily_pipeline",
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Pipeline scheduled at %02d:%02d JST", settings.pipeline_hour, settings.pipeline_minute)
    else:
        logger.info("Auto-fetch disabled; no pipeline scheduled")
