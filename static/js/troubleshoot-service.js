(function () {
  const modal = document.getElementById("service-troubleshoot-modal");
  if (!modal) return;

  const titleEl = document.getElementById("service-troubleshoot-title");
  const summaryEl = document.getElementById("service-troubleshoot-summary");
  const progressEl = document.getElementById("service-troubleshoot-progress");
  const progressLabel = document.getElementById("service-troubleshoot-progress-label");
  const findingsEl = document.getElementById("service-troubleshoot-findings");
  const actionsEl = document.getElementById("service-troubleshoot-actions");
  const logEl = document.getElementById("service-troubleshoot-log");
  const copyBtn = document.getElementById("service-troubleshoot-copy");
  const downloadBtn = document.getElementById("service-troubleshoot-download");
  let active = null;
  let pollTimer = null;
  let lastFocused = null;

  const STATUS_LABELS = {
    queued: "Looking",
    running: "Looking",
    healthy: "Looks good",
    needs_action: "Needs a fix",
    manual_only: "Needs you",
    failed: "Could not finish",
    cancelled: "Cancelled",
  };

  function csrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function closeModal() {
    modal.hidden = true;
    modal.setAttribute("aria-busy", "false");
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    active = null;
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function setProgress(on, label) {
    progressEl.hidden = !on;
    progressLabel.textContent = label || "Looking";
    modal.setAttribute("aria-busy", on ? "true" : "false");
  }

  async function fetchJson(url, options) {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.error || data.hint || "Request failed");
      err.payload = data;
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  function lookingLabel(payload, fallbackName) {
    const name = (payload && payload.service && payload.service.name) || fallbackName || "this service";
    return `Looking at ${name}`;
  }

  function render(payload) {
    if (!payload) return;
    titleEl.textContent = payload.service ? `Troubleshoot — ${payload.service.name}` : "Troubleshoot";
    summaryEl.textContent = payload.summary || "";
    findingsEl.replaceChildren();
    const visible = (payload.findings || []).filter((row) => row.issue_id !== "ISSUE_HEALTHY");
    if (!visible.length && payload.status && payload.status !== "queued" && payload.status !== "running") {
      const empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "Nothing to fix right now.";
      findingsEl.appendChild(empty);
    }
    visible.forEach((row) => {
      const article = document.createElement("article");
      article.className = "troubleshoot-finding";
      const heading = document.createElement("h3");
      heading.textContent = row.title || "Needs attention";
      const body = document.createElement("p");
      body.className = "settings-hint";
      body.textContent = row.plain_language || "";
      article.append(heading, body);
      findingsEl.appendChild(article);
    });
    actionsEl.replaceChildren();
    let primaryAssigned = false;
    (payload.actions || []).forEach((action) => {
      if (action.href) {
        const link = document.createElement("a");
        link.className = "btn secondary";
        link.href = action.href;
        link.textContent = action.title;
        actionsEl.appendChild(link);
        return;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      const isRecheck = action.action_id === "ACTION_RECHECK";
      const isDanger = action.risk === "destructive" || action.risk === "disruptive";
      if (!isRecheck && !primaryAssigned) {
        btn.className = isDanger ? "btn danger" : "btn";
        primaryAssigned = true;
      } else {
        btn.className = isDanger ? "btn danger" : "btn secondary";
      }
      btn.textContent = action.title;
      btn.dataset.actionId = action.action_id;
      btn.dataset.confirm = action.confirm ? "1" : "";
      btn.dataset.confirmText = action.confirmation_language || "";
      btn.dataset.risk = action.risk || "safe";
      if (!payload.can_repair && action.action_id !== "ACTION_RECHECK") btn.disabled = true;
      actionsEl.appendChild(btn);
    });
    const snap = payload.snapshot || {};
    const service = payload.service || {};
    const cardHost = service.host || "";
    const cardPort = service.port || "";
    const liveHost = snap.host || "";
    const livePort = snap.port || "";
    const container = snap.container_name || "None";
    logEl.textContent = [
      `Status: ${STATUS_LABELS[payload.status] || payload.status || "—"}`,
      `Card address: ${cardHost}${cardPort ? `:${cardPort}` : ""}`,
      `Live address: ${liveHost}${livePort ? `:${livePort}` : ""}`,
      `Container: ${container}`,
    ].join("\n");
    if (payload.report_url) {
      downloadBtn.hidden = false;
      downloadBtn.href = payload.report_url;
    }
    if (payload.cache_bust && window.dashboardCache && window.dashboardCache.clear) {
      window.dashboardCache.clear();
    }
  }

  async function poll(url) {
    const payload = await fetchJson(url);
    active = payload;
    const running = payload.status === "queued" || payload.status === "running";
    setProgress(running, running ? lookingLabel(payload) : "");
    render(payload);
    if (running) {
      pollTimer = setTimeout(() => poll(url).catch((err) => {
        summaryEl.textContent = err.message;
        setProgress(false);
      }), 1500);
    }
  }

  async function startTroubleshoot({ serviceId, name }) {
    lastFocused = document.activeElement;
    modal.hidden = false;
    titleEl.textContent = name ? `Troubleshoot — ${name}` : "Troubleshoot";
    summaryEl.textContent = name ? `Looking at ${name}…` : "Looking at this service…";
    findingsEl.replaceChildren();
    actionsEl.replaceChildren();
    logEl.textContent = "";
    setProgress(true, name ? `Looking at ${name}` : "Looking at this service");
    try {
      const payload = await fetchJson(`/api/services/${serviceId}/troubleshoot/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf() },
      });
      active = payload;
      await poll(payload.poll_url);
    } catch (err) {
      setProgress(false);
      summaryEl.textContent = err.message;
      if (window.ccDialog) window.ccDialog.alert(err.message, { title: "Troubleshoot" });
    }
  }

  async function runRepair(action) {
    if (!active) return;
    let confirmed = !action.confirm;
    if (action.confirm) {
      const ok = await window.ccDialog.confirm(action.confirmation_language || `Run ${action.title}?`, {
        title: action.title,
        confirmLabel: action.title,
        danger: action.risk !== "safe",
      });
      if (!ok) return;
      confirmed = true;
    }
    setProgress(true, action.title);
    try {
      const started = await fetchJson(active.poll_url + "repair/", {
        method: "POST",
        headers: {
          "X-CSRFToken": csrf(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action_id: action.action_id,
          confirmed,
          confirm_token: confirmed ? "ok" : "",
        }),
      });
      if (started.needs_confirm) {
        const ok = await window.ccDialog.confirm(started.confirmation_language || action.title, {
          title: action.title,
          danger: true,
        });
        if (!ok) {
          setProgress(false);
          return;
        }
        await fetchJson(active.poll_url + "repair/", {
          method: "POST",
          headers: {
            "X-CSRFToken": csrf(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            action_id: action.action_id,
            confirmed: true,
            confirm_token: started.confirm_token || "ok",
          }),
        });
      }
      const jobId = started.job_id;
      if (jobId) {
        const repairUrl = `${active.poll_url}repair/${jobId}/`;
        const wait = async () => {
          const job = await fetchJson(repairUrl);
          if (job.status === "queued" || job.status === "running") {
            pollTimer = setTimeout(wait, 1500);
            return;
          }
          if (job.status !== "succeeded") {
            await window.ccDialog.alert(job.message || "That did not work.", { title: "Troubleshoot" });
          }
          await poll(active.poll_url);
        };
        await wait();
      } else {
        await poll(active.poll_url);
      }
    } catch (err) {
      setProgress(false);
      await window.ccDialog.alert(err.message, { title: "Troubleshoot" });
    }
  }

  actionsEl.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-action-id]");
    if (!btn) return;
    runRepair({
      action_id: btn.dataset.actionId,
      title: btn.textContent,
      confirm: btn.dataset.confirm === "1",
      confirmation_language: btn.dataset.confirmText,
      risk: btn.dataset.risk,
    });
  });

  copyBtn.addEventListener("click", async () => {
    if (!active) return;
    try {
      const payload = await fetchJson(active.report_json_url || `${active.poll_url}report.json`);
      const text = payload.report_text || logEl.textContent;
      await navigator.clipboard.writeText(text);
      copyBtn.textContent = "Copied";
      setTimeout(() => {
        copyBtn.textContent = "Copy report";
      }, 1200);
    } catch (err) {
      await window.ccDialog.alert(err.message || "Could not copy the report.", { title: "Troubleshoot" });
    }
  });

  modal.querySelectorAll("[data-troubleshoot-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      event.preventDefault();
      closeModal();
    }
  });

  window.ccOpenServiceTroubleshoot = startTroubleshoot;
})();
