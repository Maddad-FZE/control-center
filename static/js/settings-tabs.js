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
    });
  });
})();
