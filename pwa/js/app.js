/**
 * App principal : router SPA + utilitaires + settings
 */

/* ── Utilitaires ── */

function esc(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function render(el, htmlStr) {
  el.textContent = "";
  el.appendChild(document.createRange().createContextualFragment(htmlStr));
}

function formatNum(n) {
  return (n || 0).toLocaleString("fr-FR");
}

function formatPct(n) {
  return (n || 0).toFixed(1) + "%";
}

function timeAgo(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return mins + "min";
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h";
  return Math.floor(hours / 24) + "j";
}

function showToast(message, type) {
  type = type || "info";
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.textContent = message;
  t.className = "toast toast-" + type + " toast-show";
  setTimeout(function () { t.classList.remove("toast-show"); }, 3000);
}

function showLoading(el) {
  render(el, '<div class="loading"><div class="spinner"></div></div>');
}

function scoreBadge(score) {
  var s = score || 0;
  if (s >= 0.8) return '<span class="badge badge-hot">\uD83D\uDD25 ' + esc((s * 100).toFixed(0)) + "</span>";
  if (s >= 0.6) return '<span class="badge badge-warm">' + esc((s * 100).toFixed(0)) + "</span>";
  return '<span class="badge">' + esc((s * 100).toFixed(0)) + "</span>";
}

function statusEmoji(status) {
  var map = {
    scraped: "\uD83D\uDCCB", scored: "\uD83C\uDFAF", followed: "\uD83D\uDC41\uFE0F",
    follow_back: "\uD83D\uDD04", dm_sent: "\uD83D\uDCAC", replied: "\uD83D\uDCE9",
    interested: "\uD83D\uDD25", rdv: "\uD83D\uDCC5", converted: "\u2705", lost: "\u274C",
    blacklisted: "\uD83D\uDEAB",
  };
  return map[status] || "\u2753";
}

/* ── Router SPA ── */

var _routes = {};

function registerRoute(path, handler) {
  _routes[path] = handler;
}

function navigateTo(hash) {
  window.location.hash = hash;
}

function _matchRoute(path) {
  for (var route in _routes) {
    var rParts = route.split("/");
    var pParts = path.split("/");
    if (rParts.length !== pParts.length) continue;
    var match = true;
    var params = {};
    for (var i = 0; i < rParts.length; i++) {
      if (rParts[i].charAt(0) === ":") {
        params[rParts[i].slice(1)] = pParts[i];
      } else if (rParts[i] !== pParts[i]) {
        match = false;
        break;
      }
    }
    if (match) return { handler: _routes[route], params: params };
  }
  return null;
}

async function handleRoute() {
  var hash = window.location.hash || "#/";
  var path = hash.slice(1) || "/";
  var container = document.getElementById("page-content");
  var result = _matchRoute(path);

  if (!result) {
    result = { handler: _routes["/"], params: {} };
    path = "/";
  }

  if (result && result.handler) {
    showLoading(container);
    try {
      await result.handler(container, result.params);
    } catch (e) {
      console.error("Route error:", e);
      render(container, '<div class="empty-state"><p>Erreur : ' + esc(e.message) + "</p></div>");
      showToast(e.message, "error");
    }
  }
  _updateNav(path);
}

function _updateNav(path) {
  var nav = document.getElementById("bottom-nav");
  if (!nav) return;
  nav.querySelectorAll(".nav-item").forEach(function (item) {
    var href = item.getAttribute("href") || "";
    var ip = href.slice(1) || "/";
    var active = ip === path || (ip !== "/" && path.startsWith(ip));
    if (path === "/" && ip === "/") active = true;
    item.classList.toggle("active", active);
  });
  nav.style.display = path.startsWith("/conversation") ? "none" : "";
}

/* ── Settings Page ── */

function renderSettings(container) {
  var apiKey = API.getApiKey();
  var notifStatus = Notifications.getPermissionStatus();

  var hours = "";
  for (var i = 0; i < 24; i++) {
    var pad = String(i).padStart(2, "0");
    hours += '<option value="' + i + '">' + pad + "h</option>";
  }

  render(container, [
    '<div class="page-header"><h1>\u2699\uFE0F Réglages</h1></div>',
    '<div class="settings-list">',
    '  <div class="card"><h3>API Key</h3>',
    '    <div class="settings-row">',
    '      <input type="text" id="api-key-input" class="input" placeholder="Entrer votre API key" value="' + esc(apiKey) + '">',
    '      <button class="btn btn-primary" id="save-api-key">Sauver</button>',
    "    </div>",
    '    <button class="btn btn-ghost" id="copy-api-key">Copier la clé</button>',
    "  </div>",
    '  <div class="card"><h3>Notifications Push</h3>',
    '    <p class="text-secondary">Statut : ' + esc(notifStatus) + "</p>",
    '    <button class="btn btn-primary" id="enable-notif"' + (notifStatus === "granted" ? " disabled" : "") + ">",
    (notifStatus === "granted" ? "Activées \u2705" : "Activer les notifications"),
    "    </button>",
    "  </div>",
    '  <div class="card"><h3>Heures actives</h3>',
    '    <div class="settings-row">',
    "      <label>Début</label><select id=\"hour-start\" class=\"input\">" + hours + "</select>",
    "      <label>Fin</label><select id=\"hour-end\" class=\"input\">" + hours + "</select>",
    "    </div>",
    "  </div>",
    '  <div class="card"><h3>Jours OFF</h3>',
    '    <div class="days-toggle" id="days-off">',
    ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map(function (d, i) {
      return '<button class="btn btn-ghost day-btn" data-day="' + i + '">' + d + "</button>";
    }).join(""),
    "    </div>",
    "  </div>",
    '  <div class="card"><h3>Application</h3>',
    '    <p class="text-secondary">InstaFarm War Machine v1.0</p>',
    '    <p class="text-secondary">PWA installable</p>',
    "  </div>",
    "</div>",
  ].join("\n"));

  // Restore hour selects
  var hs = document.getElementById("hour-start");
  var he = document.getElementById("hour-end");
  if (hs) hs.value = localStorage.getItem("instafarm_hour_start") || "9";
  if (he) he.value = localStorage.getItem("instafarm_hour_end") || "20";

  // Events
  document.getElementById("save-api-key").addEventListener("click", function () {
    var key = document.getElementById("api-key-input").value.trim();
    if (key) { API.setApiKey(key); showToast("API Key sauvegardée", "success"); }
  });
  document.getElementById("copy-api-key").addEventListener("click", function () {
    var key = document.getElementById("api-key-input").value;
    if (key) navigator.clipboard.writeText(key).then(function () { showToast("Clé copiée", "success"); });
  });
  document.getElementById("enable-notif").addEventListener("click", async function () {
    var ok = await Notifications.requestPermission();
    showToast(ok ? "Notifications activées" : "Erreur activation", ok ? "success" : "error");
  });
  if (hs) hs.addEventListener("change", function () { localStorage.setItem("instafarm_hour_start", hs.value); });
  if (he) he.addEventListener("change", function () { localStorage.setItem("instafarm_hour_end", he.value); });
  document.querySelectorAll(".day-btn").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.classList.toggle("active"); });
  });
}

/* ── Init ── */

document.addEventListener("DOMContentLoaded", function () {
  registerRoute("/", renderDashboard);
  registerRoute("/inbox", renderInbox);
  registerRoute("/conversation/:id", renderConversation);
  registerRoute("/pipeline", renderPipeline);
  registerRoute("/control", renderControl);
  registerRoute("/settings", renderSettings);

  window.addEventListener("hashchange", handleRoute);

  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("message", function (e) {
      if (e.data && e.data.type === "navigate") window.location.hash = e.data.url;
    });
    navigator.serviceWorker.register("/sw.js").catch(console.error);
  }

  Notifications.init();
  handleRoute();
});
