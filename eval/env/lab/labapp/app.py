import logging
import os
import random
import signal
import socket
import sys
import time

from prometheus_client import Counter, Histogram, start_http_server

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
)
log = logging.getLogger(os.environ.get("APP_NAME", "app"))
MODE = os.environ.get("MODE", "normal")
LEAK_MB = int(os.environ.get("LEAK_MB", "8"))
REQUESTS = Counter("app_requests_total", "Handled requests", ["status"])
LATENCY = Histogram("app_request_duration_seconds", "Request latency")


def stop(signum, frame) -> None:
    log.info("received SIGTERM, shutting down")
    raise SystemExit(0)


def dependency_ok() -> bool:
    dep = os.environ.get("DEPENDS_ON")
    if not dep:
        return True
    host, port = dep.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=1).close()
        return True
    except OSError as exc:
        log.error("dependency %s unreachable: %s", dep, exc)
        return False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    for name in filter(None, os.environ.get("REQUIRED_ENV", "").split(",")):
        if name not in os.environ:
            log.critical("missing required setting %s", name)
            raise SystemExit(1)
    start_http_server(8000)
    log.info("started version %s", os.environ.get("APP_VERSION", "0.0.0"))
    hog: list[bytes] = []
    written = 0
    while True:
        if extra := os.environ.get("EXTRA_LOG"):
            log.warning(extra)
        if MODE == "leak":
            hog.append(b"x" * (LEAK_MB * 1024 * 1024))
            log.info("cache size %d MiB", LEAK_MB * len(hog))
        if MODE == "disk":
            try:
                with open("/data/spool.bin", "ab") as f:
                    f.write(os.urandom(1024 * 1024))
                written += 1
                log.info("spooled %d MiB", written)
            except OSError as exc:
                log.critical("cannot write spool: %s", exc)
                raise SystemExit(1)
        ok = dependency_ok() and not (MODE == "error" and random.random() < 0.6)
        with LATENCY.time():
            time.sleep(random.uniform(1.5, 3.0) if MODE == "slow" else random.uniform(0.01, 0.05))
        REQUESTS.labels("200" if ok else "500").inc()
        if MODE == "error" and not ok:
            log.error("request failed: upstream returned 500")
        time.sleep(0.5)


main()
