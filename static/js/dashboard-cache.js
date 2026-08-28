(function () {
  const CACHE_PREFIX = "cc-dash:v1:";
  const MAX_AGE_MS = 24 * 60 * 60 * 1000;

  function saveDashboardCache(key, data) {
    try {
      localStorage.setItem(
        CACHE_PREFIX + key,
        JSON.stringify({ savedAt: Date.now(), data })
      );
    } catch (e) {
      console.warn("dashboard cache save failed", e);
    }
  }

  function loadDashboardCache(key) {
    try {
      const raw = localStorage.getItem(CACHE_PREFIX + key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (Date.now() - parsed.savedAt > MAX_AGE_MS) return null;
      return parsed;
    } catch {
      return null;
    }
  }

  window.dashboardCache = {
    save: saveDashboardCache,
    load: loadDashboardCache,
    hydrateKeys: ["system", "docker", "alerts", "health", "uptime", "widgets"],
    loadAll() {
      const out = {};
      this.hydrateKeys.forEach((key) => {
        const entry = loadDashboardCache(key);
        if (entry) out[key] = entry.data;
      });
      return out;
    },
  };
})();
