"""Service status tools backed by live Docker container discovery."""

from agent.tools import docker


async def get_service_status(service: str) -> dict:
    """Return the current status of a service by matching a running container."""
    container = await docker.find_container(service)
    if container is None:
        return {"service": service, "status": "not found"}
    return {
        "service": service,
        "container": docker.container_name(container),
        "status": container.get("State", "unknown"),
        "detail": container.get("Status", ""),
        "image": container.get("Image", ""),
    }
