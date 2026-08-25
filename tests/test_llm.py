"""The model is passed to create_agent as a ``provider:model`` string, so ``settings.model_id`` plus the exported environment must resolve to a client pointed at the configured endpoint."""

import os

import pytest
from langchain.chat_models import init_chat_model

from agent.config.settings import Settings, _export_provider_env, settings


def _api_key_missing() -> bool:
    if settings.llm_provider == "google":
        return not settings.google_api_key
    return not settings.llm_api_key or settings.llm_api_key == "sk-optional"


def test_model_id_maps_provider_and_summarizer_fallback():
    """Both providers, and the summarizer falling back to the main model."""
    openai = Settings(LLM_PROVIDER="openai", llm_model="m", llm_summarizer_model="", _env_file=None)
    assert openai.model_id == "openai:m"
    assert openai.summarizer_model_id == "openai:m"

    google = Settings(LLM_PROVIDER="google", llm_model="g", llm_summarizer_model="small", _env_file=None)
    assert google.model_id == "google_genai:g"
    assert google.summarizer_model_id == "google_genai:small"


def test_provider_config_is_exported_to_the_environment(monkeypatch):
    """The configured endpoint and key must reach the client through the environment."""
    monkeypatch.setattr(settings, "llm_api_key", "key-123")
    monkeypatch.setattr(settings, "llm_base_url", "http://endpoint:4000/v1")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _export_provider_env()

    assert os.environ["OPENAI_API_BASE"] == "http://endpoint:4000/v1"
    assert os.environ["OPENAI_API_KEY"] == "key-123"


@pytest.mark.skipif(
    settings.llm_provider != "openai", reason="openai-specific client attributes"
)
def test_the_string_form_resolves_to_the_configured_endpoint():
    """The identifier the agent passes really does build a client aimed at this deployment's endpoint."""
    llm = init_chat_model(settings.model_id)
    assert llm.model_name == settings.llm_model
    assert llm.openai_api_base == settings.llm_base_url


@pytest.mark.integration
@pytest.mark.skipif(_api_key_missing(), reason="API key not configured for the selected LLM_PROVIDER")
def test_llm_connection_and_api_key():
    """A simple chat completion proves the endpoint and key work."""
    response = init_chat_model(settings.model_id).invoke("Reply with the single word 'pong'.")
    assert isinstance(response.content, str)
    assert response.content.strip()
