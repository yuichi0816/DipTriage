import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_generate_returns_text_and_elapsed():
    mock_response = MagicMock()
    mock_response.message.content = "test output"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        text, elapsed = await generate("hello", model="test-model")

    assert text == "test output"
    assert elapsed >= 0.0


async def test_generate_passes_prompt_to_chat():
    mock_response = MagicMock()
    mock_response.message.content = "ok"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        await generate("my special prompt", model="qwen3:30b")

        chat_call = mock_instance.chat.call_args
        messages = chat_call.kwargs.get("messages") or chat_call.args[1]
        assert any("my special prompt" in str(m) for m in messages)
