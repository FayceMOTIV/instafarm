/**
 * API client centralise. Toutes les calls passent par ici.
 */
const API = {
  baseUrl: "",
  apiKey: localStorage.getItem("instafarm_api_key") || "",

  setApiKey(key) {
    this.apiKey = key;
    localStorage.setItem("instafarm_api_key", key);
  },

  getApiKey() {
    return this.apiKey;
  },

  async _fetch(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
      ...options.headers,
    };

    const resp = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (resp.status === 401) {
      window.location.hash = "#/settings";
      throw new Error("Non authentifie");
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Erreur API");
    }

    // Handle CSV responses
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("text/csv")) {
      return resp.text();
    }

    return resp.json();
  },

  // === NICHES ===
  getNiches: () => API._fetch("/api/niches"),
  getNiche: (id) => API._fetch(`/api/niches/${id}`),
  getNicheStats: (id) => API._fetch(`/api/niches/${id}/stats`),
  togglePauseNiche: (id) => API._fetch(`/api/niches/${id}/pause`, { method: "POST" }),
  triggerScrape: (id) => API._fetch(`/api/niches/${id}/scrape`, { method: "POST" }),

  // === PROSPECTS ===
  getProspects: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return API._fetch(`/api/prospects?${qs}`);
  },
  getProspect: (id) => API._fetch(`/api/prospects/${id}`),
  updateProspect: (id, data) => API._fetch(`/api/prospects/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  blacklistProspect: (id) => API._fetch(`/api/prospects/${id}/blacklist`, { method: "POST" }),
  exportCSV: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return API._fetch(`/api/prospects/export?${qs}`);
  },

  // === MESSAGES ===
  getMessages: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return API._fetch(`/api/messages?${qs}`);
  },
  getConversation: (prospectId) => API._fetch(`/api/messages/${prospectId}`),
  sendMessage: (prospectId, content) =>
    API._fetch(`/api/messages/${prospectId}`, { method: "POST", body: JSON.stringify({ content }) }),
  suggestResponse: (prospectId, lastMessage) =>
    API._fetch("/api/messages/suggest", {
      method: "POST",
      body: JSON.stringify({ prospect_id: prospectId, last_message: lastMessage }),
    }),

  // === ANALYTICS ===
  getDashboard: (period = "last_7_days") => API._fetch(`/api/analytics/dashboard?period=${period}`),
  getFunnel: (nicheId) => API._fetch(`/api/analytics/funnel${nicheId ? `?niche_id=${nicheId}` : ""}`),
  getHeatmap: () => API._fetch("/api/analytics/heatmap"),
  getAbTest: () => API._fetch("/api/analytics/ab-test"),
  getNicheRanking: () => API._fetch("/api/analytics/niche-ranking"),

  // === BOT CONTROL ===
  getBotStatus: () => API._fetch("/api/bot/status"),
  pauseBot: () => API._fetch("/api/bot/pause", { method: "POST" }),
  resumeBot: () => API._fetch("/api/bot/resume", { method: "POST" }),
  getQueues: () => API._fetch("/api/bot/queues"),

  // === ACCOUNTS ===
  getAccounts: () => API._fetch("/api/accounts"),
  getAccountStatus: (id) => API._fetch(`/api/accounts/${id}/status`),
  createAccount: () => API._fetch("/api/accounts/create", { method: "POST" }),

  // === WEBHOOKS ===
  getWebhooks: () => API._fetch("/api/webhooks"),
  createWebhook: (data) => API._fetch("/api/webhooks", { method: "POST", body: JSON.stringify(data) }),
  deleteWebhook: (id) => API._fetch(`/api/webhooks/${id}`, { method: "DELETE" }),
};
