"""Agent workflows: the units of work a Discord command or message triggers.

Each module is one workflow with no Discord types in its signature — a
plain ``async def -> str`` the bot layer (``agent.bot``) calls and sends.
"""
