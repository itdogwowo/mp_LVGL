// projects/slave/pages/pixel_lab_rgb.js — PixelLab RGB (WS2812) 頁
//
// 對應 ui/lvgl/page/pixel_lab_rgb.py
//
// 與 APA 頁共用 SimplePage，只差 mode / 標題 / 主色：
// mode="rgb" 讓 pixel_lab_common 選綠色系的底色與 bar。

import { SimplePage } from "./pixel_lab_common.js";

export const meta = {
  id: "pixel_lab_rgb",
  title: "PixelLab RGB",
  icon: "lightbulb",
  desc: "WS2812",
  order: 2,
  accent: 0x0E9F6E,
};

const _page = new SimplePage("rgb", "PixelLab RGB", "WS2812", 0x0E9F6E);
export let scr = null;

export function build() {
  scr = _page.build();
  return scr;
}

export function on_enter() {
  _page.on_enter();
}

export function on_leave() {
  _page.on_leave();
}

export function on_enc(d) {
  _page.on_enc(d);
}

export function on_confirm() {
  return _page.on_confirm();
}

export function on_exit() {
  return _page.on_exit();
}

export function update(run) {
  _page.update(run);
}
