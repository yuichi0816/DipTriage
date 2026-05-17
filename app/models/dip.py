from sqlalchemy import String, Integer, Float, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class DipEvent(Base):
    __tablename__ = "dip_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    detected_date: Mapped[str] = mapped_column(String, nullable=False)
    trigger_date: Mapped[str] = mapped_column(String, nullable=False)

    change_pct_1d: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct_5d: Mapped[float | None] = mapped_column(Float)

    macro_flag: Mapped[int] = mapped_column(Integer, default=0)
    macro_note: Mapped[str | None] = mapped_column(String)

    # detected → analyzed → interviewed → diagnosed → watching → closed
    status: Mapped[str] = mapped_column(String, default="detected")

    # 事後検証用（Phase 5）
    outcome_30d: Mapped[str | None] = mapped_column(String)
    outcome_note: Mapped[str | None] = mapped_column(String)

    extra_json: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "trigger_date", name="uq_dip_events_symbol_trigger_date"),
        Index("idx_dip_events_detected_date", "detected_date"),
        Index("idx_dip_events_status", "status"),
    )
