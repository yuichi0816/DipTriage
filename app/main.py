import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.database import init_db, AsyncSessionLocal
from app.models.settings import AppSettings
from app.routers import dashboard, dip_detail, watchlist, settings as settings_router, manual as manual_router
from app.scheduler import PipelineStatus, reschedule_pipeline
from app.security import BasicAuthMiddleware, OriginCheckMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _load_settings(session) -> AppSettings:
    result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        await session.commit()
    return settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    app.state.pipeline_status = PipelineStatus()
    app.state.news_status = PipelineStatus()

    scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
    app.state.scheduler = scheduler
    scheduler.start()

    async with AsyncSessionLocal() as session:
        db_settings = await _load_settings(session)
    await reschedule_pipeline(scheduler, db_settings)

    yield
    scheduler.shutdown()


app = FastAPI(title="DipTriage", lifespan=lifespan)

app.add_middleware(OriginCheckMiddleware)

_AUTH_PASSWORD = os.getenv("DIPTRIAGE_PASSWORD", "")
if _AUTH_PASSWORD:
    app.add_middleware(
        BasicAuthMiddleware,
        username=os.getenv("DIPTRIAGE_USER", "diptriage"),
        password=_AUTH_PASSWORD,
    )
else:
    logger.warning(
        "DIPTRIAGE_PASSWORD が未設定のため認証なしで起動します。"
        "Tailscale IP または 127.0.0.1 へのバインドを必ず併用してください。"
    )

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(dip_detail.router)
app.include_router(watchlist.router)
app.include_router(settings_router.router)
app.include_router(manual_router.router)
