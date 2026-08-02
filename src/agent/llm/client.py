"""Build a ChatOpenAI client pointing at a self-hosted endpoint.

Supports A/B switching between local providers via ``LLM_PROVIDER``: "ollama" or
"vllm" select the matching presets; empty uses the legacy LLM_BASE_URL/LLM_MODEL.
``set_llm_provider`` flips the selection at runtime (e.g. from a Discord button),
and ``get_llm`` reads it fresh on every call, so a switch takes effect on the
next LLM invocation with no restart.
"""

from langchain_openai import ChatOpenAI

from agent.config.settings import settings

PROVIDERS = ("", "ollama", "vllm")


def _resolve(provider: str) -> tuple[str, str]:
    provider = (provider or "").lower()
    if provider == "ollama":
        return settings.ollama_base_url, settings.ollama_model
    if provider == "vllm":
        return settings.vllm_base_url, settings.vllm_model
    return settings.llm_base_url, settings.llm_model


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    base_url, model = _resolve(settings.llm_provider)
    # Local providers don't need a key, but ChatOpenAI requires a non-empty one.
    api_key = settings.llm_api_key or "local-no-key"
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
    )


def set_llm_provider(provider: str) -> str:
    """Set the active LLM provider at runtime.

    Accepts "", "ollama", "vllm" (case-insensitive). Returns the normalised value.
    Raises ValueError on anything else.
    """
    p = (provider or "").lower()
    if p not in PROVIDERS:
        raise ValueError(f"unknown LLM provider: {provider!r}")
    settings.llm_provider = p
    return p
