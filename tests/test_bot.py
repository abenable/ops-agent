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


def test_slash_commands_registered():
    from agent.bot.slash import setup_slash_commands

    class FakeTree:
        def __init__(self):
            self.commands = {}

        def command(self, *, name: str, description: str):
            def decorator(func):
                self.commands[name] = func
                return func

            return decorator

    class FakeBot:
        def __init__(self):
            self.tree = FakeTree()

    bot = FakeBot()
    setup_slash_commands(bot)
    for name in (
        "status", "investigate", "report", "containers",
        "watching", "watch", "unwatch", "watchlist",
    ):
        assert name in bot.tree.commands


def test_discord_log_handler_forwards_info_and_quiets_httpx():
    import asyncio
    import logging

    from agent.bot.client import DiscordLogHandler, _setup_logging

    _setup_logging()
    # httpx/httpx2 are transport noise; one INFO line per request would flood the
    # Discord log channel, so they must be silenced to WARNING.
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpx2").level == logging.WARNING

    class FakeChannel:
        def __init__(self):
            self.sent = []

        async def send(self, msg):
            self.sent.append(msg)

    class FakeBot:
        def __init__(self, ch):
            self._ch = ch

        def get_channel(self, _id):
            return self._ch

        async def fetch_channel(self, _id):
            return self._ch

    ch = FakeChannel()
    bot = FakeBot(ch)
    handler = DiscordLogHandler(bot, 123)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s\n%(message)s"))
    test_logger = logging.getLogger("agent.test")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)  # don't depend on root's effective level
    # Drive the pump so the bootstrap banner and any queued records flush.
    async def run():
        import asyncio as _aio
        task = _aio.create_task(handler.pump())
        test_logger.info("tool call happened")
        await _aio.sleep(0.2)
        task.cancel()
        try:
            await task
        except _aio.CancelledError:
            pass

    asyncio.run(run())
    assert any("Log forwarding active (INFO and above)." in m for m in ch.sent)
    assert any("tool call happened" in m for m in ch.sent)
