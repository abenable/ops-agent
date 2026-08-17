"""Live check for the configured LLM endpoint and API key, plus client construction."""

import pytest

from agent.config.settings import settings
from agent.llm.client import get_llm


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


def test_get_llm_reads_base_url_and_model():
    llm = get_llm()
    assert llm.model_name == settings.llm_model
    assert llm.openai_api_base == settings.llm_base_url
