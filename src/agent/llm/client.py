"""Build a ChatOpenAI client pointing at the self-hosted endpoint."""

from langchain_openai import ChatOpenAI

from agent.config.settings import settings


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    # Local providers don't need a key, but ChatOpenAI requires a non-empty one.
    api_key = settings.llm_api_key or "local-no-key"
    kwargs: dict = dict(
        model=settings.llm_model, api_key=api_key, base_url=settings.llm_base_url, temperature=temperature
    )
    if settings.llm_disable_thinking:
        # Qwen3-style reasoning models: turn the thinking trace off so the bot
        # answers in seconds, not minutes. vLLM reads chat_template_kwargs from
        # the request body; extra_body is the OpenAI SDK's route into that body.
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return ChatOpenAI(**kwargs)
