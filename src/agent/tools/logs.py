"""Log retrieval tools."""

from agent.bot.utils import format_loki
from agent.tools import docker
from agent.tools.normalize import regex_parts
from agent.tools.sources import loki


async def get_recent_logs(service: str, lines: int = 10) -> str:
    """Return recent logs for a service. Tries Loki first, falls back to
    Docker container logs when Loki has no matching stream.
    """
    # Loki's stream labels are keyed on the docker-compose service name
    # ('n8n'), not the full container name ('marconi-agent-n8n') callers often
    # pass in — resolve to the label Loki actually carries before matching.
    label = await docker.resolve_label_name(service)
    frag = regex_parts(label)
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

    # Middle fallback: the ``.log`` store collected by agent.logstore —
    # cheaper than Docker, and Loki stays the primary structured source.
    try:
        from datetime import datetime, timedelta, timezone

        from agent.logstore.reader import iter_lines
        from agent.storage.repository import list_watched_containers
        from agent.tools.normalize import normalize as _normalize

        for name in list_watched_containers():
            if _normalize(name) == _normalize(service):
                since = datetime.now(timezone.utc) - timedelta(days=1)
                recs = list(iter_lines(name, since=since))[-lines:]
                if recs:
                    out = "\n".join(f"[{r.get('ts')}] {r.get('raw','')}" for r in recs)
                    if out.strip():
                        return out[:4000]
                break
    except Exception:
        pass

    # Last resort: Docker container logs.
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
