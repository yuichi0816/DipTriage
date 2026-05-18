import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.stock import Base
from app.main import app
from app.database import get_db


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_dip_event(session):
    from app.models.dip import DipEvent
    event = DipEvent(
        symbol="AAPL", detected_date="2024-01-10", trigger_date="2024-01-10",
        change_pct_1d=-10.5, status="diagnosed", macro_flag=0,
        created_at="2024-01-10T00:00:00", updated_at="2024-01-10T00:00:00",
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_stock_price(session, symbol, date, close):
    from app.models.stock import StockPrice
    price = StockPrice(symbol=symbol, date=date, close=close)
    session.add(price)
    await session.flush()
    return price


# ── GET /watchlist ──────────────────────────────────────────────

async def test_get_watchlist_empty(client):
    response = await client.get("/watchlist")
    assert response.status_code == 200


async def test_get_watchlist_with_entries(client, db_session):
    from app.models.watchlist import WatchlistEntry
    event = await _seed_dip_event(db_session)
    entry = WatchlistEntry(
        dip_event_id=event.id, symbol="AAPL",
        added_date="2024-01-10", trigger_price=185.0, status="watching",
    )
    db_session.add(entry)
    await db_session.commit()

    response = await client.get("/watchlist")
    assert response.status_code == 200
    assert "AAPL" in response.text


# ── POST /dip/{id}/watchlist ────────────────────────────────────

async def test_add_to_watchlist_success(client, db_session):
    from app.models.watchlist import WatchlistEntry
    event = await _seed_dip_event(db_session)
    await _seed_stock_price(db_session, "AAPL", "2024-01-10", 185.0)
    await db_session.commit()

    response = await client.post(f"/dip/{event.id}/watchlist")
    assert response.status_code == 200
    assert "watchlist-button-container" in response.text

    result = await db_session.execute(
        select(WatchlistEntry).where(WatchlistEntry.dip_event_id == event.id)
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.symbol == "AAPL"
    assert entry.trigger_price == pytest.approx(185.0)
    assert entry.status == "watching"


async def test_add_to_watchlist_duplicate(client, db_session):
    from app.models.watchlist import WatchlistEntry
    event = await _seed_dip_event(db_session)
    await _seed_stock_price(db_session, "AAPL", "2024-01-10", 185.0)
    await db_session.commit()

    await client.post(f"/dip/{event.id}/watchlist")
    await client.post(f"/dip/{event.id}/watchlist")

    result = await db_session.execute(
        select(WatchlistEntry).where(WatchlistEntry.dip_event_id == event.id)
    )
    entries = result.scalars().all()
    assert len(entries) == 1


async def test_add_to_watchlist_dip_not_found(client):
    response = await client.post("/dip/9999/watchlist")
    assert response.status_code == 404


# ── POST /watchlist/{id}/close ──────────────────────────────────

async def test_close_watchlist_entry(client, db_session):
    from app.models.watchlist import WatchlistEntry
    event = await _seed_dip_event(db_session)
    entry = WatchlistEntry(
        dip_event_id=event.id, symbol="AAPL",
        added_date="2024-01-10", trigger_price=185.0, status="watching",
    )
    db_session.add(entry)
    await db_session.commit()

    response = await client.post(f"/watchlist/{entry.id}/close")
    assert response.status_code == 200
    assert "watchlist-button-container" in response.text

    await db_session.refresh(entry)
    assert entry.status == "closed"


async def test_close_watchlist_entry_not_found(client):
    response = await client.post("/watchlist/9999/close")
    assert response.status_code == 404


# ── Stage 4: snapshot ───────────────────────────────────────────

async def test_pipeline_snapshot(db_session):
    from app.models.dip import DipEvent
    from app.models.watchlist import WatchlistEntry, WatchlistSnapshot
    from app.models.stock import StockPrice
    from app.pipeline.runner import snapshot_watching_entries

    event = DipEvent(
        symbol="AAPL", detected_date="2024-01-10", trigger_date="2024-01-10",
        change_pct_1d=-10.5, status="diagnosed", macro_flag=0,
        created_at="2024-01-10T00:00:00", updated_at="2024-01-10T00:00:00",
    )
    db_session.add(event)
    await db_session.flush()

    entry = WatchlistEntry(
        dip_event_id=event.id, symbol="AAPL",
        added_date="2024-01-10", trigger_price=185.0, status="watching",
    )
    db_session.add(entry)
    await db_session.flush()

    price = StockPrice(symbol="AAPL", date="2024-02-01", close=200.0)
    db_session.add(price)
    await db_session.commit()

    await snapshot_watching_entries(db_session, "2024-02-01")

    result = await db_session.execute(
        select(WatchlistSnapshot).where(WatchlistSnapshot.watchlist_entry_id == entry.id)
    )
    snapshot = result.scalar_one_or_none()
    assert snapshot is not None
    assert snapshot.close_price == pytest.approx(200.0)
    assert snapshot.recovery_pct == pytest.approx((200.0 - 185.0) / 185.0 * 100)
    assert snapshot.snapshot_date == "2024-02-01"
