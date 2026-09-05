"""Interactive console sessions (PTY) for Settings → Console."""

import asyncio
import fcntl
import logging
import os
import pty
import secrets
import signal
import struct
import termios
import time
from pathlib import Path

import docker
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from core.models import log_audit
from dashboard.hostops import CONTAINER_NAME_RE

logger = logging.getLogger(__name__)

User = get_user_model()

TICKET_PREFIX = "console:ticket:"
SESSION_COUNT_KEY = "console:sessions"
USER_SESSION_PREFIX = "console:user:"


def client_ip_from_scope(scope):
    client = scope.get("client")
    if client:
        return client[0]
    headers = dict(scope.get("headers") or [])
    forwarded = headers.get(b"x-forwarded-for", b"").decode("latin1")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return ""


def origin_allowed(scope):
    headers = dict(scope.get("headers") or [])
    origin = headers.get(b"origin", b"").decode("latin1")
    if not origin:
        return True
    host = headers.get(b"host", b"").decode("latin1")
    allowed = set(settings.ALLOWED_HOSTS)
    for item in settings.CSRF_TRUSTED_ORIGINS:
        allowed.add(item.replace("https://", "").replace("http://", ""))
    if host:
        allowed.add(host.split(":")[0])
    for candidate in (origin,):
        cleaned = candidate.replace("https://", "").replace("http://", "").split("/")[0]
        if cleaned.split(":")[0] in allowed or cleaned in allowed:
            return True
    return False


def _session_limits():
    return {
        "idle": settings.CONSOLE_IDLE_SECONDS,
        "max": settings.CONSOLE_MAX_SECONDS,
        "per_user": settings.CONSOLE_MAX_PER_USER,
        "global": settings.CONSOLE_MAX_GLOBAL,
    }


def _count_sessions(user_id=None):
    total = int(cache.get(SESSION_COUNT_KEY) or 0)
    user_count = int(cache.get(f"{USER_SESSION_PREFIX}{user_id}") or 0) if user_id else 0
    return total, user_count


def _bump_sessions(user_id, delta):
    try:
        total = max(0, int(cache.get(SESSION_COUNT_KEY) or 0) + delta)
        cache.set(SESSION_COUNT_KEY, total, 86400)
        key = f"{USER_SESSION_PREFIX}{user_id}"
        user_total = max(0, int(cache.get(key) or 0) + delta)
        cache.set(key, user_total, 86400)
    except Exception:
        pass


def create_ticket(user, target, ip, password, totp_code="", vault_entry_id=None):
    if not settings.CONSOLE_ENABLED:
        return None, "Console is disabled."
    if target not in ("app", "host"):
        return None, "Invalid target."
    if target == "host" and not settings.CONSOLE_HOST_ENABLED:
        return None, "Host console is disabled."
    if not user.check_password(password):
        return None, "Invalid password."
    from core.totp import consume_recovery_code, twofa_enabled, verify_totp

    if twofa_enabled(user):
        secret = user.profile.totp_secret
        if not verify_totp(secret, totp_code) and not consume_recovery_code(user, totp_code):
            return None, "Invalid authenticator code."
    extra_env = {}
    if vault_entry_id:
        from core.vault import get_credentials_by_id

        creds = get_credentials_by_id(user, vault_entry_id)
        if not creds:
            return None, "Vault entry not found."
        extra_env = {
            "CC_SVC_USER": creds.username,
            "CC_SVC_SECRET": creds.secret,
            "CC_SVC_LABEL": creds.label,
        }
        log_audit(
            "console",
            user=user,
            message=f"Console ticket with vault entry {creds.label}",
            entry_id=creds.entry_id,
        )
    limits = _session_limits()
    total, user_count = _count_sessions(user.id)
    if total >= limits["global"]:
        return None, "Too many console sessions are active."
    if user_count >= limits["per_user"]:
        return None, "You already have the maximum number of console sessions."
    token = secrets.token_urlsafe(32)
    cache.set(
        f"{TICKET_PREFIX}{token}",
        {"user_id": user.id, "target": target, "ip": ip, "env": extra_env},
        60,
    )
    return token, ""


