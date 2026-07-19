"""Smoke tests for Discord command wiring."""

from agent.bot.utils import format_loki, format_prometheus, split_discord_text


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


def test_format_prometheus_renders_lines_not_json():
    vector = {"data": {"resultType": "vector", "result": [
        {"metric": {"service": "web"}, "value": [0, "0.42"]},
    ]}}
    assert format_prometheus(vector) == "web: 0.42"
    assert format_prometheus({"data": {"resultType": "scalar", "result": [0, "3"]}}) == "3"
    assert format_prometheus({"data": {"result": []}}) == "No data."


def test_format_loki_renders_plain_log_lines():
    result = {"data": {"result": [
        {"stream": {}, "values": [["1", "line a"], ["2", "line b"]]},
    ]}}
    assert format_loki(result) == "line a\nline b"
    assert format_loki({"data": {"result": []}}) == "No logs."


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
