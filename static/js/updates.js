(function () {
  const checkBtn = document.getElementById("update-check-btn");
  const installBtn = document.getElementById("update-install-btn");
  const banner = document.getElementById("update-banner");
  const latestEl = document.getElementById("update-latest");
  const checkedEl = document.getElementById("update-checked");
  const logWrap = document.getElementById("update-log-wrap");
  const logEl = document.getElementById("update-log");
  if (!checkBtn || !installBtn) return;

  let pollTimer = null;

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function formatRelative(iso) {
    if (!iso) return "Never";
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  function setBanner(text, available) {
    if (!banner) return;
    banner.textContent = text;
    banner.classList.toggle("update-banner--available", !!available);
  }

  function render(data) {
    if (latestEl) latestEl.textContent = data.latest_version || "—";
    if (checkedEl) checkedEl.textContent = formatRelative(data.last_checked_at);

    const running = data.install_state === "running";
    installBtn.disabled = !data.update_available || !data.install_allowed || running;

    if (running) {
      setBanner("Installing update…", true);
    } else if (data.install_state === "failed") {
      setBanner("Last update attempt failed. See the install log below.", false);
    } else if (data.restart_required) {
      setBanner(
        `Updated to v${data.installed_version}. Restart the service to load the new version.`,
        true
      );
    } else if (data.update_available) {
      setBanner(`Update ${data.latest_version} is available.`, true);
    } else if (data.check_error) {
      setBanner(data.check_error, false);
    } else {
      setBanner("You are running the latest version.", false);
    }

    if (logWrap && logEl) {
      if (data.install_log) {
        logWrap.hidden = false;
        logEl.textContent = data.install_log;
        logEl.scrollTop = logEl.scrollHeight;
      } else {
        logWrap.hidden = true;
      }
    }

    if (running) startPolling();
    else stopPolling();
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(refresh, 3000);
  }

  function stopPolling() {
    if (!pollTimer) return;
    clearInterval(pollTimer);
    pollTimer = null;
  }

  async function refresh() {
    try {
      const resp = await fetch("/api/updates/status/");
      if (!resp.ok) return;
      render(await resp.json());
    } catch (e) {
      console.warn("update status failed", e);
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

  checkBtn.addEventListener("click", async () => {
    checkBtn.disabled = true;
    const original = checkBtn.textContent;
    checkBtn.textContent = "Checking…";
    try {
      render(await post("/api/updates/check/"));
    } catch (e) {
      setBanner(e.message, false);
    } finally {
      checkBtn.disabled = false;
      checkBtn.textContent = original;
    }
  });

  installBtn.addEventListener("click", async () => {
    const version = latestEl ? latestEl.textContent : "the latest release";
    if (
      !confirm(
        `Install ${version}? The service will restart and be briefly unavailable.`
      )
    ) {
      return;
    }
    installBtn.disabled = true;
    try {
      render(await post("/api/updates/install/"));
      startPolling();
    } catch (e) {
      setBanner(e.message, false);
      installBtn.disabled = false;
    }
  });

  refresh();
})();
