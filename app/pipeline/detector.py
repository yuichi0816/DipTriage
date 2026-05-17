"""第1段階：急落検知（マクロフィルタ + 個別スクリーニング）"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MACRO_FILTER_PCT, THRESHOLD_DIP_PCT
from app.models import DipEvent, IndexPrice, StockPrice

logger = logging.getLogger(__name__)


@dataclass
class MacroFilterResult:
    is_macro_shock: bool
    note: str
    index_changes: dict[str, float] = field(default_factory=dict)


@dataclass
class DipCandidate:
    symbol: str
    trigger_date: str
    change_pct_1d: float
    change_pct_5d: float | None = None
    macro_flag: int = 0
    macro_note: str | None = None


def apply_macro_filter(
    index_changes: dict[str, float],
    threshold: float = MACRO_FILTER_PCT,
) -> MacroFilterResult:
    """
    指数が threshold% 以上下落している場合はマクロショックと判定。
    個別銘柄を除外するのではなく、フラグとして記録する。
    """
    shocks = {sym: chg for sym, chg in index_changes.items() if chg <= threshold}
    if shocks:
        note_parts = [f"{sym}: {chg:.1f}%" for sym, chg in shocks.items()]
        return MacroFilterResult(
            is_macro_shock=True,
            note="マクロ要因による市場全体の下落: " + ", ".join(note_parts),
            index_changes=index_changes,
        )
    return MacroFilterResult(is_macro_shock=False, note="", index_changes=index_changes)


async def get_price_changes(
    session: AsyncSession,
    target_date: str,
    symbols: list[str] | None = None,
) -> list[DipCandidate]:
    """DB の stock_prices から前日比・5日比を計算してスクリーニングする。"""
    # 5営業日 = 最大7カレンダー日。14日を下限にして無制限スキャンを防ぐ
    lower_bound = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=14)
    ).strftime("%Y-%m-%d")

    stmt = (
        select(StockPrice)
        .where(StockPrice.date >= lower_bound, StockPrice.date <= target_date)
        .order_by(StockPrice.symbol, StockPrice.date.desc())
    )
    if symbols:
        stmt = stmt.where(StockPrice.symbol.in_(symbols))

    result = await session.execute(stmt)
    rows = result.scalars().all()

    # シンボルごとに最新7日分を収集（1d + 5d 計算に必要）
    sym_prices: dict[str, list[StockPrice]] = {}
    for row in rows:
        sym_prices.setdefault(row.symbol, [])
        if len(sym_prices[row.symbol]) < 7:
            sym_prices[row.symbol].append(row)

    candidates = []
    for sym, prices in sym_prices.items():
        if len(prices) < 2:
            continue
        today_price, prev_price = prices[0], prices[1]
        if today_price.date != target_date:
            continue
        change_1d = (today_price.close - prev_price.close) / prev_price.close * 100
        change_5d = None
        if len(prices) >= 6:
            five_days_ago = prices[5]
            if five_days_ago.close:
                change_5d = (today_price.close - five_days_ago.close) / five_days_ago.close * 100
        candidates.append(DipCandidate(
            symbol=sym,
            trigger_date=target_date,
            change_pct_1d=change_1d,
            change_pct_5d=change_5d,
        ))

    return candidates


def screen_dips(
    candidates: list[DipCandidate],
    threshold: float = THRESHOLD_DIP_PCT,
    macro_result: MacroFilterResult | None = None,
) -> list[DipCandidate]:
    """閾値以下の下落のみを残し、マクロフラグを付与する。"""
    filtered = [c for c in candidates if c.change_pct_1d <= threshold]
    if macro_result and macro_result.is_macro_shock:
        for c in filtered:
            c.macro_flag = 1
            c.macro_note = macro_result.note
    logger.info(
        "Dip screening: %d candidates → %d dips (threshold=%.1f%%)",
        len(candidates), len(filtered), threshold,
    )
    return filtered


async def save_dip_events(
    session: AsyncSession,
    candidates: list[DipCandidate],
    detected_date: str,
) -> list[DipEvent]:
    """DipEvent を DB に保存。UNIQUE 制約により冪等（重複しない）。"""
    now = datetime.now(timezone.utc).isoformat()
    saved = []
    for c in candidates:
        stmt = insert(DipEvent).values(
            symbol=c.symbol,
            detected_date=detected_date,
            trigger_date=c.trigger_date,
            change_pct_1d=c.change_pct_1d,
            change_pct_5d=c.change_pct_5d,
            macro_flag=c.macro_flag,
            macro_note=c.macro_note,
            status="detected",
            created_at=now,
            updated_at=now,
        ).on_conflict_do_nothing(index_elements=["symbol", "trigger_date"])
        await session.execute(stmt)

        # 保存済みのレコードを取得
        existing = await session.execute(
            select(DipEvent).where(
                DipEvent.symbol == c.symbol,
                DipEvent.trigger_date == c.trigger_date,
            )
        )
        event = existing.scalar_one_or_none()
        if event:
            saved.append(event)

    await session.commit()
    logger.info("Saved %d dip events", len(saved))
    return saved
