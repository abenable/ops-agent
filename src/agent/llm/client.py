"""Build a ChatOpenAI client pointing at a self-hosted endpoint."""

from langchain_openai import ChatOpenAI

from agent.config.settings import settings


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
    )
