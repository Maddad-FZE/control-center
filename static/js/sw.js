/* Control Center service worker — versioned caches, CSS/JS always revalidated */
const ASSET_VERSION = "__ASSET_VERSION__";
const SHELL_CACHE = `cc-shell-${ASSET_VERSION}`;
const STATIC_CACHE = `cc-static-${ASSET_VERSION}`;
const API_CACHE = `cc-api-${ASSET_VERSION}`;
const LIVE_CACHES = [SHELL_CACHE, STATIC_CACHE, API_CACHE];

const PRECACHE_STATIC = [
  `/static/css/fonts.css?v=${ASSET_VERSION}`,
  `/static/css/theme.css?v=${ASSET_VERSION}`,
  `/static/css/crt.css?v=${ASSET_VERSION}`,
  `/static/css/dashboard.css?v=${ASSET_VERSION}`,
  `/static/js/dashboard-cache.js?v=${ASSET_VERSION}`,
  `/static/js/dashboard.js?v=${ASSET_VERSION}`,
  `/static/js/clock.js?v=${ASSET_VERSION}`,
  `/static/js/user-menu.js?v=${ASSET_VERSION}`,
  "/static/img/favicon.svg",
  "/static/img/service-default.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_STATIC))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !LIVE_CACHES.includes(key)).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

function isDashboardNavigation(request, url) {
  return request.mode === "navigate" && (url.pathname === "/" || url.pathname === "");
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isStyleOrScript(url) {
  return (
    url.pathname.startsWith("/static/css/") ||
    url.pathname.startsWith("/static/js/") ||
    url.pathname === "/sw.js"
  );
}

function isStaticRequest(url) {
  return url.pathname.startsWith("/static/");
}

async function cachePut(cacheName, request, response) {
  if (!response || response.status !== 200) return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response);
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request, { cache: "no-cache" });
    await cachePut(cacheName, request, response.clone());
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw new Error("offline");
  }
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    await cachePut(cacheName, request, response.clone());
    return response;
  } catch {
    return cached || new Response("", { status: 504 });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isDashboardNavigation(request, url)) {
    event.respondWith(
      networkFirst(request, SHELL_CACHE).catch(async () => {
        const cached = await caches.match(request);
        if (cached) return cached;
        return new Response("Offline — no cached dashboard.", {
          status: 503,
          headers: { "Content-Type": "text/plain" },
        });
      })
    );
    return;
  }

  if (isApiRequest(url)) {
    event.respondWith(
      networkFirst(request, API_CACHE).catch(
        () =>
          new Response(JSON.stringify({ offline: true }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          })
      )
    );
    return;
  }

  if (isStyleOrScript(url)) {
    event.respondWith(
      networkFirst(request, STATIC_CACHE).catch(() => new Response("", { status: 504 }))
    );
    return;
  }

  if (isStaticRequest(url)) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
  }
});
