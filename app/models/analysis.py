from sqlalchemy import String, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class NumericalAnalysis(Base):
    __tablename__ = "numerical_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dip_event_id: Mapped[int] = mapped_column(Integer, ForeignKey("dip_events.id"), nullable=False)

    # 出来高
    volume_ratio_20d: Mapped[float | None] = mapped_column(Float)

    # ボラティリティ
    volatility_1y_sigma: Mapped[float | None] = mapped_column(Float)
    vol_deviation: Mapped[float | None] = mapped_column(Float)  # 今回の下落が何σか

    # 銘柄固有性
    beta_1y: Mapped[float | None] = mapped_column(Float)
    sector_change_pct: Mapped[float | None] = mapped_column(Float)
    sector_relative: Mapped[float | None] = mapped_column(Float)  # 超過下落率
    sector_corr_90d: Mapped[float | None] = mapped_column(Float)

    # バリュエーション
    per: Mapped[float | None] = mapped_column(Float)
    pbr: Mapped[float | None] = mapped_column(Float)
    equity_ratio: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)

    # 固有判定スコア（0〜1、高いほど銘柄固有）
    is_idiosyncratic: Mapped[int | None] = mapped_column(Integer)
    idiosyncratic_score: Mapped[float | None] = mapped_column(Float)

    analysis_json: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_numerical_analyses_dip_event_id", "dip_event_id"),
    )
