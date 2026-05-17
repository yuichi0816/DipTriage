from datetime import datetime
from sqlalchemy import String, Integer, Float, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StockMeta(Base):
    __tablename__ = "stock_meta"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)  # "US" | "JP"
    exchange: Mapped[str | None] = mapped_column(String)
    sector: Mapped[str | None] = mapped_column(String)
    sector_etf: Mapped[str | None] = mapped_column(String)
    index_name: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    meta_json: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_stock_prices_symbol_date"),
        Index("idx_stock_prices_symbol_date", "symbol", "date"),
    )


class IndexPrice(Base):
    __tablename__ = "index_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_index_prices_symbol_date"),
    )
