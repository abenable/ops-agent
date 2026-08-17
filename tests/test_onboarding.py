"""Tests for the #welcome and #project-notes startup messages."""

from agent.bot.onboarding import build_project_notes_embed, build_welcome_embed


def test_welcome_embed_has_commands_and_channels():
    embed = build_welcome_embed(None)
    assert "Infrastructure Ops Agent" in embed.title
    fields = {f.name: f.value for f in embed.fields}
    assert "Commands (slash `/`)" in fields
    assert "containers" in fields["Commands (slash `/`)"]
    assert "Channels" in fields


def test_project_notes_embed_lists_architecture_and_llm():
    embed = build_project_notes_embed()
    fields = {f.name: f.value for f in embed.fields}
    assert "Architecture" in fields
    assert "Channels" in fields
    assert "LLM" in fields
