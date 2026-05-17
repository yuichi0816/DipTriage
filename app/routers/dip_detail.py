from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.intelligence.diagnosis import run_diagnosis
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta
from app.models.news import NewsArticle

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dip/{dip_id}", response_class=HTMLResponse)
async def dip_detail(dip_id: int, request: Request, session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(DipEvent).where(DipEvent.id == dip_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Not found")

    ana_result = await session.execute(
        select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == dip_id).limit(1)
    )
    analysis = ana_result.scalar_one_or_none()

    meta_result = await session.execute(select(StockMeta).where(StockMeta.symbol == event.symbol))
    meta = meta_result.scalar_one_or_none()

    briefing_result = await session.execute(
        select(Briefing)
        .where(Briefing.dip_event_id == dip_id, Briefing.is_latest == 1)
        .order_by(Briefing.created_at.desc())
    )
    briefings = briefing_result.scalars().all()
    interview = next((b for b in briefings if b.briefing_type == "interview"), None)
    diagnosis = next((b for b in briefings if b.briefing_type == "diagnosis"), None)

    return templates.TemplateResponse(request, "dip_detail.html", {
        "event": event,
        "analysis": analysis,
        "meta": meta,
        "interview": interview,
        "diagnosis": diagnosis,
    })


@router.post("/dip/{dip_id}/diagnose", response_class=HTMLResponse)
async def diagnose_dip(
    dip_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(DipEvent).where(DipEvent.id == dip_id))
    event = result.scalar_one_or_none()
    if not event:
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "イベントが見つかりません"},
            status_code=404,
        )
    if event.status not in ("interviewed", "diagnosed"):
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "問診が完了していません"},
            status_code=400,
        )

    ana_r = await session.execute(
        select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == dip_id).limit(1)
    )
    analysis = ana_r.scalar_one_or_none()

    iw_r = await session.execute(
        select(Briefing).where(
            Briefing.dip_event_id == dip_id,
            Briefing.briefing_type == "interview",
            Briefing.is_latest == 1,
        )
    )
    interview = iw_r.scalar_one_or_none()
    if not interview:
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "問診データが見つかりません"},
            status_code=400,
        )

    art_r = await session.execute(
        select(NewsArticle).where(NewsArticle.dip_event_id == dip_id)
    )
    articles = list(art_r.scalars().all())

    meta_r = await session.execute(select(StockMeta).where(StockMeta.symbol == event.symbol))
    meta = meta_r.scalar_one_or_none()

    diagnosis = await run_diagnosis(session, event, analysis, interview, articles, meta)

    return templates.TemplateResponse(
        request, "partials/diagnosis_result.html",
        {
            "dip_id": dip_id,
            "diagnosis": diagnosis,
            "error": None if diagnosis else "診断に失敗しました。Ollama が起動しているか確認してください。",
        },
    )
