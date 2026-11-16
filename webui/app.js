/* 网页控制台：每秒刷新状态，并绑定配置、采集和调试操作。 */
"use strict";

function $(id) { return document.getElementById(id); }

function toast(msg) {
  const box = $("toast");
  const s = document.createElement("span");
  s.textContent = msg;
  box.appendChild(s);
  setTimeout(() => s.remove(), 3000);
}

document.querySelectorAll("#tabs button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document.querySelectorAll("main .page").forEach((p) => {
      p.classList.toggle("active", p.dataset.p === b.dataset.p);
    });
  });
});

async function refresh() {
  const r = await callApi("get_status");
  if (!r || !r.ok) return;
  const st = r.state || {};
  const pill = $("runPill");
  const txt = $("runText");
  pill.classList.toggle("on", !!st.connected);
  pill.classList.toggle("run", !!st.running && !st.connected);
  txt.textContent = st.connected ? "已连接 core" : (st.running ? "运行中(未连 core)" : "未启动");
  $("connLine").textContent = (st.connector_id || "") + " " + (st.account_id || "");
  $("stBackend").textContent = st.backend_ok ? "OK" : "-";
  $("stConn").textContent = st.connected ? "已连接" : "未连接";
  $("stHwnd").textContent = st.hwnd || "-";
  $("stErr").textContent = st.last_error || "-";
  const c = st.counts || {};
  $("counts").innerHTML =
    `<div>轮询<b>${c.poll || 0}</b></div><div>上报<b>${c.events || 0}</b></div>` +
    `<div>已发core<b>${c.reported || 0}</b></div><div>core确认<b>${c.acked || 0}</b></div>` +
    `<div>拦截<b>${c.blocked || 0}</b></div><div>发送OK<b>${c.sent_ok || 0}</b></div>` +
    `<div>发送失败<b>${c.sent_fail || 0}</b></div><div>最近事件<b>${st.last_event_ts ? new Date(st.last_event_ts * 1000).toLocaleTimeString() : "-"}</b></div>`;
  const ev = (r.events || []).slice(0, 8);
  $("homeEvents").innerHTML = ev.length
    ? ev.map((e) => `<div><span class="t">[${e.ts}]</span>${chatTypeBadge(e.chat_type)}<b>${e.chat}</b> | ${e.sender}: ${e.text}</div>`).join("")
    : "<div>暂无上报</div>";
  const evAll = r.events || [];
  $("eventsList").innerHTML = evAll.length
    ? evAll.map((e) => `<div><span class="t">[${e.ts}]</span>${chatTypeBadge(e.chat_type)}<b>${e.chat}</b> | ${e.sender}: ${e.text}</div>`).join("")
    : "<div>暂无上报</div>";
  const bl = r.blocked || [];
  $("blockedList").innerHTML = bl.length
    ? bl.map((x) => `<div><span class="t">[${x[2]}]</span><b>${x[0]}</b> (${x[1]})</div>`).join("")
    : "<div>暂无拦截</div>";
  const logs = r.logs || [];
  $("logs").textContent = logs.map((l) => `[${l[0]}] ${l[1]}`).join("\n") || "(暂无日志)";
  const cfg = r.config || {};
  if (!$("edWs").dataset.init) {
    $("edWs").value = cfg.core_ws_url || "";
    $("edCid").value = cfg.connector_id || "";
    $("edAcc").value = cfg.account_id || "";
    $("edPoll").value = cfg.poll_sec || 2;
    $("edExtra").value = cfg.filter_extra || "";
    $("edAllow").value = cfg.filter_allow || "";
    $("ckAstrbot").checked = !!cfg.astrbot_enabled;
    $("edAstrWs").value = cfg.astrbot_ws_url || "";
    if (cfg.astrbot_token) $("edAstrToken").value = cfg.astrbot_token;
    else if (cfg.has_astrbot_token) $("edAstrToken").placeholder = "已保存（留空 = 不改动）";
    if (cfg.token) $("edToken").value = cfg.token;
    else if (cfg.has_token) $("edToken").placeholder = "已保存（留空 = 不改动）";
    $("edWs").dataset.init = "1";
  } else if (cfg.token && !$("edToken").value && document.activeElement !== $("edToken")) {
    // 核心连接令牌为空且未聚焦时，补回后端返回的已保存值。
    $("edToken").value = cfg.token;
  } else if (cfg.astrbot_token && !$("edAstrToken").value && document.activeElement !== $("edAstrToken")) {
    $("edAstrToken").value = cfg.astrbot_token;
  }
  // 显示后端返回的连接目标与生效地址。
  const tgt = cfg.backend_target === "astrbot" ? "AstrBot 直连" : "core";
  if ($("connTargetHint")) {
    $("connTargetHint").textContent =
      "当前连接目标：" + tgt + (cfg.effective_ws_url ? "（" + cfg.effective_ws_url + "）" : "");
  }
}

