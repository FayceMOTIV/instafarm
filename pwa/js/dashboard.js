/**
 * Dashboard Home — Hero + metrics glassmorphiques + chart 7j
 * Dark Glassmorphism Aurora 2026
 */

var _dashboardNiches = [];
var _dashboardSelectedNiche = null;

async function renderDashboard(container) {
  var now = new Date();
  var hh = String(now.getHours()).padStart(2, "0");
  var mm = String(now.getMinutes()).padStart(2, "0");

  var data, niches, raw;
  try {
    var results = await Promise.all([
      API.getDashboard("last_7_days"),
      API.getNiches(),
    ]);
    raw = results[0];
    var g = raw.global || {};
    data = {
      dms_sent: g.dms_sent || 0,
      responses: g.responses || 0,
      response_rate: g.response_rate_pct || 0,
      hot_prospects: (raw.roi || {}).hot_prospects || 0,
      pipeline_value: (raw.roi || {}).estimated_pipeline_eur || 0,
      daily_stats: raw.daily_stats || [],
    };
    var nichesRaw = results[1];
    niches = Array.isArray(nichesRaw) ? nichesRaw : (nichesRaw.niches || []);
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
    // Hero section
    '<div class="hero-section">',
    '  <div class="hero-title">',
    '    <span class="gradient-text">InstaFarm</span> War Machine',
    '  </div>',
    '  <div class="hero-subtitle" id="hero-sub"></div>',
    '</div>',

    // Metrics grid
    '<div class="metrics-grid">',
    '  <div class="metric-card">',
    '    <div class="metric-value accent" id="m-dms">0</div>',
    '    <div class="metric-label">DMs envoy\u00E9s</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value success" id="m-rate">0%</div>',
    '    <div class="metric-label">Taux r\u00E9ponse</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value hot" id="m-hot">0</div>',
    '    <div class="metric-label">Prospects \uD83D\uDD25</div>',
    "  </div>",
    '  <div class="metric-card">',
    '    <div class="metric-value" id="m-pipeline">0 \u20AC</div>',
    '    <div class="metric-label">Pipeline</div>',
    "  </div>",
    "</div>",

    // Niche selector
    '<div class="niche-selector" id="niche-bar">' + nicheChips + "</div>",

    // Chart
    '<div class="card">',
    '  <h3>7 derniers jours</h3>',
    '  <canvas id="chart-7d" width="360" height="200" style="width:100%;height:200px"></canvas>',
    "</div>",

    // CTA
    '<div style="padding:4px 0 8px">',
    '  <button class="btn btn-primary btn-full btn-glow" id="btn-hot">\uD83D\uDD25 Voir prospects chauds</button>',
    "</div>",
  ].join("\n"));

  // Typewriter hero subtitle
  var heroSub = document.getElementById("hero-sub");
  var subtitleText = hh + ":" + mm + " \u2022 Hier: " + (yesterday.dms || 0) + " DMs, " + (yesterday.responses || 0) + " r\u00E9ponses";
  typeWriter(heroSub, subtitleText, 30);

  // Animate count up on metrics
  animateCountUp(document.getElementById("m-dms"), data.dms_sent, 1000);
  animateCountUp(document.getElementById("m-rate"), data.response_rate, 1000);
  animateCountUp(document.getElementById("m-hot"), data.hot_prospects, 800);

  var mPipe = document.getElementById("m-pipeline");
  if (mPipe) {
    var pipeTarget = data.pipeline_value;
    var pipeStart = 0;
    var pipeStartTime = null;
    function animPipe(ts) {
      if (!pipeStartTime) pipeStartTime = ts;
      var prog = Math.min((ts - pipeStartTime) / 1200, 1);
      var eased = 1 - Math.pow(1 - prog, 3);
      mPipe.textContent = Math.round(pipeStart + (pipeTarget - pipeStart) * eased).toLocaleString("fr-FR") + " \u20AC";
      if (prog < 1) requestAnimationFrame(animPipe);
    }
    requestAnimationFrame(animPipe);
  }

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
    var raw = await API.getDashboard("last_7_days");
    var g = raw.global || {};
    var data = {
      dms_sent: g.dms_sent || 0,
      response_rate: g.response_rate_pct || 0,
      hot_prospects: (raw.roi || {}).hot_prospects || 0,
      pipeline_value: (raw.roi || {}).estimated_pipeline_eur || 0,
      daily_stats: raw.daily_stats || [],
    };
    var mDms = document.getElementById("m-dms");
    var mRate = document.getElementById("m-rate");
    var mHot = document.getElementById("m-hot");
    var mPipe = document.getElementById("m-pipeline");
    if (mDms) animateCountUp(mDms, data.dms_sent, 600);
    if (mRate) animateCountUp(mRate, data.response_rate, 600);
    if (mHot) animateCountUp(mHot, data.hot_prospects, 600);
    if (mPipe) mPipe.textContent = formatNum(data.pipeline_value) + " \u20AC";
    _drawChart(data.daily_stats || []);
  } catch (e) {
    showToast("Erreur refresh", "error");
  }
}

