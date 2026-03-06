/**
 * Dashboard Home — metrics + niche selector + chart 7j
 */

var _dashboardNiches = [];
var _dashboardSelectedNiche = null;

async function renderDashboard(container) {
  var now = new Date();
  var hh = String(now.getHours()).padStart(2, "0");
  var mm = String(now.getMinutes()).padStart(2, "0");
  var greeting = now.getHours() < 12 ? "\u2600\uFE0F Bonjour" : now.getHours() < 18 ? "\u2600\uFE0F Bon après-midi" : "\uD83C\uDF19 Bonsoir";

  var data, niches;
  try {
    var results = await Promise.all([
      API.getDashboard("last_7_days"),
      API.getNiches(),
    ]);
    data = results[0];
    niches = results[1] || [];
    _dashboardNiches = niches;
  } catch (e) {
    data = { dms_sent: 0, responses: 0, response_rate: 0, hot_prospects: 0, pipeline_value: 0, daily_stats: [] };
    niches = [];
  }

  var nicheChips = '<button class="chip active" data-niche="">Toutes</button>';
  niches.forEach(function (n) {
    nicheChips += '<button class="chip" data-niche="' + esc(n.id) + '">'
      + esc(n.emoji || "") + " " + esc(n.name) + "</button>";
  });

  var yesterday = data.daily_stats && data.daily_stats.length > 0
    ? data.daily_stats[data.daily_stats.length - 1]
    : { dms: 0, responses: 0 };

  render(container, [
    '<div class="page-header">',
    "  <h1>" + greeting + " !</h1>",
    '  <p class="text-secondary">' + hh + ":" + mm + " — Hier: " + esc(yesterday.dms) + " DMs, " + esc(yesterday.responses) + " réponses</p>",
    "</div>",
    "",
    '<div class="metrics-grid">',
    '  <div class="metric-card">',
    '    <div class="metric-value" id="m-dms">' + formatNum(data.dms_sent) + "</div>",
    '    <div class="metric-label">DMs envoyés</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value" id="m-rate">' + formatPct(data.response_rate) + "</div>",
    '    <div class="metric-label">Taux réponse</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value hot" id="m-hot">' + formatNum(data.hot_prospects) + ' \uD83D\uDD25</div>',
    '    <div class="metric-label">Prospects chauds</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value" id="m-pipeline">' + formatNum(data.pipeline_value) + " \u20AC</div>",
    '    <div class="metric-label">Pipeline</div>',
    "  </div>",
    "</div>",
    "",
    '<div class="niche-selector" id="niche-bar">' + nicheChips + "</div>",
    "",
    '<div class="card">',
    '  <h3>7 derniers jours</h3>',
    '  <canvas id="chart-7d" width="360" height="180"></canvas>',
    "</div>",
    "",
    '<div style="padding:0 1rem 1rem">',
    '  <button class="btn btn-primary btn-full" id="btn-hot">Voir prospects chauds \uD83D\uDD25</button>',
    "</div>",
  ].join("\n"));

  // Draw chart
  _drawChart(data.daily_stats || []);

  // Niche selector events
  document.getElementById("niche-bar").addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    document.querySelectorAll("#niche-bar .chip").forEach(function (c) { c.classList.remove("active"); });
    chip.classList.add("active");
    _dashboardSelectedNiche = chip.dataset.niche || null;
    _refreshDashboard(container);
  });

  // Hot prospects button
  document.getElementById("btn-hot").addEventListener("click", function () {
    navigateTo("#/inbox?filter=hot");
  });
}

async function _refreshDashboard(container) {
  try {
    var period = "last_7_days";
    var data = await API.getDashboard(period);
    var mDms = document.getElementById("m-dms");
    var mRate = document.getElementById("m-rate");
    var mHot = document.getElementById("m-hot");
    var mPipe = document.getElementById("m-pipeline");
    if (mDms) mDms.textContent = formatNum(data.dms_sent);
    if (mRate) mRate.textContent = formatPct(data.response_rate);
    if (mHot) mHot.textContent = formatNum(data.hot_prospects) + " \uD83D\uDD25";
    if (mPipe) mPipe.textContent = formatNum(data.pipeline_value) + " \u20AC";
    _drawChart(data.daily_stats || []);
  } catch (e) {
    showToast("Erreur refresh", "error");
  }
}

function _drawChart(dailyStats) {
  var canvas = document.getElementById("chart-7d");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var w = canvas.width;
  var h = canvas.height;
  var pad = 40;

  ctx.clearRect(0, 0, w, h);

  if (!dailyStats.length) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "14px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Pas encore de données", w / 2, h / 2);
    return;
  }

  var maxDms = Math.max.apply(null, dailyStats.map(function (d) { return d.dms || 0; }));
  if (maxDms === 0) maxDms = 1;
  var maxResp = Math.max.apply(null, dailyStats.map(function (d) { return d.responses || 0; }));
  if (maxResp === 0) maxResp = 1;
  var maxVal = Math.max(maxDms, maxResp);

  var stepX = (w - pad * 2) / Math.max(dailyStats.length - 1, 1);

  // Grid lines
  ctx.strokeStyle = "rgba(148,163,184,0.15)";
  ctx.lineWidth = 1;
  for (var g = 0; g <= 4; g++) {
    var gy = pad + ((h - pad * 2) * g) / 4;
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(w - pad, gy);
    ctx.stroke();
  }

  // DMs line (violet)
  _drawLine(ctx, dailyStats, "dms", maxVal, w, h, pad, stepX, "#7c3aed", 2);

  // Responses line (green)
  _drawLine(ctx, dailyStats, "responses", maxVal, w, h, pad, stepX, "#10b981", 2);

  // Labels
  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "center";
  dailyStats.forEach(function (d, i) {
    var x = pad + i * stepX;
    var label = d.date ? d.date.slice(5) : "" + i;
    ctx.fillText(label, x, h - 8);
  });

  // Legend
  ctx.fillStyle = "#7c3aed";
  ctx.fillRect(pad, 8, 12, 3);
  ctx.fillStyle = "#f8fafc";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("DMs", pad + 16, 12);

  ctx.fillStyle = "#10b981";
  ctx.fillRect(pad + 60, 8, 12, 3);
  ctx.fillStyle = "#f8fafc";
  ctx.fillText("Réponses", pad + 76, 12);
}

function _drawLine(ctx, data, key, maxVal, w, h, pad, stepX, color, width) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  data.forEach(function (d, i) {
    var x = pad + i * stepX;
    var val = d[key] || 0;
    var y = h - pad - ((val / maxVal) * (h - pad * 2));
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots
  ctx.fillStyle = color;
  data.forEach(function (d, i) {
    var x = pad + i * stepX;
    var val = d[key] || 0;
    var y = h - pad - ((val / maxVal) * (h - pad * 2));
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}
