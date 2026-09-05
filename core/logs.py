"""Log sources and tail/read helpers for Settings → Logs."""

import logging
import time
from pathlib import Path

import docker
from django.conf import settings
from django.core.cache import cache

from dashboard.hostops import CONTAINER_NAME_RE

logger = logging.getLogger(__name__)

MAX_TAIL = 1000
MAX_RESPONSE_BYTES = 256 * 1024
MAX_LINE_BYTES = 2048
MAX_DOWNLOAD_BYTES = 1024 * 1024
DOCKER_LOG_TIMEOUT = 5
CACHE_TTL = 3

FILE_SOURCES = {
    "app": "Control Center",
    "tick": "Tick sidecar",
}

CORE_CONTAINERS = ("control-center", "control-center-tick")


def ensure_log_dirs():
    log_dir = Path(settings.CC_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    console_dir = Path(settings.CC_CONSOLE_LOG_DIR)
    console_dir.mkdir(parents=True, exist_ok=True)


def _log_file(source_id):
    if source_id == "app":
        return Path(settings.CC_LOG_FILE)
    if source_id == "tick":
        return Path(settings.CC_TICK_LOG_FILE)
    return None


def _allowed_container_names():
    names = set(CORE_CONTAINERS)
    try:
        from library.models import InstalledService

        for row in InstalledService.objects.exclude(container_name="").values_list(
            "container_name", flat=True
        ):
            name = (row or "").strip()
            if name and CONTAINER_NAME_RE.match(name):
                names.add(name)
    except Exception:
        logger.debug("Could not load installed container names", exc_info=True)
    return names


def _docker_available():
    try:
        client = docker.DockerClient(base_url=settings.DOCKER_HOST)
        client.ping()
        return True, client
    except Exception:
        return False, None


def _container_state(client, name):
    try:
        container = client.containers.get(name)
        return container.status or "unknown"
    except Exception:
        return "missing"


def list_sources():
    sources = []
    for source_id, label in FILE_SOURCES.items():
        path = _log_file(source_id)
        sources.append(
            {
                "id": source_id,
                "label": label,
                "kind": "file",
                "state": "ok" if path and path.exists() else "empty",
            }
        )

    ok, client = _docker_available()
    if not ok:
        return sources

    for name in sorted(_allowed_container_names()):
        sources.append(
            {
                "id": f"docker:{name}",
                "label": name,
                "kind": "docker",
                "state": _container_state(client, name),
            }
        )
    return sources


def _validate_source(source_id):
    if source_id in FILE_SOURCES:
        return source_id
    if source_id.startswith("docker:"):
        name = source_id[7:]
        if CONTAINER_NAME_RE.match(name) and name in _allowed_container_names():
            return source_id
    return None


def _truncate_line(line):
    raw = line.rstrip("\n\r")
    if len(raw.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
        return raw[:MAX_LINE_BYTES] + "…"
    return raw


def _filter_lines(lines, query):
    if not query:
        return lines
    q = query.lower()
    return [line for line in lines if q in line.lower()]


def _cap_payload(lines):
    out = []
    total = 0
    truncated = False
    for line in lines:
        encoded = (line + "\n").encode("utf-8", errors="replace")
        if total + len(encoded) > MAX_RESPONSE_BYTES:
            truncated = True
            break
        out.append(line)
        total += len(encoded)
    return out, truncated


def _read_file_tail(path, tail, since_offset=None, query=""):
    if not path.exists():
        return {"lines": [], "cursor": "0", "truncated": False, "error": ""}
    try:
        size = path.stat().st_size
        offset = 0
        if since_offset is not None:
            try:
                offset = max(0, min(int(since_offset), size))
            except (TypeError, ValueError):
                offset = 0
            if offset >= size:
                return {"lines": [], "cursor": str(size), "truncated": False, "error": ""}
            with path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        else:
            with path.open("rb") as handle:
                chunk = handle.read()
        text = chunk.decode("utf-8", errors="replace")
        lines = [_truncate_line(line) for line in text.splitlines() if line]
        if since_offset is None:
            lines = lines[-tail:]
        lines = _filter_lines(lines, query)
        lines, truncated = _cap_payload(lines)
        return {
            "lines": lines,
            "cursor": str(size),
            "truncated": truncated,
            "error": "",
        }
    except OSError as exc:
        return {"lines": [], "cursor": "0", "truncated": False, "error": str(exc)[:200]}


def _read_docker_logs(name, tail, since=None, query=""):
    ok, _ = _docker_available()
    if not ok:
        return {
            "lines": [],
            "cursor": "",
            "truncated": False,
            "error": "Docker is not available.",
        }
    kwargs = {"tail": min(tail, MAX_TAIL), "timestamps": True}
    if since:
        try:
            since_ts = int(since)
            kwargs["since"] = since_ts
        except (TypeError, ValueError):
            pass
    try:
        client = docker.DockerClient(
            base_url=settings.DOCKER_HOST,
            timeout=DOCKER_LOG_TIMEOUT,
        )
        container = client.containers.get(name)
        raw = container.logs(**kwargs)
        text = raw.decode("utf-8", errors="replace")
        lines = [_truncate_line(line) for line in text.splitlines() if line]
        lines = _filter_lines(lines, query)
        lines, truncated = _cap_payload(lines)
        cursor = str(int(time.time()))
        return {"lines": lines, "cursor": cursor, "truncated": truncated, "error": ""}
    except Exception as exc:
        logger.debug("Docker logs failed for %s: %s", name, exc)
        return {
            "lines": [],
            "cursor": since or "",
            "truncated": False,
            "error": str(exc)[:200],
        }


def fetch_logs(source_id, query="", tail=400, since=None):
    source_id = _validate_source(source_id)
    if not source_id:
        return {"error": "Invalid log source.", "lines": [], "cursor": "", "truncated": False}

    tail = max(1, min(int(tail or 400), MAX_TAIL))
    cache_key = f"logs:{source_id}:{tail}:{since or ''}:{query.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if source_id in FILE_SOURCES:
        result = _read_file_tail(_log_file(source_id), tail, since, query)
    else:
        name = source_id[7:]
        result = _read_docker_logs(name, tail, since, query)

    result["source"] = source_id
    cache.set(cache_key, result, CACHE_TTL)
    return result


def download_logs(source_id, tail=MAX_TAIL):
    payload = fetch_logs(source_id, tail=min(tail, MAX_TAIL))
    if payload.get("error") and not payload.get("lines"):
        return None, payload.get("error", "Unavailable")
    body = "\n".join(payload.get("lines") or [])
    if len(body.encode("utf-8", errors="replace")) > MAX_DOWNLOAD_BYTES:
        body = body.encode("utf-8", errors="replace")[:MAX_DOWNLOAD_BYTES].decode(
            "utf-8", errors="replace"
        )
    return body, ""
