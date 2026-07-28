"""Pydantic settings loaded from environment and `.env`."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.config.dotenv_loader import load_env

load_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_parse_none_str="",
    )

    # Discord
    discord_bot_token: str = Field(default="", validation_alias="DISCORD_BOT_TOKEN")
    discord_guild_id: int | None = None
    discord_alert_channel_id: int | None = None
    discord_incident_channel_id: int | None = None
    discord_status_channel_id: int | None = None
    discord_log_channel_id: int | None = None
    discord_test_scenarios_channel_id: int | None = None
    # User ID to DM when incidents are created (optional).
    discord_dm_user_id: int | None = None

    # Endpoint monitoring loop
    monitored_endpoints: str = ""
    monitor_interval_seconds: int = 60

    # Self-hosted LLM (OpenAI-compatible)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "mistral"
    llm_api_key: str = Field(
        default="",
        validation_alias="LLM_API_KEY",
    )

    # API server
    api_key: str = Field(default="", validation_alias="API_KEY")
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Monitoring / logging integrations
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    prometheus_alert_rules: str = ""
    prometheus_token: str = ""
    loki_token: str = ""

    # Agentic investigation loop
    max_tool_steps: int = 6
    loki_max_limit: int = 500
    range_max_hours: int = 6

    # Docker container discovery (DOCKER_HOST is read from the env by tools/docker.py)
    docker_monitor: bool = False
    docker_name_filter: str = ""

    # Storage
    database_url: str = "sqlite:///data/agent.db"

    @model_validator(mode="before")
    @classmethod
    def _blank_env_to_empty_string(cls, data):
        # env_parse_none_str="" turns empty env vars into None (needed for the
        # optional int fields). Keep plain str fields as "" instead of None.
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                if field.annotation is not str:
                    continue
                alias = field.validation_alias if isinstance(field.validation_alias, str) else None
                for key in (name, alias):
                    if key in data and data[key] is None:
                        data[key] = ""
        return data


settings = Settings()
