function el(id) {
  return document.getElementById(id);
}

const cpuHistory = [];
const MAX_CPU_HISTORY = 30;
let prevNet = null;
let pollFailCount = 0;
let healthPollCounter = 0;
let offlineMode = false;
let lastLiveAt = null;
const BASE_TITLE = document.title.replace(/^\(\d+ DOWN\) /, "");
const PANEL_STORAGE_KEY = "tva-panel-collapse";

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

function formatUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

function formatTime24(date) {
  const h = String(date.getHours()).padStart(2, "0");
  const m = String(date.getMinutes()).padStart(2, "0");
  const s = String(date.getSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function formatRelativeTime(iso) {
  const then = new Date(iso);
  const diff = Math.floor((Date.now() - then.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatBucketTooltip(iso, up) {
  const d = new Date(iso);
  return `${formatTime24(d)} — ${up ? "up" : "down"}`;
}

function gaugeRow(label, percent, detail) {
  const critical = percent >= 90 ? " critical" : "";
  return `
    <div class="gauge-row">
      <div class="gauge-header">
        <span class="stat-label">${label}</span>
        <span class="stat-value">${detail || percent + "%"}</span>
      </div>
      <div class="gauge-track"><div class="gauge-fill${critical}" style="width:${Math.min(100, percent)}%"></div></div>
    </div>`;
}

function groupAlerts(alerts) {
  const grouped = [];
  alerts.forEach((a) => {
    const last = grouped[grouped.length - 1];
    if (last && last.title === a.title && last.level === a.level) {
      last.count += 1;
      last.created_at = a.created_at;
      last.acknowledged = last.acknowledged && a.acknowledged;
    } else {
      grouped.push({ ...a, count: 1 });
    }
  });
  return grouped;
}

function applyServiceFilter() {
  const input = el("service-filter");
  if (!input) return;
  const q = input.value.trim().toLowerCase();
  const downOnly = q === "is:down";

  document.querySelectorAll(".service-card").forEach((card) => {
    const name = card.dataset.serviceName || "";
    const desc = card.dataset.serviceDesc || "";
    const isDown = card.dataset.serviceDown === "1";
    let match = true;
    if (downOnly) {
      match = isDown;
    } else if (q) {
      match = name.includes(q) || desc.includes(q);
    }
    card.classList.toggle("hidden-by-filter", !match);
    card.classList.toggle("filter-match", !!q && match && !downOnly);
  });

  document.querySelectorAll(".services-group").forEach((group) => {
    const visible = group.querySelectorAll(".service-card:not(.hidden-by-filter)").length;
    group.classList.toggle("hidden-by-filter", visible === 0 && !!q);
  });
}

function updateGroupTitles() {
  document.querySelectorAll(".services-group").forEach((group) => {
    const title = group.querySelector(".group-title");
    if (!title) return;
    const hasDown = group.querySelector(".service-card--down") !== null;
    title.classList.toggle("group-title--alert", hasDown);
  });
}

function renderWidgets(data) {
  const widgets = data.widgets || {};
  Object.entries(widgets).forEach(([serviceId, entry]) => {
    const container = document.querySelector(
      `.service-card__stats[data-widget-service-id="${serviceId}"]`
    );
    if (!container) return;
    const widgetData = entry.data || {};
    if (widgetData.error) {
      container.innerHTML = `<div class="widget-stat widget-stat--error"><span class="widget-stat-value">${widgetData.error}</span><span class="widget-stat-label">Widget</span></div>`;
      return;
    }
    const stats = widgetData.stats || [];
    if (!stats.length) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = stats
      .map(
        (stat) =>
          `<div class="widget-stat"><span class="widget-stat-value">${stat.value}</span><span class="widget-stat-label">${stat.label}</span></div>`
      )
      .join("");
  });
}

function renderSystem(data) {
  const box = el("system-stats");
  if (!box) return;

  cpuHistory.push(data.cpu_percent);
  if (cpuHistory.length > MAX_CPU_HISTORY) cpuHistory.shift();

  const load = (data.load_avg || []).map((n) => n.toFixed(2)).join(" / ");
  let netLine = "";
  if (prevNet) {
    const dt = 10;
    const upKb = Math.max(0, ((data.network_sent_mb - prevNet.sent) * 1024) / dt).toFixed(1);
    const downKb = Math.max(0, ((data.network_recv_mb - prevNet.recv) * 1024) / dt).toFixed(1);
    netLine = `<div class="stat-row"><span class="stat-label">Network</span><span class="stat-value">↑${upKb} ↓${downKb} KB/s</span></div>`;
  }
  prevNet = { sent: data.network_sent_mb, recv: data.network_recv_mb };

  const cpuBars = cpuHistory
    .map((v) => `<span style="height:${Math.max(8, v)}%"></span>`)
    .join("");

  const hostUptime = el("stat-host-uptime");
  if (hostUptime) {
    hostUptime.textContent = `Host ${formatUptime(data.uptime_seconds)}`;
  }

  box.innerHTML = `
    ${gaugeRow("CPU", data.cpu_percent)}
    <div class="cpu-sparkline" aria-hidden="true">${cpuBars}</div>
    <div class="stat-row"><span class="stat-label">Load</span><span class="stat-value">${load || "n/a"}</span></div>
    ${gaugeRow("Memory", data.memory_percent, `${data.memory_used_gb} / ${data.memory_total_gb} GB`)}
    ${(data.disks || []).map((d) => gaugeRow(d.mount, d.percent, `${d.used_gb}/${d.total_gb} GB`)).join("")}
    ${data.temperature_c != null ? `<div class="stat-row"><span class="stat-label">Temp</span><span class="stat-value">${data.temperature_c.toFixed(1)}°C</span></div>` : ""}
    ${netLine}
  `;
}

function renderDocker(data) {
  const box = el("docker-stats");
  const countEl = el("docker-count");
  if (!box) return;
  if (!data.available) {
    if (countEl) countEl.textContent = "";
    box.innerHTML = `<div class="stat-label">Docker unavailable (${data.message || "no socket"})</div>`;
    return;
  }
  if (!data.containers.length) {
    if (countEl) countEl.textContent = "0/0";
    box.innerHTML = `<div class="stat-label">No containers found.</div>`;
    return;
  }
  const running = data.containers.filter((c) => c.state === "running").length;
  if (countEl) countEl.textContent = `${running}/${data.containers.length}`;

  box.innerHTML = data.containers
    .slice(0, 12)
    .map((c) => {
      const stateClass = `state-${(c.state || c.status || "").toLowerCase().replace(/[^a-z]/g, "")}`;
      return `
        <div class="container-row ${stateClass}">
          <div class="stat-row">
            <span class="stat-label">${c.name}</span>
            <span class="stat-value">${c.status}</span>
          </div>
          <span class="container-image" title="${c.image}">${c.image}</span>
        </div>`;
    })
    .join("");
}

function renderHealth(data) {
  let up = 0;
  let down = 0;
  let unknown = 0;

  (data.services || []).forEach((s) => {
    const dot = document.querySelector(`.service-card .status-dot[data-service-id="${s.id}"]`);
    const card = dot ? dot.closest(".service-card") : null;
    const latency = document.querySelector(`.service-latency[data-service-id="${s.id}"]`);

    if (dot) {
      dot.classList.remove("up", "down");
      dot.classList.add(s.is_up ? "up" : "down");
      dot.setAttribute("aria-label", `${s.name}: ${s.is_up ? "up" : "down"}`);
    }
    if (card) {
      card.classList.toggle("service-card--down", !s.is_up);
      card.dataset.serviceDown = s.is_up ? "0" : "1";
      const latencyText = s.response_ms != null ? ` · ${s.response_ms}ms` : "";
      card.title = `${s.name}${latencyText}`;
    }
    if (latency && s.response_ms != null) {
      latency.textContent = `${s.response_ms}ms`;
    }

    if (s.is_up) up += 1;
    else down += 1;
  });

  document.querySelectorAll(".service-card .status-dot").forEach((dot) => {
    if (!dot.classList.contains("up") && !dot.classList.contains("down")) unknown += 1;
  });

  const upEl = el("stat-up");
  const downEl = el("stat-down");
  const unknownEl = el("stat-unknown");
  if (upEl) upEl.textContent = `${up} up`;
  if (downEl) downEl.textContent = `${down} down`;
  if (unknownEl) unknownEl.textContent = `${unknown} unknown`;

  document.title = down > 0 ? `(${down} DOWN) ${BASE_TITLE}` : BASE_TITLE;
  updateGroupTitles();
  applyServiceFilter();
}

function renderUptime(data) {
  const box = el("uptime-panel");
  if (!box) return;
  const uptime = data.uptime || {};
  const ids = Object.keys(uptime);
  if (!ids.length) {
    box.innerHTML = `<div class="stat-label">No uptime data yet. Health checks populate history.</div>`;
    updateUptimeChip(null);
    return;
  }

  const percents = [];
  box.innerHTML = ids
    .map((id) => {
      const entry = uptime[id];
      if (entry.percent != null) percents.push(entry.percent);
      const bars = (entry.bars || [])
        .map((bucket) => {
          const up = typeof bucket === "object" ? bucket.up : bucket;
          const at = typeof bucket === "object" ? bucket.at : null;
          const title = at ? formatBucketTooltip(at, up) : up ? "up" : "down";
          return `<span class="${up ? "up" : ""}" style="height:${up ? 100 : 35}%" title="${title}"></span>`;
        })
        .join("");
      const pct = entry.percent != null ? `${entry.percent}%` : "—";
      return `
        <div class="uptime-row">
          <div class="uptime-header">
            <span class="uptime-name">${entry.name || "Service #" + id}</span>
            <span class="uptime-pct">${pct}</span>
          </div>
          <div class="sparkline">${bars}</div>
        </div>`;
    })
    .join("");

  if (percents.length) {
    const mean = percents.reduce((a, b) => a + b, 0) / percents.length;
    updateUptimeChip(mean);
  }
}

function updateUptimeChip(meanPercent) {
  const chip = el("stat-uptime-24h");
  if (!chip) return;
  chip.textContent = meanPercent != null ? `24H ${meanPercent.toFixed(1)}%` : "24H —";
}

function renderAlerts(data) {
  const box = el("alerts-panel");
  const badge = el("alerts-badge");
  if (!box) return;
  const alerts = data.alerts || [];
  const unack = alerts.filter((a) => !a.acknowledged).length;

  if (badge) {
    badge.hidden = unack === 0;
    badge.textContent = unack;
  }

  const alertsChip = el("stat-alerts");
  if (alertsChip) {
    alertsChip.textContent = `${unack} alert${unack !== 1 ? "s" : ""}`;
  }

  if (!alerts.length) {
    box.innerHTML = `<div class="stat-label">No recent alerts.</div>`;
    return;
  }

  const grouped = groupAlerts(alerts.slice(0, 30));
  box.innerHTML = grouped
    .slice(0, 12)
    .map((a) => {
      const icon = a.level === "error" ? "!" : a.level === "success" ? "✓" : "·";
      const countSuffix = a.count > 1 ? ` <span class="alert-count">×${a.count}</span>` : "";
      return `
        <div class="alert-item ${a.level}${a.acknowledged ? " acknowledged" : ""}">
          <span class="alert-icon" aria-hidden="true">${icon}</span>
          <span class="alert-text">${a.title}${countSuffix}</span>
          <span class="alert-time">${formatRelativeTime(a.created_at)}</span>
        </div>`;
    })
    .join("");
}

function setOfflineBanner(show) {
  const banner = el("offline-banner");
  if (!banner) return;
  banner.hidden = !show;
}

function setRefreshState(ok, fromCache) {
  const indicator = el("refresh-indicator");
  if (!indicator) return;
  if (ok) {
    pollFailCount = 0;
    offlineMode = false;
    lastLiveAt = new Date();
    setOfflineBanner(false);
    indicator.textContent = `Updated ${formatTime24(lastLiveAt)}`;
    indicator.classList.remove("stale");
  } else if (fromCache) {
    offlineMode = true;
    setOfflineBanner(true);
    const stamp = lastLiveAt ? formatTime24(lastLiveAt) : "cached";
    indicator.textContent = `Offline — ${stamp}`;
    indicator.classList.add("stale");
  } else {
    pollFailCount += 1;
    offlineMode = true;
    setOfflineBanner(true);
    indicator.textContent =
      pollFailCount > 1 ? "Offline — retrying" : "Sync failed — retrying";
    indicator.classList.add("stale");
  }
}

async function fetchWithCache(url, cacheKey) {
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (window.dashboardCache) {
      window.dashboardCache.save(cacheKey, data);
    }
    return { ok: true, stale: false, data };
  } catch (e) {
    const cached = window.dashboardCache ? window.dashboardCache.load(cacheKey) : null;
    if (cached) {
      return { ok: false, stale: true, data: cached.data };
    }
    throw e;
  }
}

function hydrateFromCache() {
  if (!window.dashboardCache) return;
  let newestSavedAt = 0;
  window.dashboardCache.hydrateKeys.forEach((key) => {
    const entry = window.dashboardCache.load(key);
    if (!entry) return;
    if (entry.savedAt > newestSavedAt) newestSavedAt = entry.savedAt;
    const data = entry.data;
    if (key === "system") renderSystem(data);
    else if (key === "docker") renderDocker(data);
    else if (key === "alerts") renderAlerts(data);
    else if (key === "health") renderHealth(data);
    else if (key === "uptime") renderUptime(data);
    else if (key === "widgets") renderWidgets(data);
  });
  if (newestSavedAt) lastLiveAt = new Date(newestSavedAt);
}

function updateClock() {
  const clock = el("tva-clock");
  if (!clock) return;
  const now = new Date();
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const date = `${months[now.getMonth()]} ${String(now.getDate()).padStart(2, "0")} ${now.getFullYear()}`;
  const h = String(now.getHours()).padStart(2, "0");
  const m = String(now.getMinutes()).padStart(2, "0");
  const s = String(now.getSeconds()).padStart(2, "0");
  clock.innerHTML = `FILED: ${date} / ${h}<span class="clock-colon">:</span>${m}<span class="clock-colon">:</span>${s}`;
  clock.setAttribute("datetime", now.toISOString());
}

function initFilter() {
  const input = el("service-filter");
  if (!input) return;

  input.addEventListener("input", applyServiceFilter);

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
    }
    if (e.key === "Escape" && document.activeElement === input) {
      input.value = "";
      applyServiceFilter();
      input.blur();
    }
  });
}

function initStatusChips() {
  const alertsChip = el("stat-alerts");
  const downChip = el("stat-down");

  if (alertsChip) {
    alertsChip.addEventListener("click", () => {
      const section = el("alerts-panel-section");
      if (section) {
        section.scrollIntoView({ behavior: "smooth", block: "nearest" });
        const panel = section.closest(".panel");
        if (panel && panel.classList.contains("panel--collapsed")) {
          togglePanel(panel, true);
        }
      }
    });
  }

  if (downChip) {
    downChip.addEventListener("click", () => {
      const input = el("service-filter");
      if (!input) return;
      input.value = "is:down";
      applyServiceFilter();
      input.focus();
    });
  }
}

function loadPanelState() {
  try {
    return JSON.parse(localStorage.getItem(PANEL_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function savePanelState(state) {
  localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(state));
}

function togglePanel(panel, expand) {
  const panelId = panel.dataset.panelId;
  const body = panel.querySelector(".panel-body");
  const toggle = panel.querySelector(".panel-toggle");
  if (!body || !panelId) return;

  const collapsed = expand === undefined ? !panel.classList.contains("panel--collapsed") : !expand;
  panel.classList.toggle("panel--collapsed", collapsed);
  if (toggle) toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");

  const state = loadPanelState();
  state[panelId] = collapsed;
  savePanelState(state);
}

function initCollapsiblePanels() {
  const state = loadPanelState();
  document.querySelectorAll(".ops-stack .panel[data-panel-id]").forEach((panel) => {
    const panelId = panel.dataset.panelId;
    const collapsed = state[panelId] === true;
    if (collapsed) {
      panel.classList.add("panel--collapsed");
      const toggle = panel.querySelector(".panel-toggle");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    }

    panel.querySelectorAll(".panel-toggle").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        if (e.target.closest(".btn-ack")) return;
        togglePanel(panel);
      });
    });
  });
}

