/**
 * App principal : router SPA + utilitaires + settings
 * Dark Glassmorphism Aurora 2026
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
  var diff = Date.now() - new Date(dateStr).getTime();
  var mins = Math.floor(diff / 60000);
  if (mins < 1) return "\u00E0 l'instant";
  if (mins < 60) return mins + "min";
  var hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h";
  return Math.floor(hours / 24) + "j";
}

function showToast(message, type) {
  type = type || "info";
  var t = document.getElementById("toast");
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
  var pct = (s * 100).toFixed(0);
  if (s >= 0.8) return '<span class="badge badge-hot">\uD83D\uDD25 ' + esc(pct) + "</span>";
  if (s >= 0.6) return '<span class="badge badge-warm">' + esc(pct) + "</span>";
  return '<span class="badge">' + esc(pct) + "</span>";
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

/* ── Nouvelles utilities Aurora ── */

function animateCountUp(el, target, duration) {
  if (!el) return;
  duration = duration || 1200;
  var start = 0;
  var startTime = null;
  var isFloat = String(target).includes(".");

  function step(timestamp) {
    if (!startTime) startTime = timestamp;
    var progress = Math.min((timestamp - startTime) / duration, 1);
    var eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    var current = start + (target - start) * eased;

    if (isFloat) {
      el.textContent = current.toFixed(1) + "%";
    } else {
      el.textContent = Math.round(current).toLocaleString("fr-FR");
    }

    if (progress < 1) requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}

function typeWriter(el, text, speed) {
  if (!el) return;
  speed = speed || 50;
  el.textContent = "";
  var i = 0;

  function type() {
    if (i < text.length) {
      el.textContent += text.charAt(i);
      i++;
      setTimeout(type, speed);
    }
  }

  type();
}

function addRipple(e) {
  var btn = e.currentTarget;
  var circle = document.createElement("span");
  var rect = btn.getBoundingClientRect();
  var size = Math.max(rect.width, rect.height);
  circle.style.width = circle.style.height = size + "px";
  circle.style.left = (e.clientX - rect.left - size / 2) + "px";
  circle.style.top = (e.clientY - rect.top - size / 2) + "px";
  circle.className = "ripple";
  btn.appendChild(circle);
  setTimeout(function () { circle.remove(); }, 600);
}

function showSkeleton(el, count) {
  if (!el) return;
  count = count || 3;
  var html = '<div class="skeleton-container">';
  for (var i = 0; i < count; i++) {
    html += [
      '<div class="skeleton-card">',
      '  <div class="skeleton-circle"></div>',
      '  <div class="skeleton-lines">',
      '    <div class="skeleton-line"></div>',
      '    <div class="skeleton-line"></div>',
      '    <div class="skeleton-line"></div>',
      '  </div>',
      '</div>',
    ].join("");
  }
  html += '</div>';
  render(el, html);
}

function avatarColor(name) {
  if (!name) return "var(--accent-primary)";
  var hash = 0;
  for (var i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  var colors = [
    "#7c3aed", "#06b6d4", "#ec4899", "#f97316",
    "#22c55e", "#3b82f6", "#a855f7", "#14b8a6",
    "#f43f5e", "#8b5cf6", "#0ea5e9", "#d946ef",
  ];
  return colors[Math.abs(hash) % colors.length];
}

function avatarInitials(name) {
  if (!name) return "?";
  var parts = name.replace("@", "").split(/[\s._-]+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.substring(0, 2).toUpperCase();
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
    '<div class="page-header"><h1>\u2699\uFE0F R\u00E9glages</h1></div>',
    '<div class="settings-list">',

    // API Key
    '  <div class="card"><h3>\uD83D\uDD11 API Key</h3>',
    '    <div class="settings-row">',
    '      <input type="password" id="api-key-input" class="input" placeholder="Entrer votre API key" value="' + esc(apiKey) + '">',
    '      <button class="btn btn-primary" id="save-api-key">Sauver</button>',
    "    </div>",
    '    <button class="btn btn-ghost btn-sm" id="copy-api-key" style="margin-top:8px">Copier la cl\u00E9</button>',
    "  </div>",

    // Notifications
    '  <div class="card"><h3>\uD83D\uDD14 Notifications Push</h3>',
    '    <p class="text-secondary" style="margin-bottom:10px">Statut : ' + esc(notifStatus) + "</p>",
    '    <button class="btn btn-primary btn-sm" id="enable-notif"' + (notifStatus === "granted" ? " disabled" : "") + ">",
    (notifStatus === "granted" ? "Activ\u00E9es \u2705" : "Activer les notifications"),
    "    </button>",
    "  </div>",

    // Active hours
    '  <div class="card"><h3>\u23F0 Heures actives</h3>',
    '    <div class="settings-row">',
    '      <label>D\u00E9but</label><select id="hour-start" class="input">' + hours + "</select>",
    '      <label>Fin</label><select id="hour-end" class="input">' + hours + "</select>",
    "    </div>",
    "  </div>",

    // Days off
    '  <div class="card"><h3>\uD83D\uDCC5 Jours OFF</h3>',
    '    <div class="days-toggle" id="days-off">',
    ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map(function (d, i) {
      return '<button class="btn btn-ghost day-btn" data-day="' + i + '">' + d + "</button>";
    }).join(""),
    "    </div>",
    "  </div>",

    // Guide
    '  <div class="card"><h3>\uD83D\uDE80 Guide de d\u00E9marrage</h3>',
    '    <div class="guide-steps">',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">1</div>',
    '        <div class="guide-step-text"><strong>API Key</strong> \u2014 Entrez votre cl\u00E9 dans le champ ci-dessus</div>',
    '      </div>',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">2</div>',
    '        <div class="guide-step-text"><strong>V\u00E9rifier les niches</strong> \u2014 Dashboard \u2192 s\u00E9lectionnez vos niches actives</div>',
    '      </div>',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">3</div>',
    '        <div class="guide-step-text"><strong>Pool comptes</strong> \u2014 Bot \u2192 cr\u00E9ez vos comptes IG (warmup 18j)</div>',
    '      </div>',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">4</div>',
    '        <div class="guide-step-text"><strong>Lancer le bot</strong> \u2014 Bot \u2192 activez le scheduler</div>',
    '      </div>',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">5</div>',
    '        <div class="guide-step-text"><strong>Surveiller l\'inbox</strong> \u2014 R\u00E9pondez aux prospects chauds \uD83D\uDD25</div>',
    '      </div>',
    '      <div class="guide-step">',
    '        <div class="guide-step-num">6</div>',
    '        <div class="guide-step-text"><strong>Convertir</strong> \u2014 Pipeline \u2192 d\u00E9placez vers \u2705 Converti</div>',
    '      </div>',
    '    </div>',
    "  </div>",

    // Version
    '  <div class="card">',
    '    <p class="text-secondary">InstaFarm War Machine v2.0</p>',
    '    <p class="text-secondary">PWA installable \u2022 Dark Aurora</p>',
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
    if (key) { API.setApiKey(key); showToast("API Key sauvegard\u00E9e", "success"); }
  });
  document.getElementById("copy-api-key").addEventListener("click", function () {
    var key = document.getElementById("api-key-input").value;
    if (key) navigator.clipboard.writeText(key).then(function () { showToast("Cl\u00E9 copi\u00E9e", "success"); });
  });
  document.getElementById("enable-notif").addEventListener("click", async function () {
    var ok = await Notifications.requestPermission();
    showToast(ok ? "Notifications activ\u00E9es" : "Erreur activation", ok ? "success" : "error");
  });
  if (hs) hs.addEventListener("change", function () { localStorage.setItem("instafarm_hour_start", hs.value); });
  if (he) he.addEventListener("change", function () { localStorage.setItem("instafarm_hour_end", he.value); });
  document.querySelectorAll(".day-btn").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.classList.toggle("active"); });
  });
}

/* ── Init ── */

document.addEventListener("DOMContentLoaded", function () {
  // Auto-set API key if not configured (redirect to settings)
  if (!API.getApiKey()) {
    window.location.hash = "#/settings";
  }

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
