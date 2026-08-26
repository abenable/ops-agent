"""Pydantic settings loaded from environment and `.env`."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_env() -> None:
    """Load environment variables from the nearest `.env` file."""
    env_file = find_dotenv()
    if env_file:
        load_dotenv(env_file, override=False)


load_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_parse_none_str="",
    )

    discord_bot_token: str = Field(default="", validation_alias="DISCORD_BOT_TOKEN")
    discord_guild_id: int | None = None
    discord_alert_channel_id: int | None = None
    discord_status_channel_id: int | None = None
    discord_reports_channel_id: int | None = None
    discord_log_channel_id: int | None = None
    discord_incident_channel_id: int | None = None
    discord_test_scenarios_channel_id: int | None = None

    monitored_endpoints: str = ""
    monitor_interval_seconds: int = 60
    prometheus_alert_rules: str = ""

    llm_provider: str = Field(
        default="google",
        validation_alias="LLM_PROVIDER",
    )
    llm_base_url: str = "http://100.64.0.7:4000/v1"
    llm_model: str = "gemma-4-31b-it"
    llm_summarizer_model: str = ""
    llm_api_key: str = Field(
        default="",
        validation_alias="LLM_API_KEY",
    )
    google_api_key: str = Field(
        default="",
        validation_alias="GEMINI_API_KEY",
    )

    @property
    def model_id(self) -> str:
        """The ``provider:model`` identifier ``init_chat_model`` takes."""
        provider = "google_genai" if self.llm_provider == "google" else "openai"
        return f"{provider}:{self.llm_model}"

    @property
    def summarizer_model_id(self) -> str:
        """``model_id`` for the cheaper summarization model, if one is set."""
        provider = "google_genai" if self.llm_provider == "google" else "openai"
        return f"{provider}:{self.llm_summarizer_model or self.llm_model}"

    prometheus_url: str = ""
    loki_url: str = ""
    prometheus_token: str = ""
    loki_token: str = ""

    max_tool_steps: int = 10
    max_context_tokens: int = 12000
    loki_max_limit: int = 500
    range_max_hours: int = 6

    report_hour_utc: int = 5
    status_interval_hours: int = 2
    weekly_report_weekday: int = 0
    digest_lookback_days: int = 7

    docker_monitor: bool = False
    docker_name_filter: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = Field(default="", validation_alias="API_KEY")

    database_url: str = "sqlite:///data/agent.db"

    @model_validator(mode="before")
    @classmethod
    def _blank_env_to_empty_string(cls, data):
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                if field.annotation is not str:
                    continue
                alias = (
                    field.validation_alias
                    if isinstance(field.validation_alias, str)
                    else None
                )
                for key in (name, alias):
                    if key in data and data[key] is None:
                        data[key] = ""
        return data


settings = Settings()

DB_PATH = Path(settings.database_url.replace("sqlite:///", ""))
if not DB_PATH.is_absolute():
    DB_PATH = Path(__file__).resolve().parents[3] / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

MEMORY_DB_PATH = DB_PATH.with_name("memory.db")


def _export_provider_env() -> None:
    """Publish the configured credentials/endpoint into the environment."""
    for name, value in (
        ("OPENAI_API_KEY", settings.llm_api_key),
        ("OPENAI_API_BASE", settings.llm_base_url),
        ("GOOGLE_API_KEY", settings.google_api_key),
    ):
        if value:
            os.environ[name] = value


_export_provider_env()
