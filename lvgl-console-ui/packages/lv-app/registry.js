// ui/registry.js — 頁面註冊表（對應 ui/lvgl/registry.py）
//
// 裝置端用 decorator：
//     @register(id="pixel_controller", title="Pixel 控制", icon="sliders-horizontal", order=0)
//     def build(): ...
//
// 這裡用 meta 物件 + register(mod)：
//     export const meta = { id: "pixel_controller", title: "Pixel 控制", ... }
//     export function build() { ... }
//
//     // page/index.js
//     register(pixel_controller)
//
// 差異只有「metadata 放哪」，語義完全一樣：build 一次、screen 永駐、
// launcher 依 order 排序自動長出卡片。

export const PAGES = {};

/**
 * 註冊一個頁面模組。
 * @param {object} mod  page 模組的 namespace（要有 meta.id / meta.title / build()）
 */
export function register(mod) {
  const m = mod.meta;
  if (!m || !m.id) throw new Error("[registry] page 缺少 meta.id");
  if (typeof mod.build !== "function") throw new Error(`[registry] ${m.id} 缺少 build()`);
  PAGES[m.id] = {
    id: m.id,
    title: m.title ?? m.id,
    icon: m.icon ?? "",
    desc: m.desc ?? "",
    order: m.order ?? 0,
    accent: m.accent ?? 0x1a73e8,
    status: m.status ?? "",
    build: mod.build,
    mod,
  };
  return mod;
}

export function ordered() {
  return Object.keys(PAGES)
    .sort((a, b) => PAGES[a].order - PAGES[b].order)
    .map((k) => PAGES[k]);
}

export function get(pageId) {
  return PAGES[pageId] ?? null;
}

export function clear() {
  for (const k of Object.keys(PAGES)) delete PAGES[k];
}
