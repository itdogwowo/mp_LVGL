// ui/ui_common.js — palette / 字型 / widget builder（對應 ui/lvgl/ui_common.py）
//
// 這個檔是「設計語言」的落點：所有頁面都透過它拿顏色、字型、常用元件，
// 所以改一次調色盤/圓角，全部頁面一起變。
//
// 跟 Python 版的差異（刻意的）：
//   1. W/H 由 init(plat) 注入（跟 Python 一樣）
//   2. 字型是非同步載入（瀏覽器要 fetch .bin）⇒ board 的 init_fonts() 改成 await
//   3. 沒有 set_num_fallback()（那是 binding 的坑，記在 DEV_NOTES）

import lv from "@lvui/frameworks/lvgl/lv.js";
import { loadBinFont, SystemFont } from "@lvui/host/font.js";
import * as fx from "./lv_ui_fx.js";
import { ICONS } from "./lv_icons.js";
import * as defaultTheme from "@packages/themes/traework/index.js";

// ====== 版面（由 init 注入） ======
export let W = 240;
export let H = 320;

// ====== 主題（token）======
// 值不是寫死在這裡：由 applyTheme() 從 packages/themes/<id> 填進來。
// 頁面永遠只讀 u.BG / u.TEXT / u.PRIMARY …，所以**換一個 theme 套件＝換一套風格**，
// 頁面一行都不用改（這就是「很多風格」的落點）。
export let theme = defaultTheme;
export let themeId = defaultTheme.id;
export let themeVersion = defaultTheme.version;

export let BG = 0xf5f5f5;
export let SURFACE = 0xffffff;
export let BORDER = 0xe0e0e0;
export let TEXT = 0x1f1f1f;
export let TEXT2 = 0x5f5f5f;
export let TEXT3 = 0x8f8f8f;
export let PRIMARY = 0x1a73e8;
export let SUCCESS = 0x188038;
export let WARNING = 0xf9ab00;
export let DANGER = 0xd93025;
export let TRACK = 0xdadce0;
export let FOCUS_BG = 0xe8f0fe;
export let DANGER_BG = 0xfce8e6;
export let R_CARD = 10;
export let R_BTN = 8;

// Montserrat 系列：裝置是 LVGL 內建點陣字型，這裡用同 px 的系統字型近似。
export let F_NUM_L = new SystemFont(22);
export let F_NUM_M = new SystemFont(16);
export let F_NUM_S = new SystemFont(12);
export let F_NUM_XL = new SystemFont(28);
let FONT_ALIAS = {};

/**
 * 套用一個 theme 套件（packages/themes/<id>/index.js）。
 * 在 build_all() 之前呼叫一次；之後頁面拿到的 u.* 就是該風格的 token。
 */
export function applyTheme(t) {
  theme = t ?? defaultTheme;
  themeId = theme.id ?? "unknown";
  themeVersion = theme.version ?? "0.0.0";

  const c = theme.colors ?? {};
  BG = c.bg ?? BG;
  SURFACE = c.surface ?? SURFACE;
  BORDER = c.border ?? BORDER;
  TEXT = c.text ?? TEXT;
  TEXT2 = c.text2 ?? TEXT2;
  TEXT3 = c.text3 ?? TEXT3;
  PRIMARY = c.primary ?? PRIMARY;
  SUCCESS = c.success ?? SUCCESS;
  WARNING = c.warning ?? WARNING;
  DANGER = c.danger ?? DANGER;
  TRACK = c.track ?? TRACK;
  FOCUS_BG = c.focus_bg ?? FOCUS_BG;
  DANGER_BG = c.danger_bg ?? DANGER_BG;

  R_CARD = theme.radii?.card ?? R_CARD;
  R_BTN = theme.radii?.button ?? R_BTN;

  const f = theme.fonts ?? {};
  F_NUM_L = new SystemFont(f.numL ?? 22);
  F_NUM_M = new SystemFont(f.numM ?? 16);
  F_NUM_S = new SystemFont(f.numS ?? 12);
  F_NUM_XL = new SystemFont(f.numXL ?? 28);
  FONT_ALIAS = {
    font_montserrat_12: F_NUM_S,
    font_montserrat_14: F_NUM_S,
    font_montserrat_16: F_NUM_M,
    font_montserrat_18: F_NUM_M,
    font_montserrat_20: F_NUM_L,
    font_montserrat_22: F_NUM_L,
    font_montserrat_24: F_NUM_XL,
    font_montserrat_26: F_NUM_XL,
    font_montserrat_28: F_NUM_XL,
  };
  return theme;
}
applyTheme(defaultTheme);