async function boot() {
  await bridgeReady;
  setInterval(refresh, 1000);
  refresh();
  bootDebug();
  $("btnStart").onclick = async () => {
    const r = await callApi("runtime_start");
    toast(r.ok ? (r.msg || "启动中") : ("失败: " + r.error));
    refresh();
  };
  $("btnStop").onclick = async () => {
    await callApi("runtime_stop");
    toast("已请求停止");
    refresh();
  };
  $("btnShot").onclick = async () => {
    const r = await callApi("test_shot");
    toast(r.ok ? ("截图: " + r.result) : ("失败: " + r.error));
  };
  $("btnTitle").onclick = async () => {
    const r = await callApi("read_title");
    toast(r.ok ? ("标题: " + r.result) : ("失败: " + r.error));
  };
  $("btnSave").onclick = async () => {
    const patch = {
      ASTRBOT_ENABLED: $("ckAstrbot").checked ? "1" : "0",
      ASTRBOT_WS_URL: $("edAstrWs").value.trim(),
      CORE_WS_URL: $("edWs").value.trim(),
      CONNECTOR_ID: $("edCid").value.trim(),
      WECHAT_ACCOUNT_ID: $("edAcc").value.trim(),
      POLL_SEC: $("edPoll").value.trim(),
    };
    if ($("edAstrToken").value.trim()) patch.ASTRBOT_TOKEN = $("edAstrToken").value.trim();
    if ($("edToken").value.trim()) patch.CONNECTOR_TOKEN = $("edToken").value.trim();
    const r = await callApi("save_config", [patch]);
    $("saveMsg").textContent = r.ok ? ("已保存: " + (r.applied || []).join(",")) : ("失败: " + r.error);
    toast($("saveMsg").textContent);
    refresh();
  };
  $("btnTestConn").onclick = async () => {
    const box = $("testConnResult");
    box.textContent = "验证中…（hello → hello_ack）";
    // 用当前表单测试连接，无需保存；令牌留空时由后端使用已保存配置。
    const useAstrbot = $("ckAstrbot").checked;
    const r = await callApi("test_connection", [{
      ws_url: (useAstrbot ? $("edAstrWs").value.trim() : $("edWs").value.trim()),
      connector_id: $("edCid").value.trim(),
      account_id: $("edAcc").value.trim(),
      token: (useAstrbot ? $("edAstrToken").value : $("edToken").value),
    }]);
    box.textContent = r.ok ? ("✅ " + r.result) : ("❌ " + r.error);
    box.style.color = r.ok ? "var(--ok)" : "var(--err)";
    toast(box.textContent);
  };
  $("btnTestSend").onclick = async () => {
    const box = $("testSendResult");
    box.textContent = "发送中…（切会话→粘贴→回车）";
    const r = await callApi("test_send", [{
      chat: $("edTestChat").value.trim(),
      text: $("edTestText").value.trim(),
    }]);
    box.textContent = r.ok ? ("✅ " + r.result) : ("❌ " + r.error);
    box.style.color = r.ok ? "var(--ok)" : "var(--err)";
    toast(box.textContent);
    refresh();
  };
  $("btnFilterSave").onclick = async () => {
    const r = await callApi("save_config", [{
      FILTER_EXTRA: $("edExtra").value.trim(), FILTER_ALLOW: $("edAllow").value.trim(),
    }]);
    toast(r.ok ? "过滤词已保存" : ("失败: " + r.error));
  };
  $("btnOcr").onclick = async () => {
    const meta = $("ocrMeta");
    meta.textContent = "抓取识别中…（首次加载 OCR 模型较慢）";
    const r = await callApi("ocr_preview");
    if (!r.ok) {
      meta.textContent = "❌ " + r.error;
      toast("OCR 失败: " + r.error);
      return;
    }
    meta.textContent = `✅ ${r.orig_width}x${r.orig_height} → 预览 ${r.width}x${r.height}，${r.count} 块，${r.elapsed_ms}ms`;
    renderOcr(r);
    toast(`识别完成: ${r.count} 块`);
  };
  $("ckBoxes").onchange = () => {
    if (lastOcr) renderOcr(lastOcr);
  };
  $("btnCaps").onclick = async () => {
    const msg = $("capsMsg");
    msg.textContent = "检测中…";
    const r = await callApi("get_capabilities");
    if (!r.ok) {
      msg.textContent = "❌ " + r.error;
      $("capsList").innerHTML = "";
      toast("能力检测失败: " + r.error);
      return;
    }
    const items = r.items || [];
    $("capsList").innerHTML = items.length
      ? items.map((x) =>
          `<div><span class="t">${x.ok ? "✅" : "⚠️"}</span><b>${escapeHtml(x.label)}</b> — ${escapeHtml(x.detail)}</div>`).join("")
      : "<div>无可检测项</div>";
    const caps = r.capabilities || {};
    const keys = Object.keys(caps);
    $("capsDeclared").innerHTML = keys.length
      ? keys.map((k) => `<div><span class="t">${caps[k] ? "✅" : "⚠️"}</span><b>${escapeHtml(k)}</b> = ${caps[k] ? "支持" : "不支持"}</div>`).join("")
      : "<div>未连接 core（尚未握手）</div>";
    msg.textContent = `✅ 检测完成（${items.filter((x) => x.ok).length}/${items.length} 项就绪）`;
    toast(msg.textContent);
  };
  $("btnMediaDetect").onclick = async () => {
    const msg = $("capsMsg");
    msg.textContent = "检测消息区气泡中…";
    const r = await callApi("test_media");
    if (!r.ok) {
      msg.textContent = "❌ " + r.error;
      toast("气泡检测失败: " + r.error);
      return;
    }
    const counts = r.counts || {};
    const parts = Object.keys(counts).map((k) => `${k}=${counts[k]}`);
    msg.textContent = `✅ 检出 ${r.count} 个气泡${parts.length ? "（" + parts.join(", ") + "）" : ""}`;
    const bs = r.bubbles || [];
    $("capsList").innerHTML = bs.length
      ? bs.map((b) =>
          `<div><span class="t">${escapeHtml(b.kind)}</span><b>[${b.x},${b.y} ${b.w}x${b.h}]</b> ${escapeHtml(b.text)}</div>`).join("")
      : "<div>未检出媒体气泡（当前消息区没有图片/文件/表情/语音）</div>";
    toast(msg.textContent);
  };
}

