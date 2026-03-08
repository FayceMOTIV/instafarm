/**
 * Control Panel — bot status + accounts + queues
 * Dark Glassmorphism Aurora 2026
 */

var _controlPollTimer = null;

async function renderControl(container) {
  // Stop any previous polling
  if (_controlPollTimer) clearInterval(_controlPollTimer);

  render(container, [
    '<div class="page-header"><h1>\uD83E\uDD16 Contr\u00F4le Bot</h1></div>',
    '<div id="control-content">',
    '  <div class="loading"><div class="spinner"></div></div>',
    "</div>",
  ].join("\n"));

  await _loadControl();

  // Poll every 30s
  _controlPollTimer = setInterval(_loadControl, 30000);
}

async function _loadControl() {
  var content = document.getElementById("control-content");
  if (!content) {
    if (_controlPollTimer) clearInterval(_controlPollTimer);
    return;
  }

  try {
    var results = await Promise.all([
      API.getBotStatus(),
      API.getAccounts(),
      API.getQueues(),
    ]);

    var status = results[0] || {};
    var accountsData = results[1] || {};
    var accountsList = accountsData.accounts || accountsData;
    var accounts = Array.isArray(accountsList) ? accountsList : [];
    var queuesData = results[2] || {};
    var queues = queuesData.queues || {};

    var isRunning = status.bot_active !== false;

    // Group accounts by status
    var accountsByStatus = {};
    accounts.forEach(function (a) {
      var s = a.status || "unknown";
      if (!accountsByStatus[s]) accountsByStatus[s] = [];
      accountsByStatus[s].push(a);
    });

    var activeCount = (accountsByStatus.active || []).length;
    var warmupCount = (accountsByStatus.warmup || []).length;
    var bannedCount = (accountsByStatus.banned || []).length;
    var totalAccounts = accounts.length || 1;

    render(content, [
      // Bot status card
      '<div class="card">',
      '  <div class="control-status-row">',
      '    <div class="status-indicator">',
      '      <span class="status-dot ' + (isRunning ? "active" : "paused") + '"></span>',
      "      " + (isRunning ? "En marche" : "En pause"),
      "    </div>",
      '    <button class="btn ' + (isRunning ? "btn-danger" : "btn-primary") + ' btn-sm" id="toggle-bot">',
      (isRunning ? "\u23F8 Pause" : "\u25B6 Reprendre"),
      "    </button>",
      "  </div>",
      '  <div class="control-stats">',
      '    <span>\uD83C\uDFAF ' + esc(status.active_niches || 0) + " niches actives</span>",
      '    <span>\u23F8 ' + esc(status.paused_niches || 0) + " en pause</span>",
      "  </div>",
      "</div>",

      // Account pool
      '<div class="card">',
      "  <h3>Pool comptes</h3>",
      '  <div class="pool-bar">',
      (activeCount > 0 ? '    <div class="pool-segment pool-active" style="width:' + ((activeCount / totalAccounts) * 100).toFixed(0) + '%">' + activeCount + " actifs</div>" : ""),
      (warmupCount > 0 ? '    <div class="pool-segment pool-warmup" style="width:' + ((warmupCount / totalAccounts) * 100).toFixed(0) + '%">' + warmupCount + " warmup</div>" : ""),
      (bannedCount > 0 ? '    <div class="pool-segment pool-banned" style="width:' + ((bannedCount / totalAccounts) * 100).toFixed(0) + '%">' + bannedCount + " ban</div>" : ""),
      "  </div>",
      '  <p class="text-secondary">' + accounts.length + " comptes total</p>",
      "</div>",

      // Queues
      '<div class="card">',
      "  <h3>Files d'attente</h3>",
      (Object.keys(queues).length > 0
        ? Object.keys(queues).map(function (qName) {
            var q = queues[qName];
            return [
              '<div class="queue-row">',
              '  <span class="queue-niche">' + esc(qName.replace(/_/g, " ")) + "</span>",
              '  <span class="text-secondary">' + esc(q.pending || 0) + " en attente \u2022 " + esc(q.processing || 0) + " en cours</span>",
              "</div>",
            ].join("\n");
          }).join("\n")
        : '<p class="text-secondary">Aucune file active</p>'
      ),
      "</div>",

      // Niche creation
      '<div class="card">',
      "  <h3>Ajouter une niche</h3>",
      '  <div class="niche-creator">',
      '    <select id="catalog-niche-select" class="input">',
      '      <option value="">Chargement niches...</option>',
      "    </select>",
      '    <input id="catalog-city" class="input" placeholder="Ville (ex: Lyon)" />',
      '    <div id="catalog-stats" class="catalog-stats hidden"></div>',
      '    <button class="btn btn-primary" id="btn-add-niche" disabled>Ajouter cette niche</button>',
      "  </div>",
      "</div>",

      // Quick actions
      '<div class="card">',
      "  <h3>Actions rapides</h3>",
      '  <div class="control-actions">',
      '    <button class="btn btn-ghost" id="btn-scrape">\uD83D\uDD0D Forcer scraping</button>',
      '    <button class="btn btn-ghost" id="btn-create-account">\u2795 Cr\u00E9er compte</button>',
      "  </div>",
      "</div>",

      // Recent logs
      '<div class="card">',
      "  <h3>Derni\u00E8res actions</h3>",
      '  <div id="recent-logs" class="logs-list">',
      '    <p class="text-secondary">Chargement...</p>',
      "  </div>",
      "</div>",
    ].join("\n"));

    // Events
    document.getElementById("toggle-bot").addEventListener("click", async function () {
      try {
        if (isRunning) {
          await API.pauseBot();
          showToast("Bot en pause", "warning");
        } else {
          await API.resumeBot();
          showToast("Bot relanc\u00E9", "success");
        }
        _loadControl();
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    document.getElementById("btn-scrape").addEventListener("click", async function () {
      try {
        var nichesData = await API.getNiches();
        var niches = Array.isArray(nichesData) ? nichesData : (nichesData.niches || []);
        if (niches.length > 0) {
          await API.triggerScrape(niches[0].id);
          showToast("Scraping lanc\u00E9 pour " + (niches[0].name || "niche 1"), "success");
        }
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    document.getElementById("btn-create-account").addEventListener("click", async function () {
      try {
        await API.createAccount();
        showToast("Cr\u00E9ation de compte lanc\u00E9e", "success");
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    // Load catalog niches into select
    _loadCatalogNiches();

  } catch (e) {
    render(content, '<div class="empty-state"><p>Erreur : ' + esc(e.message) + "</p></div>");
  }
}

var _catalogNichesCache = null;
var _catalogStatsTimeout = null;

async function _loadCatalogNiches() {
  var select = document.getElementById("catalog-niche-select");
  if (!select) return;

  try {
    if (!_catalogNichesCache) {
      var data = await API.getCatalogNiches();
      _catalogNichesCache = data.niches || [];
    }

    // Build options safely using DOM methods
    select.textContent = "";
    var defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "-- Choisir une niche --";
    select.appendChild(defaultOpt);

    _catalogNichesCache.forEach(function (n) {
      var opt = document.createElement("option");
      opt.value = n.key;
      var igBadge = n.instagram_direct ? " [IG direct]" : "";
      opt.textContent = n.emoji + " " + n.label + igBadge + " (" + n.sources_count + " sources)";
      select.appendChild(opt);
    });

    // Event: niche selected → load Sirene stats
    select.addEventListener("change", function () {
      _onNicheOrCityChange();
    });

    var cityInput = document.getElementById("catalog-city");
    if (cityInput) {
      cityInput.addEventListener("input", function () {
        if (_catalogStatsTimeout) clearTimeout(_catalogStatsTimeout);
        _catalogStatsTimeout = setTimeout(_onNicheOrCityChange, 600);
      });
    }
  } catch (e) {
    select.textContent = "";
    var errOpt = document.createElement("option");
    errOpt.value = "";
    errOpt.textContent = "Erreur chargement niches";
    select.appendChild(errOpt);
  }
}

async function _onNicheOrCityChange() {
  var select = document.getElementById("catalog-niche-select");
  var cityInput = document.getElementById("catalog-city");
  var statsDiv = document.getElementById("catalog-stats");
  var addBtn = document.getElementById("btn-add-niche");
  if (!select || !statsDiv) return;

  var sector = select.value;
  var city = cityInput ? cityInput.value.trim() : "";

  if (!sector) {
    statsDiv.classList.add("hidden");
    if (addBtn) addBtn.disabled = true;
    return;
  }

  // Find niche info from cache
  var nicheInfo = (_catalogNichesCache || []).find(function (n) { return n.key === sector; });
  var igDirect = nicheInfo ? nicheInfo.instagram_direct : false;

  statsDiv.classList.remove("hidden");
  render(statsDiv, '<div class="spinner-sm"></div> Interrogation Sirene...');

  try {
    var stats = await API.getCatalogNicheStats(sector, city, "");

    var total = stats.total_establishments || 0;
    var igEst = stats.estimated_with_instagram || 0;
    var goldSrc = stats.gold_source || "sirene";

    render(statsDiv, [
      '<div class="catalog-stat-row">',
      '  <span class="stat-label">Etablissements actifs</span>',
      '  <span class="stat-value">' + esc(formatNum(total)) + "</span>",
      "</div>",
      '<div class="catalog-stat-row">',
      '  <span class="stat-label">Estimes avec Instagram</span>',
      '  <span class="stat-value ' + (igEst > 100 ? "text-green" : "") + '">' + esc(formatNum(igEst)) + "</span>",
      "</div>",
      '<div class="catalog-stat-row">',
      '  <span class="stat-label">Source principale</span>',
      '  <span class="badge ' + (igDirect ? "badge-success" : "badge-neutral") + '">' + esc(goldSrc) + (igDirect ? " (IG direct)" : "") + "</span>",
      "</div>",
    ].join("\n"));

    if (addBtn) addBtn.disabled = false;
  } catch (e) {
    render(statsDiv, '<span class="text-danger">Erreur : ' + esc(e.message) + "</span>");
    if (addBtn) addBtn.disabled = true;
  }
}
