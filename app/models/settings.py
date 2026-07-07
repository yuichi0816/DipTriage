from sqlalchemy import Float, String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_fetch_enabled: Mapped[int] = mapped_column(Integer, default=1)   # 1=ON, 0=OFF
    include_nikkei225: Mapped[int] = mapped_column(Integer, default=1)    # 1=ON, 0=OFF
    include_standard: Mapped[int] = mapped_column(Integer, default=0)     # 1=ON, 0=OFF
    include_growth: Mapped[int] = mapped_column(Integer, default=0)       # 1=ON, 0=OFF
    include_sp500: Mapped[int] = mapped_column(Integer, default=1)        # 1=ON, 0=OFF
    pipeline_hour: Mapped[int] = mapped_column(Integer, default=7)
    pipeline_minute: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str | None] = mapped_column(String)
    llm_provider: Mapped[str] = mapped_column(String, default="ollama")  # ollama | groq
    groq_api_key: Mapped[str | None] = mapped_column(String)
    groq_model_interview: Mapped[str] = mapped_column(String, default="llama-3.1-8b-instant")
    groq_model_diagnosis: Mapped[str] = mapped_column(String, default="llama-3.3-70b-versatile")
    news_refresh_days: Mapped[int] = mapped_column(Integer, default=5)
    dip_lookback_days: Mapped[int] = mapped_column(Integer, default=2)
    threshold_dip_pct: Mapped[float] = mapped_column(Float, default=-5.0)
    macro_filter_pct: Mapped[float] = mapped_column(Float, default=-2.0)
