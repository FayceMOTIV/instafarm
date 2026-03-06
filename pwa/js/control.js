/**
 * Control Panel — bot status + accounts + queues
 */

var _controlPollTimer = null;

async function renderControl(container) {
  // Stop any previous polling
  if (_controlPollTimer) clearInterval(_controlPollTimer);

  render(container, [
    '<div class="page-header"><h1>\uD83E\uDD16 Contrôle Bot</h1></div>',
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
    var accounts = results[1] || [];
    var queues = results[2] || [];

    var isRunning = status.running !== false;

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
      '    <div class="status-indicator ' + (isRunning ? "status-on" : "status-off") + '">',
      "      " + (isRunning ? "\uD83D\uDFE2 En marche" : "\uD83D\uDD34 En pause"),
      "    </div>",
      '    <button class="btn ' + (isRunning ? "btn-danger" : "btn-primary") + '" id="toggle-bot">',
      (isRunning ? "\u23F8 Pause" : "\u25B6 Reprendre"),
      "    </button>",
      "  </div>",
      '  <div class="control-stats">',
      '    <span>' + esc(status.active_niches || 0) + " niches actives</span>",
      '    <span>' + esc(status.paused_niches || 0) + " en pause</span>",
      "  </div>",
      "</div>",
      "",
      // Account pool
      '<div class="card">',
      "  <h3>Pool comptes</h3>",
      '  <div class="pool-bar">',
      '    <div class="pool-segment pool-active" style="width:' + ((activeCount / totalAccounts) * 100).toFixed(0) + '%">' + activeCount + " actifs</div>",
      '    <div class="pool-segment pool-warmup" style="width:' + ((warmupCount / totalAccounts) * 100).toFixed(0) + '%">' + warmupCount + " warmup</div>",
      (bannedCount > 0 ? '    <div class="pool-segment pool-banned" style="width:' + ((bannedCount / totalAccounts) * 100).toFixed(0) + '%">' + bannedCount + " ban</div>" : ""),
      "  </div>",
      '  <p class="text-secondary">' + accounts.length + " comptes total</p>",
      "</div>",
      "",
      // Queues
      '<div class="card">',
      "  <h3>Files d'attente</h3>",
      (queues.length > 0
        ? queues.map(function (q) {
            return [
              '<div class="queue-row">',
              '  <span class="queue-niche">' + esc(q.emoji || "") + " " + esc(q.niche || q.name || "?") + "</span>",
              '  <span class="text-secondary">' + esc(q.follows_pending || 0) + " follows, " + esc(q.dms_pending || 0) + " DMs</span>",
              "</div>",
            ].join("\n");
          }).join("\n")
        : '<p class="text-secondary">Aucune file active</p>'
      ),
      "</div>",
      "",
      // Quick actions
      '<div class="card">',
      "  <h3>Actions rapides</h3>",
      '  <div class="control-actions">',
      '    <button class="btn btn-ghost" id="btn-scrape">\uD83D\uDD0D Forcer scraping</button>',
      '    <button class="btn btn-ghost" id="btn-create-account">\u2795 Créer compte</button>',
      "  </div>",
      "</div>",
      "",
      // Recent logs
      '<div class="card">',
      "  <h3>Dernières actions</h3>",
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
          showToast("Bot relancé", "success");
        }
        _loadControl();
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    document.getElementById("btn-scrape").addEventListener("click", async function () {
      try {
        var niches = await API.getNiches();
        if (niches.length > 0) {
          await API.triggerScrape(niches[0].id);
          showToast("Scraping lancé pour " + (niches[0].name || "niche 1"), "success");
        }
      } catch (e) {
        showToast(e.message, "error");
      }
    });

    document.getElementById("btn-create-account").addEventListener("click", async function () {
      try {
        await API.createAccount();
        showToast("Création de compte lancée", "success");
      } catch (e) {
        showToast(e.message, "error");
      }
    });

  } catch (e) {
    render(content, '<div class="empty-state"><p>Erreur : ' + esc(e.message) + "</p></div>");
  }
}
