from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import AppSettings
from app.scheduler import reschedule_pipeline

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_or_create_settings(session: AsyncSession) -> AppSettings:
    result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        await session.commit()
    return settings


@router.get("/settings")
async def get_settings():
    return RedirectResponse(url="/", status_code=303)


@router.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    session: AsyncSession = Depends(get_db),
    auto_fetch_enabled: str = Form(default="off"),
    market_scope: str = Form(...),
    pipeline_hour: int = Form(...),
    pipeline_minute: int = Form(...),
    llm_provider: str = Form(default="ollama"),
    groq_api_key: str = Form(default=""),
    groq_model_interview: str = Form(default="llama-3.1-8b-instant"),
    groq_model_diagnosis: str = Form(default="llama-3.3-70b-versatile"),
    news_refresh_days: int = Form(default=5),
    dip_lookback_days: int = Form(default=2),
):
    settings = await _get_or_create_settings(session)
    settings.auto_fetch_enabled = 1 if auto_fetch_enabled == "on" else 0
    settings.market_scope = market_scope
    settings.pipeline_hour = max(0, min(23, pipeline_hour))
    settings.pipeline_minute = max(0, min(59, pipeline_minute))
    settings.llm_provider = llm_provider
    if groq_api_key:
        settings.groq_api_key = groq_api_key
    settings.groq_model_interview = groq_model_interview
    settings.groq_model_diagnosis = groq_model_diagnosis
    settings.news_refresh_days = max(1, min(30, news_refresh_days))
    settings.dip_lookback_days = max(2, min(10, dip_lookback_days))
    settings.updated_at = datetime.now(timezone.utc).isoformat()
    await session.commit()

    await reschedule_pipeline(request.app.state.scheduler, settings)

    return RedirectResponse(url="/", status_code=303)


@router.post("/settings/run-pipeline", response_class=HTMLResponse)
async def run_pipeline_now(
    request: Request,
    background_tasks: BackgroundTasks,
    target_date: str = Form(default=""),
    max_stage: int = Form(default=4),
):
    status = request.app.state.pipeline_status
    if status.status == "running":
        return templates.TemplateResponse(request, "partials/pipeline_status.html", {"status": status})

    max_stage = max(1, min(4, max_stage))
    resolved_date = target_date.strip() or None

    async def _run():
        from app.pipeline.runner import run_daily_pipeline
        ps = request.app.state.pipeline_status
        ps.status = "running"
        ps.stage = ""
        ps.progress = ""
        ps.message = ""
        ps.updated_at = datetime.now(timezone.utc)

        def on_stage(stage: str, current: str, total: str) -> None:
            ps.stage = stage
            ps.progress = f"{current} / {total}" if current else ""
            ps.updated_at = datetime.now(timezone.utc)

        try:
            await run_daily_pipeline(target_date=resolved_date, on_stage=on_stage, max_stage=max_stage)
            ps.status = "done"
            ps.stage = "完了"
            ps.progress = ""
            ps.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            ps.status = "error"
            ps.message = str(e)
            ps.updated_at = datetime.now(timezone.utc)

    background_tasks.add_task(_run)
    status.status = "running"
    status.stage = "開始中..."
    status.updated_at = datetime.now(timezone.utc)

    return templates.TemplateResponse(request, "partials/pipeline_status.html", {"status": status})


@router.get("/settings/pipeline-status", response_class=HTMLResponse)
async def pipeline_status(request: Request):
    status = request.app.state.pipeline_status
    return templates.TemplateResponse(request, "partials/pipeline_status.html", {"status": status})


@router.post("/settings/run-news-refresh", response_class=HTMLResponse)
async def run_news_refresh_now(request: Request, background_tasks: BackgroundTasks):
    status = request.app.state.news_status
    if status.status == "running":
        return templates.TemplateResponse(request, "partials/news_status.html", {"status": status})

    async def _run():
        from app.pipeline.runner import run_news_refresh
        from app.database import AsyncSessionLocal
        from sqlalchemy import select
        from app.models.settings import AppSettings

        async with AsyncSessionLocal() as s:
            r = await s.execute(select(AppSettings).where(AppSettings.id == 1))
            db_settings = r.scalar_one_or_none()
        days = db_settings.news_refresh_days if db_settings else 5

        ns = request.app.state.news_status
        ns.status = "running"
        ns.stage = ""
        ns.progress = ""
        ns.message = ""
        ns.updated_at = datetime.now(timezone.utc)

        def on_stage(stage: str, current: str, total: str) -> None:
            ns.stage = stage
            ns.progress = f"{current} / {total}" if current else ""
            ns.updated_at = datetime.now(timezone.utc)

        try:
            await run_news_refresh(days=days, on_stage=on_stage)
            ns.status = "done"
            ns.stage = "完了"
            ns.progress = ""
            ns.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            ns.status = "error"
            ns.message = str(e)
            ns.updated_at = datetime.now(timezone.utc)

    background_tasks.add_task(_run)
    status.status = "running"
    status.stage = "開始中..."
    status.updated_at = datetime.now(timezone.utc)

    return templates.TemplateResponse(request, "partials/news_status.html", {"status": status})


@router.get("/settings/news-status", response_class=HTMLResponse)
async def news_status(request: Request):
    status = request.app.state.news_status
    return templates.TemplateResponse(request, "partials/news_status.html", {"status": status})
