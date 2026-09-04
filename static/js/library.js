(function () {
  const typeFilter = document.getElementById("library-type-filter");
  const categoryFilter = document.getElementById("library-category-filter");
  const installedFilter = document.getElementById("library-installed-filter");
  const searchInput = document.getElementById("library-search");
  const emptyEl = document.getElementById("library-empty");
  const cards = document.querySelectorAll(".library-card");

  function cardSearchText(card) {
    return [
      card.dataset.slug,
      card.dataset.category,
      card.dataset.type,
      card.querySelector(".library-card__name")?.textContent,
      card.querySelector(".library-card__tagline")?.textContent,
    ]
      .join(" ")
      .toLowerCase();
  }

  function applyFilters() {
    const typeVal = typeFilter ? typeFilter.value : "";
    const catVal = categoryFilter ? categoryFilter.value : "";
    const instVal = installedFilter ? installedFilter.value : "";
    const query = (searchInput?.value || "").trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const typeMatch = !typeVal || card.dataset.type === typeVal;
      const catMatch = !catVal || card.dataset.category === catVal;
      const isInstalled = card.dataset.installed === "1" || card.dataset.status === "installing";
      const instMatch = !instVal || (instVal === "1" ? isInstalled : !isInstalled);
      const searchMatch = !query || cardSearchText(card).includes(query);
      const show = typeMatch && catMatch && instMatch && searchMatch;
      card.classList.toggle("hidden-by-filter", !show);
      if (show) visible += 1;
    });
    if (emptyEl) emptyEl.hidden = visible > 0;
  }

  if (typeFilter) typeFilter.addEventListener("change", applyFilters);
  if (categoryFilter) categoryFilter.addEventListener("change", applyFilters);
  if (installedFilter) installedFilter.addEventListener("change", applyFilters);
  if (searchInput) searchInput.addEventListener("input", applyFilters);

  const params = new URLSearchParams(window.location.search);
  const q = params.get("q") || params.get("search") || "";
  if (searchInput && q) {
    searchInput.value = q;
  }
  applyFilters();

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  const installModal = document.getElementById("install-progress-modal");
  const installDesc = document.getElementById("install-progress-desc");
  const credModal = document.getElementById("install-credentials-modal");
  const credForm = document.getElementById("install-credentials-form");
  const credError = document.getElementById("install-credentials-error");
  let pendingInstall = null;

  function showInstallModal(name) {
    if (!installModal) return;
    if (installDesc) installDesc.textContent = `Installing ${name}. Please wait…`;
    installModal.hidden = false;
  }

  function hideInstallModal() {
    if (installModal) installModal.hidden = true;
  }

  function showCredentialsError(message) {
    if (!credError) return;
    credError.textContent = message;
    credError.hidden = !message;
  }

  function validateCredentials(user, password) {
    if (!user) return "Admin username is required.";
    if (user.length > 64 || !/^[A-Za-z0-9._@-]+$/.test(user)) {
      return "Admin username may only use letters, numbers, dots, underscores, @, and hyphens.";
    }
    if (password.length < 10) return "Admin password must be at least 10 characters.";
    if (password.length > 128) return "Admin password is too long.";
    if (password.toLowerCase() === user.toLowerCase()) {
      return "Admin password must be different from the username.";
    }
    return "";
  }

  function openCredentialsModal(slug, name, btn) {
    pendingInstall = { slug, name, btn };
    showCredentialsError("");
    const user = document.getElementById("install-admin-user");
    const pass = document.getElementById("install-admin-password");
    if (user && !user.value) user.value = "admin";
    if (pass) {
      pass.value = "";
      pass.type = "password";
    }
    const toggle = credModal?.querySelector("[data-secret-toggle]");
    if (toggle) toggle.textContent = "Show";
    if (credModal) credModal.hidden = false;
    pass?.focus();
  }

  function closeCredentialsModal() {
    if (credModal) credModal.hidden = true;
    pendingInstall = null;
  }

  credModal?.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", closeCredentialsModal);
  });

  credModal?.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const field = document.getElementById(btn.dataset.secretToggle);
      if (!field) return;
      const hidden = field.type === "password";
      field.type = hidden ? "text" : "password";
      btn.textContent = hidden ? "Hide" : "Show";
    });
  });

  const modal = document.getElementById("uninstall-modal");
  const modalDesc = document.getElementById("uninstall-modal-desc");
  const removeDataWrap = document.getElementById("uninstall-data-wrap");
  const removeDataInput = document.getElementById("uninstall-remove-data");
  const confirmBtn = document.getElementById("uninstall-confirm-btn");
  let pendingUninstall = null;

  function openModal(type, slug, name, managed) {
    pendingUninstall = { type, slug, managed };
    let desc = `Remove ${name} from your homelab?`;
    if (type === "service" && !managed) {
      desc +=
        " This container was not created by Control Center — uninstall will stop and remove it.";
    }
    modalDesc.textContent = desc;
    if (removeDataWrap) {
      removeDataWrap.hidden = type !== "service";
    }
    if (removeDataInput) removeDataInput.checked = true;
    modal.hidden = false;
  }

  function closeModal() {
    modal.hidden = true;
    pendingUninstall = null;
  }

  modal?.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  confirmBtn?.addEventListener("click", async () => {
    if (!pendingUninstall) return;
    confirmBtn.disabled = true;
    const { type, slug } = pendingUninstall;
    try {
      let url;
      let body;
      if (type === "addon") {
        url = `/library/api/addons/${slug}/toggle/`;
        body = null;
      } else {
        url = `/library/api/services/${slug}/uninstall/`;
        const removeData = removeDataInput?.checked ? "1" : "0";
        body = new URLSearchParams({ remove_data: removeData });
      }
      const resp = await fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          ...(body ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
        },
        body,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Uninstall failed");
      window.location.reload();
    } catch (e) {
      console.warn("uninstall failed", e);
      confirmBtn.disabled = false;
    }
  });

  document.querySelectorAll(".library-uninstall-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".library-card");
      const name = card?.querySelector(".library-card__name")?.textContent || btn.dataset.slug;
      const managed = card?.dataset.managed !== "0";
      openModal(btn.dataset.type, btn.dataset.slug, name, managed);
    });
  });

  async function pollInstall(slug) {
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const resp = await fetch(`/library/api/services/${slug}/status/`);
      const data = await resp.json();
      if (data.status === "running") {
        hideInstallModal();
        window.location.reload();
        return;
      }
      if (data.status === "error") {
        hideInstallModal();
        alert(data.error || "Install failed");
        window.location.reload();
        return;
      }
    }
    hideInstallModal();
    window.location.reload();
  }

  document.querySelectorAll(".library-restart-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const slug = btn.dataset.slug;
      const name = btn.dataset.name || slug;
      if (!slug) return;
      if (!window.confirm(`Restart ${name}? It will be briefly offline.`)) return;
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Restarting…";
      try {
        const resp = await fetch(`/library/api/services/${slug}/restart/`, {
          method: "POST",
          headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || "Restart failed");
        btn.textContent = "Restarted";
        window.setTimeout(() => {
          btn.disabled = false;
          btn.textContent = original;
        }, 1500);
      } catch (e) {
        window.alert(e.message || "Restart failed");
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });

  async function startServiceInstall(slug, name, btn, body) {
    btn.disabled = true;
    btn.textContent = "Installing…";
    showInstallModal(name);
    try {
      const headers = { "X-CSRFToken": getCsrfToken() };
      let payload;
      if (body) {
        headers["Content-Type"] = "application/json";
        payload = JSON.stringify(body);
      }
      const resp = await fetch(`/library/api/services/${slug}/install/`, {
        method: "POST",
        headers,
        body: payload,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Install failed");
      await pollInstall(slug);
    } catch (e) {
      console.warn("install failed", e);
      hideInstallModal();
      btn.disabled = false;
      btn.textContent = "Install";
      alert(e.message || "Install failed");
    }
  }

  credForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!pendingInstall) return;
    const user = (document.getElementById("install-admin-user")?.value || "").trim();
    const password = document.getElementById("install-admin-password")?.value || "";
    const error = validateCredentials(user, password);
    if (error) {
      showCredentialsError(error);
      return;
    }
    const { slug, name, btn } = pendingInstall;
    if (credModal) credModal.hidden = true;
    pendingInstall = null;
    await startServiceInstall(slug, name, btn, {
      admin_user: user,
      admin_password: password,
    });
  });

  document.querySelectorAll(".library-install-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const type = btn.dataset.type;
      const slug = btn.dataset.slug;
      if (!slug) return;
      const card = btn.closest(".library-card");
      const name = card?.querySelector(".library-card__name")?.textContent || slug;
      if (type === "addon") {
        btn.disabled = true;
        btn.textContent = "Enabling…";
        try {
          const resp = await fetch(`/library/api/addons/${slug}/toggle/`, {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.error || "Install failed");
          window.location.reload();
        } catch (e) {
          console.warn("install failed", e);
          btn.disabled = false;
          btn.textContent = "Install";
          alert(e.message || "Install failed");
        }
        return;
      }
      if (btn.dataset.credentials === "1") {
        openCredentialsModal(slug, name, btn);
        return;
      }
      await startServiceInstall(slug, name, btn, null);
    });
  });

  document.querySelectorAll(".library-card[data-status='installing']").forEach((card) => {
    const slug = card.dataset.slug;
    if (card.dataset.type === "service" && slug) {
      const name = card.querySelector(".library-card__name")?.textContent || slug;
      showInstallModal(name);
      pollInstall(slug);
    }
  });

  const notesEditor = document.getElementById("library-notes-editor");
  const notesStatus = document.getElementById("library-notes-status");
  let notesTimer = null;
  let notesInFlight = false;
  let notesQueued = false;
  let lastSaved = notesEditor ? notesEditor.innerHTML : "";

  function setNotesStatus(text) {
    if (notesStatus) notesStatus.textContent = text;
  }

  function notesBody() {
    return notesEditor ? notesEditor.innerHTML : "";
  }

  async function saveNotes(opts) {
    if (!notesEditor) return;
    const immediate = opts && opts.immediate;
    const body = notesBody();
    if (body === lastSaved) {
      if (!notesInFlight) setNotesStatus(lastSaved ? "Saved" : "");
      return;
    }
    if (notesInFlight) {
      notesQueued = true;
      return;
    }
    notesInFlight = true;
    setNotesStatus("Saving…");
    try {
      const resp = await fetch("/library/api/notes/", {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/json",
        },
        keepalive: !!immediate,
        body: JSON.stringify({ body }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Save failed");
      lastSaved = body;
      setNotesStatus("Saved");
    } catch (e) {
      console.warn("notes save failed", e);
      setNotesStatus("Save failed");
    } finally {
      notesInFlight = false;
      if (notesQueued) {
        notesQueued = false;
        saveNotes();
      }
    }
  }

  function scheduleNotesSave() {
    setNotesStatus("Saving…");
    clearTimeout(notesTimer);
    notesTimer = setTimeout(() => saveNotes(), 180);
  }

  document.querySelectorAll(".library-notes-fmt").forEach((btn) => {
    btn.addEventListener("mousedown", (event) => event.preventDefault());
    btn.addEventListener("click", () => {
      if (!notesEditor) return;
      notesEditor.focus();
      const cmd = btn.dataset.cmd;
      const value = btn.dataset.value || null;
      document.execCommand(cmd, false, value);
      scheduleNotesSave();
    });
  });

  ["input", "paste", "keyup"].forEach((eventName) => {
    notesEditor?.addEventListener(eventName, scheduleNotesSave);
  });
  notesEditor?.addEventListener("blur", () => saveNotes({ immediate: true }));
  window.addEventListener("pagehide", () => saveNotes({ immediate: true }));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveNotes({ immediate: true });
  });
})();
