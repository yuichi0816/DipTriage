from sqlalchemy import String, Integer, Float, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dip_event_id: Mapped[int] = mapped_column(Integer, ForeignKey("dip_events.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    added_date: Mapped[str] = mapped_column(String, nullable=False)
    trigger_price: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(String, default="watching")  # watching | closed
    closed_date: Mapped[str | None] = mapped_column(String)
    closed_reason: Mapped[str | None] = mapped_column(String)

    user_note: Mapped[str | None] = mapped_column(String)
    extra_json: Mapped[str | None] = mapped_column(String)


class WatchlistSnapshot(Base):
    __tablename__ = "watchlist_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlist_entries.id"), nullable=False)
    snapshot_date: Mapped[str] = mapped_column(String, nullable=False)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)
    recovery_pct: Mapped[float] = mapped_column(Float, nullable=False)
    volume_ratio: Mapped[float | None] = mapped_column(Float)
    new_news_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("watchlist_entry_id", "snapshot_date", name="uq_watchlist_snapshots"),
        Index("idx_watchlist_snapshots_entry_id", "watchlist_entry_id"),
    )
