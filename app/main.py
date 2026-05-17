import logging
import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import PIPELINE_HOUR, PIPELINE_MINUTE
from app.database import init_db
from app.pipeline.runner import run_daily_pipeline
from app.routers import dashboard, dip_detail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.add_job(
        run_daily_pipeline,
        trigger="cron",
        hour=PIPELINE_HOUR,
        minute=PIPELINE_MINUTE,
        id="daily_pipeline",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (daily at %02d:%02d JST)", PIPELINE_HOUR, PIPELINE_MINUTE)
    yield
    scheduler.shutdown()


app = FastAPI(title="DipTriage", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(dip_detail.router)
