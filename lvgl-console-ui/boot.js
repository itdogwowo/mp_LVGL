// lvgl-console-ui/boot.js — 模擬器啟動
//
// 這裡刻意分成「工具」與「工程」兩塊：
//   工具（這支檔＋host/frameworks/inspect/cli）只知道怎麼跑，不知道你在做哪個 UI
//   工程（projects/<id>/）只有 pages + project.json + seed
//
// 啟動順序：
//   1. 讀 ../projects.json → 決定開哪個專案（?project=<id>，預設 default）
//   2. 讀 projects/<id>/project.json → 綁定的 theme / 尺寸 / 字型 / 轉換目標
//   3. 動態載入 packages/themes/<theme.id> → u.applyTheme()
//   4. 建 display、載入 .bin 字型、跑 seed
//   5. 動態載入 projects/<id>/pages/index.js（副作用：註冊頁面）
//   6. app.build_all() → app.go("launcher")
//
// 裝置上對應的是 board.py + main.py；第 5 步之後就是「跟裝置同一套」的 app 流程。

import lv from "@lvui/frameworks/lvgl/lv.js";
import "@lvui/frameworks/lvgl/anim.js"; // 註冊 lv.anim_t + tick 掛勾
import { bus } from "@packages/lv-app/bus.js";
import * as registry from "@packages/lv-app/registry.js";
import * as app from "@packages/lv-app/app.js";
import * as u from "@packages/lv-app/ui_common.js";
import { createDisplay } from "@lvui/host/display.js";
import { createInspector, pathOf } from "@lvui/inspect/inspector.js";
import { createHud } from "@lvui/inspect/hud.js";

const STEP_MS = 5; // 裝置主迴圈的 sleep(5)
const SCALE = 2;

