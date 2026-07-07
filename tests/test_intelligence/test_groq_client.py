import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_generate_sets_deterministic_params():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"

    with patch("app.intelligence.groq_client.AsyncGroq") as MockGroq:
        instance = MockGroq.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_response)

        from app.intelligence.groq_client import generate
        text, elapsed = await generate("p", model="m", api_key="k")

    kwargs = instance.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["seed"] == 42
    assert kwargs["max_tokens"] == 1024
    assert MockGroq.call_args.kwargs["timeout"] == 120.0
    assert text == "ok"
    assert elapsed >= 0.0


async def test_generate_think_mode_uses_long_timeout_and_budget():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"

    with patch("app.intelligence.groq_client.AsyncGroq") as MockGroq:
        instance = MockGroq.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_response)

        from app.intelligence.groq_client import generate
        await generate("p", model="m", api_key="k", think=True)

    assert MockGroq.call_args.kwargs["timeout"] == 600.0
    assert instance.chat.completions.create.call_args.kwargs["max_tokens"] == 4096
