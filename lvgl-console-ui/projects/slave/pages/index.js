// projects/slave/pages/index.js — 註冊這個工程的所有頁面（對應 ui/lvgl/page/__init__.py）
//
// 註冊順序＝launcher 的卡片順序由 meta.order 決定（不是這裡）。
// 容錯照裝置的 page/__init__.py：單頁載入失敗不拖垮其他頁（try-import 跳過）。
//
// 2026-10 改版：移除舊的 control_panel / pca9685（功能由 pixel_controller +
// pixel_lab_* 取代），目前 7 頁：
//   0 Pixel 控制  1 PixelLab PCA  2 PixelLab RGB  3 PixelLab APA
//   4 遙控器      5 ESP-NOW       6 系統設定

import { register } from "@packages/lv-app/registry.js";

const PAGES = [
  ["pixel_controller", () => import("./pixel_controller.js")],
  ["pixel_lab_pca", () => import("./pixel_lab_pca.js")],
  ["pixel_lab_rgb", () => import("./pixel_lab_rgb.js")],
  ["pixel_lab_apa", () => import("./pixel_lab_apa.js")],
  ["remote", () => import("./remote.js")],
  ["now_setting", () => import("./now_setting.js")],
  ["settings", () => import("./settings.js")],
  // 復原的參考頁（order 7）：遷移 pixel_controller 版面時拿來對照，完成後移除。
  ["control_panel", () => import("./control_panel.js")],
];

for (const [id, load] of PAGES) {
  try {
    register(await load());
  } catch (e) {
    console.warn(`[pages] skip ${id}:`, e.message);
  }
}
