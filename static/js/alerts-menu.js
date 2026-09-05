(function () {
  const menu = document.getElementById("alerts-menu");
  const trigger = document.getElementById("alerts-bell");
  const dropdown = document.getElementById("alerts-dropdown");
  const list = document.getElementById("alerts-panel");
  const badge = document.getElementById("alerts-badge");
  const ackBtn = document.getElementById("ack-all-btn");
  if (!menu || !trigger || !dropdown || !list) return;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function formatRelativeTime(iso) {
    const then = new Date(iso);
    const diff = Math.floor((Date.now() - then.getTime()) / 1000);
    if (Number.isNaN(diff)) return "";
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  function groupAlerts(alerts) {
    const grouped = [];
    alerts.forEach((a) => {
      const last = grouped[grouped.length - 1];
      if (last && last.title === a.title && last.level === a.level) {
        last.count += 1;
        last.created_at = a.created_at;
        last.acknowledged = last.acknowledged && a.acknowledged;
      } else {
        grouped.push({ ...a, count: 1 });
      }
    });
    return grouped;
  }

  function closeUserMenu() {
    const userMenu = document.getElementById("user-menu");
    const userTrigger = document.getElementById("user-menu-trigger");
    const userDropdown = document.getElementById("user-menu-dropdown");
    if (userTrigger) userTrigger.setAttribute("aria-expanded", "false");
    if (userDropdown) userDropdown.hidden = true;
    userMenu?.classList.remove("is-open");
  }

  function closeMenu() {
    trigger.setAttribute("aria-expanded", "false");
    dropdown.hidden = true;
    menu.classList.remove("is-open");
  }

  function openMenu() {
    closeUserMenu();
    trigger.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;
    menu.classList.add("is-open");
    refreshAlerts();
  }

  function render(data) {
    const alerts = data?.alerts || [];
    const unack = alerts.filter((a) => !a.acknowledged).length;
    if (badge) {
      badge.hidden = unack === 0;
      badge.textContent = unack;
    }
    trigger.setAttribute("aria-label", unack ? `${unack} unacknowledged alerts` : "Alerts");
    if (!alerts.length) {
      list.innerHTML = `<div class="stat-label">No recent alerts.</div>`;
      return;
    }
    const grouped = groupAlerts(alerts.slice(0, 30));
    list.innerHTML = grouped
      .slice(0, 12)
      .map((a) => {
        const icon = a.level === "error" ? "!" : a.level === "success" ? "✓" : "·";
        const countSuffix = a.count > 1 ? ` <span class="alert-count">×${a.count}</span>` : "";
        const when = a.created_at ? formatRelativeTime(a.created_at) : "";
        return `
        <div class="alert-item ${a.level}${a.acknowledged ? " acknowledged" : ""}">
          <span class="alert-icon" aria-hidden="true">${icon}</span>
          <span class="alert-text">${escapeHtml(a.title)}${countSuffix}</span>
          <span class="alert-time">${when}</span>
        </div>`;
      })
      .join("");
  }

  async function refreshAlerts() {
    try {
      const resp = await fetch("/api/alerts/");
      if (!resp.ok) throw new Error("alerts failed");
      render(await resp.json());
    } catch {
      if (!list.innerHTML.trim()) {
        list.innerHTML = `<div class="stat-label">No recent alerts.</div>`;
      }
    }
  }

  async function ackAll() {
    if (ackBtn) ackBtn.disabled = true;
    try {
      const resp = await fetch("/api/alerts/ack/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({}),
      });
      if (!resp.ok) throw new Error("ack failed");
      await refreshAlerts();
    } catch (e) {
      console.warn("ack all failed", e);
    } finally {
      if (ackBtn) ackBtn.disabled = false;
    }
  }

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    if (dropdown.hidden) openMenu();
    else closeMenu();
  });

  document.addEventListener("click", function (e) {
    if (!menu.contains(e.target)) closeMenu();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMenu();
  });

  ackBtn?.addEventListener("click", function (e) {
    e.stopPropagation();
    ackAll();
  });

  window.addEventListener("cc-alerts-refresh", refreshAlerts);

  window.ccAlertsMenu = {
    open: openMenu,
    close: closeMenu,
    render,
    refresh: refreshAlerts,
  };
})();
