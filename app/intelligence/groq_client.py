"""Groq API の薄いラッパー。ollama_client と同じインターフェース。"""
from __future__ import annotations

import time

from groq import AsyncGroq


async def generate(
    prompt: str,
    model: str,
    api_key: str = "",
    think: bool = False,
) -> tuple[str, float]:
    """Groq にプロンプトを送り (response_text, elapsed_seconds) を返す。

    分類の再現性のため temperature=0 / seed 固定（監査 1-1）。
    """
    client = AsyncGroq(api_key=api_key, timeout=600.0 if think else 120.0)
    t0 = time.monotonic()
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        seed=42,
        max_tokens=4096 if think else 1024,
    )
    elapsed = time.monotonic() - t0
    return response.choices[0].message.content, elapsed
