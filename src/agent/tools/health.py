"""HTTP endpoint health checks."""

import time

import httpx2 as httpx


async def check_endpoint(url: str, timeout: float = 5.0) -> dict:
    """Check whether an HTTP/HTTPS endpoint is reachable and measure latency."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "url": url,
                "reachable": True,
                "status_code": response.status_code,
                "response_time_ms": round(elapsed_ms, 2),
            }
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "url": url,
            "reachable": False,
            "status_code": None,
            "response_time_ms": round(elapsed_ms, 2),
            "error": str(exc),
        }
