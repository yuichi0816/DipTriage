import logging
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


@dataclass
class PipelineStatus:
    status: str = "idle"       # idle | running | done | error
    stage: str = ""
    progress: str = ""
    message: str = ""
    updated_at: datetime | None = None


async def reschedule_pipeline(scheduler: AsyncIOScheduler, settings) -> None:
    """DB設定に基づいてスケジューラーを再設定する。"""
    from app.pipeline.runner import run_daily_pipeline

    if scheduler.get_job("daily_pipeline"):
        scheduler.remove_job("daily_pipeline")
    if settings.auto_fetch_enabled:
        scheduler.add_job(
            run_daily_pipeline,
            CronTrigger(hour=settings.pipeline_hour, minute=settings.pipeline_minute, timezone="Asia/Tokyo"),
            id="daily_pipeline",
        )
        logger.info("Pipeline scheduled at %02d:%02d JST", settings.pipeline_hour, settings.pipeline_minute)
    else:
        logger.info("Auto-fetch disabled; no pipeline scheduled")
