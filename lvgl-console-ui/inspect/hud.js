// dev/hud.js — 右側面板（屬性 / 元件樹 / 資產 / Console）
//
// 這裡只做「把資料變成 DOM」。資料一律由 boot.js 或 inspector 提供，
// 這樣面板本身不需要知道 app / display / bus 的存在。

import { pathOf, locatorOf, ALIGN_NAME, FLAG_NAME } from "./inspector.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const flagsOf = (w) => {
  const out = [];
  for (const [name, bit] of Object.entries(FLAG_NAME)) {
    if (w.has_flag?.(Number(bit))) out.push(name);
  }
  return out;
};

function css(color) {
  if (color == null) return null;
  return typeof color === "string" ? color : color.css();
}

export function createHud({ onSelectOid } = {}) {
  const statsEl = document.getElementById("stats");
  const tabsEl = document.getElementById("tabs");
  const panels = {
    inspect: document.getElementById("panel-inspect"),
    tree: document.getElementById("panel-tree"),
    assets: document.getElementById("panel-assets"),
    console: document.getElementById("panel-console"),
  };
  const logEl = document.getElementById("log");
  const byOid = new Map();
  let currentTab = "inspect";
  let selectedOid = null;

  // ── 分頁 ──
  tabsEl?.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) setTab(b.dataset.tab);
  });

  function setTab(name) {
    currentTab = name;
    for (const b of tabsEl.querySelectorAll("button")) b.classList.toggle("active", b.dataset.tab === name);
    for (const [k, el] of Object.entries(panels)) el?.classList.toggle("hidden", k !== name);
    if (name === "assets") loadAssets();
  }

  // ── 狀態列 ──
  function stats({ page, fps, renderMs, steps, widgets }) {
    if (!statsEl) return;
    statsEl.innerHTML = `
      <div class="stat"><div class="k">page</div><div class="v">${esc(page ?? "—")}</div></div>
      <div class="stat"><div class="k">fps</div><div class="v">${fps ?? "—"}</div></div>
      <div class="stat"><div class="k">render</div><div class="v">${(renderMs ?? 0).toFixed(2)}<span style="font-size:10px;color:#626a7d"> ms</span></div></div>
      <div class="stat"><div class="k">widgets</div><div class="v">${widgets ?? 0}</div></div>
    `;
  }

  // ── 屬性 ──
  function showProps(w) {
    if (!panels.inspect) return;
    if (!w) {
      selectedOid = null;
      panels.inspect.innerHTML = `
        <div class="empty">
          <div class="empty__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M4 4l7 16 2.5-6.5L20 11 4 4z" />
            </svg>
          </div>
          <h3>選一個元件</h3>
          <p>把游標移到畫面上會標出元件框；點一下＝選取，這裡會顯示它的屬性、建立位置，以及焦點狀態。</p>
          <div class="keys"><span><kbd>I</kbd> 開關檢視器</span></div>
        </div>`;
      markTreeSelection();
      return;
    }
    selectedOid = w.oid;

    const font = w.getStyle?.("text_font");
    const fontDesc = font
      ? `${esc(font.name ?? "font")} · ${font.px ?? font.size ?? "?"}px` +
        (font.lineHeight ? ` · lineH ${font.lineHeight}` : "")
      : "（繼承／未設定）";
    const bg = css(w.getStyle?.("bg_color"));
    const bgOpa = w.getStyle?.("bg_opa");
    const bw = w.getStyle?.("border_width");
    const bc = css(w.getStyle?.("border_color"));
    const radius = w.getStyle?.("radius");
    const ow = w.getStyle?.("outline_width");
    const oc = css(w.getStyle?.("outline_color"));
    const text = typeof w.get_text === "function" ? w.get_text() : null;

    // 索引路徑：從 screen 起算的 child index（例：4/2/1）。
    // 為什麼要這個：oid 會隨程式碼增減而跳號，原始碼行號在迴圈裡又對應到 N 個元件，
    // 只有「索引 + 類別 + 文字 + 尺寸座標」合起來才足以唯一描述一個元件。
    const chain = [];
    for (let n = w; n; n = n.parent) chain.unshift(n);
    const idxPath = chain
      .slice(1)
      .map((n) => (n.parent ? n.parent.children.indexOf(n) : 0))
      .join("/");
    const align = w._align ? `${ALIGN_NAME[w._align.type] ?? w._align.type} (${w._align.dx}, ${w._align.dy})` : "—";
    const value =
      typeof w.get_value === "function"
        ? `${w.get_value()}${w._max !== undefined ? ` / ${w._min}..${w._max}` : ""}`
        : null;

    const rows = [
      ["位置", `x=${w.x} y=${w.y}　絕對 ${w._ax},${w._ay}`],
      ["尺寸", `${w.w} × ${w.h}`],
      ["對齊", align],
      ["字型", fontDesc],
      ["文字色", colorRow(css(w.getStyle?.("text_color")))],
      ["底色", bg ? `${colorRow(bg)}　opa ${bgOpa ?? 255}` : "—"],
      ["外框", bw ? `${bw}px ${colorRow(bc)}` : "—"],
      ["圓角", radius != null ? `${radius}px` : "—"],
      ["焦點框", ow ? `${ow}px ${colorRow(oc)}` : "—"],
      ["flag", flagsOf(w).join(" ") || "—"],
    ];
    if (value !== null) rows.push(["數值", value]);
    rows.push(["子元件", String(w.children.length)]);
    rows.push(["索引", `screen/${idxPath}`]);
    rows.push(["路徑", pathOf(w)]);

    // 一顆就夠：定位字串已含 file:line、索引路徑、類別、尺寸座標
    // （`screen › obj #68` 只是索引路徑的好看寫法，oid 又會跳號 → 不需要第二顆）
    const locator = locatorOf(w);
    const src =
      `<div class="src">` +
      (w._src
        ? `<span>${esc(w._src.file)}:${w._src.line}` +
          (w._src.via ? `<span class="via">via ${esc(w._src.via)}</span>` : "") +
          `</span>`
        : `<span style="color:#626a7d">（無建立位置）</span>`) +
      `<button data-copy="${esc(locator)}">複製定位</button>` +
      `</div>`;

    panels.inspect.innerHTML = `
      <div class="props">
        <div class="title">
          <span class="badge ${esc(w.objClass)}">${esc(w.objClass)}</span>
          <span style="color:#626a7d">#${w.oid}</span>
          ${text !== null ? `<span style="color:#e7e9ee">「${esc(text)}」</span>` : ""}
        </div>
        <dl class="kv">
          ${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}
        </dl>
        ${src}
      </div>
    `;
    panels.inspect.querySelectorAll("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const el = e.currentTarget;
        navigator.clipboard?.writeText(el.dataset.copy);
        const old = el.textContent;
        el.textContent = "已複製";
        setTimeout(() => (el.textContent = old), 900);
      });
    });
    markTreeSelection();
  }

  function colorRow(c) {
    if (!c) return "—";
    return `<span class="sw" style="background:${esc(c)}"></span>${esc(c)}`;
  }

  // ── 元件樹 ──
  function buildTree(root) {
    if (!panels.tree) return;
    byOid.clear();
    const out = [];
    const walk = (w, depth) => {
      byOid.set(w.oid, w);
      const text = typeof w.get_text === "function" ? w.get_text() : "";
      const preview = text ? `<span class="txt">「${esc(text.slice(0, 14))}」</span>` : "";
      const focused = w.getStyle?.("outline_width") > 0 ? `<span style="color:#f9ab00">◉</span> ` : "";
      out.push(
        `<div class="node${w.oid === selectedOid ? " sel" : ""}" data-oid="${w.oid}" ` +
          `style="padding-left:${6 + depth * 12}px">${focused}<span class="cls">${esc(w.objClass)}</span> ` +
          `${preview}<span class="sz">${w.w}×${w.h}</span></div>`
      );
      for (const c of w.children) walk(c, depth + 1);
    };
    walk(root, 0);
    panels.tree.innerHTML = `<div class="tree">${out.join("")}</div>`;
    panels.tree.querySelectorAll(".node").forEach((el) => {
      el.addEventListener("click", () => {
        const w = byOid.get(Number(el.dataset.oid));
        if (w) onSelectOid?.(w);
      });
    });
  }

  function markTreeSelection() {
    if (!panels.tree) return;
    panels.tree.querySelectorAll(".node").forEach((el) => {
      el.classList.toggle("sel", Number(el.dataset.oid) === selectedOid);
    });
  }

  // ── 資產（字元 / 圖示） ──
  let assetsLoaded = false;
  let projectId = null;

  /** 由 boot 設定：資產盤點是「每個工程各自一份」。 */
  function setProject(id) {
    if (id === projectId) return;
    projectId = id;
    assetsLoaded = false;
  }

  async function loadAssets(force = false) {
    if (!panels.assets || (assetsLoaded && !force)) return;
    assetsLoaded = true;
    panels.assets.innerHTML = `<div class="empty">載入資產盤點 …</div>`;
    try {
      const q = projectId ? `?project=${encodeURIComponent(projectId)}` : "";
      const res = await fetch(`/api/assets-report${q}&t=${Date.now()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      renderAssets(await res.json());
    } catch (e) {
      panels.assets.innerHTML = `
        <div class="assets">
          <h3>還沒有盤點結果</h3>
          <p class="note">先跑一次掃描（讀 <code>projects/&lt;id&gt;/pages/*.js</code> 的字串與圖示，比對兩顆 .bin）：</p>
          <code class="cmd">node lvgl-console-ui/cli/assets.mjs</code>
          <p class="note">${esc(String(e.message || e))}</p>
        </div>`;
    }
  }

  function renderAssets(r) {
    if (!panels.assets) return;
    const chars = r.chars ?? { total: 0, missing: [] };
    const icons = r.icons ?? { used: [], unknown: [], missing_in_bin: [], unused: [] };
    const missChips = chars.missing.length
      ? chars.missing.map((m) => `<span class="chip bad">${esc(m.ch)} ${esc(m.cp)}</span>`).join("")
      : `<span class="chip good">全部都有</span>`;
    const iconChips = icons.used
      .map((n) => `<span class="chip ${icons.missing_in_bin.includes(n) ? "bad" : "good"}">${esc(n)}</span>`)
      .join("");
    panels.assets.innerHTML = `
      <div class="assets">
        <h3>字元 · ${chars.total} 個（非 ASCII，只算字串）</h3>
        <div class="chips">${missChips}</div>
        <p class="note">缺字＝裝置上會是方框。字型是子集，要補就得重新跑 lv_font_conv。</p>

        <h3>圖示 · 用到 ${icons.used.length} / 對照表 ${icons.total_in_map ?? "?"} 個</h3>
        <div class="chips">${iconChips || '<span class="chip">未使用</span>'}</div>
        ${icons.unknown.length ? `<p class="note">名稱不在 lv_icons 對照表：${icons.unknown.join(", ")}</p>` : ""}
        ${icons.unused.length ? `<p class="note">對照表裡沒用到：${icons.unused.join(", ")}</p>` : ""}

        <h3>重新產生字型</h3>
        <code class="cmd">${esc(r.command ?? "node lvgl-console-ui/cli/assets.mjs --print-cmd")}</code>
        <p class="note">產生時間：${esc(r.generated_at ?? "—")}</p>
      </div>`;
  }

  // ── Console ──
  function log(kind, text) {
    if (!logEl) return;
    const div = document.createElement("div");
    div.className = `line ${kind}`;
    div.textContent = text;
    logEl.appendChild(div);
    while (logEl.childElementCount > 500) logEl.removeChild(logEl.firstChild);
    if (currentTab === "console" || logEl.scrollHeight - logEl.scrollTop < logEl.clientHeight + 60) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  return { stats, showProps, buildTree, markTreeSelection, loadAssets, log, setTab, setProject };
}
