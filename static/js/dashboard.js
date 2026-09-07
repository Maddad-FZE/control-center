function el(id) {
  return document.getElementById(id);
}

const cpuHistory = [];
const MAX_CPU_HISTORY = 30;
let prevNet = null;
let pollFailCount = 0;
let offlineMode = false;
let lastLiveAt = null;
const BASE_TITLE = document.title.replace(/^\(\d+ DOWN\) /, "");
const PANEL_STORAGE_KEY = "tva-panel-collapse";

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

function applyServiceFilter() {
  const input = el("service-filter");
  if (!input) return;
  const q = input.value.trim().toLowerCase();
  const downOnly = q === "is:down";
  const upOnly = q === "is:up";

  function matches(node) {
    const name = node.dataset.serviceName || "";
    const desc = node.dataset.serviceDesc || "";
    const isDown = node.dataset.serviceDown === "1";
    const isUp = node.dataset.serviceUp === "1";
    if (downOnly) return isDown;
    if (upOnly) return isUp;
    if (q) return name.includes(q) || desc.includes(q);
    return true;
  }

  document.querySelectorAll(".service-card-wrap").forEach((wrap) => {
    const target = wrap.querySelector(".service-card, .bookmark");
    if (!target) return;
    const match = matches(target);
    wrap.classList.toggle("hidden-by-filter", !match);
    target.classList.toggle("hidden-by-filter", !match);
    target.classList.toggle("filter-match", !!q && match && !downOnly && !upOnly);
  });

  document.querySelectorAll(".services-group").forEach((group) => {
    const wraps = Array.from(group.querySelectorAll(".service-card-wrap")).filter(
      (node) => !node.classList.contains("hidden-by-filter")
    );
    const visible = wraps.length;
    const empty = group.querySelector(".section-empty");
    if (empty) {
      empty.hidden = visible > 0;
      empty.textContent = q && visible === 0
        ? "Nothing matches this filter. Check back later or try another search."
        : empty.dataset.empty || "Nothing here right now. Check back later.";
    }
  });

  const upChip = el("stat-up");
  const downChip = el("stat-down");
  if (upChip) {
    upChip.classList.toggle("is-pressed", upOnly);
    upChip.setAttribute("aria-pressed", upOnly ? "true" : "false");
  }
  if (downChip) {
    downChip.classList.toggle("is-pressed", downOnly);
    downChip.setAttribute("aria-pressed", downOnly ? "true" : "false");
  }
}

function updateGroupTitles() {
  document.querySelectorAll(".services-group").forEach((group) => {
    const title = group.querySelector(".group-title");
    if (!title) return;
    const hasDown = group.querySelector(".service-card--down, .bookmark--down") !== null;
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
      const name = escapeHtml(c.name);
      const image = escapeHtml(c.image);
      const status = escapeHtml(c.status);
      const restartBtn = IS_ADMIN
        ? `<button type="button" class="container-restart-btn" data-docker-restart="${name}" aria-label="Restart ${name}" title="Restart">
            <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
              <path fill="currentColor" d="M13.65 4.35A7.5 7.5 0 1 0 15 8h-2a5.5 5.5 0 1 1-1.2-3.4L10 7h5V2l-1.35 2.35z"/>
            </svg>
          </button>`
        : "";
      return `
        <div class="container-row ${stateClass}">
          <div class="stat-row container-row__head">
            <span class="stat-label">${name}</span>
            <span class="container-row__status">
              <span class="stat-value">${status}</span>
              ${restartBtn}
            </span>
          </div>
          <span class="container-image" title="${image}">${image}</span>
        </div>`;
    })
    .join("");
  if (IS_ADMIN) bindDockerRestart(box);
}

