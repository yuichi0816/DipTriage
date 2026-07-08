"""LLM プロバイダーディスパッチャー。設定に応じて Ollama か Groq に振り分ける。"""
from __future__ import annotations

from sqlalchemy import select

from app.config import GROQ_API_KEY
from app.database import AsyncSessionLocal
from app.models.settings import AppSettings
from app.intelligence import ollama_client, groq_client


async def generate(prompt: str, model: str, think: bool = False) -> tuple[str, float]:
    """プロンプトを送り (response_text, elapsed_seconds) を返す。

    llm_provider=groq のとき model 引数は無視し、DB の groq_model_* を使う。
    think=True → diagnosis モデル、think=False → interview モデルで振り分け。
    """
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(AppSettings).where(AppSettings.id == 1))
        settings = r.scalar_one_or_none()

    if settings and settings.llm_provider == "groq":
        groq_model = settings.groq_model_diagnosis if think else settings.groq_model_interview
        # .env の GROQ_API_KEY を優先。DB 保存キーは後方互換のフォールバック（監査 4-3）
        api_key = GROQ_API_KEY or settings.groq_api_key or ""
        return await groq_client.generate(
            prompt, model=groq_model, api_key=api_key, think=think
        )
    return await ollama_client.generate(prompt, model=model, think=think)
