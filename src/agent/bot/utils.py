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
