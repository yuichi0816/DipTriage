"""Groq API の薄いラッパー。ollama_client と同じインターフェース。"""
from __future__ import annotations

import time

from groq import AsyncGroq


async def generate(prompt: str, model: str, api_key: str = "") -> tuple[str, float]:
    """Groq にプロンプトを送り (response_text, elapsed_seconds) を返す。"""
    client = AsyncGroq(api_key=api_key)
    t0 = time.monotonic()
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - t0
    return response.choices[0].message.content, elapsed
