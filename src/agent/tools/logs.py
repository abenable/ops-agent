"""Log retrieval tools."""


async def get_recent_logs(service: str, lines: int = 10) -> str:
    """Return recent logs for a service.

    Replace this stub with integration to Loki, journald, or log files.
    """
    return f"// ponytail: stub log output for {service} ({lines} lines)"
