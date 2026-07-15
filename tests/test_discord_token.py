"""Live check that the Discord bot token is accepted by Discord."""

import httpx2 as httpx
import pytest

from agent.config.settings import settings


@pytest.mark.integration
@pytest.mark.skipif(
    not settings.discord_bot_token,
    reason="DISCORD_BOT_TOKEN not configured",
)
def test_discord_bot_token_valid():
    """Hit Discord's @me endpoint without opening a gateway connection."""
    response = httpx.get(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {settings.discord_bot_token}"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    assert "id" in data
    assert data.get("bot") is True
