"""HTTP API exposing the same read-only workflows the Discord bot runs."""

import json
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.bot import digest
from agent.bot.monitor import get_monitored_endpoints, in_scope, probe
from agent.config.settings import settings
from agent.tools import DOCKER_TOOLS, PROMETHEUS_TOOLS, configured_tools, docker
from agent.watchlist.repository import (
    add_watched_container,
    events_since,
    find_watched_container,
    list_watched_containers,
    remove_watched_container,
)
from agent.workflows.conversations import awaiting_approval, list_threads, read_thread
from agent.workflows.investigate import investigate, stream_investigation
from agent.workflows.report import report, report_question

MAX_EVENT_HOURS = 24 * 90


async def require_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject a request when API_KEY is set and the header does not match."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


app = FastAPI(
    title="Marconi Infrastructure Operations Agent",
    description="Read-only HTTP access to the agent's status, investigation, and reporting workflows.",
    version="1.0.0",
)
guarded = [Depends(require_key)]


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, max_length=100)


class StreamRequest(BaseModel):
    # A client asking for approval must never be silently ignored, so unknown fields are an error.
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, max_length=100)
    tools: list[str] | None = Field(default=None, max_length=50)
    approval: bool = False
    decisions: dict[str, bool] | None = None
    report: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_request(self):
        if sum(x is not None for x in (self.question, self.decisions, self.report)) != 1:
            raise ValueError("send exactly one of question, decisions, or report")
        if self.decisions is not None and not self.thread_id:
            raise ValueError("decisions need the thread_id of the paused run")
        return self


class ServiceRequest(BaseModel):
    service: str = Field(min_length=1, max_length=200)


class WatchRequest(BaseModel):
    container: str = Field(min_length=1, max_length=200)


class Answer(BaseModel):
    answer: str


