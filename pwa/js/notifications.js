/**
 * Push notifications handler
 */
const Notifications = {
  async init() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    try {
      await navigator.serviceWorker.ready;
    } catch (e) {
      console.error("Push init error:", e);
    }
  },

  async requestPermission() {
    if (!("Notification" in window)) return false;
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return false;
    return this.subscribe();
  },

  async subscribe() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const vapidKey = localStorage.getItem("instafarm_vapid_key");
      if (!vapidKey) return false;

      await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this._urlBase64ToUint8Array(vapidKey),
      });
      return true;
    } catch (e) {
      console.error("Push subscribe error:", e);
      return false;
    }
  },

  _urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  },

  getPermissionStatus() {
    if (!("Notification" in window)) return "unsupported";
    return Notification.permission;
  },
};
