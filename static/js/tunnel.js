(function () {
  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  async function jsonFetch(url, options) {
    const resp = await fetch(url, {
      ...options,
      headers: {
        "X-CSRFToken": csrfToken(),
        "Content-Type": "application/json",
        ...(options && options.headers),
      },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  function fillSelect(select, rows, valueKey, labelKey) {
    select.innerHTML = "";
    rows.forEach((row) => {
      const opt = document.createElement("option");
      opt.value = row[valueKey];
      opt.textContent = row[labelKey] || row[valueKey];
      select.appendChild(opt);
    });
  }

  function renderRoutes(list, empty, routes) {
    if (!list) return;
    list.innerHTML = "";
    if (!routes.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    routes.forEach((route) => {
      const li = document.createElement("li");
      li.className = "tunnel-route-item";
      li.innerHTML = `<span>${route.hostname}</span> <span class="settings-hint">${route.origin_url}</span>
        <button type="button" class="btn danger" data-unpublish="${route.hostname}">Unpublish</button>`;
      list.appendChild(li);
    });
  }

  async function loadTunnelStatus() {
    const statusLine = document.getElementById("tunnel-status-line");
    const notInstalled = document.getElementById("tunnel-not-installed");
    const installedSettings = document.getElementById("tunnel-installed-settings");
    const installCta = document.getElementById("tunnel-install-cta");
    const linkForm = document.getElementById("tunnel-link-form");
    const linkedPanel = document.getElementById("tunnel-linked-panel");
    const tokenLink = document.getElementById("tunnel-token-link");
    const meta = document.getElementById("tunnel-linked-meta");
    const list = document.getElementById("tunnel-route-list");
    const empty = document.getElementById("tunnel-route-empty");
    const installedStatus = document.getElementById("tunnel-installed-status");
    if (!notInstalled && !installedSettings) return null;
    const data = await jsonFetch("/library/api/tunnel/status/", { method: "GET" });
    if (tokenLink && data.token_url) tokenLink.href = data.token_url;
    if (!data.installed) {
      if (statusLine) statusLine.textContent = "Cloudflare Tunnel is not installed.";
      if (notInstalled) notInstalled.hidden = false;
      if (installCta) installCta.hidden = false;
      if (installedSettings) installedSettings.hidden = true;
      if (linkForm) linkForm.hidden = true;
      if (linkedPanel) linkedPanel.hidden = true;
      return data;
    }
    if (notInstalled) notInstalled.hidden = true;
    if (installCta) installCta.hidden = true;
    if (installedSettings) installedSettings.hidden = false;
    if (!data.linked) {
      if (installedStatus) {
        installedStatus.textContent = "Paste a token and click Connect. Nothing is published yet.";
      }
      if (linkForm) linkForm.hidden = false;
      if (linkedPanel) linkedPanel.hidden = true;
      if (accountGroup) accountGroup.hidden = true;
      if (zoneGroup) zoneGroup.hidden = true;
      setLinkStep("connect");
      return data;
    }
    if (installedStatus) {
      installedStatus.textContent = "Linked. Publish a service only when you mean to expose it online.";
    }
    if (linkForm) linkForm.hidden = true;
    if (linkedPanel) linkedPanel.hidden = false;
    if (meta) meta.textContent = data.zone_name ? `Zone ${data.zone_name}` : "Account linked.";
    renderRoutes(list, empty, data.routes || []);
    return data;
  }

  const linkBtn = document.getElementById("tunnel-link-btn");
  const unlinkBtn = document.getElementById("tunnel-unlink-btn");
  const errorEl = document.getElementById("tunnel-link-error");
  const accountGroup = document.getElementById("tunnel-account-group");
  const zoneGroup = document.getElementById("tunnel-zone-group");
  const accountSelect = document.getElementById("tunnel-account");
  const zoneSelect = document.getElementById("tunnel-zone");

  function setLinkStep(step) {
    if (!linkBtn) return;
    linkBtn.dataset.step = step;
    linkBtn.textContent = step === "link" ? "Link account" : "Connect";
  }

  function showPreview(result) {
    if (accountGroup && accountSelect && (result.accounts || []).length) {
      fillSelect(accountSelect, result.accounts, "id", "name");
      accountGroup.hidden = false;
    }
    if (zoneGroup && zoneSelect && (result.zones || []).length) {
      fillSelect(zoneSelect, result.zones, "id", "name");
      zoneGroup.hidden = false;
    }
    setLinkStep("link");
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = "Review the account and zone, then click Link account.";
    }
  }

  linkBtn?.addEventListener("click", async () => {
    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
    const token = document.getElementById("tunnel-api-token")?.value || "";
    const confirm = linkBtn.dataset.step === "link";
    linkBtn.disabled = true;
    try {
      const result = await jsonFetch("/library/api/tunnel/link/", {
        method: "POST",
        body: JSON.stringify({
          token,
          account_id: accountSelect?.value || "",
          zone_id: zoneSelect?.value || "",
          confirm,
        }),
      });
      if (result.preview || result.needs_choice) {
        showPreview(result);
        return;
      }
      await loadTunnelStatus();
    } catch (err) {
      if (errorEl) {
        errorEl.hidden = false;
        errorEl.textContent = err.message;
      }
    } finally {
      linkBtn.disabled = false;
    }
  });

  unlinkBtn?.addEventListener("click", async () => {
    if (!window.confirm("Unlink Cloudflare? Published hostnames on this host will be removed here.")) return;
    unlinkBtn.disabled = true;
    try {
      await jsonFetch("/library/api/tunnel/unlink/", { method: "POST", body: "{}" });
      await loadTunnelStatus();
    } finally {
      unlinkBtn.disabled = false;
    }
  });

  document.getElementById("tunnel-route-list")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-unpublish]");
    if (!btn) return;
    try {
      await jsonFetch("/library/api/tunnel/unpublish/", {
        method: "POST",
        body: JSON.stringify({ hostname: btn.dataset.unpublish }),
      });
      window.location.reload();
    } catch (err) {
      window.alert(err.message);
    }
  });

  if (document.getElementById("tunnel-status-line")) {
    loadTunnelStatus().catch(() => {
      const statusLine = document.getElementById("tunnel-status-line");
      if (statusLine) statusLine.textContent = "Could not load tunnel status.";
    });
  }

  const modal = document.getElementById("tunnel-publish-modal");
  const hostInput = document.getElementById("tunnel-publish-subdomain");
  const zoneEl = document.getElementById("tunnel-publish-zone");
  const desc = document.getElementById("tunnel-publish-desc");
  const pubError = document.getElementById("tunnel-publish-error");
  const confirmBtn = document.getElementById("tunnel-publish-confirm");
  let pending = null;

  function zoneName() {
    return (zoneEl?.dataset.zone || zoneEl?.textContent || "").replace(/^\./, "").trim();
  }

  function setZoneLabel(zone) {
    if (!zoneEl) return;
    const clean = (zone || "").replace(/^\./, "").trim();
    zoneEl.dataset.zone = clean;
    zoneEl.textContent = clean ? `.${clean}` : "";
  }

  function composePublishHost() {
    const sub = (hostInput?.value || "").trim().toLowerCase().replace(/\.+$/, "");
    const zone = zoneName();
    if (!sub) throw new Error("Enter a subdomain, for example photos.");
    if (sub.includes(".")) throw new Error("Enter only the subdomain. The zone is not editable.");
    if (!zone) throw new Error("Link a Cloudflare zone first.");
    return `${sub}.${zone}`;
  }

  function closePublish() {
    if (modal) modal.hidden = true;
    pending = null;
  }

  function openPublish(payload) {
    pending = payload;
    if (desc) {
      desc.textContent = `You are about to put ${payload.name || "this service"} on the public internet. Anyone who can find the hostname may reach it.`;
    }
    if (payload.zone) setZoneLabel(payload.zone);
    if (hostInput) hostInput.value = payload.subdomain || "";
    if (pubError) {
      pubError.hidden = true;
      pubError.textContent = "";
    }
    if (modal) modal.hidden = false;
    hostInput?.focus();
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && !modal.hidden) closePublish();
  });

  document.querySelectorAll("[data-publish-close]").forEach((el) => {
    el.addEventListener("click", closePublish);
  });

  document.querySelectorAll(".library-publish-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      openPublish({
        name: btn.dataset.name,
        slug: btn.dataset.slug,
        hostPort: btn.dataset.hostPort,
      });
    });
  });

  document.querySelectorAll(".library-unpublish-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm(`Stop publishing ${btn.dataset.hostname}?`)) return;
      try {
        await jsonFetch("/library/api/tunnel/unpublish/", {
          method: "POST",
          body: JSON.stringify({ hostname: btn.dataset.hostname }),
        });
        window.location.reload();
      } catch (err) {
        window.alert(err.message);
      }
    });
  });

  confirmBtn?.addEventListener("click", async () => {
    if (!pending) return;
    let hostname;
    try {
      hostname = composePublishHost();
    } catch (err) {
      if (pubError) {
        pubError.hidden = false;
        pubError.textContent = err.message;
      }
      return;
    }
    confirmBtn.disabled = true;
    try {
      await jsonFetch("/library/api/tunnel/publish/", {
        method: "POST",
        body: JSON.stringify({
          subdomain: (hostInput?.value || "").trim(),
          hostname,
          slug: pending.slug || "",
          host_port: pending.hostPort || 0,
          service_id: pending.serviceId || null,
        }),
      });
      window.location.reload();
    } catch (err) {
      if (pubError) {
        pubError.hidden = false;
        pubError.textContent = err.message;
      }
    } finally {
      confirmBtn.disabled = false;
    }
  });

  window.ccOpenTunnelPublish = openPublish;
})();
