from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta

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
