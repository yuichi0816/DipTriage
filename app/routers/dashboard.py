from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DipEvent, NumericalAnalysis, StockMeta

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_db)):
    # 直近 7 日の急落イベントを取得
    result = await session.execute(
        select(DipEvent)
        .order_by(desc(DipEvent.detected_date), desc(DipEvent.change_pct_1d))
        .limit(50)
    )
    events = result.scalars().all()

    # 各イベントの数値分析を取得
    analyses: dict[int, NumericalAnalysis] = {}
    for event in events:
        a = await session.execute(
            select(NumericalAnalysis)
            .where(NumericalAnalysis.dip_event_id == event.id)
            .limit(1)
        )
        ana = a.scalar_one_or_none()
        if ana:
            analyses[event.id] = ana

    # 銘柄名を取得
    symbols = list({e.symbol for e in events})
    meta_result = await session.execute(
        select(StockMeta).where(StockMeta.symbol.in_(symbols))
    )
    meta_map: dict[str, StockMeta] = {m.symbol: m for m in meta_result.scalars().all()}

    return templates.TemplateResponse(request, "dashboard.html", {
        "events": events,
        "analyses": analyses,
        "meta_map": meta_map,
    })
