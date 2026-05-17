"""Ollama AsyncClient の薄いラッパー。"""
from __future__ import annotations

import time

from ollama import AsyncClient

from app.config import OLLAMA_HOST, OLLAMA_MODEL_INTERVIEW


async def generate(
    prompt: str,
    model: str = OLLAMA_MODEL_INTERVIEW,
    think: bool = False,
) -> tuple[str, float]:
    """Ollama にプロンプトを送り (response_text, elapsed_seconds) を返す。

    think=False で Qwen3 の thinking mode を無効化し高速化する（問診用）。
    think=True は Phase 3 診断など深い推論が必要な場合に使う。
    """
    client = AsyncClient(host=OLLAMA_HOST)
    t0 = time.monotonic()
    response = await client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        think=think,
    )
    elapsed = time.monotonic() - t0
    return response.message.content, elapsed
