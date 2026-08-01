"""Build a ChatOpenAI client pointing at a self-hosted endpoint.

Supports A/B switching between local providers via ``LLM_PROVIDER``: "ollama" or
"vllm" select the matching presets; empty uses the legacy LLM_BASE_URL/LLM_MODEL.
"""

from langchain_openai import ChatOpenAI

from agent.config.settings import settings


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        base_url, model = settings.ollama_base_url, settings.ollama_model
    elif provider == "vllm":
        base_url, model = settings.vllm_base_url, settings.vllm_model
    else:
        base_url, model = settings.llm_base_url, settings.llm_model

    # Local providers don't need a key, but ChatOpenAI requires a non-empty one.
    api_key = settings.llm_api_key or "local-no-key"
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
    )
