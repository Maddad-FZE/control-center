"""Redact secrets from Debug evidence and escalation reports."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_QUERY_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "password",
    "secret",
    "key",
    "sid",
}
SECRET_HEADER_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-ftl-sid",
    "x-auth-token",
}
ENV_SECRET_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:password|secret|token)|api[_-]?key|authorization)=([^\s,;]+)"
)
BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")


def redact_url(url):
    if not url:
        return url
    parsed = urlsplit(url)
    query = []
    changed = False
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SECRET_QUERY_KEYS:
            query.append((key, "***"))
            changed = True
        else:
            query.append((key, value))
    netloc = parsed.netloc
    if "@" in netloc:
        _, host = netloc.rsplit("@", 1)
        netloc = f"***@{host}"
        changed = True
    new_query = urlencode(query, safe="*") if changed else parsed.query
    return urlunsplit((parsed.scheme, netloc, parsed.path, new_query, parsed.fragment))


def redact_text(text):
    if not text:
        return text
    out = BEARER_RE.sub(r"\1***", str(text))
    out = ENV_SECRET_RE.sub(lambda m: f"{m.group(1)}=***", out)
    return out


def redact_mapping(data):
    if not isinstance(data, dict):
        return data
    out = {}
    for key, value in data.items():
        lowered = str(key).lower()
        if lowered in SECRET_QUERY_KEYS or lowered in SECRET_HEADER_KEYS or "password" in lowered:
            out[key] = "***"
        elif isinstance(value, dict):
            out[key] = redact_mapping(value)
        elif isinstance(value, list):
            out[key] = [redact_mapping(item) if isinstance(item, dict) else redact_text(str(item)) if isinstance(item, str) else item for item in value]
        elif isinstance(value, str):
            if "://" in value:
                out[key] = redact_url(value)
            else:
                out[key] = redact_text(value)
        else:
            out[key] = value
    return out


def sanitize_log_lines(lines, limit=40):
    out = []
    for line in lines[:limit]:
        out.append(redact_text(line)[:500])
    return out
