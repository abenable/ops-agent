"""Discord-specific helpers."""


def split_discord_text(text: str, max_len: int = 1900) -> list[str]:
    """Split a long message into chunks that fit Discord's 2000-character limit."""
    if not text:
        return []

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def format_prometheus(result: dict) -> str:
    """Render a Prometheus query response as human-readable lines, not JSON."""
    data = result.get("data", {})
    if data.get("resultType") == "scalar":
        return str(data.get("result", ["", "?"])[1])

    series = data.get("result") or []
    if not series:
        return "No data."

    lines = []
    for s in series:
        metric = s.get("metric", {})
        name = metric.get("service") or metric.get("instance") or metric.get("__name__") or "value"
        value = s.get("value", [None, "?"])[1]
        lines.append(f"{name}: {value}")
    return "\n".join(lines)


def format_loki(result: dict, limit: int = 25) -> str:
    """Render a Loki query response as plain log lines, not JSON."""
    streams = result.get("data", {}).get("result", [])
    lines = [line for s in streams for _ts, line in s.get("values", [])]
    if not lines:
        return "No logs."
    return "\n".join(lines[-limit:])
