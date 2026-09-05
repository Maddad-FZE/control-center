(function () {
  const pane = document.getElementById("settings-logs");
  if (!pane) return;

  const sourceSelect = document.getElementById("logs-source");
  const filterInput = document.getElementById("logs-filter");
  const liveToggle = document.getElementById("logs-live");
  const refreshBtn = document.getElementById("logs-refresh-btn");
  const downloadBtn = document.getElementById("logs-download-btn");
  const view = document.getElementById("logs-view");
  const status = document.getElementById("logs-status");

  let cursor = "";
  let timer = null;
  let stickBottom = true;
  let filterTimer = null;

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function paneActive() {
    return pane.classList.contains("is-active");
  }

  function setStatus(text) {
    if (status) status.textContent = text || "";
  }

  async function loadSources() {
    if (!sourceSelect) return;
    try {
      const resp = await fetch("/settings/api/logs/sources/");
      const data = await resp.json();
      const sources = data.sources || [];
      const current = sourceSelect.value;
      sourceSelect.innerHTML = sources
        .map(
          (row) =>
            `<option value="${row.id}">${row.label}${row.state && row.state !== "ok" && row.state !== "running" ? ` (${row.state})` : ""}</option>`
        )
        .join("");
      if (current && sources.some((row) => row.id === current)) {
        sourceSelect.value = current;
      }
    } catch (err) {
      setStatus("Could not load sources.");
    }
  }

  function renderLines(lines) {
    if (!view) return;
    view.textContent = lines.length ? lines.join("\n") : "No matching lines.";
    if (stickBottom) {
      view.scrollTop = view.scrollHeight;
    }
  }

  async function fetchLogs(reset) {
    if (!sourceSelect) return;
    const source = sourceSelect.value || "app";
    const q = filterInput ? filterInput.value.trim() : "";
    const params = new URLSearchParams({ source, tail: "400" });
    if (q) params.set("q", q);
    if (!reset && cursor) params.set("since", cursor);
    setStatus("Loading…");
    try {
      const resp = await fetch(`/settings/api/logs/?${params.toString()}`, { cache: "no-store" });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.error || "Could not load logs.");
        return;
      }
      cursor = data.cursor || cursor;
      if (reset) {
        renderLines(data.lines || []);
      } else if (data.lines && data.lines.length) {
        const existing = view.textContent === "No matching lines." ? "" : `${view.textContent}\n`;
        renderLines(`${existing}${data.lines.join("\n")}`.split("\n").filter(Boolean));
      }
      const suffix = data.truncated ? " (truncated)" : "";
      setStatus(data.error ? data.error : `${(data.lines || []).length} line(s)${suffix}`);
    } catch (err) {
      setStatus("Log fetch failed.");
    }
  }

  function stopLive() {
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  function startLive() {
    stopLive();
    if (!liveToggle || !liveToggle.checked || !paneActive()) return;
    timer = window.setInterval(() => fetchLogs(false), 3000);
  }

  function onRefresh() {
    cursor = "";
    stickBottom = true;
    fetchLogs(true);
  }

  refreshBtn?.addEventListener("click", onRefresh);
  downloadBtn?.addEventListener("click", () => {
    const source = sourceSelect?.value || "app";
    window.location.href = `/settings/api/logs/download/?source=${encodeURIComponent(source)}`;
  });

  filterInput?.addEventListener("input", () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(onRefresh, 300);
  });

  liveToggle?.addEventListener("change", () => {
    if (liveToggle.checked) startLive();
    else stopLive();
  });

  sourceSelect?.addEventListener("change", onRefresh);

  view?.addEventListener("scroll", () => {
    if (!view) return;
    stickBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 24;
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopLive();
    else if (liveToggle?.checked && paneActive()) startLive();
  });

  window.addEventListener("cc-wizard-section", () => {
    if (paneActive()) {
      loadSources().then(() => {
        if (view && (view.textContent.includes("Select a source") || view.textContent === "Loading…")) onRefresh();
        startLive();
      });
    } else {
      stopLive();
    }
  });

  if (pane.classList.contains("is-active")) {
    loadSources().then(onRefresh);
  }
})();
