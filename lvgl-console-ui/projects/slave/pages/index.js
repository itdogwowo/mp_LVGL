// projects/slave/pages/index.js — 註冊這個工程的所有頁面（對應 ui/lvgl/page/__init__.py）
//
// 註冊順序＝launcher 的卡片順序由 meta.order 決定（不是這裡）。
// 容錯照裝置的 page/__init__.py：單頁載入失敗不拖垮其他頁（try-import 跳過）。

import { register } from "@packages/lv-app/registry.js";

const PAGES = [
  ["remote", () => import("./remote.js")],
  ["now_setting", () => import("./now_setting.js")],
  ["control_panel", () => import("./control_panel.js")],
  ["pca9685", () => import("./pca9685.js")],
  ["pixel_controller", () => import("./pixel_controller.js")],
  ["pixel_lab_apa", () => import("./pixel_lab_apa.js")],
  ["pixel_lab_rgb", () => import("./pixel_lab_rgb.js")],
  ["pixel_lab_pca", () => import("./pixel_lab_pca.js")],
  ["settings", () => import("./settings.js")],
];

for (const [id, load] of PAGES) {
  try {
    register(await load());
  } catch (e) {
    console.warn(`[pages] skip ${id}:`, e.message);
  }
}
