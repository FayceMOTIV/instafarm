const CACHE_NAME = "instafarm-v1";
const ASSETS_TO_CACHE = [
  "/",
  "/css/app.css",
  "/js/app.js",
  "/js/api.js",
  "/js/dashboard.js",
  "/js/inbox.js",
  "/js/pipeline.js",
  "/js/control.js",
  "/js/notifications.js",
  "/manifest.json",
];

// Install : cache assets
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting();
});

// Activate : clean old caches
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch : network-first, fallback cache
self.addEventListener("fetch", (e) => {
  // Skip API calls (toujours reseau)
  if (e.request.url.includes("/api/") || e.request.url.includes("/admin/")) {
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});

// Push notifications
self.addEventListener("push", (e) => {
  const data = e.data ? e.data.json() : {};
  const level = data.level || "info"; // urgent | normal | info

  const vibrationPatterns = {
    urgent: [200, 100, 200, 100, 200],
    normal: [100, 50, 100],
    info: [],
  };

  const icons = { urgent: "🔴", normal: "🟡", info: "🟢" };

  e.waitUntil(
    self.registration.showNotification(data.title || "InstaFarm", {
      body: data.body || "",
      icon: "/manifest.json",
      badge: "/manifest.json",
      tag: data.tag || "instafarm",
      data: { url: data.url || "/", prospect_id: data.prospect_id },
      vibrate: vibrationPatterns[level] || [],
    })
  );
});

// Click notification → ouvre la bonne conversation
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";

  e.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin)) {
          client.focus();
          client.postMessage({ type: "navigate", url });
          return;
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
