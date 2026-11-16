/* 等待 pywebview 接口注入；接口不可用时通过 HTTP 调用 /api/<方法名>。 */
"use strict";

const REMOTE = false; // 当前控制台使用本地模式标记。
let IS_REAL = false;

const bridgeReady = new Promise((resolve) => {
  let settled = false;
  const check = () => {
    if (settled) return true;
    if (window.pywebview && window.pywebview.api &&
        typeof window.pywebview.api.get_status === "function") {
      settled = true;
      IS_REAL = true;
      resolve(true);
      return true;
    }
    return false;
  };
  window.addEventListener("pywebviewready", () => { check(); });
  const t0 = Date.now();
  const timer = setInterval(() => {
    if (check() || Date.now() - t0 > 3000) {
      clearInterval(timer);
      if (!settled) { settled = true; IS_REAL = false; resolve(false); }
    }
  }, 60);
});

async function callApi(name, args = [], kwargs = {}) {
  await bridgeReady;
  if (IS_REAL) {
    try {
      const fn = window.pywebview.api[name];
      if (typeof fn === "function") return await fn(...args);
    } catch (e) { return { ok: false, error: String(e) }; }
  }
  const resp = await fetch("/api/" + encodeURIComponent(name), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ args, kwargs }),
  });
  return resp.json();
}
