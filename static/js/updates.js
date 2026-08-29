(function () {
  const modal = document.getElementById("update-modal");
  const footerBtn = document.getElementById("footer-update-btn");
  const headerBtn = document.getElementById("header-update-btn");
  const checkBtn = document.getElementById("update-check-btn");
  const settingsInstallBtn = document.getElementById("update-install-btn");
  const modalInstallBtn = document.getElementById("update-modal-install");
  const modalReloadBtn = document.getElementById("update-modal-reload");
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');

  if (!modal && !checkBtn && !settingsInstallBtn && !headerBtn && !footerBtn) return;

  let pollTimer = null;
  let restarting = false;
  let lastData = null;

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

  function padPercent(n) {
    return String(Math.max(0, Math.min(100, Math.round(n)))).padStart(3, "0");
  }

  function stepLine(percent, label) {
    return `[${padPercent(percent)}%] ${(label || "PREPARING").toUpperCase()}`;
  }

  function setProgress(prefix, data) {
    const wrap = document.getElementById(`${prefix}-progress`);
    const fill = document.getElementById(`${prefix}-fill`);
    const bar = document.getElementById(`${prefix}-bar`);
    const stepEl = document.getElementById(`${prefix}-step`);
    const running = data.install_state === "running" || restarting;
    const show = running || data.install_state === "success" || data.install_state === "failed";
    if (wrap) wrap.hidden = !show;
    const percent = restarting ? Math.max(data.install_percent || 0, 90) : data.install_percent || 0;
    if (fill) {
      fill.classList.remove("is-running");
      fill.style.width = `${percent}%`;
    }
    if (bar) bar.setAttribute("aria-valuenow", String(percent));
    let label = data.install_step || "Preparing";
    if (restarting) label = "Restart";
    else if (data.install_state === "success") label = "Complete";
    else if (data.install_state === "failed") label = "Failed";
    if (stepEl) stepEl.textContent = stepLine(percent, label);
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
    if (headerBtn) {
      headerBtn.hidden = !data.update_available && data.install_state !== "running" && !restarting;
      const label = headerBtn.querySelector(".update-chip__label");
      if (label) label.textContent = running || restarting ? "Updating" : "Update";
      headerBtn.setAttribute(
        "aria-label",
        running || restarting
          ? "Update in progress"
          : data.latest_version
            ? `Update ${data.latest_version} available`
            : "Update available"
      );
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

  if (headerBtn) {
    headerBtn.addEventListener("click", () => {
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