function renderUsb(data) {
  const box = el("usb-stats");
  if (!box) return;
  if (!data || !data.available) {
    box.innerHTML = `<div class="stat-label">${escapeHtml(data?.message || "USB devices are not visible from this container.")}</div>`;
    return;
  }
  if (!data.devices.length) {
    box.innerHTML = `<div class="stat-label">No USB devices connected.</div>`;
    return;
  }
  box.innerHTML = data.devices
    .map((dev) => {
      const bits = [dev.kind, `${dev.vendor_id}:${dev.product_id}`, dev.speed].filter(Boolean);
      if (dev.blocks && dev.blocks.length) bits.push(dev.blocks.map((b) => `/dev/${b}`).join(" "));
      const mounts = (dev.mounts || [])
        .map((m) => {
          const path = escapeHtml(m.path);
          const unmount = IS_ADMIN
            ? `<button type="button" class="btn secondary btn-compact" data-usb-unmount="${path}">Unmount</button>`
            : "";
          return `<div class="usb-row__actions"><span class="usb-row__meta">${path}</span>${unmount}</div>`;
        })
        .join("");
      return `
        <div class="usb-row">
          <span class="usb-row__name">${escapeHtml(dev.name)}</span>
          <span class="usb-row__meta">${escapeHtml(bits.join(" · "))}</span>
          ${mounts}
        </div>`;
    })
    .join("");
  if (IS_ADMIN) bindUsbUnmount(box);
}

