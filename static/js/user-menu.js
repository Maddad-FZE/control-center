(function () {
  const menu = document.getElementById("user-menu");
  const trigger = document.getElementById("user-menu-trigger");
  const dropdown = document.getElementById("user-menu-dropdown");
  if (!menu || !trigger || !dropdown) return;

  function closeMenu() {
    trigger.setAttribute("aria-expanded", "false");
    dropdown.hidden = true;
    menu.classList.remove("is-open");
  }

  function openMenu() {
    trigger.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;
    menu.classList.add("is-open");
  }

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    if (dropdown.hidden) {
      document.getElementById("alerts-menu")?.classList.remove("is-open");
      const alertsDrop = document.getElementById("alerts-dropdown");
      const alertsBell = document.getElementById("alerts-bell");
      if (alertsDrop) alertsDrop.hidden = true;
      if (alertsBell) alertsBell.setAttribute("aria-expanded", "false");
      openMenu();
    } else {
      closeMenu();
    }
  });

  document.addEventListener("click", function (e) {
    if (!menu.contains(e.target)) {
      closeMenu();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeMenu();
    }
  });
})();
