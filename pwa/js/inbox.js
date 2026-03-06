/**
 * Inbox unifiée + vue conversation
 */

var _inboxPage = 1;
var _inboxFilter = "";
var _inboxSearch = "";

async function renderInbox(container) {
  _inboxPage = 1;
  _inboxFilter = "";
  _inboxSearch = "";

  // Check URL filter param
  var hash = window.location.hash;
  if (hash.includes("filter=hot")) _inboxFilter = "hot";

  render(container, [
    '<div class="page-header"><h1>\uD83D\uDCAC Inbox</h1></div>',
    '<div class="search-bar">',
    '  <input type="text" id="inbox-search" class="input" placeholder="Rechercher un prospect...">',
    "</div>",
    '<div class="filter-bar" id="inbox-filters">',
    '  <button class="chip ' + (_inboxFilter === "" ? "active" : "") + '" data-filter="">Tous</button>',
    '  <button class="chip ' + (_inboxFilter === "hot" ? "active" : "") + '" data-filter="hot">\uD83D\uDD25 Chauds</button>',
    '  <button class="chip" data-filter="unread">\uD83D\uDCE9 Non-lus</button>',
    '  <button class="chip" data-filter="niche">\uD83C\uDFAF Niche</button>',
    "</div>",
    '<div id="inbox-list" class="inbox-list"></div>',
    '<div id="inbox-loader" class="loading" style="display:none"><div class="spinner"></div></div>',
  ].join("\n"));

  // Events
  document.getElementById("inbox-search").addEventListener("input", _debounce(function (e) {
    _inboxSearch = e.target.value.trim();
    _inboxPage = 1;
    _loadInbox();
  }, 300));

  document.getElementById("inbox-filters").addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    document.querySelectorAll("#inbox-filters .chip").forEach(function (c) { c.classList.remove("active"); });
    chip.classList.add("active");
    _inboxFilter = chip.dataset.filter || "";
    _inboxPage = 1;
    _loadInbox();
  });

  // Infinite scroll
  var list = document.getElementById("inbox-list");
  list.addEventListener("scroll", function () {
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 50) {
      _inboxPage++;
      _loadInbox(true);
    }
  });

  _loadInbox();
}

async function _loadInbox(append) {
  var list = document.getElementById("inbox-list");
  var loader = document.getElementById("inbox-loader");
  if (!list) return;

  if (!append) list.textContent = "";
  if (loader) loader.style.display = "flex";

  try {
    var params = { page: _inboxPage, per_page: 20 };
    if (_inboxSearch) params.search = _inboxSearch;
    if (_inboxFilter === "hot") params.min_score = 0.8;
    if (_inboxFilter === "unread") params.unread = true;

    var data = await API.getMessages(params);
    var items = data.items || data || [];

    if (!items.length && !append) {
      render(list, '<div class="empty-state"><p>Aucune conversation</p></div>');
      if (loader) loader.style.display = "none";
      return;
    }

    items.forEach(function (item) {
      var el = document.createElement("a");
      el.className = "inbox-item" + (item.unread ? " unread" : "");
      el.href = "#/conversation/" + (item.prospect_id || item.id);

      render(el, [
        '<div class="inbox-avatar">' + esc(item.niche_emoji || "\uD83D\uDC64") + "</div>",
        '<div class="inbox-info">',
        '  <div class="inbox-header-row">',
        '    <span class="inbox-name">' + esc(item.username || item.full_name || "?") + "</span>",
        "    " + scoreBadge(item.score),
        "  </div>",
        '  <div class="inbox-preview">' + esc(_truncate(item.last_message || item.content || "", 50)) + "</div>",
        "</div>",
        '<div class="inbox-meta">',
        '  <span class="inbox-time">' + esc(timeAgo(item.last_message_at || item.sent_at || item.created_at)) + "</span>",
        '  <span class="inbox-niche-badge">' + esc(item.niche_name || "") + "</span>",
        "</div>",
      ].join("\n"));

      list.appendChild(el);
    });
  } catch (e) {
    if (!append) render(list, '<div class="empty-state"><p>Erreur chargement</p></div>');
    showToast(e.message, "error");
  }

  if (loader) loader.style.display = "none";
}

/* ── Conversation ── */