function renderHealth(data) {
  let up = 0;
  let down = 0;
  let unknown = 0;

  (data.services || []).forEach((s) => {
    const dot = document.querySelector(`.service-card .status-dot[data-service-id="${s.id}"]`);
    const card = dot ? dot.closest(".service-card") : null;
    const latency = document.querySelector(`.service-latency[data-service-id="${s.id}"]`);

    document.querySelectorAll(`.status-dot[data-service-id="${s.id}"]`).forEach((node) => {
      node.classList.remove("up", "down", "is-checking");
      if (s.is_up === true) {
        node.classList.add("up");
        node.setAttribute("aria-label", `${s.name}: up`);
      } else if (s.is_up === false) {
        node.classList.add("down");
        node.setAttribute("aria-label", `${s.name}: down`);
      } else {
        node.setAttribute("aria-label", `${s.name}: unknown`);
      }
    });
    if (card) {
      card.classList.toggle("service-card--down", s.is_up === false);
      card.dataset.serviceDown = s.is_up === false ? "1" : "0";
      card.dataset.serviceUp = s.is_up === true ? "1" : "0";
      const latencyText = s.response_ms != null ? ` · ${s.response_ms}ms` : "";
      card.title = `${s.name}${latencyText}`;
    }
    const bookmark = document.querySelector(`.bookmark[data-service-id="${s.id}"]`);
    if (bookmark) {
      bookmark.classList.toggle("bookmark--down", s.is_up === false);
      bookmark.dataset.serviceDown = s.is_up === false ? "1" : "0";
      bookmark.dataset.serviceUp = s.is_up === true ? "1" : "0";
    }
    if (latency && s.response_ms != null) {
      latency.textContent = `${s.response_ms}ms`;
    }

    if (s.is_up === true) up += 1;
    else if (s.is_up === false) down += 1;
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
  if (data.kuma_available === false) {
    const canInstall = data.kuma_can_install || box.dataset.canInstall === "1";
    const cta = canInstall
      ? `<a class="btn" href="/library/?q=uptime-kuma">Install Uptime Kuma</a>`
      : "";
    box.innerHTML = `<div class="uptime-empty"><div class="stat-label">Install Uptime Kuma to see the monitor.</div>${cta}</div>`;
    updateUptimeChip(null);
    return;
  }
  if (data.kuma_synced === false || !ids.length) {
    box.innerHTML = `<div class="uptime-empty"><div class="stat-label">Waiting for the first monitor check.</div></div>`;
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
      const state =
        entry.is_up === true ? "up" : entry.is_up === false ? "down" : "unknown";
      const stateLabel = state === "up" ? "Up" : state === "down" ? "Down" : "—";
      return `
        <div class="uptime-row${state === "down" ? " uptime-row--down" : ""}">
          <div class="uptime-header">
            <span class="uptime-name">${escapeHtml(entry.name || "Service #" + id)}</span>
            <span class="uptime-pct">
              <span class="uptime-state uptime-state--${state}">${stateLabel}</span>
              ${pct}
            </span>
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
  if (window.ccAlertsMenu) {
    window.ccAlertsMenu.render(data);
    return;
  }
}

function setOfflineBanner(show, message) {
  const banner = el("offline-banner");
  if (!banner) return;
  banner.hidden = !show;
  if (show && message) banner.textContent = message;
}

function setRefreshChip(state, labelText, timeText, when) {
  const indicator = el("refresh-indicator");
  if (!indicator) return;
  const label = indicator.querySelector(".sync-chip__label");
  const time = indicator.querySelector(".sync-chip__time");
  indicator.dataset.state = state;
  indicator.classList.toggle("stale", state === "stale" || state === "down");
  if (label) label.textContent = labelText;
  if (time) {
    time.textContent = timeText;
    if (when) time.setAttribute("datetime", when.toISOString());
    else time.removeAttribute("datetime");
  }
}

function setRefreshState(ok, fromCache) {
  if (ok) {
    pollFailCount = 0;
    offlineMode = false;
    lastLiveAt = new Date();
    clearHostDown();
    setOfflineBanner(false);
    setRefreshChip("live", "Live", formatTime24(lastLiveAt), lastLiveAt);
  } else if (fromCache) {
    offlineMode = true;
    setOfflineBanner(true, "Host unreachable — layout is cached, metrics are not live");
    setRefreshChip(
      "down",
      "Down",
      lastLiveAt ? formatTime24(lastLiveAt) : "––:––:––",
      lastLiveAt
    );
  } else {
    pollFailCount += 1;
    offlineMode = true;
    setOfflineBanner(true, "Host unreachable — layout is cached, metrics are not live");
    setRefreshChip(
      "down",
      pollFailCount > 1 ? "Retry" : "Down",
      lastLiveAt ? formatTime24(lastLiveAt) : "––:––:––",
      lastLiveAt
    );
  }
}

const FETCH_TIMEOUT_MS = 6000;
const lastPayload = {};

function payloadStamp(data) {
  try {
    return JSON.stringify(data);
  } catch {
    return String(Date.now());
  }
}

function shouldRender(key, data) {
  const stamp = payloadStamp(data);
  if (lastPayload[key] === stamp) return false;
  lastPayload[key] = stamp;
  return true;
}

function setFeedStopped(bodyId, stopped) {
  const body = el(bodyId);
  if (!body) return;
  let note = body.querySelector(".feed-stopped");
  if (!note) {
    note = document.createElement("div");
    note.className = "feed-stopped";
    note.setAttribute("role", "status");
    note.textContent = "Feed stopped — retrying";
    body.prepend(note);
  }
  note.hidden = !stopped;
  body.classList.toggle("is-stopped", stopped);
}

function renderSystemZeroed() {
  const box = el("system-stats");
  if (!box) return;
  cpuHistory.length = 0;
  prevNet = null;
  const hostUptime = el("stat-host-uptime");
  if (hostUptime) hostUptime.textContent = "Host —";
  box.innerHTML = `
    ${gaugeRow("CPU", 0, "—")}
    <div class="cpu-sparkline" aria-hidden="true"></div>
    <div class="stat-row"><span class="stat-label">Load</span><span class="stat-value">—</span></div>
    ${gaugeRow("Memory", 0, "—")}
  `;
}

function applyHostDown() {
  document.body.classList.add("host-down");
  lastPayload.system = "";
  lastPayload.docker = "";
  lastPayload.usb = "";
  renderSystemZeroed();
  const dockerBox = el("docker-stats");
  const countEl = el("docker-count");
  if (countEl) countEl.textContent = "—";
  if (dockerBox) dockerBox.innerHTML = `<div class="stat-label">Host unreachable.</div>`;
  const usbBox = el("usb-stats");
  if (usbBox) usbBox.innerHTML = `<div class="stat-label">Host unreachable.</div>`;
  ["panel-system", "panel-usb", "panel-containers"].forEach((id) => {
    setFeedStopped(id, true);
  });
}

function clearHostDown() {
  document.body.classList.remove("host-down");
}

async function fetchWithTimeout(url) {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    return await fetch(url, { signal: ctrl.signal, cache: "no-store" });
  } finally {
    window.clearTimeout(timer);
  }
}

async function fetchWithCache(url, cacheKey) {
  try {
    const resp = await fetchWithTimeout(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data && data.offline) throw new Error("offline");
    if (window.dashboardCache) {
      window.dashboardCache.save(cacheKey, data);
    }
    return { ok: true, stale: false, data };
  } catch (e) {
    const cached = window.dashboardCache ? window.dashboardCache.load(cacheKey) : null;
    if (cached) {
      return { ok: false, stale: true, data: cached.data };
    }
    return { ok: false, stale: false, data: null };
  }
}

function hydrateFromCache() {
  if (!window.dashboardCache) return;
  if (navigator.onLine) return;
  let newestSavedAt = 0;
  window.dashboardCache.hydrateKeys.forEach((key) => {
    const entry = window.dashboardCache.load(key);
    if (!entry) return;
    if (entry.savedAt > newestSavedAt) newestSavedAt = entry.savedAt;
    const data = entry.data;
    if (key === "alerts") renderAlerts(data);
    else if (key === "health") renderHealth(data);
    else if (key === "uptime") renderUptime(data);
    else if (key === "widgets") renderWidgets(data);
  });
  if (newestSavedAt) lastLiveAt = new Date(newestSavedAt);
  applyHostDown();
  setRefreshState(false, false);
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
  const downChip = el("stat-down");

  function toggleStatusFilter(token) {
    const input = el("service-filter");
    if (!input) return;
    input.value = input.value.trim().toLowerCase() === token ? "" : token;
    applyServiceFilter();
  }

  const upChip = el("stat-up");
  if (upChip) {
    upChip.addEventListener("click", () => toggleStatusFilter("is:up"));
  }

  if (downChip) {
    downChip.addEventListener("click", () => toggleStatusFilter("is:down"));
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

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "Request failed");
  return data;
}

function bindDockerRestart(box) {
  box.querySelectorAll("[data-docker-restart]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.dockerRestart;
      if (!name) return;
      const ok = await window.ccDialog.confirm(
        `Restart ${name}? It will be briefly offline.`,
        { title: "Restart", confirmLabel: "Restart" },
      );
      if (!ok) return;
      btn.disabled = true;
      try {
        await postJson("/api/docker/restart/", { name });
        const data = await fetch("/api/docker/").then((r) => r.json());
        renderDocker(data);
      } catch (err) {
        await window.ccDialog.alert(err.message, { title: "Restart" });
        btn.disabled = false;
      }
    });
  });
}

function bindUsbUnmount(box) {
  box.querySelectorAll("[data-usb-unmount]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.usbUnmount;
      if (!path) return;
      const ok = await window.ccDialog.confirm(`Unmount ${path}?`, {
        title: "Unmount",
        confirmLabel: "Unmount",
        danger: true,
      });
      if (!ok) return;
      btn.disabled = true;
      try {
        await postJson("/api/system/usb/unmount/", { path });
        const data = await fetch("/api/system/usb/").then((r) => r.json());
        renderUsb(data);
      } catch (err) {
        await window.ccDialog.alert(err.message, { title: "Unmount" });
        btn.disabled = false;
      }
    });
  });
}

function initHostOps() {
  const refresh = el("usb-refresh-btn");
  if (refresh) {
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        const data = await fetch("/api/system/usb/").then((r) => r.json());
        renderUsb(data);
      } catch (err) {
        console.warn("usb refresh failed", err);
      } finally {
        refresh.disabled = false;
      }
    });
  }

  const modal = el("host-reboot-modal");
  const openBtn = el("host-reboot-btn");
  const confirmBtn = el("host-reboot-confirm");
  const close = () => {
    if (modal) modal.hidden = true;
  };
  openBtn?.addEventListener("click", () => {
    if (modal) modal.hidden = false;
  });
  modal?.querySelectorAll("[data-reboot-close]").forEach((node) => {
    node.addEventListener("click", close);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) close();
  });
  confirmBtn?.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    try {
      const data = await postJson("/api/system/reboot/", {});
      close();
      await window.ccDialog.alert(data.message || "Reboot scheduled.", { title: "Reboot" });
    } catch (err) {
      await window.ccDialog.alert(err.message, { title: "Reboot" });
    } finally {
      confirmBtn.disabled = false;
    }
  });
}

const IS_GUEST = !document.querySelector('meta[name="csrf-token"]');
const IS_ADMIN = document.querySelector(".ops-stack")?.dataset.admin === "1";

async function pollGuest() {
  const result = await fetchWithCache("/api/widgets/", "widgets");
  if (result.data) renderWidgets(result.data);
  setRefreshState(result.ok, result.stale);
}

async function pollWidgets() {
  const result = await fetchWithCache("/api/widgets/", "widgets");
  if (result.ok && result.data) renderWidgets(result.data);
}

async function pollFast() {
  const [systemR, dockerR, alertsR, usbR] = await Promise.all([
    fetchWithCache("/api/system/", "system"),
    fetchWithCache("/api/docker/", "docker"),
    fetchWithCache("/api/alerts/", "alerts"),
    fetchWithCache("/api/system/usb/", "usb"),
  ]);
  const live = [systemR, dockerR, alertsR, usbR].some((row) => row.ok);
  if (!live) {
    applyHostDown();
    setRefreshState(false, false);
    if (alertsR.data) renderAlerts(alertsR.data);
    return;
  }

  if (systemR.ok && systemR.data) {
    setFeedStopped("panel-system", false);
    if (shouldRender("system", systemR.data)) renderSystem(systemR.data);
  } else {
    setFeedStopped("panel-system", true);
  }

  if (dockerR.ok && dockerR.data) {
    setFeedStopped("panel-containers", false);
    if (shouldRender("docker", dockerR.data)) renderDocker(dockerR.data);
  } else {
    setFeedStopped("panel-containers", true);
  }

  if (alertsR.data) renderAlerts(alertsR.data);

  if (usbR.ok && usbR.data) {
    setFeedStopped("panel-usb", false);
    if (shouldRender("usb", usbR.data)) renderUsb(usbR.data);
  } else {
    setFeedStopped("panel-usb", true);
  }

  setRefreshState(true, false);
}

async function pollSlow() {
  const [healthR, uptimeR] = await Promise.all([
    fetchWithCache("/api/health/", "health"),
    fetchWithCache("/api/uptime/", "uptime"),
  ]);
  if (healthR.ok && healthR.data) {
    const fresh = healthJustRan(healthR.data || {});
    if (fresh) beginDownCheckPulse();
    renderHealth(healthR.data);
    if (fresh) window.setTimeout(endDownCheckPulse, 700);
  } else {
    endDownCheckPulse();
    if (healthR.data) renderHealth(healthR.data);
  }
  if (uptimeR.ok && uptimeR.data) {
    setFeedStopped("panel-uptime", false);
    if (shouldRender("uptime", uptimeR.data)) renderUptime(uptimeR.data);
  } else if (uptimeR.data) {
    setFeedStopped("panel-uptime", true);
    if (shouldRender("uptime", uptimeR.data)) renderUptime(uptimeR.data);
  } else {
    setFeedStopped("panel-uptime", true);
  }
}

function beginDownCheckPulse() {
  document.querySelectorAll(".status-dot.down").forEach((dot) => {
    dot.classList.add("is-checking");
  });
  document.querySelectorAll(".bookmark--down").forEach((chip) => {
    chip.classList.add("is-checking");
    const wrap = chip.closest(".service-card-wrap--misc");
    if (wrap) wrap.classList.add("is-checking");
  });
}

function endDownCheckPulse() {
  document.querySelectorAll(".is-checking").forEach((node) => {
    node.classList.remove("is-checking");
  });
}

let lastHealthStamp = "";
let fastTimer = null;
let slowTimer = null;
let widgetTimer = null;

function healthJustRan(data) {
  let newest = "";
  (data.services || []).forEach((s) => {
    if (s.checked_at && s.checked_at > newest) newest = s.checked_at;
  });
  if (!newest) return false;
  if (!lastHealthStamp) {
    lastHealthStamp = newest;
    return false;
  }
  if (newest === lastHealthStamp) return false;
  lastHealthStamp = newest;
  return true;
}

function stopDashboardTimers() {
  if (fastTimer) window.clearInterval(fastTimer);
  if (slowTimer) window.clearInterval(slowTimer);
  if (widgetTimer) window.clearInterval(widgetTimer);
  fastTimer = null;
  slowTimer = null;
  widgetTimer = null;
}

function startDashboardTimers() {
  stopDashboardTimers();
  if (document.hidden) return;
  if (IS_GUEST) {
    widgetTimer = window.setInterval(pollGuest, 30000);
    return;
  }
  fastTimer = window.setInterval(pollFast, 15000);
  slowTimer = window.setInterval(pollSlow, 45000);
  widgetTimer = window.setInterval(pollWidgets, 30000);
}

function refreshDashboard() {
  if (IS_GUEST) {
    pollGuest();
    return;
  }
  pollFast();
  pollSlow();
  pollWidgets();
}

hydrateFromCache();
initFilter();
initStatusChips();
window.addEventListener("cc-cards-changed", () => {
  updateGroupTitles();
  applyServiceFilter();
});
if (!IS_GUEST) {
  initCollapsiblePanels();
  initHostOps();
  updateGroupTitles();
}
refreshDashboard();
startDashboardTimers();
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopDashboardTimers();
    return;
  }
  refreshDashboard();
  startDashboardTimers();
});
