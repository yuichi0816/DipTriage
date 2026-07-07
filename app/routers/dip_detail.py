from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.intelligence.diagnosis import run_diagnosis
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta, StockPrice
from app.models.news import NewsArticle
from app.models.watchlist import WatchlistEntry

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

    wl_result = await session.execute(
        select(WatchlistEntry)
        .where(WatchlistEntry.dip_event_id == dip_id, WatchlistEntry.status == "watching")
        .limit(1)
    )
    watchlist_entry = wl_result.scalar_one_or_none()

    return templates.TemplateResponse(request, "dip_detail.html", {
        "event": event,
        "analysis": analysis,
        "meta": meta,
        "interview": interview,
        "diagnosis": diagnosis,
        "watchlist_entry": watchlist_entry,
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
            {"dip_id": dip_id, "diagnosis": None, "error": "問診が完了していません（ステータス: " + event.status + "）"},
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
        ).limit(1)
    )
    interview = iw_r.scalars().first()
    if not interview:
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "問診データが見つかりません"},
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


@router.post("/dip/{dip_id}/watchlist", response_class=HTMLResponse)
async def add_to_watchlist(
    dip_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(DipEvent).where(DipEvent.id == dip_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Not found")

    existing_r = await session.execute(
        select(WatchlistEntry)
        .where(WatchlistEntry.dip_event_id == dip_id, WatchlistEntry.status == "watching")
        .limit(1)
    )
    existing = existing_r.scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(request, "partials/watchlist_button.html", {
            "entry": existing,
            "dip_id": dip_id,
        })

    price_r = await session.execute(
        select(StockPrice)
        .where(StockPrice.symbol == event.symbol, StockPrice.date == event.trigger_date)
        .limit(1)
    )
    price_rec = price_r.scalar_one_or_none()
    trigger_price = price_rec.close if price_rec else 0.0

    entry = WatchlistEntry(
        dip_event_id=dip_id,
        symbol=event.symbol,
        added_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        trigger_price=trigger_price,
        status="watching",
    )
    session.add(entry)
    await session.commit()

    return templates.TemplateResponse(request, "partials/watchlist_button.html", {
        "entry": entry,
        "dip_id": dip_id,
    })
