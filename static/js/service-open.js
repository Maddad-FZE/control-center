(function () {
  const STORAGE_KEY = "cc:open-new-tab";

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function isGuest() {
    return !getCsrfToken();
  }

  function readIds() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(raw) ? raw.map(Number).filter(Number.isFinite) : [];
    } catch {
      return [];
    }
  }

  function writeIds(ids) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  }

  function prefersNewTab(serviceId) {
    return readIds().includes(Number(serviceId));
  }

  function setPrefLocal(serviceId, enabled) {
    const id = Number(serviceId);
    const ids = new Set(readIds());
    if (enabled) ids.add(id);
    else ids.delete(id);
    writeIds([...ids]);
  }

  async function setPrefRemote(serviceId, enabled) {
    const resp = await fetch(`/api/services/${serviceId}/open-pref/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ open_in_new_tab: enabled }),
    });
    if (!resp.ok) throw new Error("pref failed");
    return resp.json();
  }

  function applyGuestCardHrefs() {
    if (!isGuest()) return;
    document.querySelectorAll("[data-external-href][data-view-href][data-service-id]").forEach((node) => {
      if (node.closest(".service-card-dropdown")) return;
      const id = node.dataset.serviceId;
      const external = node.dataset.externalHref;
      const viewHref = node.dataset.viewHref;
      if (prefersNewTab(id)) {
        node.setAttribute("href", external);
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener");
      } else {
        node.setAttribute("href", viewHref);
        node.removeAttribute("target");
        node.removeAttribute("rel");
      }
    });
  }

  function bindAlwaysToggle() {
    const btn = document.getElementById("overlay-always-btn");
    const root = document.querySelector(".service-overlay");
    if (!btn || !root) return;
    const serviceId = root.dataset.serviceId;
    const sync = (enabled) => {
      btn.setAttribute("aria-pressed", enabled ? "true" : "false");
      root.dataset.openNewTab = enabled ? "1" : "0";
    };
    if (isGuest()) sync(prefersNewTab(serviceId));
    btn.addEventListener("click", async () => {
      const next = btn.getAttribute("aria-pressed") !== "true";
      try {
        if (isGuest()) setPrefLocal(serviceId, next);
        else await setPrefRemote(serviceId, next);
        sync(next);
        if (next) {
          const href = root.dataset.externalHref;
          if (href) window.open(href, "_blank", "noopener");
        }
      } catch (err) {
        console.warn("open pref failed", err);
      }
    });
  }

  applyGuestCardHrefs();
  bindAlwaysToggle();
})();
