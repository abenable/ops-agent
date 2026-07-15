"""Smoke tests for Discord command wiring."""

from agent.bot.utils import split_discord_text


def test_split_discord_text_chunks_at_limit_and_prefers_newlines():
    short = "hello"
    assert split_discord_text(short) == ["hello"]

    long = "a" * 2000
    chunks = split_discord_text(long, max_len=10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == long

    with_newlines = "\n".join(["line"] * 500)
    chunks = split_discord_text(with_newlines, max_len=20)
    assert all(len(c) <= 20 for c in chunks)
    assert "\n".join(chunks) == with_newlines


def test_commands_registered():
    from agent.bot.commands import setup_commands

    class FakeBot:
        def __init__(self):
            self.commands = {}

        def command(self, *, name: str):
            def decorator(func):
                self.commands[name] = func
                return func

            return decorator

    bot = FakeBot()
    setup_commands(bot)
    assert "status" in bot.commands
    assert "logs" in bot.commands
    assert "metrics" in bot.commands
    assert "incident" in bot.commands