// ══════════════════════════════════════════════════════════════════
//  Console / print → 右側面板
// ══════════════════════════════════════════════════════════════════
const consoleOrig = {
  log: console.log.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

const hud = createHud({
  onSelectOid: (w) => {
    inspector.select(w);
    hud.showProps(w);
    hud.setTab("inspect");
  },
});

function log(kind, args) {
  const text = args
    .map((a) => {
      if (typeof a === "string") return a;
      if (a instanceof Error) return `${a.message}\n${(a.stack || "").split("\n").slice(1, 4).join("\n")}`;
      try {
        return JSON.stringify(a);
      } catch {
        return String(a);
      }
    })
    .join(" ");
  hud.log(kind, text);
  const out = kind === "err" ? consoleOrig.error : kind === "warn" ? consoleOrig.warn : consoleOrig.log;
  out(...args);
}

globalThis.print = (...args) => log("out", args);
console.log = (...args) => log("out", args);
console.warn = (...args) => log("warn", args);
console.error = (...args) => log("err", args);

// ══════════════════════════════════════════════════════════════════
//  1) 專案索引 → 2) project.json
// ══════════════════════════════════════════════════════════════════
const index = await fetch("./projects.json", { cache: "no-store" }).then((r) => {
  if (!r.ok) throw new Error(`projects.json HTTP ${r.status}`);
  return r.json();
});
const wanted = new URLSearchParams(location.search).get("project");
const entry =
  index.projects.find((p) => p.id === wanted) ||
  index.projects.find((p) => p.default) ||
  index.projects[0];
if (!entry) throw new Error("projects.json 裡沒有任何專案");

// 專案資料夾（以本頁 URL 為基準：/ → /projects/<id>/）
const projectBase = new URL(`./${entry.path.replace(/^\/+/, "")}/`, location.href);
const manifest = await fetch(new URL("project.json", projectBase), { cache: "no-store" }).then((r) => {
  if (!r.ok) throw new Error(`project.json HTTP ${r.status}`);
  return r.json();
});

// ══════════════════════════════════════════════════════════════════
//  3) theme 套件（設計庫）
// ══════════════════════════════════════════════════════════════════
const themeId = manifest.theme?.id ?? "traework";
const theme = await import(`@packages/themes/${themeId}/index.js`);
u.applyTheme(theme);
if (manifest.theme?.version && theme.version && manifest.theme.version !== theme.version) {
  log("warn", [
    `[theme] 版本不合：project 綁 ${themeId}@${manifest.theme.version}，` +
      `實際載入 ${theme.version}（UI 可能跟當初設計時不同）`,
  ]);
}

// ══════════════════════════════════════════════════════════════════
//  4) display + 字型 + 假資料
// ══════════════════════════════════════════════════════════════════
const canvas = document.getElementById("sim");
const overlay = document.getElementById("overlay");
const display = createDisplay(canvas, {
  w: manifest.display?.w ?? 320,
  h: manifest.display?.h ?? 240,
  scale: SCALE,
});
u.init(display);

// 裝置上方的身份列（哪個工程 / 解析度 / 風格）
document.getElementById("device-title").textContent = manifest.title ?? entry.id;
document.getElementById("device-res").textContent = `${display.w}×${display.h}`;
document.getElementById("device-theme").textContent = `${u.themeId}@${u.themeVersion}`;

const resolveFont = (p, fallback) => (p ? new URL(p, projectBase).href : fallback);
await u.init_fonts({
  zh: resolveFont(manifest.fonts?.zh, "./assets/fonts/zh_hant_16.bin"),
  icons: resolveFont(manifest.fonts?.icons, "./assets/fonts/icons_16.bin"),
});

const seedMod = await import(`@projects/${entry.id}/${manifest.seed ?? "seed.js"}`);
seedMod.seed?.();

// ══════════════════════════════════════════════════════════════════
//  檢視器（畫布疊層）
// ══════════════════════════════════════════════════════════════════
//  畫布上只畫框；文字一律寫到畫布外的資訊列（#inspect-bar）。
//  為什麼：文字疊在畫面上會蓋住 UI、元件貼邊時還會被裁掉，
//  而且「label 65×19」這種標籤會擋住你正要看的字（例如它自己）。
const inspectBar = document.getElementById("inspect-bar");
const escHtml = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let selectedW = null; // 離開 hover 後，資訊列要退回「已選取」那一筆

function renderInspectBar(w, kind) {
  if (!inspectBar) return;
  if (!w) {
    inspectBar.classList.remove("hot");
    inspectBar.innerHTML = `<span class="k">HOVER</span><span class="muted">把游標移到畫面上 · 點一下＝選取</span>`;
    return;
  }
  const text = typeof w.get_text === "function" ? w.get_text() : "";
  inspectBar.classList.toggle("hot", kind === "HOVER");
  inspectBar.innerHTML =
    `<span class="k">${kind}</span>` +
    `<span class="v">${escHtml(w.objClass)} #${w.oid}${text ? ` 「${escHtml(text)}」` : ""}</span>` +
    `<span class="muted">${w.w}×${w.h} · x=${w._ax} y=${w._ay} · ${escHtml(pathOf(w))}</span>`;
}

const inspector = createInspector({
  canvas,
  overlay,
  display,
  onSelect: (w) => {
    selectedW = w;
    hud.showProps(w);
    renderInspectBar(w, "SELECT");
  },
  // 游標離開 → 退回已選取那一筆（不要整個清空，否則選了什麼就看不到）
  onHover: (w) => renderInspectBar(w ?? selectedW, w ? "HOVER" : "SELECT"),
});

/**
 * 依視窗大小挑整數倍率（裝置置中、不留一大片空白）。
 *
 * 為什麼是整數：canvas 用 image-rendering: pixelated，2.4× 會讓像素大小不一致
 * （有些 2px、有些 3px），看起來像糊掉。整數倍率才是「點陣面板」該有的樣子。
 */
const stageEl = document.querySelector(".stage");
const PAD_X = 80;
const PAD_Y = 220; // 身份列 + 狀態列 + 快捷鍵列
let _fitTimer = 0;
function fitDevice() {
  if (!stageEl) return;
  const aw = Math.max(320, stageEl.clientWidth - PAD_X);
  const ah = Math.max(240, stageEl.clientHeight - PAD_Y);
  const s = Math.max(2, Math.min(4, Math.floor(Math.min(aw / display.w, ah / display.h))));
  if (s !== display.scale) display.setScale(s);
  inspector.sync();
}
window.addEventListener("resize", () => {
  clearTimeout(_fitTimer);
  _fitTimer = setTimeout(fitDevice, 120);
});
fitDevice();

// ══════════════════════════════════════════════════════════════════
//  Platform（對應 board.py 的 _make_snapshot_inputs）
// ══════════════════════════════════════════════════════════════════
const platform = {
  enc_delta: () => bus.consume_input("enc", { idx: 0 }) | 0,
  confirm: () => bus.consume_input("pin", { key: "encC" }) !== 0,
  exit: () => bus.consume_input("pin", { key: "btn" }) !== 0,
  tick() {},
  take() {
    return [];
  },
  show() {},
};

// ══════════════════════════════════════════════════════════════════
//  5) 頁面（副作用：register）→ 6) 預建 + 首頁
// ══════════════════════════════════════════════════════════════════
await import(`@projects/${entry.id}/${manifest.pages ?? "pages"}/index.js`);

app.init(platform);
app.build_all();
app.go("launcher");
hud.buildTree(display.screen);
hud.setProject?.(entry.id);

// ══════════════════════════════════════════════════════════════════
//  輸入：鍵盤 / 滾輪 → bus
// ══════════════════════════════════════════════════════════════════
const KEYMAP = {
  ArrowRight: () => bus.push_enc(+1),
  ArrowLeft: () => bus.push_enc(-1),
  ArrowUp: () => bus.push_enc(+1),
  ArrowDown: () => bus.push_enc(-1),
  Enter: () => bus.push_pin("encC"),
  " ": () => bus.push_pin("encC"),
  Escape: () => bus.push_pin("btn"),
  Backspace: () => bus.push_pin("btn"),
};

const toggleBtn = document.getElementById("inspector-toggle");
function setInspector(on) {
  inspector.enabled = on;
  toggleBtn?.classList.toggle("on", on);
}

window.addEventListener("keydown", (e) => {
  if (e.key === "i" || e.key === "I") {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    setInspector(!inspector.enabled);
    e.preventDefault();
    return;
  }
  const fn = KEYMAP[e.key];
  if (!fn) return;
  e.preventDefault();
  if (e.repeat) return; // 裝置：按住不重複觸發（去抖邊緣語義）
  fn();
});

toggleBtn?.addEventListener("click", () => setInspector(!inspector.enabled));

let wheelAcc = 0;
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    wheelAcc += e.deltaY;
    if (Math.abs(wheelAcc) >= 40) {
      bus.push_enc(wheelAcc > 0 ? +1 : -1);
      wheelAcc = 0;
    }
  },
  { passive: false }
);