/** 注入螢幕尺寸（display 的 W/H，跟真機從 bus 讀 tft_width/height 同義）。 */
export function init(plat) {
  W = plat?.W ?? 240;
  H = plat?.H ?? 320;
}

// ====== 字型 ======
/** 繁中 16px 字型（真機 /ui/lvgl/src/zh_hant_16.bin 的同一份）。 */
export let ZH = null;
/** 圖示字型（Material Symbols 子集，icons_16.bin）。 */
export let ICON_FONT = null;
let _iconFontTried = false;

/**
 * 載入真機字型檔（.bin）。瀏覽器要多一個 await（裝置是同步的）。
 * @param {{zh?: string, icons?: string}} files  字型 URL；不給就用模擬器內建的
 */
export async function init_fonts(files = {}) {
  const zhUrl = files.zh ?? "./assets/fonts/zh_hant_16.bin";
  const iconUrl = files.icons ?? "./assets/fonts/icons_16.bin";
  try {
    ZH = await loadBinFont(zhUrl, "zh_hant_16");
    console.log(`[font] zh_hant_16 loaded (${ZH.glyphCount} glyphs, lineH=${ZH.lineHeight})`);
  } catch (e) {
    console.error("[font] zh_hant_16 載入失敗，中文會缺字:", e);
    ZH = null;
  }
  try {
    ICON_FONT = await loadBinFont(iconUrl, "icons_16");
    _iconFontTried = true;
    console.log(`[font] icons_16 loaded (${ICON_FONT.glyphCount} glyphs)`);
  } catch (e) {
    console.warn("[icons] 載入失敗（圖示會退成文字）:", e);
  }
}

/** 取第一個可用的字型（對齊 Python 的 font(*names)）。 */
export function font(...names) {
  for (const n of names) {
    const f = FONT_ALIAS[n];
    if (f) return f;
  }
  return F_NUM_M;
}

// ====== 顏色 ======
export function C(hexval) {
  return lv.color_hex(hexval);
}

// ====== 基礎 builder ======

export function mk_label(parent, text, x, y, color = TEXT, f = null) {
  const lb = lv.label(parent);
  lb.set_text(text);
  lb.set_pos(x, y);
  lb.set_style_text_color(C(color), 0);
  if (f) lb.set_style_text_font(f, 0);
  else if (ZH) lb.set_style_text_font(ZH, 0);
  return lb;
}

export function mk_card(parent, x, y, w, h) {
  const c = lv.obj(parent);
  c.set_size(w, h);
  c.set_pos(x, y);
  c.set_style_bg_color(C(SURFACE), 0);
  c.set_style_bg_opa(255, 0);
  c.set_style_radius(R_CARD, 0);
  c.set_style_border_color(C(BORDER), 0);
  c.set_style_border_width(1, 0);
  c.set_style_pad_all(0, 0);
  c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return c;
}

/** 頂欄 36px：返回符號 + 標題 + 右側狀態。 */
export function mk_appbar(scr, title, right = "") {
  const bar = lv.obj(scr);
  bar.set_size(W, 36);
  bar.set_pos(0, 0);
  bar.set_style_bg_color(C(SURFACE), 0);
  bar.set_style_bg_opa(255, 0);
  bar.set_style_radius(0, 0);
  bar.set_style_border_color(C(BORDER), 0);
  bar.set_style_border_width(1, 0);
  bar.set_style_pad_all(0, 0);
  bar.remove_flag(lv.obj.FLAG.SCROLLABLE);

  let back = mk_icon(bar, "chevron-left", 8, 9, TEXT2);
  if (back === null) mk_label(bar, "<", 10, 9, TEXT2, F_NUM_M);
  mk_label(bar, title, 28, 9, TEXT, ZH);

  let r = null;
  if (right) {
    r = mk_label(bar, right, 0, 0, TEXT3, F_NUM_S);
    r.align(lv.ALIGN.RIGHT_MID, -10, 0);
  }
  return [bar, r];
}