let lastOcr = null;

function renderOcr(r) {
  lastOcr = r;
  const cv = $("ocrCanvas");
  const showBoxes = $("ckBoxes").checked;
  const img = new Image();
  img.onload = () => {
    cv.width = r.width;
    cv.height = r.height;
    const ctx = cv.getContext("2d");
    ctx.drawImage(img, 0, 0, r.width, r.height);
    if (showBoxes) {
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 1.5;
      for (const b of (r.items || [])) {
        ctx.strokeRect(b.x, b.y, Math.max(b.w, 2), Math.max(b.h, 2));
      }
    }
  };
  img.src = r.image;
  $("ocrCount").textContent = String(r.count || 0);
  $("ocrList").innerHTML = (r.items || []).length
    ? r.items.map((b, i) =>
        `<div><span class="t">#${i + 1} [${b.x},${b.y} ${b.w}x${b.h}]</span><b></b> ${escapeHtml(b.text)}</div>`).join("")
    : "<div>无文本块（OCR 引擎正常但画面无文字，或需先登录微信）</div>";
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

/* 调试结果状态与渲染。 */
const DBG = {
  canvas: null, ctx: null, img: null, boxes: [], kind: "",
};

function dbgRaw(obj) {
  $("dbgRaw").textContent = JSON.stringify(obj, null, 2);
}

/* 按分组同步折叠内容与按钮状态。 */
const DBG_FOLD_STATE = {};

function dbgToggleFold(key, force) {
  const bodies = document.querySelectorAll(`[data-fold-body="${key}"]`);
  if (!bodies.length) return false;
  const btn = document.querySelector(`.dbg-fold-btn[data-fold="${key}"]`);
  const collapsed = force === undefined ? !bodies[0].classList.contains("collapsed") : !force;
  bodies.forEach((body) => body.classList.toggle("collapsed", collapsed));
  if (btn) btn.classList.toggle("open", !collapsed);
  DBG_FOLD_STATE[key] = collapsed;
  return !collapsed;
}

function dbgInitFold() {
  document.querySelectorAll(".dbg-fold-btn[data-fold]").forEach((btn) => {
    const key = btn.dataset.fold;
    btn.onclick = () => dbgToggleFold(key);
    // 初始化为折叠；区域编辑卡片随后由 bootDebug 单独展开。
    dbgToggleFold(key, false);
  });
}

/* 将会话类型渲染为私信、群聊或未知徽章。 */
function chatTypeBadge(chatType) {
  const t = String(chatType || "").toLowerCase();
  const cls = t === "group" ? "group" : (t === "private" ? "private" : "unknown");
  const text = t === "group" ? "群聊" : (t === "private" ? "私信" : "未知");
  return `<span class="chat-type-badge ${cls}">${text}</span>`;
}

function dbgSetChatType(chatType, label, extra) {
  const el = $("dbgChatType");
  if (!el) return;
  const t = String(chatType || "").toLowerCase();
  const cls = t === "group" ? "group" : (t === "private" ? "private" : "unknown");
  const text = label || (t === "group" ? "群聊" : (t === "private" ? "私信" : "未知"));
  el.className = "chat-type-badge " + cls;
  let txt = "会话类型 " + text;
  if (extra && extra.member_count != null) txt += ` · ${extra.member_count}人`;
  el.textContent = txt;
  el.title = (extra && extra.reason) ? extra.reason : "";
}

function dbgClearChatType() {
  dbgSetChatType("", "未知", null);
  const el = $("dbgChatType");
  if (el) el.textContent = "会话类型 -";
}

function dbgStats(pairs) {
  $("dbgStats").innerHTML = pairs
    .map(([k, v]) => `<div class="stat">${escapeHtml(k)} <b>${escapeHtml(v)}</b></div>`)
    .join("");
}

function dbgOut(id, lines) {
  $(id).innerHTML = lines.map(([k, v, cls]) =>
    `<div class="line"><span class="k">${escapeHtml(k)}</span>` +
    `<span class="v">${cls ? `<span class="verdict ${cls}">${escapeHtml(v)}</span>` : escapeHtml(v)}</span></div>`
  ).join("");
}

/** 绘制预览图；文字识别模式额外绘制文本框。 */
function dbgDraw(dataUri, w, h, boxes, kind) {
  const cv = $("dbgCanvas");
  if (!cv) return;
  DBG.img = new Image();
  DBG.img.onload = () => {
    cv.width = w;
    cv.height = h;
    const ctx = cv.getContext("2d");
    ctx.drawImage(DBG.img, 0, 0);
    if (kind === "ocr") {
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 1.5;
      for (const b of boxes) ctx.strokeRect(b.x, b.y, Math.max(b.w, 2), Math.max(b.h, 2));
    }
    DBG.ctx = ctx;
  };
  DBG.img.src = dataUri;
  DBG.boxes = boxes || [];
  DBG.kind = kind || "";
}

function dbgRenderOcr(r) {
  dbgStats([
    ["区域", r.label || "-"],
    ["块数", r.count || 0],
    ["耗时", (r.elapsed_ms || 0) + "ms"],
    ["引擎", r.engine ? "可用" : "不可用"],
    ["原图", `${r.orig_width}x${r.orig_height}`],
  ]);
  if (r.chat_type) {
    dbgSetChatType(r.chat_type, r.chat_type_label, {
      member_count: r.member_count,
      reason: r.chat_type_reason || "",
    });
  }  if (r.stats) {
    const s = r.stats;
    dbgStats([
      ["灰度均值", s.mean],
      ["灰度最大", s.max],
      ["黑图", s.black ? "⚠ 是" : "否"],
    ]);
  }
  dbgDraw(r.image, r.width, r.height, r.items || [], "ocr");
  $("dbgCanvasMeta").textContent =
    `预览 ${r.width}x${r.height}（原图 ${r.orig_width}x${r.orig_height}）· 像素框 ${JSON.stringify(r.box || [])}`;
  $("dbgText").innerHTML = (r.items || []).length
    ? r.items.map((b) => `<div class="blk"><span class="c">[${b.x},${b.y} ${b.w}x${b.h}]</span><span>${escapeHtml(b.text)}</span></div>`).join("")
    : "<div>未检出文本</div>";
  dbgRaw(r);
}

function mediaKindLabel(kind) {
  return ({all: "全部媒体", emoji: "表情", image: "图片", video: "视频", file: "文件", audio: "语音"})[kind] || "未知媒体";
}

function dbgRenderMedia(r) {
  dbgClearChatType();
  dbgStats([
    ["区域", r.label || "-"], ["类型", mediaKindLabel(r.kind)],
    ["气泡数", r.count || 0],
    ...Object.entries(r.counts || {}).map(([kind, count]) => [mediaKindLabel(kind), count]),
  ]);
  dbgDraw(r.image, r.width, r.height, [], "media");
  $("dbgCanvasMeta").textContent =
    `${r.label || ""} · 原图 ${r.orig_width}x${r.orig_height} · 预览 ${r.width}x${r.height} · 像素框 ${JSON.stringify(r.box || [])} · 绿=图片 橙=文件 红=视频 紫=表情 蓝=语音`;
  const list = $("dbgText");
  list.replaceChildren();
  for (const b of (r.bubbles || [])) {
    const row = document.createElement("div");
    row.className = "blk";
    const coords = document.createElement("span");
    coords.className = "c";
    coords.textContent = `[${b.x},${b.y} ${b.w}x${b.h}]`;
    const detail = document.createElement("span");
    const confidence = typeof b.confidence === "number" && Number.isFinite(b.confidence)
      ? `${(Math.min(1, Math.max(0, b.confidence)) * 100).toFixed(0)}%` : "未提供";
    detail.textContent = `${mediaKindLabel(b.kind)} · 置信度 ${confidence} · 依据：${b.reason || "未提供识别依据"}` +
      (b.duration != null ? ` · 时长：${b.duration}` : "") +
      (b.text ? ` · ${b.text}` : "");
    row.append(coords, detail);
    list.appendChild(row);
  }
  if (!(r.bubbles || []).length) {
    list.textContent = `${r.label || "所选区域"}未检出${r.kind === "all" ? "媒体气泡" : mediaKindLabel(r.kind)}，可检查目标区域、标定或切换到包含该类消息的会话。`;
  }
  dbgRaw(r);
}

function dbgRenderEnv(r) {
  const w = r.window || {};
  const sc = r.scale || {};
  const eng = r.ocr_engine || {};
  const lines = [];
  lines.push(`<h4>依赖</h4>`);
  (r.deps || []).forEach((d) => {
    lines.push(`<div class="row-item"><span class="k">${escapeHtml(d.label)} <span class="hint">${escapeHtml(d.why)}</span></span>` +
      `<span class="v">${d.ok ? "✅" : "❌"} ${escapeHtml(d.detail)}</span></div>`);
  });
  lines.push(`<h4>微信窗口</h4>`);
  lines.push(`<div class="row-item"><span class="k">hwnd</span><span class="v">${w.hwnd ? "0x" + Number(w.hwnd).toString(16) : "未找到"}</span></div>`);
  lines.push(`<div class="row-item"><span class="k">标题</span><span class="v">${escapeHtml(w.title || "-")}</span></div>`);
  lines.push(`<div class="row-item"><span class="k">窗口尺寸</span><span class="v">${(r.window_size || []).join("x") || "-"}</span></div>`);
  lines.push(`<h4>缩放档位</h4>`);
  lines.push(`<div class="row-item"><span class="k">生效档</span><span class="v">${sc.active}% (k=${sc.k})</span></div>`);
  lines.push(`<div class="row-item"><span class="k">实测 DPI</span><span class="v">${sc.measured ? sc.measured + "%" : "未测得"}</span></div>`);
  lines.push(`<div class="row-item"><span class="k">支持区间</span><span class="v">${sc.min || 100}% ~ ${sc.max || 175}%${sc.out_of_range ? " ⚠ 已钳制" : ""}</span></div>`);
  const dt = r.detect || {};
  lines.push(`<div class="row-item"><span class="k">标定模式</span><span class="v">${dt.mode === "manual" ? "✅ 手动标定（已保存）" : dt.mode === "pixel" ? "✅ 像素探测（自适应）" : "⚠ 静态标定（兜底）"}</span></div>`);
  lines.push(`<h4>三区域</h4>`);
  (r.regions || []).forEach((g) => {
    lines.push(`<div class="row-item"><span class="k">${escapeHtml(g.label)}</span><span class="v">px ${g.px.join(",")}</span></div>`);
  });
  lines.push(`<h4>其它</h4>`);
  lines.push(`<div class="row-item"><span class="k">OCR 引擎</span><span class="v">${eng.ok ? "✅" : "❌"} ${escapeHtml(eng.detail || "")} (${eng.load_ms || 0}ms)</span></div>`);
  lines.push(`<div class="row-item"><span class="k">配置文件</span><span class="v">${r.config && r.config.exists ? "✅" : "⚠"} ${escapeHtml((r.config && r.config.path) || "-")}</span></div>`);
  lines.push(`<div class="row-item"><span class="k">连接目标</span><span class="v">${escapeHtml((r.target || {}).name || "-")} ${(r.target || {}).has_token ? "✅ token" : "❌ 无 token"}</span></div>`);
  $("dbgEnv").innerHTML = lines.join("");
  dbgRaw(r);
}

/** 显示缩放参数、区域坐标和后端生成的标定预览图。 */
function dbgRenderScale(r) {
  const d = r.detect || {};
  dbgOut("dbgScaleOut", [
    ["生效档", `${r.active}%`, r.out_of_range ? "warn" : "ok"],
    ["实测 DPI", r.measured ? r.measured + "%" : "未测得"],
    ["支持区间", `${r.min}% ~ ${r.max}%`],
    ["基准档 / k", `${r.calib}% / ${r.k}`],
    ["窗口尺寸", (r.window_size || []).join("x")],
    ["标定模式", d.mode === "manual" ? "✅ 手动标定（已保存）" : d.mode === "pixel" ? "✅ 像素探测（自适应）" : "⚠ 静态标定（兜底）",
      d.mode === "static" ? "warn" : "ok"],
    ["分隔线 x", d.divider_x == null ? "未探测到" : d.divider_x],
    ["顶栏线 y", d.header_y == null ? "未探测到" : d.header_y],
    ["输入区 y", d.input_top_y == null ? "未探测到" : d.input_top_y],
    ...(r.regions || []).map((g) => [g.label, `px ${g.px.join(",")}`]),
  ]);
  if (r.image && r.display) {
    const cv = $("dbgScaleCanvasEl");
    const img = new Image();
    img.onload = () => {
      cv.width = r.display[0];
      cv.height = r.display[1];
      cv.getContext("2d").drawImage(img, 0, 0);
    };
    img.src = r.image;
  }
  dbgRaw(r);
}


async function dbgRun(name, args, onOk) {
  const r = await callApi(name, args || []);
  if (!r || !r.ok) {
    toast("失败: " + ((r && r.error) || "未知错误"));
    dbgRaw(r);
    return null;
  }
  if (onOk) onOk(r);
  return r;
}

function bootDebug() {
  dbgInitFold();
  bootRegionEditor();
  $("btnDbgEnv").onclick = async () => {
    const r = await dbgRun("debug_env", [], dbgRenderEnv);
    if (r) toast("环境体检完成");
  };
  $("btnDbgScale").onclick = async () => {
    const v = parseInt($("dbgScalePct").value, 10);
    if (!v) {
      toast("请填写缩放档位百分比");
      return;
    }
    await dbgRun("debug_scale", [v], (r) => {
      dbgRenderScale(r);
      toast(`档位已设为 ${r.active}%${r.out_of_range ? "（超出区间，已钳制）" : ""}`);
    });
  };
  $("btnDbgScaleAuto").onclick = async () => {
    const r = await dbgRun("debug_scale", [0], (x) => {
      const m = x.measured || 0;
      if (!m) {
        toast("未测得 DPI，无法自动设置");
        dbgRenderScale(x);
        return;
      }
      dbgRenderScale(x);
    });
    if (r && r.measured) {
      await dbgRun("debug_scale", [r.measured], (x) => {
        dbgRenderScale(x);
        toast(`已按实测 DPI 设为 ${x.active}%`);
      });
    }
  };
  $("btnDbgScaleProbe").onclick = async () => {
    await dbgRun("debug_scale", [0], (x) => {
      dbgRenderScale(x);
      toast("当前档位预览");
    });
  };
  $("btnDbgShot").onclick = async () => {
    await dbgRun("debug_shot", [$("dbgRegion").value], (r) => {
      dbgStats([["区域", r.label], ["预览", `${r.width}x${r.height}`], ["原图", `${r.orig_width}x${r.orig_height}`]]);
      dbgDraw(r.image, r.width, r.height, [], "");
      $("dbgCanvasMeta").textContent = `像素框 ${JSON.stringify(r.box || [])}`;
      $("dbgText").innerHTML = "<div>（纯抓图，无识别）</div>";
      dbgRaw(r);
      toast("已抓图");
    });
  };
  $("btnDbgOcr").onclick = async () => {
    const btn = $("btnDbgOcr");
    btn.textContent = "识别中…";
    await dbgRun("debug_ocr", [$("dbgRegion").value], (r) => {
      dbgRenderOcr(r);
      toast(`识别完成: ${r.count} 块`);
    });
    btn.textContent = "区域 OCR";
  };
  for (const [id, kind] of [["btnDbgMedia", "all"], ["btnDbgEmoji", "emoji"], ["btnDbgImage", "image"], ["btnDbgVideo", "video"]]) {
    $(id).onclick = async () => {
      dbgToggleFold("dbgCard1", true);
      const r = await dbgRun("debug_media", [kind, $("dbgRegion").value], dbgRenderMedia);
      if (r) toast(`${mediaKindLabel(kind)}识别完成：${r.count} 个气泡`);
    };
  }
  $("btnDbgBadge").onclick = async () => {
    await dbgRun("debug_badges", [], (x) => {
      dbgStats([["红圈数", x.count || 0]]);
      dbgDraw(x.image, x.width, x.height, [], "badge");
      $("dbgCanvasMeta").textContent = "红圈已框出（红框）";
      $("dbgText").innerHTML = (x.badges || []).length
        ? x.badges.map((b) => `<div class="blk"><span class="c">[${b.l},${b.t} ${b.r - b.l}x${b.b - b.t}]</span><span>未读</span></div>`).join("")
        : "<div>未检出红圈</div>";
      dbgRaw(x);
    });
  };
  $("btnDbgTitle").onclick = async () => {
    await dbgRun("debug_title", [], (x) => {
      dbgStats([["原始标题", x.raw || "(空)"], ["会话名", x.name || "-"], ["会话类型", x.chat_type_label || "-"], ["群聊", x.is_group ? "是" : "否"], ["人数", x.member_count == null ? "-" : x.member_count]]);
      dbgSetChatType(x.chat_type, x.chat_type_label, {
        member_count: x.member_count,
        reason: x.chat_type_reason || "",
      });
      $("dbgText").innerHTML = `<div class="blk"><span class="c">原始</span><span>${escapeHtml(x.raw || "(空)")}</span></div>` +
        `<div class="blk"><span class="c">规范名</span><span>${escapeHtml(x.name || "-")}</span></div>` +
        `<div class="blk"><span class="c">类型</span><span>${escapeHtml(x.chat_type_label || "-")}${x.member_count != null ? ` / ${escapeHtml(String(x.member_count))} 人` : ""}</span></div>` +
        `<div class="blk"><span class="c">依据</span><span>${escapeHtml(x.chat_type_reason || "-")}</span></div>`;
      dbgRaw(x);
    });
  };
  $("btnDbgMsgs").onclick = async () => {
    await dbgRun("debug_messages", [true], (x) => {
      const t = x.title || {};
      dbgStats([["消息条数", x.count || 0], ["当前会话", t.name || "-"], ["会话类型", t.chat_type_label || "-"], ["群聊", t.is_group ? "是" : "否"]]);
      dbgSetChatType(t.chat_type, t.chat_type_label, {
        member_count: t.member_count,
        reason: t.chat_type_reason || "",
      });
      const isGroup = Boolean(t.is_group);
      $("dbgText").innerHTML = (x.rows || []).length
        ? x.rows.map((m) => {
            const mm = (m.media || []).map((b) => `[${b.kind}${b.filename ? ":" + b.filename : ""}]`).join(" ");
            const flag = m.blocked ? "🚫" : "";
            const sender = isGroup && m.sender ? `${m.sender}：` : "";
            return `<div class="blk"><span class="c">${escapeHtml(m.type)} ${flag}</span>` +
              `<span>${escapeHtml(sender)}${escapeHtml(m.text || "")} ${mm ? `<span class="hint">${escapeHtml(mm)}</span>` : ""}` +
              `${m.blocked_reason ? `<span class="hint">(${escapeHtml(m.blocked_reason)})</span>` : ""}</span></div>`;
          }).join("")
        : "<div>未解析出消息（先切到有消息的会话）</div>";
      dbgRaw(x);
    });
  };
  $("btnDbgFilter").onclick = async () => {
    await dbgRun("debug_filter", [$("dbgFilterName").value, $("dbgFilterTitle").value], (x) => {
      dbgOut("dbgFilterOut", [
        ["输入", x.input || "(空)"],
        ["归一化", x.normalized || "-"],
        ["判定", x.blocked ? "🚫 拦截" : "✅ 放行", x.blocked ? "no" : "ok"],
        ["原因", x.reason || "-"],
        ["放行词", (x.allow || []).join(",") || "(无)"],
        ["扩展词", (x.extra || []).join(",") || "(无)"],
      ]);
      dbgRaw(x);
    });
  };
  $("btnDbgDedup").onclick = async () => {
    await dbgRun("debug_dedup", [$("dbgDedupChat").value, $("dbgDedupText").value, $("dbgDedupSeq").value], (x) => {
      dbgOut("dbgDedupOut", [
        ["会话", x.chat],
        ["client_seq", x.client_seq],
        ["指纹", x.fingerprint],
        ["首次", x.first.dup ? "判重 " + x.first.reason : "通过", x.first.dup ? "no" : "ok"],
        ["二次", x.second.dup ? "判重 " + x.second.reason : "通过", x.second.dup ? "no" : "ok"],
        ["时间窗", x.window_sec + "s"],
      ]);
      dbgRaw(x);
    });
  };
  $("btnDbgSendDry").onclick = async () => {
    await dbgRun("debug_send", [$("dbgSendChat").value, $("dbgSendText").value, true], (x) => {
      dbgOut("dbgSendOut", [
        ["输入框", JSON.stringify(x.input_box)],
        ["目标会话", x.chat || "-"],
        ["过滤", x.blocked ? "🚫 拦截 " + (x.blocked_reason || "") : "✅ 放行", x.blocked ? "no" : "ok"],
        ["模式", "仅体检（未发送）", "warn"],
      ]);
      dbgRaw(x);
    });
  };
  $("btnDbgSendReal").onclick = async () => {
    if (!confirm("确认真发一条消息到目标会话？")) return;
    await dbgRun("debug_send", [$("dbgSendChat").value, $("dbgSendText").value, false], (x) => {
      dbgOut("dbgSendOut", [
        ["输入框", JSON.stringify(x.input_box)],
        ["目标会话", x.chat || "-"],
        ["切会话", x.switched === undefined ? "-" : (x.switched ? "✅ 成功" : "❌ 失败"), x.switched ? "ok" : "no"],
        ["发送", x.sent === undefined ? "-" : (x.sent ? "✅ 成功" : "❌ 失败"), x.sent ? "ok" : "no"],
        ["结果", x.message || "-"],
      ]);
      dbgRaw(x);
      toast(x.message || "已发送");
    });
  };
  $("btnDbgFiles").onclick = async () => {
    await dbgRun("debug_files", [$("dbgFileName").value], (x) => {
      dbgOut("dbgFileOut", [
        ["接收目录", (x.dirs || []).join(" | ") || "(未找到)"],
        ["查询", x.query || "-"],
        ["命中文件", x.found || "(未命中)", x.found ? "ok" : "warn"],
      ]);
      dbgRaw(x);
    });
  };
  $("btnDbgVoice").onclick = async () => {
    await dbgRun("debug_voice", [], (x) => {
      dbgOut("dbgVoiceOut", [
        ["ASR 端点", x.asr_endpoint || "(未配置)", x.asr_configured ? "ok" : "warn"],
        ["语音通道", x.voice_channel ? "✅ 可用" : "❌ 不可用", x.voice_channel ? "ok" : "no"],
        ["最近音频", (x.recent_audio || []).join(",") || "(无)"],
        ["错误", x.error || "-"],
      ]);
      dbgRaw(x);
    });
  };
  $("btnDbgAll").onclick = async () => {
    toast("一键全检开始…");
    await dbgRun("debug_env", [], dbgRenderEnv);
    await dbgRun("debug_title", [], (x) => {
      dbgSetChatType(x.chat_type, x.chat_type_label, {
        member_count: x.member_count,
        reason: x.chat_type_reason || "",
      });
    });
    await dbgRun("debug_ocr", [$("dbgRegion").value], dbgRenderOcr);
    await dbgRun("debug_media", ["all", $("dbgRegion").value], dbgRenderMedia);
    await dbgRun("debug_badges", [], (x) => {
      $("dbgText").innerHTML = (x.badges || []).length
        ? x.badges.map((b) => `<div class="blk"><span class="c">[${b.l},${b.t}]</span><span>未读红圈</span></div>`).join("")
        : "<div>未检出红圈</div>";
      dbgRaw(x);
    });
    toast("全检完成");
  };
}


boot();