def consume_ticket(token, ip):
    key = f"{TICKET_PREFIX}{token}"
    payload = cache.get(key)
    if not payload:
        return None, "Invalid or expired ticket."
    cache.delete(key)
    if payload.get("ip") and ip and payload["ip"] != ip:
        return None, "Ticket IP mismatch."
    try:
        user = User.objects.get(pk=payload["user_id"], is_active=True, is_superuser=True)
    except User.DoesNotExist:
        return None, "User not allowed."
    return user, {"target": payload.get("target", "app"), "env": payload.get("env") or {}}


def _docker_client():
    return docker.DockerClient(base_url=settings.DOCKER_HOST)


def _in_docker():
    return Path("/var/run/docker.sock").exists()


def _set_winsize(fd, rows, cols):
    if rows <= 0 or cols <= 0:
        return
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class LocalPtySession:
    def __init__(self, target, extra_env=None):
        self.target = target
        self.extra_env = extra_env or {}
        self.pid = None
        self.fd = None
        self._closed = False

    def start(self):
        shell = shutil_which("bash") or shutil_which("sh")
        if not shell:
            raise RuntimeError("No shell available.")
        cwd = str(settings.BASE_DIR)
        if self.target == "host":
            cwd = os.path.expanduser("~") or "/"
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.environ["TERM"] = "xterm-256color"
            os.environ["HOME"] = cwd
            for key, value in self.extra_env.items():
                if value is not None:
                    os.environ[str(key)] = str(value)
            os.execvp(shell, [shell, "-l"])
        self.pid = pid
        self.fd = fd
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def resize(self, rows, cols):
        if self.fd is not None:
            _set_winsize(self.fd, rows, cols)
            if self.pid:
                try:
                    os.kill(self.pid, signal.SIGWINCH)
                except OSError:
                    pass

    def write(self, data):
        if self.fd is None:
            return
        os.write(self.fd, data)

    def read(self):
        if self.fd is None:
            return b""
        try:
            return os.read(self.fd, 4096)
        except BlockingIOError:
            return b""

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGHUP)
            except OSError:
                pass
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.pid = None


def shutil_which(name):
    from shutil import which

    return which(name)


