"""Live check for the configured LLM endpoint and API key."""

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