function _drawChart(dailyStats) {
  var canvas = document.getElementById("chart-7d");
  if (!canvas) return;

  // Handle high-DPI displays
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  var ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  var w = rect.width;
  var h = rect.height;
  var pad = 40;

  ctx.clearRect(0, 0, w, h);

  if (!dailyStats.length) {
    ctx.fillStyle = "#8b8fa8";
    ctx.font = "14px 'DM Sans', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Pas encore de donn\u00E9es", w / 2, h / 2);
    return;
  }

  var maxDms = Math.max.apply(null, dailyStats.map(function (d) { return d.dms || 0; }));
  if (maxDms === 0) maxDms = 1;
  var maxResp = Math.max.apply(null, dailyStats.map(function (d) { return d.responses || 0; }));
  if (maxResp === 0) maxResp = 1;
  var maxVal = Math.max(maxDms, maxResp);

  var stepX = (w - pad * 2) / Math.max(dailyStats.length - 1, 1);

  // Grid lines
  ctx.strokeStyle = "rgba(139,143,168,0.08)";
  ctx.lineWidth = 1;
  for (var g = 0; g <= 4; g++) {
    var gy = pad + ((h - pad * 2) * g) / 4;
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(w - pad, gy);
    ctx.stroke();
  }

  // DMs area fill (violet gradient)
  _drawAreaFill(ctx, dailyStats, "dms", maxVal, w, h, pad, stepX, "rgba(124, 58, 237, 0.15)", "rgba(124, 58, 237, 0.02)");

  // DMs line (violet)
  _drawLine(ctx, dailyStats, "dms", maxVal, w, h, pad, stepX, "#a855f7", 2.5);

  // Responses line (green)
  _drawLine(ctx, dailyStats, "responses", maxVal, w, h, pad, stepX, "#22c55e", 2);

  // Labels
  ctx.fillStyle = "#8b8fa8";
  ctx.font = "11px 'DM Sans', sans-serif";
  ctx.textAlign = "center";
  dailyStats.forEach(function (d, i) {
    var x = pad + i * stepX;
    var label = d.date ? d.date.slice(5) : "" + i;
    ctx.fillText(label, x, h - 8);
  });

  // Legend
  ctx.fillStyle = "#a855f7";
  ctx.fillRect(pad, 6, 12, 4);
  ctx.fillStyle = "#f0f0f8";
  ctx.font = "11px 'DM Sans', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("DMs", pad + 16, 12);

  ctx.fillStyle = "#22c55e";
  ctx.fillRect(pad + 55, 6, 12, 4);
  ctx.fillStyle = "#f0f0f8";
  ctx.fillText("R\u00E9ponses", pad + 71, 12);
}

function _drawAreaFill(ctx, data, key, maxVal, w, h, pad, stepX, colorTop, colorBottom) {
  var gradient = ctx.createLinearGradient(0, pad, 0, h - pad);
  gradient.addColorStop(0, colorTop);
  gradient.addColorStop(1, colorBottom);

  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.moveTo(pad, h - pad);

  data.forEach(function (d, i) {
    var x = pad + i * stepX;
    var val = d[key] || 0;
    var y = h - pad - ((val / maxVal) * (h - pad * 2));
    if (i === 0) ctx.lineTo(x, y);
    else ctx.lineTo(x, y);
  });

  ctx.lineTo(pad + (data.length - 1) * stepX, h - pad);
  ctx.closePath();
  ctx.fill();
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

  // Glow dots
  data.forEach(function (d, i) {
    var x = pad + i * stepX;
    var val = d[key] || 0;
    var y = h - pad - ((val / maxVal) * (h - pad * 2));

    // Glow
    ctx.fillStyle = color.replace(")", ", 0.3)").replace("rgb", "rgba");
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fill();

    // Dot
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}