export function mk_icon(parent, name, x, y, color = TEXT2) {
  const f = _icon_font_ready();
  if (f === null) return null;
  if (!(name in ICONS)) return null;
  const lb = lv.label(parent);
  lb.set_text(ICONS[name]);
  lb.set_pos(x, y);
  lb.set_style_text_color(C(color), 0);
  lb.set_style_text_font(f, 0);
  return lb;
}

function _icon_font_ready() {
  if (!_iconFontTried) return null; // init_fonts() 還沒跑
  return ICON_FONT;
}

export function mk_btn(parent, text, x, y, w, h, kind = "primary") {
  const b = lv.button(parent);
  b.set_size(w, h);
  b.set_pos(x, y);
  let fg;
  if (kind === "primary") {
    b.set_style_bg_color(C(PRIMARY), 0);
    b.set_style_bg_opa(255, 0);
    b.set_style_border_width(0, 0);
    fg = 0xffffff;
  } else if (kind === "danger") {
    b.set_style_bg_color(C(DANGER_BG), 0);
    b.set_style_bg_opa(255, 0);
    b.set_style_border_width(0, 0);
    fg = DANGER;
  } else {
    b.set_style_bg_color(C(SURFACE), 0);
    b.set_style_bg_opa(255, 0);
    b.set_style_border_color(C(BORDER), 0);
    b.set_style_border_width(1, 0);
    fg = TEXT2;
  }
  b.set_style_radius(R_BTN, 0);
  const lb = lv.label(b);
  lb.set_text(text);
  lb.align(lv.ALIGN.CENTER, 0, 0);
  lb.set_style_text_color(C(fg), 0);
  if (ZH) lb.set_style_text_font(ZH, 0);
  return b;
}

export function mk_slider(parent, x, y, w, lo, hi, val, color = PRIMARY) {
  const s = lv.slider(parent);
  s.set_size(w, 8);
  s.set_pos(x, y);
  s.set_range(lo, hi);
  s.set_value(val, 0);
  s.set_style_bg_color(C(TRACK), lv.PART.MAIN);
  s.set_style_radius(4, lv.PART.MAIN);
  s.set_style_bg_color(C(color), lv.PART.INDICATOR);
  s.set_style_radius(4, lv.PART.INDICATOR);
  s.set_style_bg_color(C(color), lv.PART.KNOB);
  s.set_style_radius(4, lv.PART.KNOB);
  s.set_style_pad_all(4, lv.PART.KNOB);
  return s;
}

/** 環形進度量表（不可調整，knob 隱藏）。 */
export function mk_arc(parent, x, y, size, color, lo = 0, hi = 100) {
  const a = lv.arc(parent);
  a.set_size(size, size);
  a.set_pos(x, y);
  a.set_range(lo, hi);
  a.set_value(hi);
  a.set_style_arc_width(6, lv.PART.MAIN);
  a.set_style_arc_color(C(TRACK), lv.PART.MAIN);
  a.set_style_arc_width(6, lv.PART.INDICATOR);
  a.set_style_arc_color(C(color), lv.PART.INDICATOR);
  a.set_style_arc_opa(0, lv.PART.KNOB);
  a.set_style_bg_opa(0, lv.PART.KNOB);
  a.set_style_outline_width(0, lv.PART.KNOB);
  a.remove_flag(lv.obj.FLAG.CLICKABLE);
  return a;
}

