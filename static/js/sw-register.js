(function () {
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((reg) => reg.update())
      .catch((err) => console.warn("service worker registration failed", err));
  });
})();
