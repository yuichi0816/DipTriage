import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, desc, tuple_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.intelligence.taxonomy import CLASS_ORDER as _CLASS_ORDER
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta
from app.models.stock import StockPrice
from app.models.settings import AppSettings
from app.models.pipeline_run import PipelineRun

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db),
    sort: str = Query(default="date"),
    days: int = Query(default=30, ge=0),
    statuses: list[str] = Query(default=[], alias="status"),
    markets: list[str] = Query(default=[], alias="market"),
    classes: list[str] = Query(default=[], alias="class"),
    min_drop: int = Query(default=0, ge=0),
    min_weekly_drop: int = Query(default=0, ge=0),
):
    query = select(DipEvent)

    if days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query = query.where(DipEvent.trigger_date >= cutoff)

    if statuses:
        query = query.where(DipEvent.status.in_(statuses))

    if markets:
        query = query.join(StockMeta, DipEvent.symbol == StockMeta.symbol)
        _MARKET_CONDITIONS = {
            "prime":    StockMeta.index_name == "Nikkei225",
            "standard": StockMeta.index_name == "TSE Standard",
            "growth":   StockMeta.index_name == "TSE Growth",
            "US":       StockMeta.market == "US",
        }
        conditions = [_MARKET_CONDITIONS[m] for m in markets if m in _MARKET_CONDITIONS]
        if conditions:
            query = query.where(or_(*conditions))

    if classes:
        subq = (
            select(Briefing.dip_event_id)
            .where(
                Briefing.briefing_type == "interview",
                Briefing.is_latest == 1,
                Briefing.initial_class.in_(classes),
            )
            .scalar_subquery()
        )
        query = query.where(DipEvent.id.in_(subq))

    if min_drop > 0:
        query = query.where(DipEvent.change_pct_1d <= -min_drop)

    if min_weekly_drop > 0:
        query = query.where(DipEvent.change_pct_5d <= -min_weekly_drop)

    query = query.order_by(desc(DipEvent.detected_date), desc(DipEvent.change_pct_1d)).limit(50)
    result = await session.execute(query)
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

    # 急落日終値（バッチ取得）
    trigger_pairs = [(e.symbol, e.trigger_date) for e in events]
    sp_by_symbol_date: dict[tuple, StockPrice] = {}
    if trigger_pairs:
        dip_result = await session.execute(
            select(StockPrice).where(
                tuple_(StockPrice.symbol, StockPrice.date).in_(trigger_pairs)
            )
        )
        sp_by_symbol_date = {(sp.symbol, sp.date): sp for sp in dip_result.scalars()}

    # 直近終値（シンボルごとの最新日）
    recent_prices: dict[str, StockPrice] = {}
    if symbols:
        subq = (
            select(StockPrice.symbol, func.max(StockPrice.date).label("max_date"))
            .where(StockPrice.symbol.in_(symbols))
            .group_by(StockPrice.symbol)
            .subquery()
        )
        recent_result = await session.execute(
            select(StockPrice).join(
                subq,
                (StockPrice.symbol == subq.c.symbol) & (StockPrice.date == subq.c.max_date),
            )
        )
        recent_prices = {sp.symbol: sp for sp in recent_result.scalars()}

    # price_map: event.id → {dip_str, recent_str, recovery_pct}
    price_map: dict[int, dict] = {}
    for event in events:
        dip_sp = sp_by_symbol_date.get((event.symbol, event.trigger_date))
        recent_sp = recent_prices.get(event.symbol)
        if dip_sp is None or recent_sp is None:
            continue
        meta = meta_map.get(event.symbol)
        is_jp = meta is not None and meta.market == "JP"
        dip_close = dip_sp.close
        recent_close = recent_sp.close
        recovery_pct = (recent_close - dip_close) / dip_close * 100
        if is_jp:
            dip_str = f"¥{dip_close:,.0f}"
            recent_str = f"¥{recent_close:,.0f}"
        else:
            dip_str = f"${dip_close:.2f}"
            recent_str = f"${recent_close:.2f}"
        price_map[event.id] = {
            "dip_str": dip_str,
            "recent_str": recent_str,
            "recovery_pct": recovery_pct,
        }

    # Python ソート
    if sort == "change":
        events.sort(key=lambda e: e.change_pct_1d)
    elif sort == "volume":
        events.sort(key=lambda e: -(analyses[e.id].volume_ratio_20d or 0) if e.id in analyses else 0)
    elif sort == "class":
        events.sort(key=lambda e: _CLASS_ORDER.get(interviews[e.id].initial_class if e.id in interviews else None, 5))
    # sort == "date" はデフォルト順のまま

    # 最終パイプライン実行（監査 3-1: 失敗・0件検知の可視化）
    run_r = await session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.id)).limit(1)
    )
    last_run = run_r.scalar_one_or_none()
    last_run_stats: dict = {}
    if last_run and last_run.stats_json:
        try:
            last_run_stats = json.loads(last_run.stats_json)
        except ValueError:
            last_run_stats = {}

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
        "price_map": price_map,
        "settings": settings,
        "sort": sort,
        "days": days,
        "statuses": statuses,
        "markets": markets,
        "classes": classes,
        "min_drop": min_drop,
        "min_weekly_drop": min_weekly_drop,
        "pipeline_status": request.app.state.pipeline_status,
        "news_status": request.app.state.news_status,
        "last_run": last_run,
        "last_run_stats": last_run_stats,
    })
