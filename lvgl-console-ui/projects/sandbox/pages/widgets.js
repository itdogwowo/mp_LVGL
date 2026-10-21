// ui/page/widgets.js — 元件測試頁（開發用，不對應真機頁面）
//
// 目的：把框架支援的每一種 widget / style 一次畫出來，肉眼檢查版面。
// 之後每加一種 widget 或改 renderer，就先看這一頁有沒有壞 —— 比開六個真頁快。
//
// 這一頁**不會**被轉換到裝置（meta.dev = true，轉換時跳過）。

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_LIST, ITEM_SLIDER, ITEM_SWITCH, ITEM_BUTTON, ITEM_INFO } from "@packages/lv-app/nav.js";

export const meta = {
  id: "widgets",
  title: "元件測試",
  icon: "layout-dashboard",
  desc: "開發用·不對應真機",
  order: 90,
  accent: 0x5b6b8c,
  dev: true,
};

const nav = new Nav();
export let scr = null;
let _sl = null;
let _sl_val = null;
let _arc = null;
let _sw = null;
let _lv_ok = 0; // 讓 pulse 的目標看得出來在呼吸

export function build() {
  nav.reset();
  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);

  // 標題
  u.mk_label(scr, "元件測試", 10, 6, u.TEXT, u.ZH);
  const pill = u.mk_label(scr, "16px 真機字型", 0, 8, u.TEXT3, u.ZH);
  pill.align(lv.ALIGN.TOP_RIGHT, -10, 0);

  // ── 按鈕三態 ──
  const b1 = u.mk_btn(scr, "主要", 10, 34, 62, 26, "primary");
  nav.add(b1, ITEM_BUTTON, { on_change: () => print("[widgets] primary") });
  const b2 = u.mk_btn(scr, "次要", 80, 34, 62, 26, "secondary");
  nav.add(b2, ITEM_BUTTON, { on_change: () => print("[widgets] secondary") });
  const b3 = u.mk_btn(scr, "警示", 150, 34, 62, 26, "danger");
  nav.add(b3, ITEM_BUTTON, { on_change: () => print("[widgets] danger") });

  // ── switch + LED ──
  _sw = u.mk_switch(scr, 224, 35, false);
  nav.add(_sw, ITEM_SWITCH, { on_change: _toggle });
  const led = u.mk_led(scr, 282, 37, 12, true);
  u.pulse(led, 1200, 90, 255); // 呼吸燈：驗證 anim 有在跑

  // ── slider ──
  u.mk_label(scr, "數值", 10, 74, u.TEXT2, u.ZH);
  _sl_val = u.mk_label(scr, "50", 284, 74, u.TEXT, u.F_NUM_M);
  _sl = u.mk_slider(scr, 10, 96, 296, 0, 100, 50);
  nav.add(_sl, ITEM_SLIDER, { on_change: _adj });

  // ── arc ──
  _arc = u.mk_arc(scr, 12, 116, 92, u.PRIMARY, 0, 255);
  _arc.set_value(170);
  u.mk_label(scr, "170 / 255", 30, 152, u.TEXT, u.ZH);

  // ── list ──
  const [lst, btns] = u.mk_list(scr, 118, 116, 190, 116, ["項目 一", "項目 二", "項目 三"], u.ZH);
  u.list_select(btns, 1, u.PRIMARY);
  nav.add(lst, ITEM_LIST, { on_change: (d) => _pick(btns, d) });

  // ── 卡片 + 圖示 ──
  const card = u.mk_card(scr, 10, 214, 300, 20);
  card.set_style_bg_opa(0, 0);
  const names = ["wifi", "settings", "sun", "zap", "thermometer", "sliders-horizontal"];
  names.forEach((n, i) => u.mk_icon(card, n, 4 + i * 22, 2, u.TEXT2));

  nav.paint();
  return scr;
}

function _adj(d) {
  const v = Math.max(0, Math.min(100, _sl.get_value() + d));
  _sl.set_value(v, 0);
  _sl_val.set_text(String(v));
  _arc.set_value(Math.round((v / 100) * 255), 0);
}

function _pick(btns, d) {
  // list 的選中位置存在 nav 之外（跟 control_panel 一樣由頁面自己記）
  _lv_ok = (_lv_ok + d + btns.length) % btns.length;
  u.list_select(btns, _lv_ok, u.PRIMARY);
}

function _toggle() {
  u.sw_set(_sw, !u.sw_get(_sw));
  print(`[widgets] switch -> ${u.sw_get(_sw) ? "ON" : "OFF"}`);
}

export function on_enter() {
  nav.focus(0);
}
export function on_leave() {
  if (nav.is_editing()) nav.exit();
}
export function on_enc(d) {
  nav.enc(d);
}
export function on_confirm() {
  nav.confirm();
  return null;
}
export function on_exit() {
  return nav.exit();
}
export function update(_run) {}

