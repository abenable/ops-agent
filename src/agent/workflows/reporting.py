"""Incident reporting workflow."""

from agent.storage.repository import get_incident


def run_report_workflow(incident_id: str) -> str:
    """Retrieve a stored incident and return a formatted report."""
    incident = get_incident(incident_id)
    if incident is None:
        return f"No incident found with id {incident_id}"
    return (
        f"Incident {incident['id']} ({incident['service']})\n"
        f"Created at: {incident['created_at']}\n"
        f"Summary: {incident['summary']}"
    )
