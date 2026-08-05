"""Log retrieval tools."""

from agent.bot.utils import format_loki
from agent.tools import docker
from agent.tools.normalize import regex_parts
from agent.tools.sources import loki


async def get_recent_logs(service: str, lines: int = 10) -> str:
    """Return recent logs for a service. Tries Loki first, falls back to
    Docker container logs when Loki has no matching stream.
    """
    frag = regex_parts(service)
    selectors = [
        f'{{service=~".*{frag}.*"}}',
        f'{{container=~".*{frag}.*"}}',
        f'{{name=~".*{frag}.*"}}',
    ]
    result: dict = {}
    for sel in selectors:
        try:
            result = await loki.query_loki_range(sel, minutes=1440, limit=lines)
        except Exception:
            continue
        if result.get("data", {}).get("result"):
            return format_loki(result, limit=lines)

    # Fall back to Docker container logs when Loki has no data for this service.
    try:
        container = await docker.find_container(service)
        if container is not None:
            from agent.tools.docker import container_logs

            cid = container.get("Id") or docker.container_name(container)
            raw = await container_logs(cid, tail=lines)
            cleaned = "".join(c for c in raw if c.isprintable() or c in "\n\t")
            if cleaned.strip():
                return cleaned[:4000]
    except Exception:
        pass

    return "No logs."
