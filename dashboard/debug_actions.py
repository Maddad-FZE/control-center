"""Allowlisted Debug repairs. Never uninstall with remove_data or guess ports."""

from __future__ import annotations

import logging
import threading
import uuid

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from core.models import log_audit
from dashboard import hostops, kuma
from dashboard.debug import ACTION_META, diagnose_service, incident_payload
from dashboard.models import DebugIncident
from library.debug_ports import (
    PROTECTED_CONTAINERS,
    apply_address_sync,
    inspect_live_address,
    invalidate_service_caches,
)
from library.installer import get_docker_client, stack_restart_order, start_install
from library.models import InstalledService, TunnelRoute

logger = logging.getLogger(__name__)

LOCK_TTL = 120
COOLDOWN = 30
SAFE_ACTIONS = {
    "ACTION_RECHECK",
    "ACTION_DISCOVER_PORT",
    "ACTION_SYNC_CARD_PORT",
    "ACTION_UPDATE_LINKED_URLS",
    "ACTION_REFRESH_HOST",
    "ACTION_CLEAR_CACHES",
    "ACTION_RESYNC_KUMA",
    "ACTION_RESTORE_RESTART_POLICY",
}
CONFIRM_ACTIONS = {
    "ACTION_START",
    "ACTION_UNPAUSE",
    "ACTION_REFRESH_HOST",
    "ACTION_REPAIR_TUNNEL_ORIGIN",
    "ACTION_RESTART",
    "ACTION_RESTART_STACK",
    "ACTION_RESTART_TICK",
    "ACTION_RESTART_KUMA",
    "ACTION_RESTART_CF",
    "ACTION_RETRY_INSTALL",
    "ACTION_RECREATE_MANAGED",
    "ACTION_REGEN_ENV",
    "ACTION_REBOOT_HOST",
}
FORBIDDEN = {"ACTION_UNINSTALL"}


def _lock_key(service_id):
    return f"debug:lock:{service_id}"


def _cooldown_key(service_id, action_id):
    return f"debug:cd:{service_id}:{action_id}"


def _container_name(service):
    slug = (service.catalog_slug or "").strip()
    if slug:
        row = InstalledService.objects.filter(slug=slug).first()
        if row and row.container_name:
            return row.container_name.lstrip("/")
        return f"cc-{slug}"
    return ""


def _allowed_now(incident, action_id):
    if action_id in FORBIDDEN:
        return False
    allowed = set(incident.actions_json or [])
    for row in incident.findings_json or []:
        allowed.update(row.get("actions") or [])
    if action_id == "ACTION_RECHECK":
        return True
    return action_id in allowed


def _job(status, message="", result=None):
    return {
        "status": status,
        "message": message,
        "result": result or {},
        "updated_at": timezone.now().isoformat(),
    }


def _verify(service):
    try:
        from dashboard.services import probe_service_health

        probe_service_health(service)
    except Exception as exc:
        logger.debug("post-repair probe failed: %s", exc)


def _run_action(incident_pk, job_id, action_id, actor_id):
    close_old_connections()
    incident = DebugIncident.objects.select_related("service").get(pk=incident_pk)
    service = incident.service
    jobs = dict(incident.repair_jobs or {})
    try:
        result = execute_action(service, action_id, incident)
        jobs[job_id] = _job(
            "succeeded" if result.get("ok") else "failed",
            result.get("message") or "",
            result,
        )
        if result.get("ok") and action_id not in ("ACTION_RECHECK", "ACTION_REBOOT_HOST"):
            _verify(service)
        log_audit(
            "admin",
            user=incident.actor,
            message=f"Debug {action_id} on {service.name}: {result.get('message')}",
            incident_id=incident.incident_id,
            action_id=action_id,
            ok=result.get("ok"),
        )
        if result.get("ok") and action_id != "ACTION_REBOOT_HOST":
            snap, probes, findings = diagnose_service(service)
            incident.findings_json = findings
            incident.snapshot_json = {"address": probes.get("address") or {}, "docker": probes.get("docker") or {}}
            incident.actions_json = []
            for row in findings:
                incident.actions_json.extend(row.get("actions") or [])
            from dashboard.debug import _overall_status, _report_text

            incident.status = _overall_status(findings)
            incident.report_text = _report_text(service, incident.incident_id, findings, snap, probes)
    except Exception as exc:
        logger.exception("Debug repair %s failed", action_id)
        jobs[job_id] = _job("failed", str(exc)[:200])
    incident.repair_jobs = jobs
    incident.save(update_fields=["repair_jobs", "findings_json", "snapshot_json", "actions_json", "status", "report_text"])
    cache.delete(_lock_key(service.id))
    cache.set(_cooldown_key(service.id, action_id), "1", COOLDOWN)
    close_old_connections()