export function mk_switch(parent, x, y, on = false, color = PRIMARY) {
  const s = lv.switch(parent);
  s.set_size(44, 24);
  s.set_pos(x, y);
  s.set_style_bg_color(C(TRACK), lv.PART.MAIN);
  s.set_style_bg_opa(255, lv.PART.MAIN);
  s.set_style_radius(12, lv.PART.MAIN);
  s.set_style_bg_color(C(color), lv.PART.INDICATOR);
  s.set_style_radius(12, lv.PART.INDICATOR);
  s.set_style_bg_color(C(SURFACE), lv.PART.KNOB);
  s.set_style_radius(10, lv.PART.KNOB);
  s.set_style_shadow_width(0, lv.PART.KNOB);
  if (on) sw_set(s, true);
  return s;
}

// ====== switch state 防護 wrapper ======

export function sw_set(sw, on) {
  if (on) sw.add_state(lv.STATE.CHECKED);
  else sw.clear_state(lv.STATE.CHECKED);
}

export function sw_get(sw) {
  return sw.has_state(lv.STATE.CHECKED);
}

// ====== 焦點視覺 ======
export function set_focus(wid, on, editing = false) {
  if (!wid) return;
  const ow = theme?.focus?.width ?? 3;
  const op = theme?.focus?.pad ?? 3;
  if (on) {
    wid.set_style_outline_color(C(editing ? WARNING : PRIMARY), 0);
    wid.set_style_outline_width(ow, 0);
    wid.set_style_outline_pad(op, 0);
  } else {
    wid.set_style_outline_width(0, 0);
  }
}

// 給 Nav 的別名（Python 是 u.set_focus；這裡保留同名 + camelCase 給內部用）
export const setFocus = set_focus;

// ====== list helper ======

/**
 * 建立 lv.list 並填入文字項。
 * @returns {[object, object[]]} [list_widget, [item_widgets]]
 */
export function mk_list(parent, x, y, w, h, items, f = null) {
  const lst = lv.list(parent);
  lst.set_size(w, h);
  lst.set_pos(x, y);
  const fnt = f || ZH;
  const btns = [];
  for (const txt of items) {
    const b = lst.add_text(txt);
    if (fnt) b.set_style_text_font(fnt, 0);
    btns.push(b);
  }
  return [lst, btns];
}

export function mk_led(parent, x, y, size = 12, on = false, on_color = SUCCESS, off_color = BORDER) {
  const d = lv.obj(parent);
  d.set_size(size, size);
  d.set_pos(x, y);
  d.set_style_radius(size / 2, 0);
  d.set_style_bg_color(C(on ? on_color : off_color), 0);
  d.set_style_bg_opa(255, 0);
  d.set_style_border_width(0, 0);
  d.set_style_pad_all(0, 0);
  d.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return d;
}

export function led_set(led, on, on_color = SUCCESS, off_color = BORDER) {
  if (!led) return;
  led.set_style_bg_color(C(on ? on_color : off_color), 0);
}

/**
 * 標示 list 第 idx 項為選中（背景色）；其他項清除。
 * color：PRIMARY(選中) / WARNING(編輯中·已送出等回覆) / SUCCESS(已確認)
 */
export function list_select(btns, idx, color = PRIMARY) {
  const n = btns.length;
  if (!n) return;
  idx = Math.max(0, Math.min(idx, n - 1));
  btns.forEach((b, i) => {
    if (i === idx) {
      b.set_style_bg_color(C(color), 0);
      b.set_style_bg_opa(255, 0);
      b.set_style_text_color(C(0xffffff), 0);
    } else {
      b.set_style_bg_color(C(BG), 0);
      b.set_style_bg_opa(0, 0);
      b.set_style_text_color(C(TEXT), 0);
    }
  });
}

// ====== 動效 ======
export function pulse(wid, period = 1500, minOpa = 110, maxOpa = 255) {
  return fx.pulse(wid, period, minOpa, maxOpa);
}
export function fade_in(wid, dy = 6, timeMs = 300, delayMs = 0) {
  return fx.fade_in(wid, dy, timeMs, delayMs);
}
export function bar_grow(bar, from = 0, to = null, timeMs = 400) {
  return fx.bar_grow(bar, from, to, timeMs);
}

/** 延遲載入，避免 ui_common ↔ lv_ui_fx 的循環相依。 */
