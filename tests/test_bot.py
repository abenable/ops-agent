"""Smoke tests for Discord command wiring."""


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