def start_repair(incident, action_id, actor, confirmed=False):
    if action_id in FORBIDDEN or action_id not in ACTION_META:
        return None, "Unknown or forbidden action.", 422
    if incident.status in (DebugIncident.Status.QUEUED, DebugIncident.Status.RUNNING):
        return None, "Diagnosis is still running.", 409
    if not _allowed_now(incident, action_id):
        return None, "stale_diagnosis", 409
    if action_id in CONFIRM_ACTIONS and not confirmed:
        meta = ACTION_META[action_id]
        return (
            {
                "needs_confirm": True,
                "action_id": action_id,
                "risk": meta.get("risk"),
                "confirm_token": "ok",
                "confirmation_language": meta.get("confirmation_language") or "",
            },
            "",
            200,
        )
    if cache.get(_cooldown_key(incident.service_id, action_id)):
        return None, "That repair just ran. Wait a few seconds.", 429
    if not cache.add(_lock_key(incident.service_id), action_id, LOCK_TTL):
        return None, "A repair is already running for this card.", 409
    job_id = "job_" + uuid.uuid4().hex[:12]
    jobs = dict(incident.repair_jobs or {})
    jobs[job_id] = _job("queued", "Starting")
    incident.repair_jobs = jobs
    incident.save(update_fields=["repair_jobs"])
    thread = threading.Thread(
        target=_run_action,
        args=(incident.pk, job_id, action_id, getattr(actor, "pk", None)),
        name=f"debug-repair-{job_id}",
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "queued", "action_id": action_id}, "", 202


