(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function closeAllMenus() {
    document.querySelectorAll(".service-card-menu").forEach((menu) => {
      const btn = menu.querySelector(".service-kebab");
      const dropdown = menu.querySelector(".service-card-dropdown");
      if (btn) btn.setAttribute("aria-expanded", "false");
      if (dropdown) dropdown.hidden = true;
    });
  }

  document.querySelectorAll(".service-card-menu").forEach((menu) => {
    const btn = menu.querySelector(".service-kebab");
    const dropdown = menu.querySelector(".service-card-dropdown");
    const serviceId = menu.dataset.serviceId;
    if (!btn || !dropdown || !serviceId) return;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const wasOpen = !dropdown.hidden;
      closeAllMenus();
      if (!wasOpen) {
        dropdown.hidden = false;
        btn.setAttribute("aria-expanded", "true");
      }
    });

    dropdown.querySelectorAll("[data-action]").forEach((actionBtn) => {
      actionBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const action = actionBtn.dataset.action;
        closeAllMenus();

        if (action === "visibility") {
          try {
            const resp = await fetch(`/api/services/${serviceId}/visibility/`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrfToken() },
            });
            if (!resp.ok) throw new Error("visibility failed");
            const data = await resp.json();
            const card = menu.closest(".service-card-wrap").querySelector(".service-card");
            if (card) card.classList.toggle("service-card--public", data.is_public);
            actionBtn.textContent = data.is_public ? "Make private" : "Make public";
          } catch (err) {
            console.warn("toggle visibility failed", err);
          }
        }

        if (action === "publish") {
          if (typeof window.ccOpenTunnelPublish === "function") {
            window.ccOpenTunnelPublish({
              name: actionBtn.dataset.name,
              serviceId: actionBtn.dataset.serviceId,
            });
          }
        }

        if (action === "unpublish") {
          try {
            const resp = await fetch("/library/api/tunnel/unpublish/", {
              method: "POST",
              headers: {
                "X-CSRFToken": getCsrfToken(),
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ hostname: actionBtn.dataset.hostname }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || "unpublish failed");
            window.location.reload();
          } catch (err) {
            console.warn("unpublish failed", err);
            window.alert(err.message);
          }
        }

        if (action === "restart") {
          const name = actionBtn.dataset.container;
          if (!name) return;
          if (!confirm(`Restart ${name}? It will be briefly offline.`)) return;
          try {
            const resp = await fetch("/api/docker/restart/", {
              method: "POST",
              headers: {
                "X-CSRFToken": getCsrfToken(),
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ name }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || "restart failed");
          } catch (err) {
            console.warn("restart failed", err);
            window.alert(err.message);
          }
        }

        if (action === "delete") {
          if (!confirm("Delete this card? This cannot be undone.")) return;
          try {
            const resp = await fetch(`/api/services/${serviceId}/delete/`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrfToken() },
            });
            if (!resp.ok) throw new Error("delete failed");
            menu.closest(".service-card-wrap").remove();
          } catch (err) {
            console.warn("delete failed", err);
          }
        }
      });
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".service-card-menu")) closeAllMenus();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllMenus();
  });
})();
