from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.watchlist import WatchlistEntry, WatchlistSnapshot

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist(request: Request, session: AsyncSession = Depends(get_db)):
    result = await session.execute(
        select(WatchlistEntry)
        .where(WatchlistEntry.status == "watching")
        .order_by(WatchlistEntry.added_date.desc())
    )
    entries = result.scalars().all()

    snapshots: dict[int, WatchlistSnapshot] = {}
    for entry in entries:
        snap_r = await session.execute(
            select(WatchlistSnapshot)
            .where(WatchlistSnapshot.watchlist_entry_id == entry.id)
            .order_by(WatchlistSnapshot.snapshot_date.desc())
            .limit(1)
        )
        snap = snap_r.scalar_one_or_none()
        if snap:
            snapshots[entry.id] = snap

    return templates.TemplateResponse(request, "watchlist.html", {
        "entries": entries,
        "snapshots": snapshots,
    })


@router.post("/watchlist/{entry_id}/close", response_class=HTMLResponse)
async def close_watchlist_entry(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")

    entry.status = "closed"
    entry.closed_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await session.commit()

    return templates.TemplateResponse(request, "partials/watchlist_button.html", {
        "entry": entry,
        "dip_id": entry.dip_event_id,
    })
