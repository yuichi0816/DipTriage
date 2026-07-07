"""Ollama AsyncClient の薄いラッパー。"""
from __future__ import annotations

import time

from ollama import AsyncClient

from app.config import OLLAMA_HOST, OLLAMA_MODEL_INTERVIEW

# 分類の再現性のため生成パラメータを固定する（監査 1-1）
_BASE_OPTIONS = {"temperature": 0.0, "seed": 42}


async def generate(
    prompt: str,
    model: str = OLLAMA_MODEL_INTERVIEW,
    think: bool = False,
) -> tuple[str, float]:
    """Ollama にプロンプトを送り (response_text, elapsed_seconds) を返す。

    think=False で Qwen3 の thinking mode を無効化し高速化する（問診用）。
    think=True は診断など深い推論が必要な場合に使う。
    """
    timeout = 600.0 if think else 120.0
    num_predict = 4096 if think else 1024
    client = AsyncClient(host=OLLAMA_HOST, timeout=timeout)
    t0 = time.monotonic()
    response = await client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        think=think,
        options={**_BASE_OPTIONS, "num_predict": num_predict},
    )
    elapsed = time.monotonic() - t0
    return response.message.content, elapsed
