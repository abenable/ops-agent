"""Service status tools."""


async def get_service_status(service: str) -> dict:
    """Return the current status of a service."""
    return {"service": service, "status": "unknown"}
