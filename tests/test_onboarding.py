"""Tests for the #welcome and #project-notes startup messages."""

from agent.bot.onboarding import build_project_notes_embed, build_welcome_embed


def test_welcome_embed_has_commands_and_channels():
    embed = build_welcome_embed(None)
    assert "Infrastructure Ops Agent" in embed.title
    fields = {f.name: f.value for f in embed.fields}
    assert "Commands (prefix `!` or slash `/`)" in fields
    assert "ask <question>" in fields["Commands (prefix `!` or slash `/`)"]
    assert "Channels" in fields


def test_project_notes_embed_lists_architecture_tools_scenarios():
    embed = build_project_notes_embed()
    fields = {f.name: f.value for f in embed.fields}
    assert "Architecture" in fields
    assert "list_services" in fields["Tools (read-only to the investigator)"]
    assert "Scenarios" in fields
    assert "api_down" in fields["Scenarios"]
    assert "LLM" in fields
