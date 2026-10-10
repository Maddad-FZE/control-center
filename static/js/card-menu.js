(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function dropdownFor(menu) {
    return menu._ccDropdown || menu.querySelector(".service-card-dropdown");
  }

  function restoreDropdown(menu) {
    const dropdown = dropdownFor(menu);
    if (!dropdown) return;
    dropdown.hidden = true;
    dropdown.classList.remove("is-portaled");
    dropdown.style.top = "";
    dropdown.style.left = "";
    dropdown.style.right = "";
    dropdown.style.maxHeight = "";
    if (dropdown.parentElement !== menu) {
      menu.appendChild(dropdown);
    }
  }

  function placeDropdown(btn, dropdown) {
    const rect = btn.getBoundingClientRect();
    const gap = 4;
    const margin = 8;
    dropdown.style.left = `${rect.left}px`;
    dropdown.style.top = `${rect.bottom + gap}px`;
    dropdown.style.right = "auto";
    const box = dropdown.getBoundingClientRect();
    let top = rect.bottom + gap;
    let left = rect.left;
    if (top + box.height > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - box.height - gap);
    }
    if (left + box.width > window.innerWidth - margin) {
      left = Math.max(margin, rect.right - box.width);
    }
    dropdown.style.top = `${top}px`;
    dropdown.style.left = `${left}px`;
    dropdown.style.maxHeight = `${Math.max(96, window.innerHeight - top - margin)}px`;
  }

  function refreshCardGroups() {
    window.dispatchEvent(new Event("cc-cards-changed"));
  }

  function takeCardWrap(menu) {
    restoreDropdown(menu);
    const wrap = menu.closest(".service-card-wrap");
    if (!wrap) return null;
    const parent = wrap.parentNode;
    const next = wrap.nextSibling;
    wrap.remove();
    refreshCardGroups();
    return { wrap, parent, next };
  }

  function putCardWrap(saved) {
    if (!saved?.wrap || !saved.parent) return;
    saved.parent.insertBefore(saved.wrap, saved.next);
    refreshCardGroups();
  }

  function closeAllMenus() {
    document.querySelectorAll(".service-card-menu").forEach((menu) => {
      const btn = menu.querySelector(".service-kebab");
      if (btn) btn.setAttribute("aria-expanded", "false");
      restoreDropdown(menu);
    });
  }

  document.querySelectorAll(".service-card-menu").forEach((menu) => {
    const btn = menu.querySelector(".service-kebab");
    const dropdown = menu.querySelector(".service-card-dropdown");
    const serviceId = menu.dataset.serviceId;
    if (!btn || !dropdown || !serviceId) return;
    menu._ccDropdown = dropdown;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const wasOpen = !dropdown.hidden && dropdown.classList.contains("is-portaled");
      closeAllMenus();
      if (!wasOpen) {
        document.body.appendChild(dropdown);
        dropdown.classList.add("is-portaled");
        dropdown.hidden = false;
        btn.setAttribute("aria-expanded", "true");
        placeDropdown(btn, dropdown);
      }
    });

    dropdown.querySelectorAll("[data-action]").forEach((actionBtn) => {
      actionBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const action = actionBtn.dataset.action;
        closeAllMenus();

        if (action === "troubleshoot") {
          if (typeof window.ccOpenServiceTroubleshoot === "function") {
            window.ccOpenServiceTroubleshoot({
              serviceId,
              name: actionBtn.dataset.name || "",
            });
          }
        }

        if (action === "explore") {
          if (typeof window.ccOpenExplore === "function") {
            window.ccOpenExplore({
              serviceId,
              name: actionBtn.dataset.name || "",
            });
          }
        }

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
            await window.ccDialog.alert(err.message, { title: "Unpublish" });
          }
        }

        if (action === "restart") {
          const name = actionBtn.dataset.container;
          if (!name) return;
          const restartOk = await window.ccDialog.confirm(
            `Restart ${name}? It will be briefly offline.`,
            { title: "Restart", confirmLabel: "Restart" },
          );
          if (!restartOk) return;
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
            await window.ccDialog.alert(err.message, { title: "Restart" });
          }
        }

        if (action === "delete") {
          const deleteOk = await window.ccDialog.confirm(
            "Delete this card? This cannot be undone.",
            { title: "Delete card", confirmLabel: "Delete", danger: true },
          );
          if (!deleteOk) return;
          const saved = takeCardWrap(menu);
          try {
            const resp = await fetch(`/api/services/${serviceId}/delete/`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrfToken() },
            });
            if (!resp.ok) throw new Error("delete failed");
          } catch (err) {
            putCardWrap(saved);
            console.warn("delete failed", err);
            await window.ccDialog.alert(err.message || "Could not delete this card.", {
              title: "Delete card",
            });
          }
        }
      });
    });
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".service-card-menu, .service-card-dropdown")) return;
    closeAllMenus();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllMenus();
  });

  window.addEventListener(
    "scroll",
    (e) => {
      if (e.target && e.target.closest && e.target.closest(".service-card-dropdown")) return;
      closeAllMenus();
    },
    true,
  );
  window.addEventListener("resize", closeAllMenus);
})();
