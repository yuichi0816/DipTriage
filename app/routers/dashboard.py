from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta
from app.models.settings import AppSettings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_CLASS_ORDER = {"accident": 0, "incident": 1, "unknown": 2, None: 3}


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db),
    sort: str = Query(default="date"),
):
    # 急落イベント（DB は日付・下落率順に取得し、その後 Python でソート）
    result = await session.execute(
        select(DipEvent)
        .order_by(desc(DipEvent.detected_date), desc(DipEvent.change_pct_1d))
        .limit(50)
    )
    events = list(result.scalars().all())

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

    symbols = list({e.symbol for e in events})
    meta_result = await session.execute(
        select(StockMeta).where(StockMeta.symbol.in_(symbols))
    )
    meta_map: dict[str, StockMeta] = {m.symbol: m for m in meta_result.scalars().all()}

    event_ids = [e.id for e in events]
    interviews: dict[int, Briefing] = {}
    if event_ids:
        br_result = await session.execute(
            select(Briefing)
            .where(
                Briefing.dip_event_id.in_(event_ids),
                Briefing.briefing_type == "interview",
                Briefing.is_latest == 1,
            )
        )
        interviews = {b.dip_event_id: b for b in br_result.scalars().all()}

    # Python ソート
    if sort == "change":
        events.sort(key=lambda e: e.change_pct_1d)
    elif sort == "volume":
        events.sort(key=lambda e: -(analyses[e.id].volume_ratio_20d or 0) if e.id in analyses else 0)
    elif sort == "class":
        events.sort(key=lambda e: _CLASS_ORDER.get(interviews[e.id].initial_class if e.id in interviews else None, 3))
    # sort == "date" はデフォルト順のまま

    # 設定
    s_result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = s_result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)

    return templates.TemplateResponse(request, "dashboard.html", {
        "events": events,
        "analyses": analyses,
        "meta_map": meta_map,
        "interviews": interviews,
        "settings": settings,
        "sort": sort,
        "pipeline_status": request.app.state.pipeline_status,
        "news_status": request.app.state.news_status,
    })
