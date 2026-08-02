"""Live check for the configured LLM endpoint and API key, plus runtime switch tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.config.settings import settings
from agent.llm.client import _resolve, get_llm, set_llm_provider


@pytest.mark.integration
@pytest.mark.skipif(
    not settings.llm_api_key or settings.llm_api_key == "sk-optional",
    reason="LLM_API_KEY not configured",
)
def test_llm_connection_and_api_key():
    """A simple chat completion proves the endpoint and key work."""
    llm = get_llm()
    response = llm.invoke("Reply with the single word 'pong'.")
    assert isinstance(response.content, str)
    assert response.content.strip()


def test_resolve_maps_each_provider_case_insensitively():
    assert _resolve("ollama") == (settings.ollama_base_url, settings.ollama_model)
    assert _resolve("vllm") == (settings.vllm_base_url, settings.vllm_model)
    assert _resolve("") == (settings.llm_base_url, settings.llm_model)
    assert _resolve("OLLAMA") == (settings.ollama_base_url, settings.ollama_model)


def test_set_llm_provider_validates_and_normalises():
    original = settings.llm_provider
    try:
        assert set_llm_provider("OLLAMA") == "ollama"
        assert settings.llm_provider == "ollama"
        assert set_llm_provider("Vllm") == "vllm"
        assert settings.llm_provider == "vllm"
        assert set_llm_provider("") == ""
        assert settings.llm_provider == ""
    finally:
        settings.llm_provider = original


def test_set_llm_provider_rejects_unknown_without_mutating():
    original = settings.llm_provider
    try:
        with pytest.raises(ValueError):
            set_llm_provider("bedrock")
        assert settings.llm_provider == original
    finally:
        settings.llm_provider = original


def test_get_llm_constructs_for_each_provider():
    original = settings.llm_provider
    try:
        for p in ("", "ollama", "vllm"):
            set_llm_provider(p)
            get_llm()  # must not raise for any configured provider
        assert _resolve(settings.llm_provider) == _resolve("vllm")
    finally:
        settings.llm_provider = original


def test_llm_provider_view_button_switches_and_reports():
    from agent.bot.views import LLMProviderView

    original = settings.llm_provider
    try:
        set_llm_provider("")  # start on Legacy
        view = LLMProviderView()
        legacy_btn = next(b for b in view.children if b.label == "Legacy")
        vllm_btn = next(b for b in view.children if b.label == "vLLM")
        assert legacy_btn.disabled is True   # active provider's button is disabled
        assert vllm_btn.disabled is False

        interaction = SimpleNamespace(
            response=SimpleNamespace(edit_message=AsyncMock())
        )
        with patch(
            "agent.bot.views.llm_supports_tool_calls",
            new=AsyncMock(return_value=True),
        ):
            import asyncio

            asyncio.run(vllm_btn.callback(interaction))

        assert settings.llm_provider == "vllm"
        interaction.response.edit_message.assert_awaited_once()
        content = interaction.response.edit_message.call_args.kwargs["content"]
        assert "vLLM" in content and "tool calls: yes" in content
    finally:
        settings.llm_provider = original
