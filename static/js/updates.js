(function () {
  const modal = document.getElementById("update-modal");
  const footerBtn = document.getElementById("footer-update-btn");
  const checkBtn = document.getElementById("update-check-btn");
  const settingsInstallBtn = document.getElementById("update-install-btn");
  const modalInstallBtn = document.getElementById("update-modal-install");
  const modalReloadBtn = document.getElementById("update-modal-reload");
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');

  if (!modal && !checkBtn && !settingsInstallBtn) return;

  let pollTimer = null;
  let restarting = false;
  let lastData = null;
  const DEFAULT_STEPS = [
    { id: "prepare", label: "Prepare" },
    { id: "fetch", label: "Fetch" },
    { id: "checkout", label: "Checkout" },
    { id: "deps", label: "Dependencies" },
    { id: "migrate", label: "Migrate" },
    { id: "collectstatic", label: "Collect static" },
    { id: "restart", label: "Restart" },
  ];

  function getCsrfToken() {
    if (csrfMeta) return csrfMeta.content;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  function formatRelative(iso) {
    if (!iso) return "Never";
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setBanner(el, text, available) {
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("update-banner--available", !!available);
  }

  function setProgress(prefix, data) {
    const wrap = document.getElementById(`${prefix}-progress`);
    const fill = document.getElementById(`${prefix}-fill`);
    const bar = document.getElementById(`${prefix}-bar`);
    const percentEl = document.getElementById(`${prefix}-percent`);
    const stepEl = document.getElementById(`${prefix}-step`);
    const running = data.install_state === "running" || restarting;
    const show = running || data.install_state === "success" || data.install_state === "failed";
    if (wrap) wrap.hidden = !show;
    const percent = restarting ? Math.max(data.install_percent || 0, 90) : data.install_percent || 0;
    if (fill) {
      fill.style.width = `${percent}%`;
      fill.classList.toggle("is-running", running);
    }
    if (bar) bar.setAttribute("aria-valuenow", String(percent));
    if (percentEl) percentEl.textContent = `${percent}%`;
    if (stepEl) {
      if (restarting) stepEl.textContent = "Restarting the service";
      else if (data.install_state === "success") stepEl.textContent = "Update complete";
      else if (data.install_state === "failed") stepEl.textContent = "Update failed";
      else stepEl.textContent = data.install_step || "Preparing…";
    }
  }

  function renderSteps(container, data) {
    if (!container) return;
    const steps = data.install_steps && data.install_steps.length ? data.install_steps : DEFAULT_STEPS;
    const index = data.install_step_index || 0;
    const failed = data.install_state === "failed";
    const success = data.install_state === "success";
    container.innerHTML = steps
      .map((step, i) => {
        const n = i + 1;
        let state = "pending";
        let mark = "";
        if (success || n < index) {
          state = "done";
          mark = "✓";
        } else if (failed && n === index) {
          state = "failed";
          mark = "!";
        } else if ((data.install_state === "running" || restarting) && n === index) {
          state = "active";
          mark = "•";
        } else if (restarting && n === steps.length) {
          state = "active";
          mark = "•";
        }
        return `<li class="update-step is-${state}"><span class="update-step__mark" aria-hidden="true">${mark}</span><span>${step.label}</span></li>`;
      })
      .join("");
  }

  function bannerText(data) {
    if (restarting) return "Restarting the service… retrying.";
    if (data.install_state === "running") return `Installing ${data.install_target_version || data.latest_version}…`;
    if (data.install_state === "failed") return "Last update attempt failed. See the install log below.";
    if (data.restart_required) {
      return `Updated to v${data.installed_version || data.current_version}. Restart the service to load the new version.`;
    }
    if (data.install_state === "success") {
      return `Updated to v${data.installed_version || data.current_version}.`;
    }
    if (data.update_available) return `Update ${data.latest_version} is available.`;
    if (data.check_error) return data.check_error;
    return "You are running the latest version.";
  }

  function render(data) {
    lastData = data;
    const running = data.install_state === "running";
    const available = !!data.update_available && !running && data.install_state !== "success";

    setText("update-latest", data.latest_version || "—");
    setText("update-checked", formatRelative(data.last_checked_at));
    setText("update-current", `v${data.current_version}`);

    if (footerBtn) {
      footerBtn.hidden = !data.update_available && data.install_state !== "running";
      footerBtn.textContent = running || restarting ? "Updating…" : "Update available";
    }

    const installAllowed = !!data.install_allowed && !!data.update_available && !running && !restarting;
    if (settingsInstallBtn) settingsInstallBtn.disabled = !installAllowed;
    if (modalInstallBtn) {
      modalInstallBtn.disabled = !installAllowed;
      modalInstallBtn.hidden = !(data.update_available && data.install_allowed) || running || restarting || data.install_state === "success";
    }
    if (modalReloadBtn) {
      const showReload = data.install_state === "success" && !running;
      modalReloadBtn.hidden = !showReload;
    }

    setBanner(document.getElementById("update-banner"), bannerText(data), available || running);
    setBanner(document.getElementById("update-modal-banner"), bannerText(data), available || running);

    const target = data.install_target_version || data.latest_version || "";
    const metaBits = [];
    if (target) metaBits.push(`${data.current_version} → ${target}`);
    if (data.release_published_at) metaBits.push(formatRelative(data.release_published_at));
    setText("update-modal-meta", metaBits.join(" · "));
    setText("update-modal-title", running || restarting ? "Installing update" : data.update_available ? "Update available" : "Updates");

    setProgress("update-modal", data);
    setProgress("settings-update", data);
    renderSteps(document.getElementById("update-modal-steps"), data);
    renderSteps(document.getElementById("settings-update-steps"), data);

    const notesWrap = document.getElementById("update-modal-notes-wrap");
    const notesEl = document.getElementById("update-modal-notes");
    if (notesWrap && notesEl) {
      if (data.release_notes) {
        notesWrap.hidden = false;
        notesEl.textContent = data.release_notes;
      } else {
        notesWrap.hidden = true;
      }
    }

    [
      ["update-log-wrap", "update-log"],
      ["update-modal-log-wrap", "update-modal-log"],
    ].forEach(([wrapId, logId]) => {
      const wrap = document.getElementById(wrapId);
      const logEl = document.getElementById(logId);
      if (!wrap || !logEl) return;
      if (data.install_log) {
        wrap.hidden = false;
        logEl.textContent = data.install_log;
        logEl.scrollTop = logEl.scrollHeight;
      } else if (wrapId !== "update-log-wrap") {
        wrap.hidden = true;
      }
    });

    if (running || restarting) startPolling();
    else stopPolling();
  }

  function openModal() {
    if (!modal) return;
    modal.hidden = false;
    if (lastData) render(lastData);
    else refresh();
  }

  function closeModal() {
    if (!modal) return;
    if (lastData && lastData.install_state === "running") return;
    modal.hidden = true;
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(refresh, 2000);
  }

  function stopPolling() {
    if (!pollTimer) return;
    clearInterval(pollTimer);
    pollTimer = null;
  }

  async function refresh() {
    try {
      const resp = await fetch("/api/updates/status/");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      restarting = false;
      render(data);
    } catch (e) {
      if (lastData && (lastData.install_state === "running" || restarting)) {
        restarting = true;
        render({ ...lastData, install_state: "running", install_step: "Restart" });
      } else {
        console.warn("update status failed", e);
      }
    }
  }

  async function post(url) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  async function startInstall() {
    try {
      const data = await post("/api/updates/install/");
      openModal();
      render(data);
      startPolling();
    } catch (e) {
      setBanner(document.getElementById("update-modal-banner"), e.message, false);
      setBanner(document.getElementById("update-banner"), e.message, false);
      if (settingsInstallBtn) settingsInstallBtn.disabled = false;
      if (modalInstallBtn) modalInstallBtn.disabled = false;
    }
  }

  if (checkBtn) {
    checkBtn.addEventListener("click", async () => {
      checkBtn.disabled = true;
      const original = checkBtn.textContent;
      checkBtn.textContent = "Checking…";
      try {
        render(await post("/api/updates/check/"));
      } catch (e) {
        setBanner(document.getElementById("update-banner"), e.message, false);
      } finally {
        checkBtn.disabled = false;
        checkBtn.textContent = original;
      }
    });
  }

  if (settingsInstallBtn) {
    settingsInstallBtn.addEventListener("click", () => {
      openModal();
    });
  }

  if (modalInstallBtn) {
    modalInstallBtn.addEventListener("click", () => {
      modalInstallBtn.disabled = true;
      startInstall();
    });
  }

  if (modalReloadBtn) {
    modalReloadBtn.addEventListener("click", () => {
      window.location.reload();
    });
  }

  if (footerBtn) {
    footerBtn.addEventListener("click", () => {
      openModal();
    });
  }

  modal?.querySelectorAll("[data-update-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  refresh();
})();
