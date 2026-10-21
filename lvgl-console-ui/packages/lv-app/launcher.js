// ui/launcher.js — 動態首頁（對應 ui/lvgl/launcher.py）
//
// 橫屏 320×240：卡片橫向輪播（旋鈕左右選、按下確認）。
// 卡片內容**全部來自 registry**：新增一頁 = 多一個檔案，這裡不用改。

import lv from "@lvui/frameworks/lvgl/lv.js";
import { ordered } from "./registry.js";
import * as u from "./ui_common.js";

export let scr = null;
export let cards = [];
let dots = [];
let _focus = 0;
let CX = 0;

const CARD_W = 160;
const CARD_H = 140;
const STRIDE = 176;
const FOCUS_Y = 48;
const IDLE_Y = 56;

export function build() {
  _focus = 0;
  dots = [];
  cards = [];
  CX = Math.floor((u.W - CARD_W) / 2);
  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);
  scr.set_style_bg_opa(255, 0);

  const title = u.mk_label(scr, "選擇功能", 0, 8, u.TEXT, u.ZH);
  title.align(lv.ALIGN.TOP_MID, 0, 8);
  const sub = u.mk_label(scr, "旋鈕切換 · 按下確認", 0, 28, u.TEXT3, u.ZH);
  sub.align(lv.ALIGN.TOP_MID, 0, 28);

  const metas = ordered();
  cards = [];
  for (const meta of metas) {
    const c = lv.obj(scr);
    c.set_size(CARD_W, CARD_H);
    c.set_style_bg_color(u.C(u.SURFACE), 0);
    c.set_style_bg_opa(255, 0);
    c.set_style_radius(12, 0);
    c.set_style_border_color(u.C(u.BORDER), 0);
    c.set_style_border_width(1, 0);
    c.set_style_pad_all(0, 0);
    c.remove_flag(lv.obj.FLAG.SCROLLABLE);

    const blk = lv.obj(c);
    blk.set_size(40, 40);
    blk.set_pos(14, 16);
    blk.set_style_bg_color(u.C(meta.accent), 0);
    blk.set_style_bg_opa(255, 0);
    blk.set_style_radius(8, 0);
    blk.set_style_border_width(0, 0);
    blk.set_style_pad_all(0, 0);
    blk.remove_flag(lv.obj.FLAG.SCROLLABLE);
    const ic = u.mk_icon(blk, meta.icon, 0, 0, 0xffffff);
    if (ic !== null) ic.align(lv.ALIGN.CENTER, 0, 0);

    const num = u.mk_label(c, String(meta.order).padStart(2, "0"), 0, 0, u.TEXT3, u.F_NUM_S);
    num.align(lv.ALIGN.TOP_RIGHT, -8, 8);

    u.mk_label(c, meta.title, 14, 68, u.TEXT, u.ZH);
    u.mk_label(c, meta.desc, 14, 92, u.TEXT3, u.ZH);
    cards.push(c);
  }

  // 分頁指示點（會亮：目前頁 = primary，其餘 = 灰）
  const n = cards.length;
  const x0 = Math.floor((u.W - (n * 8 + (n - 1) * 6)) / 2);
  for (let i = 0; i < n; i++) {
    const d = lv.obj(scr);
    d.set_size(8, 8);
    d.set_pos(x0 + i * 14, u.H - 40);
    d.set_style_radius(4, 0);
    d.set_style_bg_color(u.C(0xdadce0), 0);
    d.set_style_bg_opa(255, 0);
    d.set_style_border_width(0, 0);
    dots.push(d);
  }

  _layout();
  return scr;
}

function _layout() {
  const n = cards.length;
  for (let i = 0; i < n; i++) {
    const c = cards[i];
    // 相對位置：把 (i - focus) 繞回 [-n/2, n/2]
    // ⚠️ 不能用 ((i-f+n+floor(n/2))%n)-floor(n/2)：偶數頁時只會得到 [-1, 0]，
    //    非焦點卡片永遠落在左邊（2 頁的時候畫面看起來一直是偏一邊的）。
    let rel = (((i - _focus) % n) + n) % n;
    if (rel > n / 2) rel -= n;
    const x = CX + rel * STRIDE;
    const foc = rel === 0;
    c.set_pos(x, foc ? FOCUS_Y : IDLE_Y);
    c.set_style_opa(foc ? 255 : 160, 0);
    c.set_style_border_color(u.C(foc ? u.PRIMARY : u.BORDER), 0);
    c.set_style_border_width(foc ? 2 : 1, 0);
  }
  // 指示點反映目前頁（原本是靜態灰點，使用者看不出自己在第幾頁）
  for (let i = 0; i < dots.length; i++) {
    dots[i].set_style_bg_color(u.C(i === _focus ? u.PRIMARY : 0xdadce0), 0);
  }
}

export function on_enc(d) {
  const n = cards.length;
  if (!n) return;
  _focus = (((_focus + d) % n) + n) % n;
  _layout();
}

export function on_confirm() {
  const metas = ordered();
  if (!metas.length) return null;
  const target = metas[_focus].id;
  print(`[launcher] enter ${target}`);
  return target;
}

export function on_exit() {
  return false;
}

export function update(_run) {}
