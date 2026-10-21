// projects/slave/pages/pixel_lab_apa.js — PixelLab APA 頁
//
// 對應 ui/lvgl/page/pixel_lab_apa.py
//
// 頁面本體（IO、選取 index、呼吸/選中亮度條）都在 pixel_lab_common.js 的
// SimplePage；這裡只負責 meta + 轉發，跟裝置上的分工一模一樣。

import { SimplePage } from "./pixel_lab_common.js";

export const meta = {
  id: "pixel_lab_apa",
  title: "PixelLab APA",
  icon: "sun",
  desc: "APA102 · 呼吸/選中",
  order: 2,
  accent: 0x6D5BD0,
};

const _page = new SimplePage("apa", "PixelLab APA", "APA102", 0x6D5BD0);
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
