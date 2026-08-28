(function () {
  const typeFilter = document.getElementById("library-type-filter");
  const categoryFilter = document.getElementById("library-category-filter");
  const cards = document.querySelectorAll(".library-card");

  function applyFilters() {
    const typeVal = typeFilter ? typeFilter.value : "";
    const catVal = categoryFilter ? categoryFilter.value : "";
    cards.forEach((card) => {
      const typeMatch = !typeVal || card.dataset.type === typeVal;
      const catMatch = !catVal || card.dataset.category === catVal;
      card.classList.toggle("hidden-by-filter", !typeMatch || !catMatch);
    });
  }

  if (typeFilter) typeFilter.addEventListener("change", applyFilters);
  if (categoryFilter) categoryFilter.addEventListener("change", applyFilters);

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  document.querySelectorAll(".library-copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = document.getElementById(btn.dataset.copyTarget);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent);
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => {
          btn.textContent = original;
        }, 1500);
      } catch (e) {
        console.warn("copy failed", e);
      }
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
    if (removeDataInput) removeDataInput.checked = false;
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
        window.location.reload();
        return;
      }
      if (data.status === "error") {
        alert(data.error || "Install failed");
        window.location.reload();
        return;
      }
    }
    window.location.reload();
  }

  document.querySelectorAll(".library-install-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const type = btn.dataset.type;
      const slug = btn.dataset.slug;
      if (!slug) return;
      btn.disabled = true;
      btn.textContent = type === "addon" ? "Enabling…" : "Installing…";
      try {
        const url =
          type === "addon"
            ? `/library/api/addons/${slug}/toggle/`
            : `/library/api/services/${slug}/install/`;
        const resp = await fetch(url, {
          method: "POST",
          headers: { "X-CSRFToken": getCsrfToken() },
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Install failed");
        if (type === "service") {
          await pollInstall(slug);
        } else {
          window.location.reload();
        }
      } catch (e) {
        console.warn("install failed", e);
        btn.disabled = false;
        btn.textContent = "Install";
        alert(e.message || "Install failed");
      }
    });
  });

  document.querySelectorAll(".library-card[data-status='installing']").forEach((card) => {
    const slug = card.dataset.slug;
    if (card.dataset.type === "service" && slug) {
      pollInstall(slug);
    }
  });
})();