def execute_action(service, action_id, incident=None):
    if action_id == "ACTION_RECHECK":
        return {"ok": True, "message": "Diagnosis refreshed.", "cache_bust": True}
    if action_id == "ACTION_DISCOVER_PORT":
        snap = inspect_live_address(service)
        if snap.conflict:
            return {"ok": False, "message": f"Could not pick a port ({snap.conflict}).", "snapshot": snap.__dict__}
        slug = (service.catalog_slug or "").strip()
        if slug and snap.port:
            InstalledService.objects.filter(slug=slug).update(host_port=int(snap.port))
        return {
            "ok": True,
            "message": f"Live port is {snap.port}." if snap.port else "No published port.",
            "port": snap.port,
            "bindings": snap.bindings,
        }
    if action_id == "ACTION_SYNC_CARD_PORT":
        snap = inspect_live_address(service)
        result = apply_address_sync(service, snap, preserve_custom_urls=True)
        return {
            "ok": result.ok,
            "message": result.message,
            "changed": result.changed,
            "partial": result.partial,
            "cache_bust": result.cache_bust,
        }
    if action_id == "ACTION_UPDATE_LINKED_URLS":
        snap = inspect_live_address(service)
        result = apply_address_sync(
            service, snap, preserve_custom_urls=True, update_tunnel=True, update_kuma=True
        )
        return {"ok": result.ok, "message": result.message, "partial": result.partial, "cache_bust": True}
    if action_id == "ACTION_REFRESH_HOST":
        snap = inspect_live_address(service)
        result = apply_address_sync(
            service, snap, preserve_custom_urls=True, update_host=True, update_tunnel=True, update_kuma=True
        )
        return {"ok": result.ok, "message": result.message, "cache_bust": True}
    if action_id == "ACTION_CLEAR_CACHES":
        invalidate_service_caches(service)
        cache.delete("health:results")
        return {"ok": True, "message": "Caches cleared.", "cache_bust": True}
    if action_id == "ACTION_RESYNC_KUMA":
        api = kuma.connect_kuma()
        if api is None:
            return {"ok": False, "message": "Could not log in to Uptime Kuma."}
        try:
            kuma.sync_monitors(api)
        finally:
            if hasattr(api, "disconnect"):
                api.disconnect()
        return {"ok": True, "message": "Uptime Kuma monitors updated."}
    if action_id == "ACTION_REPAIR_TUNNEL_ORIGIN":
        from core.models import SiteSettings
        from library import cloudflare as cf

        route = TunnelRoute.objects.filter(service_id=service.id).first()
        if route is None and service.catalog_slug:
            route = TunnelRoute.objects.filter(catalog_slug=service.catalog_slug).first()
        if route is None:
            return {"ok": False, "message": "This card is not published."}
        origin = cf.origin_for_service(service, catalog_slug=service.catalog_slug, host_port=service.port or 0)
        if not origin:
            return {"ok": False, "message": "No LAN origin to publish."}
        if cf.is_control_center_target(origin_url=origin, catalog_slug=service.catalog_slug, port=service.port):
            return {"ok": False, "message": "Control Center stays on the LAN."}
        previous = route.origin_url
        route.origin_url = origin
        route.save(update_fields=["origin_url"])
        try:
            cf._sync_ingress(SiteSettings.load(), list(TunnelRoute.objects.order_by("hostname")))
        except Exception as exc:
            route.origin_url = previous
            route.save(update_fields=["origin_url"])
            return {"ok": False, "message": str(exc)[:200]}
        return {"ok": True, "message": f"Tunnel origin is now {origin}."}
    name = _container_name(service)
    if action_id == "ACTION_START":
        if not name or name in PROTECTED_CONTAINERS:
            return {"ok": False, "message": "No safe container to start."}
        ok, message = hostops.start_container(name)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_UNPAUSE":
        if not name or name in PROTECTED_CONTAINERS:
            return {"ok": False, "message": "No safe container to unpause."}
        ok, message = hostops.unpause_container(name)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RESTART":
        if not name or name in PROTECTED_CONTAINERS:
            return {"ok": False, "message": "No safe container to restart."}
        ok, message = hostops.restart_container(name)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RESTORE_RESTART_POLICY":
        if not name or name in PROTECTED_CONTAINERS:
            return {"ok": False, "message": "No managed container to update."}
        ok, message = hostops.restore_restart_policy(name)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RESTART_STACK":
        slug = (service.catalog_slug or "").strip()
        names = stack_restart_order(slug)
        if not names:
            return {"ok": False, "message": "This is not a known stack."}
        errors = []
        for item in names:
            if item in PROTECTED_CONTAINERS:
                continue
            ok, message = hostops.restart_container(item)
            if not ok and "not found" not in message.lower():
                errors.append(message)
        if errors:
            return {"ok": False, "message": "; ".join(errors)[:200]}
        return {"ok": True, "message": "Restarted the stack in order."}
    if action_id == "ACTION_RESTART_TICK":
        ok, message = hostops.restart_container("control-center-tick")
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RESTART_KUMA":
        row = InstalledService.objects.filter(slug="uptime-kuma").first()
        target = (row.container_name if row else "cc-uptime-kuma") or "cc-uptime-kuma"
        ok, message = hostops.restart_container(target)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RESTART_CF":
        row = InstalledService.objects.filter(slug="cloudflare-tunnel").first()
        target = (row.container_name if row else "cc-cloudflare-tunnel") or "cc-cloudflare-tunnel"
        ok, message = hostops.restart_container(target)
        return {"ok": ok, "message": message}
    if action_id == "ACTION_RETRY_INSTALL":
        slug = (service.catalog_slug or "").strip()
        row = InstalledService.objects.filter(slug=slug).first()
        if not row or row.status != InstalledService.Status.ERROR:
            return {"ok": False, "message": "Retry is only offered after a failed install."}
        ok, message = start_install(slug)
        return {"ok": ok, "message": message}
    if action_id in ("ACTION_RECREATE_MANAGED", "ACTION_REGEN_ENV"):
        return _recreate_primary(service)
    if action_id == "ACTION_REBOOT_HOST":
        ok, message = hostops.schedule_reboot()
        return {"ok": ok, "message": message}
    return {"ok": False, "message": "Unsupported action."}


