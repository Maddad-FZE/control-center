(function () {
  const navItems = document.querySelectorAll(".settings-nav__item");
  const panes = document.querySelectorAll(".settings-pane");

  function showSection(section) {
    navItems.forEach((item) => {
      const active = item.dataset.section === section;
      item.classList.toggle("is-active", active);
    });
    panes.forEach((pane) => {
      const active = pane.dataset.section === section;
      pane.classList.toggle("is-active", active);
    });
  }

  navItems.forEach((item) => {
    item.addEventListener("click", (e) => {
      const section = item.dataset.section;
      if (!section) return;
      e.preventDefault();
      showSection(section);
      const url = new URL(window.location.href);
      url.searchParams.set("section", section);
      history.replaceState(null, "", url);
      window.dispatchEvent(new Event("cc-wizard-section"));
    });
  });

  const master = document.querySelector("[data-wizard-master]");
  const notify = document.querySelector("[data-wizard-notify]");
  const notifyGroup = document.getElementById("wizard-notify-group");

  function syncWizardNotify() {
    if (!master || !notify) return;
    const on = master.checked;
    notify.disabled = !on;
    notifyGroup?.classList.toggle("is-disabled", !on);
  }

  master?.addEventListener("change", syncWizardNotify);
  syncWizardNotify();

  document.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const field = document.getElementById(btn.dataset.secretToggle);
      if (!field) return;
      const hidden = field.type === "password";
      field.type = hidden ? "text" : "password";
      btn.textContent = hidden ? "Hide" : "Show";
    });
  });

  document.querySelectorAll("[data-secret-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const field = document.getElementById(btn.dataset.secretCopy);
      const value = field ? field.value : "";
      try {
        await navigator.clipboard.writeText(value);
        const prev = btn.textContent;
        btn.textContent = "Copied";
        window.setTimeout(() => {
          btn.textContent = prev;
        }, 1200);
      } catch {
        if (field) {
          field.focus();
          field.select();
        }
      }
    });
  });
})();