async function ackAllAlerts() {
  const btn = el("ack-all-btn");
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/alerts/ack/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({}),
    });
    if (!resp.ok) throw new Error("ack failed");
    const data = await fetch("/api/alerts/").then((r) => r.json());
    renderAlerts(data);
  } catch (e) {
    console.warn("ack all failed", e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function initAckButton() {
  const btn = el("ack-all-btn");
  if (btn) btn.addEventListener("click", ackAllAlerts);
}

const IS_GUEST = !document.querySelector('meta[name="csrf-token"]');

async function pollGuest() {
  try {
    const result = await fetchWithCache("/api/widgets/", "widgets");
    renderWidgets(result.data);
    setRefreshState(result.ok, result.stale);
  } catch (e) {
    console.warn("guest widget poll failed", e);
    setRefreshState(false, false);
  }
}

async function pollWidgets() {
  try {
    const result = await fetchWithCache("/api/widgets/", "widgets");
    renderWidgets(result.data);
    if (!result.ok && result.stale) {
      setRefreshState(false, true);
    }
  } catch (e) {
    console.warn("widget poll failed", e);
  }
}

async function pollFast() {
  try {
    const [systemR, dockerR, alertsR] = await Promise.all([
      fetchWithCache("/api/system/", "system"),
      fetchWithCache("/api/docker/", "docker"),
      fetchWithCache("/api/alerts/", "alerts"),
    ]);
    renderSystem(systemR.data);
    renderDocker(dockerR.data);
    renderAlerts(alertsR.data);
    const anyOk = systemR.ok || dockerR.ok || alertsR.ok;
    const anyStale =
      (systemR.stale && !systemR.ok) ||
      (dockerR.stale && !dockerR.ok) ||
      (alertsR.stale && !alertsR.ok);
    setRefreshState(anyOk, anyStale && !anyOk);
  } catch (e) {
    console.warn("dashboard fast poll failed", e);
    setRefreshState(false, !!window.dashboardCache?.load("system"));
  }
}

async function pollSlow() {
  try {
    const [healthR, uptimeR] = await Promise.all([
      fetchWithCache("/api/health/", "health"),
      fetchWithCache("/api/uptime/", "uptime"),
    ]);
    renderHealth(healthR.data);
    renderUptime(uptimeR.data);
  } catch (e) {
    console.warn("dashboard slow poll failed", e);
  }
}

async function poll() {
  await pollFast();
  healthPollCounter += 1;
  if (healthPollCounter === 1 || healthPollCounter % 3 === 0) {
    await pollSlow();
  }
}

updateClock();
setInterval(updateClock, 1000);

if (IS_GUEST) {
  hydrateFromCache();
  pollGuest();
  setInterval(pollGuest, 15000);
} else {
  hydrateFromCache();
  initFilter();
  initStatusChips();
  initCollapsiblePanels();
  initAckButton();
  updateGroupTitles();
  poll();
  pollWidgets();
  setInterval(poll, 10000);
  setInterval(pollWidgets, 12000);
}