def _recreate_primary(service):
    slug = (service.catalog_slug or "").strip()
    row = InstalledService.objects.filter(slug=slug, managed=True).first()
    if not row:
        return {"ok": False, "message": "Only managed library services can be recreated from Troubleshoot."}
    name = (row.container_name or f"cc-{slug}").lstrip("/")
    if name in PROTECTED_CONTAINERS:
        return {"ok": False, "message": "That container cannot be recreated here."}
    try:
        client = get_docker_client()
        container = client.containers.get(name)
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:200]}
    attrs = container.attrs or {}
    config = attrs.get("Config") or {}
    host = attrs.get("HostConfig") or {}
    image = config.get("Image") or ""
    env = list(config.get("Env") or [])
    labels = dict(config.get("Labels") or {})
    restart_policy = host.get("RestartPolicy") or {"Name": "unless-stopped"}
    binds = host.get("Binds") or []
    port_bindings = host.get("PortBindings") or {}
    network_mode = host.get("NetworkMode") or "bridge"
    extra_hosts = host.get("ExtraHosts") or None
    pid_mode = host.get("PidMode") or None
    snap = inspect_live_address(service)
    old = f"{service.host}:{service.port}" if service.host and service.port else ""
    new_host = snap.host or service.host
    new_port = snap.port or service.port
    new = f"{new_host}:{new_port}" if new_host and new_port else ""
    if old and new and old != new:
        env = [item.replace(old, new) if isinstance(item, str) else item for item in env]
    volumes = {}
    for bind in binds:
        parts = bind.split(":")
        if len(parts) >= 2:
            volumes[parts[0]] = {"bind": parts[1], "mode": parts[2] if len(parts) > 2 else "rw"}
    ports = {}
    for key, bindings in port_bindings.items():
        if bindings:
            ports[key] = int(bindings[0].get("HostPort") or 0) or None
    try:
        container.stop(timeout=15)
        container.remove(force=True)
        run_kwargs = {
            "name": name,
            "detach": True,
            "environment": env or None,
            "labels": labels or None,
            "restart_policy": restart_policy,
            "volumes": volumes or None,
            "ports": ports or None,
        }
        if network_mode and network_mode not in ("default", "bridge"):
            run_kwargs["network"] = network_mode
        if extra_hosts:
            parsed = {}
            for item in extra_hosts:
                if ":" in item:
                    host_name, addr = item.split(":", 1)
                    parsed[host_name] = addr
            if parsed:
                run_kwargs["extra_hosts"] = parsed
        if pid_mode:
            run_kwargs["pid_mode"] = pid_mode
        client.containers.run(image, **run_kwargs)
    except Exception as exc:
        logger.exception("Managed recreate failed for %s", name)
        return {"ok": False, "message": str(exc)[:200]}
    live = inspect_live_address(service)
    apply_address_sync(service, live, preserve_custom_urls=True)
    return {"ok": True, "message": f"Recreated {name} with existing volumes."}