class DockerExecSession:
    """Host shell via short-lived privileged helper + docker exec socket."""

    def __init__(self, extra_env=None):
        self.extra_env = extra_env or {}
        self.client = None
        self.container = None
        self.exec_id = None
        self.sock = None
        self._closed = False

    def start(self):
        self.client = _docker_client()
        image = "alpine:3.20"
        try:
            self.client.images.get(image)
        except Exception:
            self.client.images.pull(image)
        name = f"cc-console-host-{os.getpid()}-{int(time.time())}"
        self.container = self.client.containers.run(
            image,
            command=["sleep", "3600"],
            name=name,
            detach=True,
            privileged=True,
            pid_mode="host",
            network_mode="host",
            remove=True,
            tty=True,
        )
        env = {"TERM": "xterm-256color", **self.extra_env}
        self.exec_id = self.client.api.exec_create(
            self.container.id,
            cmd=["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "/bin/sh", "-l"],
            stdin=True,
            tty=True,
            environment=env,
        )["Id"]
        self.sock = self.client.api.exec_start(self.exec_id, socket=True, tty=True)
        self.sock._sock.setblocking(False)

    def resize(self, rows, cols):
        if not self.exec_id or not self.client:
            return
        try:
            self.client.api.exec_resize(self.exec_id, height=rows, width=cols)
        except Exception:
            pass

    def write(self, data):
        if self.sock:
            self.sock._sock.send(data)

    def read(self):
        if not self.sock:
            return b""
        try:
            return self.sock._sock.recv(4096)
        except BlockingIOError:
            return b""

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.container:
                self.container.stop(timeout=2)
        except Exception:
            pass
        self.sock = None
        self.container = None
        self.client = None


def open_session(target, extra_env=None):
    extra_env = extra_env or {}
    if target == "host" and _in_docker() and settings.CONSOLE_HOST_ENABLED:
        session = DockerExecSession(extra_env=extra_env)
        session.start()
        return session
    session = LocalPtySession(target, extra_env=extra_env)
    session.start()
    return session


async def websocket_console(scope, receive, send):
    if not settings.CONSOLE_ENABLED:
        await send({"type": "websocket.close", "code": 4403})
        return
    if not origin_allowed(scope):
        await send({"type": "websocket.close", "code": 4403})
        return

    query = scope.get("query_string", b"").decode("latin1")
    params = dict(pair.split("=", 1) if "=" in pair else (pair, "") for pair in query.split("&") if pair)
    token = params.get("ticket", "")
    ip = client_ip_from_scope(scope)

    user, target_or_error = await sync_to_async(consume_ticket)(token, ip)
    if not user:
        await send({"type": "websocket.close", "code": 4403})
        return
    extra = target_or_error if isinstance(target_or_error, dict) else {"target": target_or_error, "env": {}}
    target = extra.get("target", "app")
    extra_env = extra.get("env") or {}

    await send({"type": "websocket.accept"})

    session = None
    started = time.time()
    last_active = started
    queue = asyncio.Queue(maxsize=32)
    _bump_sessions(user.id, 1)
    log_audit(
        "console",
        user=user,
        message=f"Console opened ({target})",
        target=target,
        ip=ip,
    )

    try:
        session = await sync_to_async(open_session)(target, extra_env)
    except Exception as exc:
        await send({"type": "websocket.send", "text": f"\r\n[Console error: {exc}]\r\n"})
        await send({"type": "websocket.close", "code": 1011})
        _bump_sessions(user.id, -1)
        return

    loop = asyncio.get_running_loop()

    async def pump_output():
        while True:
            chunk = await sync_to_async(session.read)()
            if not chunk:
                await asyncio.sleep(0.02)
                continue
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(chunk)

    async def flush_queue():
        nonlocal last_active
        while True:
            chunk = await queue.get()
            last_active = time.time()
            try:
                await send({"type": "websocket.send", "bytes": chunk})
            except Exception:
                break

    pump_task = asyncio.create_task(pump_output())
    flush_task = asyncio.create_task(flush_queue())

    limits = _session_limits()
    try:
        while True:
            if time.time() - started > limits["max"]:
                await send({"type": "websocket.send", "text": "\r\n[Session time limit reached]\r\n"})
                break
            if time.time() - last_active > limits["idle"]:
                await send({"type": "websocket.send", "text": "\r\n[Session idle timeout]\r\n"})
                break

            try:
                message = await asyncio.wait_for(receive(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if message["type"] == "websocket.disconnect":
                break
            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    await sync_to_async(session.write)(message["bytes"])
                    last_active = time.time()
                elif "text" in message and message["text"]:
                    text = message["text"]
                    if text.startswith("{"):
                        import json

                        try:
                            payload = json.loads(text)
                            if payload.get("type") == "resize":
                                await sync_to_async(session.resize)(
                                    int(payload.get("rows", 24)),
                                    int(payload.get("cols", 80)),
                                )
                                continue
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                    await sync_to_async(session.write)(text.encode("utf-8"))
                    last_active = time.time()
    finally:
        pump_task.cancel()
        flush_task.cancel()
        if session:
            await sync_to_async(session.close)()
        _bump_sessions(user.id, -1)
        duration = int(time.time() - started)
        await sync_to_async(log_audit)(
            "console",
            user=user,
            message=f"Console closed ({target}, {duration}s)",
            target=target,
            ip=ip,
            duration=duration,
        )
        try:
            await send({"type": "websocket.close", "code": 1000})
        except Exception:
            pass
