"""Incident action tools backed by SQLite storage."""

from agent.storage import repository


def acknowledge_incident(incident_id: str) -> dict | None:
    """Mark an incident as acknowledged."""
    return repository.update_incident_status(incident_id, "acknowledged")


def resolve_incident(incident_id: str) -> dict | None:
    """Mark an incident as resolved."""
    return repository.update_incident_status(incident_id, "resolved")


def list_incidents(status: str | None = None, limit: int = 50) -> list[dict]:
    """List recent incidents, optionally filtered by status."""
    return repository.list_incidents(status=status, limit=limit)