async def _containers() -> list[dict]:
    watched = set(list_watched_containers())
    try:
        found = await docker.list_containers(all_containers=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"docker unavailable: {exc}") from exc
    return [
        {
            "name": docker.container_name(c),
            "state": c.get("State", "unknown"),
            "status": c.get("Status", ""),
            "image": c.get("Image", ""),
        }
        for c in found
        if in_scope(docker.container_name(c), watched)
    ]


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness check; the only route that never requires a key."""
    return {"status": "ok", "read_only": True}


@app.get("/services", dependencies=guarded, tags=["inventory"])
async def services() -> dict:
    """Container names and monitored endpoints, the same list the agent resolves against."""
    return {
        "containers": [c["name"] for c in await _containers()],
        "endpoints": get_monitored_endpoints(),
    }


@app.get("/containers", dependencies=guarded, tags=["inventory"])
async def containers() -> dict:
    """Every in-scope container with its current state."""
    found = await _containers()
    return {"count": len(found), "containers": found}


@app.get("/status", dependencies=guarded, tags=["inventory"])
async def status() -> dict:
    """Current health of every watched container and endpoint."""
    found = await _containers()
    endpoints = get_monitored_endpoints()
    probed = [
        {"name": name, "url": url, "reachable": await probe(url)}
        for name, url in sorted(endpoints.items())
    ]
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "containers": found,
        "containers_down": [c["name"] for c in found if c["state"] != "running"],
        "endpoints": probed,
        "endpoints_down": [e["name"] for e in probed if not e["reachable"]],
    }


@app.get("/events", dependencies=guarded, tags=["inventory"])
async def events(hours: int = 24) -> dict:
    """Recorded up/down transitions within the last `hours`."""
    if not 1 <= hours <= MAX_EVENT_HOURS:
        raise HTTPException(status_code=422, detail=f"hours must be 1..{MAX_EVENT_HOURS}")
    since = datetime.now(UTC) - timedelta(hours=hours)
    found = events_since(since)
    return {"since": since.isoformat(), "count": len(found), "events": found}


@app.post("/investigate", dependencies=guarded, response_model=Answer, tags=["agent"])
async def run_investigation(body: Question) -> Answer:
    """Put a free-form ops question to the agent."""
    return Answer(answer=await investigate(body.question, thread_id=body.thread_id))


@app.get("/tools", dependencies=guarded, tags=["agent"])
async def tools() -> dict:
    """The tools the agent can use here, for narrowing a streamed investigation."""

    def backend(tool) -> str:
        return "docker" if tool in DOCKER_TOOLS else "prometheus" if tool in PROMETHEUS_TOOLS else "loki"

    return {
        "tools": [
            {"name": t.name, "description": t.description.strip().split("\n")[0], "backend": backend(t)}
            for t in configured_tools()
        ]
    }


@app.post("/investigate/stream", dependencies=guarded, tags=["agent"])
async def stream_investigate(body: StreamRequest) -> StreamingResponse:
    """The same investigation as ``/investigate``, streamed as server-sent events.

    ``tools`` narrows the agent to those tools. With ``approval`` the run pauses before
    every tool call (event ``approval_required``); resume it by sending ``decisions``.
    ``report`` (a service name) asks the ``/report`` incident-report question instead.
    """
    available = {t.name for t in configured_tools()}
    if unknown := sorted(set(body.tools or []) - available):
        raise HTTPException(status_code=422, detail=f"unknown or unconfigured tools: {', '.join(unknown)}")

    async def events():
        async for event, data in stream_investigation(
            report_question(body.report) if body.report else body.question,
            thread_id=body.thread_id,
            tools=body.tools,
            approval=body.approval,
            decisions=body.decisions,
        ):
            yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/report", dependencies=guarded, response_model=Answer, tags=["agent"])
async def run_report(body: ServiceRequest) -> Answer:
    """Generate a structured incident report for one service."""
    return Answer(answer=await report(body.service))


@app.get("/digest/{kind}", dependencies=guarded, tags=["agent"])
async def render_digest(kind: str) -> dict:
    """Render the daily or weekly digest without waiting for its scheduled hour."""
    if kind not in ("daily", "weekly"):
        raise HTTPException(status_code=422, detail="kind must be 'daily' or 'weekly'")
    now = datetime.now(UTC)
    body = await (digest.build_weekly(now) if kind == "weekly" else digest.build_daily(now))
    return {"kind": kind, "generated_at": now.isoformat(), "body": body}


@app.get("/threads", dependencies=guarded, tags=["conversations"])
async def threads() -> dict:
    """Every stored conversation (Discord channels, DMs, and API threads), most recent first."""
    found = await list_threads()
    return {"count": len(found), "threads": found}


@app.get("/threads/{thread_id}", dependencies=guarded, tags=["conversations"])
async def thread(thread_id: str) -> dict:
    """The full transcript of one conversation, and any tool calls still awaiting approval."""
    messages = await read_thread(thread_id)
    if messages is None:
        raise HTTPException(status_code=404, detail=f"no conversation '{thread_id}'")
    return {
        "thread_id": thread_id,
        "messages": messages,
        "awaiting_approval": await awaiting_approval(thread_id),
    }


@app.get("/watchlist", dependencies=guarded, tags=["watchlist"])
async def get_watchlist() -> dict:
    """Containers pinned into monitoring scope regardless of the name filter."""
    watched = list_watched_containers()
    return {"count": len(watched), "containers": watched}


@app.post("/watchlist", dependencies=guarded, status_code=201, tags=["watchlist"])
async def add_to_watchlist(body: WatchRequest) -> dict:
    """Pin a container into monitoring scope."""
    return {"container": body.container, "added": add_watched_container(body.container)}


@app.delete("/watchlist/{container}", dependencies=guarded, tags=["watchlist"])
async def remove_from_watchlist(container: str) -> dict:
    """Unpin a container, matching the stored name separator-agnostically."""
    stored = find_watched_container(container)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"'{container}' is not on the watch list")
    return {"container": stored, "removed": remove_watched_container(stored)}