async function renderConversation(container, params) {
  var prospectId = params.id;

  render(container, [
    '<div class="conv-header" id="conv-header">',
    '  <button class="btn btn-ghost" id="conv-back">\u2190</button>',
    '  <div class="conv-title">Chargement...</div>',
    "</div>",
    '<div class="conv-status-bar" id="conv-status"></div>',
    '<div class="conv-messages" id="conv-messages">',
    '  <div class="loading"><div class="spinner"></div></div>',
    "</div>",
    '<div class="conv-actions" id="conv-actions">',
    '  <div class="conv-input-row">',
    '    <input type="text" id="conv-input" class="input" placeholder="Écrire un message...">',
    '    <button class="btn btn-primary" id="conv-send">\u27A4</button>',
    "  </div>",
    '  <div class="conv-quick-actions">',
    '    <button class="btn btn-ghost" id="conv-suggest">\u2728 Suggestion IA</button>',
    '    <button class="btn btn-ghost" id="conv-convert">\u2705 Converti</button>',
    '    <button class="btn btn-ghost btn-danger-text" id="conv-blacklist">\uD83D\uDEAB Blacklist</button>',
    "  </div>",
    "</div>",
  ].join("\n"));

  // Back button
  document.getElementById("conv-back").addEventListener("click", function () {
    navigateTo("#/inbox");
  });

  try {
    var data = await API.getConversation(prospectId);
    var prospect = data.prospect || {};
    var messages = data.messages || data || [];

    // Update header
    var header = document.getElementById("conv-header");
    render(header, [
      '<button class="btn btn-ghost" id="conv-back-2">\u2190</button>',
      '<div class="conv-title">',
      "  <strong>@" + esc(prospect.username || "?") + "</strong> " + scoreBadge(prospect.score),
      "</div>",
      '<a class="btn btn-ghost" href="https://instagram.com/' + esc(prospect.username) + '" target="_blank">\uD83C\uDFAF IG</a>',
    ].join("\n"));
    document.getElementById("conv-back-2").addEventListener("click", function () {
      navigateTo("#/inbox");
    });

    // Status bar
    _renderFunnelBar(prospect.status);

    // Messages
    var msgContainer = document.getElementById("conv-messages");
    msgContainer.textContent = "";

    if (!messages.length) {
      render(msgContainer, '<div class="empty-state"><p>Aucun message</p></div>');
    } else {
      messages.forEach(function (msg) {
        var bubble = document.createElement("div");
        bubble.className = "bubble bubble-" + (msg.direction === "outbound" ? "sent" : "received");

        var contentDiv = document.createElement("div");
        contentDiv.className = "bubble-content";
        contentDiv.textContent = msg.content || "";

        var metaDiv = document.createElement("div");
        metaDiv.className = "bubble-meta";
        metaDiv.textContent = timeAgo(msg.sent_at || msg.created_at);
        if (msg.ab_variant) metaDiv.textContent += " [" + msg.ab_variant + "]";

        bubble.appendChild(contentDiv);
        bubble.appendChild(metaDiv);
        msgContainer.appendChild(bubble);
      });
      msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    // Send message
    var sendBtn = document.getElementById("conv-send");
    var inputEl = document.getElementById("conv-input");

    sendBtn.addEventListener("click", function () {
      _sendMessage(prospectId, inputEl, msgContainer);
    });
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") _sendMessage(prospectId, inputEl, msgContainer);
    });

    // IA suggestion
    document.getElementById("conv-suggest").addEventListener("click", async function () {
      var btn = this;
      btn.disabled = true;
      btn.textContent = "\u2728 Génération...";
      try {
        var lastMsg = messages.length > 0 ? messages[messages.length - 1].content : "";
        var result = await API.suggestResponse(prospectId, lastMsg);
        inputEl.value = result.suggestion || result.content || "";
        inputEl.focus();
      } catch (e) {
        showToast("Erreur IA : " + e.message, "error");
      }
      btn.disabled = false;
      btn.textContent = "\u2728 Suggestion IA";
    });

    // Convert
    document.getElementById("conv-convert").addEventListener("click", async function () {
      try {
        await API.updateProspect(prospectId, { status: "converted" });
        showToast("Prospect converti !", "success");
        _renderFunnelBar("converted");
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    // Blacklist
    document.getElementById("conv-blacklist").addEventListener("click", async function () {
      if (!confirm("Blacklister ce prospect ?")) return;
      try {
        await API.blacklistProspect(prospectId);
        showToast("Prospect blacklisté", "warning");
        navigateTo("#/inbox");
      } catch (e) {
        showToast(e.message, "error");
      }
    });
  } catch (e) {
    render(document.getElementById("conv-messages"), '<div class="empty-state"><p>Erreur : ' + esc(e.message) + "</p></div>");
  }
}

async function _sendMessage(prospectId, inputEl, msgContainer) {
  var content = inputEl.value.trim();
  if (!content) return;

  inputEl.value = "";

  // Optimistic UI
  var bubble = document.createElement("div");
  bubble.className = "bubble bubble-sent";
  var cd = document.createElement("div");
  cd.className = "bubble-content";
  cd.textContent = content;
  var md = document.createElement("div");
  md.className = "bubble-meta";
  md.textContent = "Envoi...";
  bubble.appendChild(cd);
  bubble.appendChild(md);
  msgContainer.appendChild(bubble);
  msgContainer.scrollTop = msgContainer.scrollHeight;

  try {
    await API.sendMessage(prospectId, content);
    md.textContent = "à l'instant";
  } catch (e) {
    md.textContent = "Erreur";
    bubble.classList.add("bubble-error");
    showToast("Erreur envoi", "error");
  }
}

function _renderFunnelBar(currentStatus) {
  var statuses = ["scraped", "scored", "followed", "follow_back", "dm_sent", "replied", "interested", "rdv", "converted"];
  var idx = statuses.indexOf(currentStatus);
  if (idx < 0) idx = 0;
  var pct = ((idx / (statuses.length - 1)) * 100).toFixed(0);

  var bar = document.getElementById("conv-status");
  if (!bar) return;
  render(bar, [
    '<div class="funnel-bar">',
    '  <div class="funnel-fill" style="width:' + pct + '%"></div>',
    "</div>",
    '<span class="funnel-label">' + statusEmoji(currentStatus) + " " + esc(currentStatus) + " (" + pct + "%)</span>",
  ].join("\n"));
}

/* ── Helpers ── */

function _truncate(str, max) {
  if (!str) return "";
  return str.length > max ? str.slice(0, max) + "\u2026" : str;
}

function _debounce(fn, delay) {
  var timer;
  return function () {
    var ctx = this;
    var args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
  };
}