// 操作列：◀ ▶ Enter Esc（沒有實體旋鈕/按鍵時用滑鼠，走同一條 bus）
document.querySelectorAll("[data-enc]").forEach((btn) => {
  btn.addEventListener("click", () => bus.push_enc(Number(btn.dataset.enc)));
});
document.querySelectorAll("[data-pin]").forEach((btn) => {
  btn.addEventListener("click", () => bus.push_pin(btn.dataset.pin));
});

// ══════════════════════════════════════════════════════════════════
//  專案切換 / 頁面切換
// ══════════════════════════════════════════════════════════════════
const projectSelect = document.getElementById("project-switch");
if (projectSelect) {
  projectSelect.innerHTML = index.projects
    .map((p) => `<option value="${p.id}"${p.id === entry.id ? " selected" : ""}>${p.title ?? p.id}</option>`)
    .join("");
  projectSelect.addEventListener("change", () => {
    const url = new URL(location.href);
    url.searchParams.set("project", projectSelect.value);
    location.href = url.toString();
  });
}

const pagesEl = document.getElementById("pages");
function renderPageButtons() {
  if (!pagesEl) return;
  pagesEl.innerHTML = "";
  const all = [{ id: "launcher", title: "首頁" }, ...registry.ordered()];
  for (const p of all) {
    const b = document.createElement("button");
    b.className = "pill";
    b.textContent = p.title;
    b.dataset.page = p.id;
    b.addEventListener("click", () => app.go(p.id));
    pagesEl.appendChild(b);
  }
}
renderPageButtons();

