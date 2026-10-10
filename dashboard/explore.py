"""Read-only file browser for one installed app's container."""

import io
import posixpath
import tarfile

import docker

from dashboard.debug_actions import _container_name
from library.installer import get_docker_client

TEXT_MAX = 512 * 1024
IMAGE_MAX = 8 * 1024 * 1024
TEXT_EXTENSIONS = {
    "cfg",
    "conf",
    "css",
    "csv",
    "env",
    "html",
    "ini",
    "js",
    "json",
    "log",
    "md",
    "py",
    "sh",
    "toml",
    "txt",
    "xml",
    "yaml",
    "yml",
}
IMAGE_TYPES = {
    "gif": "image/gif",
    "ico": "image/x-icon",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "svg": "image/svg+xml",
    "webp": "image/webp",
}


class ExploreError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def jail_path(raw):
    """Return a container path. Reject parent segments and non-container paths."""
    text = str(raw or "").strip()
    if not text:
        return "/"
    if "\\" in text or "\x00" in text or ":" in text:
        raise ExploreError("That path is not inside this app.")
    if not text.startswith("/"):
        text = "/" + text
    if any(part == ".." for part in text.split("/")):
        raise ExploreError("That path is not inside this app.")
    normalized = posixpath.normpath(text)
    if not normalized.startswith("/"):
        raise ExploreError("That path is not inside this app.")
    return normalized


def preview_kind(name):
    ext = ""
    if "." in (name or ""):
        ext = name.rsplit(".", 1)[-1].lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in IMAGE_TYPES:
        return "image"
    return ""


def content_type_for(name):
    ext = ""
    if "." in (name or ""):
        ext = name.rsplit(".", 1)[-1].lower()
    return IMAGE_TYPES.get(ext, "application/octet-stream")


def parse_ls(output):
    entries = []
    for line in (output or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        kind = "dir" if raw.endswith("/") else "file"
        name = raw.rstrip("/")
        if name in (".", "..") or not name or "/" in name:
            continue
        entries.append(
            {
                "name": name,
                "kind": kind,
                "preview": preview_kind(name) if kind == "file" else "",
            }
        )
    entries.sort(key=lambda row: (0 if row["kind"] == "dir" else 1, row["name"].lower()))
    return entries


def _parent(path):
    if path == "/":
        return None
    parent = posixpath.dirname(path)
    return parent or "/"


def _mounts(container):
    found = []
    for row in (container.attrs.get("Mounts") or []):
        dest = (row.get("Destination") or "").strip()
        if not dest:
            continue
        try:
            dest = jail_path(dest)
        except ExploreError:
            continue
        if dest not in found:
            found.append(dest)
    return found


def open_container(name):
    try:
        client = get_docker_client(timeout=30)
        container = client.containers.get(name)
        container.reload()
    except docker.errors.NotFound as exc:
        raise ExploreError("Container is not running.", 404) from exc
    except docker.errors.DockerException as exc:
        raise ExploreError("Docker is not available.", 502) from exc
    return container


def run_ls(container, path):
    try:
        code, output = container.exec_run(["ls", "-1pa", path], demux=False)
    except docker.errors.APIError as exc:
        raise ExploreError("Could not list this folder.", 502) from exc
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output or "")
    if code not in (0, None):
        lowered = text.lower()
        if code == 127 or "not found" in lowered or "executable file" in lowered:
            raise ExploreError("This image has no shell to list files.", 502)
        raise ExploreError(text.strip() or "Could not list this folder.", 400)
    return text


def list_service_files(service, raw_path):
    name = _container_name(service)
    if not name:
        raise ExploreError("This app is not a container on this server, so there are no files to open.", 404)
    requested = str(raw_path or "").strip()
    path = jail_path(requested) if requested else ""
    container = open_container(name)
    mounts = _mounts(container)
    if not path:
        path = mounts[0] if mounts else "/"
    entries = parse_ls(run_ls(container, path))
    return {
        "path": path,
        "parent": _parent(path),
        "mounts": mounts,
        "entries": entries,
    }


def _read_capped(stream, limit):
    chunks = []
    total = 0
    iterator = stream.stream(amt=65536) if hasattr(stream, "stream") else stream
    for chunk in iterator:
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise ExploreError("This file is too large to preview.", 413)
        chunks.append(chunk)
    return b"".join(chunks)


def _file_from_tar(raw):
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
    except tarfile.TarError as exc:
        raise ExploreError("Could not read this file.", 502) from exc
    with archive:
        members = archive.getmembers()
        files = [member for member in members if member.isfile()]
        if any(member.isdir() for member in members) or len(files) != 1:
            raise ExploreError("That path is a folder.", 400)
        extracted = archive.extractfile(files[0])
        if extracted is None:
            raise ExploreError("Could not read this file.", 502)
        return extracted.read()


def fetch_file(container, path, limit):
    try:
        stream, stat = container.get_archive(path)
    except docker.errors.NotFound as exc:
        raise ExploreError("File not found.", 404) from exc
    except docker.errors.APIError as exc:
        raise ExploreError("Could not read this file.", 502) from exc
    try:
        size = int((stat or {}).get("size") or 0)
        if size > limit:
            raise ExploreError("This file is too large to preview.", 413)
        raw = _read_capped(stream, limit + 65536)
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()
    body = _file_from_tar(raw)
    if len(body) > limit:
        raise ExploreError("This file is too large to preview.", 413)
    return body


def read_service_file(service, raw_path):
    path = jail_path(raw_path)
    name = posixpath.basename(path)
    kind = preview_kind(name)
    if not kind:
        raise ExploreError("This file cannot be previewed.", 415)
    container_name = _container_name(service)
    if not container_name:
        raise ExploreError("This app is not a container on this server, so there are no files to open.", 404)
    container = open_container(container_name)
    limit = TEXT_MAX if kind == "text" else IMAGE_MAX
    body = fetch_file(container, path, limit)
    return {
        "kind": kind,
        "name": name,
        "body": body,
        "content_type": content_type_for(name),
    }
