/* Control Center service worker — offline shell + API cache fallback */
const SHELL_CACHE = "cc-shell-v1";
const STATIC_CACHE = "cc-static-v1";
const API_CACHE = "cc-api-v1";

const PRECACHE_STATIC = [
  "/static/css/fonts.css",
  "/static/css/theme.css",
  "/static/css/crt.css",
  "/static/css/dashboard.css",
  "/static/js/dashboard-cache.js",
  "/static/js/dashboard.js",
  "/static/js/user-menu.js",
  "/static/img/favicon.svg",
  "/static/img/service-default.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE_STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => ![SHELL_CACHE, STATIC_CACHE, API_CACHE].includes(key))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

function isDashboardNavigation(request, url) {
  return request.mode === "navigate" && (url.pathname === "/" || url.pathname === "");
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isStaticRequest(url) {
  return url.pathname.startsWith("/static/");
}

async function cachePut(cacheName, request, response) {
  if (!response || response.status !== 200) return;
  const cache = await caches.open(cacheName);
  await cache.put(request, response);
}

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    await cachePut(SHELL_CACHE, request, response.clone());
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    const root = await caches.match("/");
    if (root) return root;
    return new Response("Offline — no cached dashboard.", {
      status: 503,
      headers: { "Content-Type": "text/plain" },
    });
  }
}

async function networkFirstApi(request) {
  try {
    const response = await fetch(request);
    await cachePut(API_CACHE, request, response.clone());
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw new Error("offline");
  }
}

async function cacheFirstStatic(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    await cachePut(STATIC_CACHE, request, response.clone());
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
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  if (isApiRequest(url)) {
    event.respondWith(
      networkFirstApi(request).catch(() =>
        new Response(JSON.stringify({ offline: true }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        })
      )
    );
    return;
  }

  if (isStaticRequest(url)) {
    event.respondWith(cacheFirstStatic(request));
  }
});