function syncPageButtons() {
  if (!pagesEl) return;
  for (const b of pagesEl.querySelectorAll("button")) {
    b.classList.toggle("active", b.dataset.page === app.cur);
  }
}

// ══════════════════════════════════════════════════════════════════
//  主迴圈
// ══════════════════════════════════════════════════════════════════
let acc = 0;
let last = performance.now();
let frames = 0;
let fps = 0;
let fpsT0 = performance.now();
let steps = 0;
let lastCur = null;

function countNodes(o) {
  if (!o) return 0;
  let n = 1;
  for (const c of o.children) n += countNodes(c);
  return n;
}

function frame(now) {
  const dt = Math.min(100, now - last);
  last = now;

  lv.tick_inc(dt);

  acc += dt;
  let guard = 0;
  while (acc >= STEP_MS && guard++ < 20) {
    acc -= STEP_MS;
    app.step();
    steps++;
  }

  display.render();
  inspector.redraw();
  frames++;

  if (app.cur !== lastCur) {
    lastCur = app.cur;
    hud.buildTree(display.screen);
    hud.showProps(null);
    inspector.clear();
    selectedW = null;
    renderInspectBar(null);
  }

  if (now - fpsT0 >= 500) {
    fps = Math.round((frames * 1000) / (now - fpsT0));
    frames = 0;
    fpsT0 = now;
    hud.stats({
      page: app.cur,
      fps,
      renderMs: display.lastRenderMs,
      steps,
      widgets: countNodes(display.screen),
      project: entry.id,
      theme: `${u.themeId}@${u.themeVersion}`,
    });
    syncPageButtons();
    reportMissingGlyphs();
  }

  requestAnimationFrame(frame);
}

requestAnimationFrame(frame);

// ══════════════════════════════════════════════════════════════════
//  缺字回報
// ══════════════════════════════════════════════════════════════════
const _reportedMissing = new Set();
function reportMissingGlyphs() {
  const fonts = [u.ZH, u.ICON_FONT, u.F_NUM_L, u.F_NUM_M, u.F_NUM_S, u.F_NUM_XL];
  for (const f of fonts) {
    if (!f || !f.missing) continue;
    for (const cp of f.missing) {
      const key = `${f.name || "font"}:${cp}`;
      if (_reportedMissing.has(key)) continue;
      _reportedMissing.add(key);
      const ch = String.fromCodePoint(cp);
      const hex = cp.toString(16).toUpperCase().padStart(4, "0");
      const isMont = String(f.name || "").startsWith("sys:");
      log("warn", [
        isMont
          ? `[font] ${f.name} 沒有 '${ch}' U+${hex} → 真機會是方框（中文請改用 u.ZH）`
          : `[font] ${f.name} 缺字 '${ch}' U+${hex} → 要補進字型子集`,
      ]);
    }
  }
}

// ══════════════════════════════════════════════════════════════════
//  對外（devtools / 腳本化測試）
// ══════════════════════════════════════════════════════════════════
window.sim = {
  lv,
  bus,
  app,
  display,
  registry,
  u,
  inspector,
  hud,
  project: entry.id,
  manifest,
  theme,
  enc: (d = 1) => bus.push_enc(d),
  confirm: () => bus.push_pin("encC"),
  exit: () => bus.push_pin("btn"),
  go: (id) => app.go(id),
  hit: (x, y) => inspector.hitTest(x, y),
  screenshot: () => canvas.toDataURL("image/png"),
};

log("out", [
  `[boot] ${manifest.title ?? entry.id} · ${display.w}×${display.h} · ` +
    `theme=${u.themeId}@${u.themeVersion} · ${registry.ordered().length} page(s)`,
]);
