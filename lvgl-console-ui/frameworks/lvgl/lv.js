// ui/core/lv.js — LVGL 的 JS 鏡像層
//
// ══════════════════════════════════════════════════════════════════════
//  設計原則：**形狀跟 MicroPython 的 lvgl binding 一樣**，只是換一種語法。
// ══════════════════════════════════════════════════════════════════════
//
//   Python (裝置)                        JS (這裡)
//   ───────────────────────────────      ───────────────────────────────
//   scr = lv.obj(None)                   const scr = lv.obj(null)
//   lb  = lv.label(scr)                  const lb  = lv.label(scr)
//   lb.set_pos(x, y)                     lb.set_pos(x, y)
//   lb.set_text("亮度")                   lb.set_text("亮度")
//   lb.set_style_text_color(u.C(u.TEXT), 0)
//   s = lv.slider(p); s.set_value(v, 0)  s = lv.slider(p); s.set_value(v, 0)
//
//  方法名刻意保留 snake_case：轉換時**幾乎逐行**，不用重建心智模型，
//  也不用在「這個到底是 LVGL 還是 JS 慣例」之間切換。
//
//  只有三件事是 JS 額外的（轉換時刪掉就好）：
//    1. import（Python 是 from ui.lvgl import ...）
//    2. const/let
//    3. 匿名函式 lamdbda → () => {}
//
//  刻意**不**做的事：
//    - 不引入 flex/grid/事件系統/主題引擎（頁面沒用到，多做只是多一個轉換斷層）
//    - 不做 dirty rect 最佳化（320×240 全畫一次 <2ms，簡單 > 聰明）
//
// ── 座標 / 樣式語義對齊 LVGL ─────────────────────────────────────────
//   1. obj 的 (x,y) 是左上角，相對 parent 的 content area（扣掉 border+pad）
//   2. border / outline 都畫在「內側」或「外側」的固定規則，跟 LVGL 一致
//   3. style 以 part 為單位（MAIN / INDICATOR / KNOB），part 沒設就 fallback MAIN
//   4. text_font / text_color 會**向上繼承**（LVGL 的 inherited props）
//      ⇒ mk_list() 對 list item 設字型，item 裡的 label 才會跟著變
//   5. label 沒設 size 時 size_to_content（量測用真機 .bin 的 advance）

import { BinFont, SystemFont } from "@lvui/host/font.js";
import { paintTree, computeLayout } from "./paint.js";

// ───────────── 常數（數值刻意跟 LVGL 一樣，方便對照/硬編碼） ─────────────

export const ALIGN = {
  DEFAULT: 0,
  TOP_LEFT: 1,
  TOP_MID: 2,
  TOP_RIGHT: 3,
  BOTTOM_LEFT: 4,
  BOTTOM_MID: 5,
  BOTTOM_RIGHT: 6,
  LEFT_MID: 7,
  RIGHT_MID: 8,
  CENTER: 9,
  OUT_TOP_LEFT: 10,
  OUT_TOP_MID: 11,
  OUT_TOP_RIGHT: 12,
  OUT_BOTTOM_LEFT: 13,
  OUT_BOTTOM_MID: 14,
  OUT_BOTTOM_RIGHT: 15,
  OUT_LEFT_TOP: 16,
  OUT_LEFT_MID: 17,
  OUT_LEFT_BOTTOM: 18,
  OUT_RIGHT_TOP: 19,
  OUT_RIGHT_MID: 20,
  OUT_RIGHT_BOTTOM: 21,
};

export const PART = {
  MAIN: 0x000000,
  SCROLLBAR: 0x010000,
  INDICATOR: 0x020000,
  KNOB: 0x030000,
  SELECTED: 0x000001,
};

export const FLAG = {
  HIDDEN: 0x0001,
  CLICKABLE: 0x0002,
  CLICKABLE_FOCUS: 0x0004,
  CHECKABLE: 0x0008,
  SCROLLABLE: 0x0010,
  SCROLL_ELASTIC: 0x0020,
  SCROLL_CHAIN: 0x0040,
  SCROLL_ON_FOCUS: 0x0080,
  SCROLL_WITH_ARROW: 0x0100,
  SNAPPABLE: 0x0200,
  PRESS_LOCK: 0x0400,
  EVENT_BUBBLE: 0x0800,
  GESTURE_BUBBLE: 0x1000,
  ADV_HITTEST: 0x2000,
  IGNORE_LAYOUT: 0x4000,
  FLOATING: 0x8000,
  OVERFLOW_VISIBLE: 0x10000,
  USER_1: 0x20000,
  USER_2: 0x40000,
  USER_3: 0x80000,
  USER_4: 0x100000,
};

export const STATE = {
  DEFAULT: 0,
  CHECKED: 0x0001,
  FOCUSED: 0x0002,
  FOCUS_KEY: 0x0004,
  EDITED: 0x0008,
  HOVERED: 0x0010,
  PRESSED: 0x0020,
  SCROLLED: 0x0040,
  DISABLED: 0x0080,
  USER_1: 0x1000,
  USER_2: 0x2000,
  USER_3: 0x4000,
  USER_4: 0x8000,
};

const OPA_COVER = 255;
const OPA_TRANSP = 0;

/** LVGL 顏色物件。只帶 hex，繪製時才轉 CSS 字串。 */
export class Color {
  constructor(hex) {
    this.hex = hex & 0xffffff;
  }
  css() {
    return "#" + this.hex.toString(16).padStart(6, "0");
  }
  toString() {
    return this.css();
  }
}

const _colorCache = new Map();
export function color_hex(hex) {
  const k = hex & 0xffffff;
  let c = _colorCache.get(k);
  if (!c) {
    c = new Color(k);
    _colorCache.set(k, c);
  }
  return c;
}

function css(color) {
  if (color == null) return null;
  return typeof color === "string" ? color : color.css();
}

// ───────────── style 屬性別名 ─────────────
// 讓 set_style_x() 可以用「屬性名」的 snake_case 傳進來，
// 對照 LVGL 的 lv_style_prop_t（只實作頁面真的會用到的）。
const STYLE_ALIAS = {
  bg_color: "bg_color",
  bg_opa: "bg_opa",
  radius: "radius",
  clip_corner: "clip_corner",
  border_color: "border_color",
  border_width: "border_width",
  border_opa: "border_opa",
  border_side: "border_side",
  outline_color: "outline_color",
  outline_width: "outline_width",
  outline_pad: "outline_pad",
  outline_opa: "outline_opa",
  shadow_color: "shadow_color",
  shadow_width: "shadow_width",
  shadow_opa: "shadow_opa",
  shadow_ofs_x: "shadow_ofs_x",
  shadow_ofs_y: "shadow_ofs_y",
  shadow_spread: "shadow_spread",
  text_color: "text_color",
  text_opa: "text_opa",
  text_font: "text_font",
  text_letter_space: "text_letter_space",
  text_line_space: "text_line_space",
  text_align: "text_align",
  text_decor: "text_decor",
  pad_all: "pad_all",
  pad_top: "pad_top",
  pad_bottom: "pad_bottom",
  pad_left: "pad_left",
  pad_right: "pad_right",
  pad_row: "pad_row",
  pad_column: "pad_column",
  pad_hor: "pad_hor",
  pad_ver: "pad_ver",
  arc_width: "arc_width",
  arc_color: "arc_color",
  arc_opa: "arc_opa",
  arc_rounded: "arc_rounded",
  line_width: "line_width",
  line_color: "line_color",
  line_opa: "line_opa",
  bg_grad_color: "bg_grad_color",
  bg_grad_dir: "bg_grad_dir",
  bg_main_stop: "bg_main_stop",
  bg_grad_stop: "bg_grad_stop",
  opa: "opa",
  opa_layered: "opa",
  transform_width: "_noop",
  transform_height: "_noop",
  transform_zoom: "_noop",
  translate_x: "_noop",
  translate_y: "_noop",
};

const IGNORED_STYLE_WARN = new Set();

// ══════════════════════════════════════════════════════════════════════
//  建立位置追蹤（給開發台的檢視器用）
// ══════════════════════════════════════════════════════════════════════
//  目的：在畫布上點一個 widget，就能說出「它是 projects/slave/pages/settings.js 第 52 行建的」。
//  做法：建構時截一次 Error stack：
//        - 跳過工具自己（/lvgl-console-ui/：new Obj、captureSource…）
//        - 第一個剩下的框 = 實際 new 的地方（可能在 packages/lv-app/ui_common.js 的 mk_btn）
//        - 優先找 /projects/ 的框 = **頁面呼叫點**（使用者真正寫的那行）當「via」上層
//  成本：每個 widget 一次 new Error().stack（~10–30µs）。一頁 ~100 個 widget，
//        全部 build 一次 ~3ms，只在開機做一次。
//  關掉：`lv.trackSource = false`（在 boot 之前設）。

let _oidSeq = 0;
const SRC_RE = /^\s*at\s+(?:(.+?)\s+\()?(.+?):(\d+):(\d+)\)?\s*$/;

// 工具自己的目錄：這些框不算「誰建的 widget」。
// 注意：工具是以 root 身分被 serve 的（/frameworks/…），所以只能比對相對路徑，
// 不能比對含有 /lvgl-console-ui/ 的絕對路徑 —— 那條在舊的掛載方式才成立。
const TOOL_FRAME = /\/(frameworks|host|inspect|cli)\//;

function _normSrc(fr) {
  const file = fr.file
    .replace(/^https?:\/\/[^/]+/, "")
    .replace(/^\//, "")
    .replace(/^.*?\/(projects|packages|frameworks|host|inspect|cli)\//, "$1/");
  return { file, line: fr.line, fn: fr.fn };
}

function captureSource() {
  if (!lv.trackSource) return null;
  const stack = new Error().stack;
  if (!stack) return null;

  const frames = [];
  for (const line of stack.split("\n")) {
    const m = SRC_RE.exec(line);
    if (!m) continue;
    const file = m[2];
    if (TOOL_FRAME.test(file) || file.endsWith("/boot.js")) continue;
    frames.push({ file, line: Number(m[3]), fn: m[1] || "" });
    if (frames.length >= 4) break;
  }
  if (!frames.length) return null;

  const site = frames[0]; // 實際 new 的位置（可能是 packages/lv-app/ui_common.js）
  const caller = frames.find((f) => f.file.includes("/projects/")); // 頁面呼叫點
  const out = _normSrc(caller || site);
  if (caller && caller !== site) out.via = `${_normSrc(site).file}:${site.line}`;
  return out;
}

// ══════════════════════════════════════════════════════════════════════
//  Widget 基底
// ══════════════════════════════════════════════════════════════════════

export class Obj {
  constructor(parent = null) {
    this.parent = parent;
    this.children = [];
    this.objClass = "obj";
    this.oid = ++_oidSeq; // 檢視器 / 元件樹用它當 key
    this._src = captureSource(); // 建立位置（pages/xxx.js:44）

    this.x = 0;
    this.y = 0;
    this.w = 0;
    this.h = 0;
    this._sizeToContent = true; // 沒 set_size 過 ⇒ 由子類決定（label 用文字）
    this._align = null; // {type, dx, dy}
    this.flags = 0;
    this.state = 0;
    this.opaqueUser = null;

    /** part → Map(prop → value)。part 沒設時 fallback MAIN。 */
    this._styles = new Map();
    this._hidden = false;

    // 每個 widget 都有的「內容區」快取（layout 後計算）
    this._content = { x: 0, y: 0, w: 0, h: 0, pad: { l: 0, r: 0, t: 0, b: 0, row: 0, col: 0 } };

    if (parent) parent.children.push(this);
    else if (lv.display) {
      // 無 parent = screen：尺寸跟 display 一樣。
      // screen 的「底」來自 theme（白底不透明）；一般 obj 預設是透明的，
      // 只有明確設了 bg_color 才有底色 —— 這樣才不會每個容器都變成白方塊。
      this.w = lv.display.w;
      this.h = lv.display.h;
      this._sizeToContent = false;
      this._style("bg_color", color_hex(0xffffff), 0);
      this._style("bg_opa", OPA_COVER, 0);
    }
  }

  // ── 幾何 ──
  set_pos(x, y) {
    this.x = Math.round(x);
    this.y = Math.round(y);
    this._align = null; // LVGL：set_pos 會清掉 align
    return this;
  }
  set_x(x) {
    return this.set_pos(x, this.y);
  }
  set_y(y) {
    return this.set_pos(this.x, y);
  }
  get_x() {
    return this.x;
  }
  get_y() {
    return this.y;
  }
  set_size(w, h) {
    this.w = Math.round(w);
    this.h = Math.round(h);
    this._sizeToContent = false;
    return this;
  }
  set_width(w) {
    this.w = Math.round(w);
    this._sizeToContent = false;
    return this;
  }
  set_height(h) {
    this.h = Math.round(h);
    this._sizeToContent = false;
    return this;
  }
  get_width() {
    return this.w;
  }
  get_height() {
    return this.h;
  }
  align(type, dx = 0, dy = 0) {
    this._align = { type, dx, dy };
    return this;
  }
  get_align() {
    return this._align || { type: ALIGN.DEFAULT, dx: 0, dy: 0 };
  }
  center() {
    return this.align(ALIGN.CENTER, 0, 0);
  }

  // ── flag / state ──
  add_flag(f) {
    this.flags |= f;
    return this;
  }
  remove_flag(f) {
    this.flags &= ~f;
    return this;
  }
  clear_flag(f) {
    return this.remove_flag(f);
  }
  has_flag(f) {
    return (this.flags & f) !== 0;
  }
  add_state(s) {
    this.state |= s;
    return this;
  }
  clear_state(s) {
    this.state &= ~s;
    return this;
  }
  has_state(s) {
    return (this.state & s) !== 0;
  }
  set_hidden(v) {
    this._hidden = !!v;
    return this;
  }
  is_hidden() {
    return this._hidden;
  }

  // ── user data ──
  set_user_data(d) {
    this.opaqueUser = d;
    return this;
  }
  get_user_data() {
    return this.opaqueUser;
  }

  // ── 樹 ──
  get_parent() {
    return this.parent;
  }
  get_child_count() {
    return this.children.length;
  }
  get_child(i) {
    return this.children[i];
  }
  delete() {
    if (!this.parent) return;
    const i = this.parent.children.indexOf(this);
    if (i >= 0) this.parent.children.splice(i, 1);
    this.parent = null;
  }
  clean() {
    for (const c of this.children.slice()) c.delete();
  }
  move_foreground() {
    const p = this.parent;
    if (!p) return;
    p.children.splice(p.children.indexOf(this), 1);
    p.children.push(this);
  }
  move_background() {
    const p = this.parent;
    if (!p) return;
    p.children.splice(p.children.indexOf(this), 1);
    p.children.unshift(this);
  }

  // ── style ──
  set_style_bg_color(v, part = 0) {
    return this._style("bg_color", v, part);
  }
  set_style_bg_opa(v, part = 0) {
    return this._style("bg_opa", v, part);
  }
  set_style_radius(v, part = 0) {
    return this._style("radius", v, part);
  }
  set_style_border_color(v, part = 0) {
    return this._style("border_color", v, part);
  }
  set_style_border_width(v, part = 0) {
    return this._style("border_width", v, part);
  }
  set_style_border_opa(v, part = 0) {
    return this._style("border_opa", v, part);
  }
  set_style_outline_color(v, part = 0) {
    return this._style("outline_color", v, part);
  }
  set_style_outline_width(v, part = 0) {
    return this._style("outline_width", v, part);
  }
  set_style_outline_pad(v, part = 0) {
    return this._style("outline_pad", v, part);
  }
  set_style_outline_opa(v, part = 0) {
    return this._style("outline_opa", v, part);
  }
  set_style_shadow_width(v, part = 0) {
    return this._style("shadow_width", v, part);
  }
  set_style_shadow_color(v, part = 0) {
    return this._style("shadow_color", v, part);
  }
  set_style_shadow_opa(v, part = 0) {
    return this._style("shadow_opa", v, part);
  }
  set_style_shadow_ofs_x(v, part = 0) {
    return this._style("shadow_ofs_x", v, part);
  }
  set_style_shadow_ofs_y(v, part = 0) {
    return this._style("shadow_ofs_y", v, part);
  }
  set_style_text_color(v, part = 0) {
    return this._style("text_color", v, part);
  }
  set_style_text_opa(v, part = 0) {
    return this._style("text_opa", v, part);
  }
  set_style_text_font(v, part = 0) {
    return this._style("text_font", v, part);
  }
  set_style_text_letter_space(v, part = 0) {
    return this._style("text_letter_space", v, part);
  }
  set_style_text_line_space(v, part = 0) {
    return this._style("text_line_space", v, part);
  }
  set_style_text_align(v, part = 0) {
    return this._style("text_align", v, part);
  }
  set_style_pad_all(v, part = 0) {
    // LVGL 的 pad_all 是「四邊一起設」：之後單獨設 pad_top 才會蓋掉上面那一個。
    // 只寫 pad_all 的話，物件本身先設過的 pad_top/bottom（例如 list item 的 4）
    // 會留下來，頁面再呼叫 pad_all(1) 就完全沒效果。
    this._style("pad_all", v, part);
    this._style("pad_top", v, part);
    this._style("pad_bottom", v, part);
    this._style("pad_left", v, part);
    this._style("pad_right", v, part);
    return this;
  }
  set_style_pad_top(v, part = 0) {
    return this._style("pad_top", v, part);
  }
  set_style_pad_bottom(v, part = 0) {
    return this._style("pad_bottom", v, part);
  }
  set_style_pad_left(v, part = 0) {
    return this._style("pad_left", v, part);
  }
  set_style_pad_right(v, part = 0) {
    return this._style("pad_right", v, part);
  }
  set_style_pad_row(v, part = 0) {
    return this._style("pad_row", v, part);
  }
  set_style_pad_column(v, part = 0) {
    return this._style("pad_column", v, part);
  }
  set_style_pad_hor(v, part = 0) {
    return this._style("pad_hor", v, part);
  }
  set_style_pad_ver(v, part = 0) {
    return this._style("pad_ver", v, part);
  }
  set_style_opa(v, part = 0) {
    return this._style("opa", v, part);
  }
  set_style_arc_width(v, part = 0) {
    return this._style("arc_width", v, part);
  }
  set_style_arc_color(v, part = 0) {
    return this._style("arc_color", v, part);
  }
  set_style_arc_opa(v, part = 0) {
    return this._style("arc_opa", v, part);
  }
  set_style_arc_rounded(v, part = 0) {
    return this._style("arc_rounded", v, part);
  }
  set_style_bg_grad_color(v, part = 0) {
    return this._style("bg_grad_color", v, part);
  }
  set_style_bg_grad_dir(v, part = 0) {
    return this._style("bg_grad_dir", v, part);
  }
  set_style_transform_zoom(v, part = 0) {
    return this; // 未實作（頁面沒用）
  }
  set_style_transform_width(v, part = 0) {
    return this;
  }
  set_style_transform_height(v, part = 0) {
    return this;
  }

  /** 通用入口：任何 set_style_xxx 沒特別寫的，走這條（別名表沒有的就忽略）。 */
  _style(prop, value, part = 0) {
    const key = STYLE_ALIAS[prop] ?? prop;
    if (key === "_noop") return this;
    if (!(key in STYLE_ALIAS) && !IGNORED_STYLE_WARN.has(prop)) {
      IGNORED_STYLE_WARN.add(prop);
      console.warn(`[lv] style '${prop}' 未實作（已忽略）`);
    }
    let m = this._styles.get(part);
    if (!m) {
      m = new Map();
      this._styles.set(part, m);
    }
    m.set(key, value);
    return this;
  }

  /**
   * 讀 style 值。part 沒設 → fallback MAIN（LVGL 行為）。
   * text_* 再往 parent 找（inherited props）。
   */
  getStyle(prop, part = 0) {
    const m = this._styles.get(part);
    if (m && m.has(prop)) return m.get(prop);
    if (part !== PART.MAIN) {
      const mm = this._styles.get(PART.MAIN);
      if (mm && mm.has(prop)) return mm.get(prop);
    }
    // text 系列往上繼承
    if (prop.startsWith("text_") && this.parent) return this.parent.getStyle(prop, 0);
    return undefined;
  }

  /** 目前生效的 pad（含 part MAIN）。 */
  getPad() {
    const all = this.getStyle("pad_all") ?? 0;
    return {
      l: this.getStyle("pad_left") ?? all,
      r: this.getStyle("pad_right") ?? all,
      t: this.getStyle("pad_top") ?? all,
      b: this.getStyle("pad_bottom") ?? all,
      row: this.getStyle("pad_row") ?? 0,
      col: this.getStyle("pad_column") ?? 0,
    };
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Label
// ══════════════════════════════════════════════════════════════════════

export class Label extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "label";
    this._text = "";
    this._sizeToContent = true;
    this._lines = [""];
  }

  set_text(t) {
    const s = String(t ?? "");
    if (s === this._text) return this;
    this._text = s;
    return this;
  }
  get_text() {
    return this._text;
  }
  set_long_mode(_m) {
    return this;
  }

  /**
   * 內容尺寸：用**當下生效的**字型量（含從 parent 繼承來的）。
   *
   * 不能只在 set_text() 量一次：頁面常見的順序是
   *   lb = lv.label(c); lb.set_text("—"); lb.set_style_text_font(u.ZH, 0)
   * 建的時候字型還沒定（會落到 14px 預設），等樣式補上就該重量。
   * 這裡每幀重量 —— label 數量少、字串短，成本可忽略。
   */
  measure() {
    const font = this.getStyle("text_font");
    const lines = this._text.split("\n");
    this._lines = lines;
    const lh = font ? font.lineHeight : 16;
    const w = lines.length
      ? Math.max(...lines.map((l) => (font ? font.measure(l) : l.length * 8)))
      : 0;
    return { w, h: lh * Math.max(1, lines.length) };
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Button / List
// ══════════════════════════════════════════════════════════════════════

export class Button extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "button";
    this._sizeToContent = true;
    // LVGL 預設 theme：button 是 primary 底、圓角。頁面幾乎都會覆寫，
    // 但沒覆寫時要長得像真機（不是透明）。
    this._style("bg_color", color_hex(0x2196f3), 0);
    this._style("bg_opa", OPA_COVER, 0);
    this._style("radius", 3, 0);
  }
}

/** lv.list 的項目：跟 LVGL 一樣是 button + 內含 label。 */
export class ListBtn extends Button {
  constructor(list, text) {
    super(list);
    this.objClass = "list_btn";
    this.set_width(list.w - 8);
    this.set_height(0);
    // ⚠ bg_opa 要是 COVER（不是 TRANSP）：裝置頁面選中列只設 bg_color，
    //   靠的就是主題的不透明底。設成透明會讓「藍底/琥珀底」完全看不到
    //   （pca9685 / remote / now_setting 三個頁面都各自回報過這個坑）。
    this._style("bg_opa", OPA_COVER, 0);
    this._style("bg_color", color_hex(0xffffff), 0);
    this._style("radius", 3, 0);
    this._style("border_width", 0, 0);
    this._style("pad_top", 4, 0);
    this._style("pad_bottom", 4, 0);
    this._style("pad_left", 4, 0);
    this._style("pad_right", 4, 0);
    this.lbl = new Label(this);
    this.lbl.set_text(text);
    this.lbl.align(ALIGN.LEFT_MID, 0, 0);
  }
}

export class List extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "list";
    // LVGL 9 default theme 的 list：白底、圓角 3、內距 4、列距 4
    this._style("bg_color", color_hex(0xffffff), 0);
    this._style("bg_opa", OPA_COVER, 0);
    this._style("radius", 3, 0);
    this._style("border_width", 0, 0);
    this._style("pad_all", 4, 0);
    this._style("pad_row", 4, 0);
    this._sizeToContent = false;
    this._items = [];
  }

  add_text(text) {
    const b = new ListBtn(this, text);
    this._items.push(b);
    this._layoutItems();
    return b;
  }

  add_btn() {
    return this.add_text("");
  }

  /**
   * 清空 list（LVGL: lv_obj_clean(list)）。
   *
   * ⚠️ 一定要覆寫：基底只會刪 children，但 `_layoutItems()` 每幀照 `_items` 排版，
   *    沒清 `_items` 的話舊項目還留在陣列裡 → 重新 add_text 之後列距會累加，
   *    內容一路往下飄（now_setting 頁重填清單時踩到，第二列從 y=32 變 y=60）。
   */
  clean() {
    super.clean();
    this._items = [];
    return this;
  }

  /**
   * list 是縱向堆疊（LVGL 的 flex column），這裡直接算。
   *
   * ⚠ 一定要讀 pad 樣式，不能寫死 4/4：
   *   - 頁面常用 `set_style_pad_all(1)` 把列壓緊（pixel_lab / pca9685 / now_setting 都這樣做）
   *   - 寫死的話列高固定 27px，3 列就要 89px，塞進 88px 的清單 → 最後一列直接被裁掉
   *   LVGL 的列高 = 字高 + item 的 pad_top + pad_bottom，列距 = list 的 pad_row。
   */
  _layoutItems() {
    const padAll = this.getStyle("pad_all") ?? 4;
    const padRow = this.getStyle("pad_row") ?? 4;
    let y = padAll;
    for (const it of this._items) {
      const lbl = it.lbl;
      const lh = (lbl.getStyle("text_font") || { lineHeight: 16 }).lineHeight;
      // 頁面通常只寫 set_style_pad_all()，所以 pad_all 要當成四邊的 fallback
      // （LVGL 的 pad_all 就是「四邊一起設」，單邊沒設時就吃這個值）
      const padTop = it.getStyle("pad_top") ?? it.getStyle("pad_all") ?? 4;
      const padBottom = it.getStyle("pad_bottom") ?? it.getStyle("pad_all") ?? 4;
      const h = lh + padTop + padBottom;
      it.set_pos(padAll, y);
      it.set_size(Math.max(0, this.w - padAll * 2), h);
      y += h + padRow;
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Slider / Arc / Switch / Bar
// ══════════════════════════════════════════════════════════════════════

export class Slider extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "slider";
    this._min = 0;
    this._max = 100;
    this._value = 0;
    this._sizeToContent = false;
  }
  set_range(min, max) {
    this._min = min;
    this._max = max;
    return this;
  }
  set_value(v, _anim = 0) {
    this._value = Math.max(this._min, Math.min(this._max, v));
    return this;
  }
  get_value() {
    return this._value;
  }
  set_mode(_m) {
    return this;
  }
  getRatio() {
    const span = this._max - this._min;
    return span === 0 ? 0 : (this._value - this._min) / span;
  }
}

export class Arc extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "arc";
    this._min = 0;
    this._max = 100;
    this._value = 0;
    this._bgStart = 135;
    this._bgEnd = 45;
    this._rotation = 0;
    this._sizeToContent = false;
  }
  set_range(min, max) {
    this._min = min;
    this._max = max;
    return this;
  }
  set_value(v, _anim = 0) {
    this._value = Math.max(this._min, Math.min(this._max, v));
    return this;
  }
  get_value() {
    return this._value;
  }
  set_bg_angles(start, end) {
    this._bgStart = start;
    this._bgEnd = end;
    return this;
  }
  set_angles(start, end) {
    this._indStart = start;
    this._indEnd = end;
    return this;
  }
  set_rotation(r) {
    this._rotation = r;
    return this;
  }
  set_mode(_m) {
    return this;
  }
  getRatio() {
    const span = this._max - this._min;
    return span === 0 ? 0 : (this._value - this._min) / span;
  }
}

export class Switch extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "switch";
    this._sizeToContent = false;
  }
  set_range(_a, _b) {
    return this;
  }
  /** LVGL：switch 的開關是 CHECKED state。 */
  set_checked(v) {
    if (v) this.add_state(STATE.CHECKED);
    else this.clear_state(STATE.CHECKED);
    return this;
  }
  get_checked() {
    return this.has_state(STATE.CHECKED);
  }
}

export class Bar extends Obj {
  constructor(parent) {
    super(parent);
    this.objClass = "bar";
    this._min = 0;
    this._max = 100;
    this._value = 0;
    this._sizeToContent = false;
  }
  set_range(a, b) {
    this._min = a;
    this._max = b;
    return this;
  }
  set_value(v, _anim = 0) {
    this._value = Math.max(this._min, Math.min(this._max, v));
    return this;
  }
  get_value() {
    return this._value;
  }
  set_mode(_m) {
    return this;
  }
  getRatio() {
    const span = this._max - this._min;
    return span === 0 ? 0 : (this._value - this._min) / span;
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Display 掛勾
// ══════════════════════════════════════════════════════════════════════

class LvRoot {
  constructor() {
    this.display = null; // 由 display.js 設定
    this.Animation = null; // 由 anim.js 設定
    this.trackSource = true; // 建立位置追蹤（檢視器用）
  }

  // ── widget 建構子（跟 binding 同名） ──
  obj(parent) {
    return new Obj(parent);
  }
  label(parent) {
    return new Label(parent);
  }
  button(parent) {
    return new Button(parent);
  }
  list(parent) {
    return new List(parent);
  }
  slider(parent) {
    return new Slider(parent);
  }
  arc(parent) {
    return new Arc(parent);
  }
  switch(parent) {
    return new Switch(parent);
  }
  bar(parent) {
    return new Bar(parent);
  }

  // ── 螢幕 ──
  screen_load(scr) {
    if (this.display) this.display.set_screen(scr);
    return 0;
  }
  screen_active() {
    return this.display ? this.display.screen : null;
  }

  // ── 時間（動畫） ──
  tick_inc(ms) {
    if (this._tickCb) this._tickCb(ms);
  }
  on_tick(cb) {
    this._tickCb = cb;
  }

  /** 對外：把整棵樹畫到 canvas（由 display 呼叫）。 */
  _paint(ctx) {
    if (!this.display || !this.display.screen) return;
    computeLayout(this.display.screen, this.display.w, this.display.h);
    paintTree(ctx, this.display.screen);
  }
}

export const lv = new LvRoot();

// Python 端會寫 lv.obj.FLAG.SCROLLABLE / lv.PART.MAIN / lv.ALIGN.CENTER
// ⇒ 讓這些常數掛在跟 binding 一樣的位置。
lv.obj.FLAG = FLAG;
lv.obj.STATE = STATE;
lv.obj.PART = PART;
lv.obj.ALIGN = ALIGN;
lv.label.ALIGN = ALIGN;
lv.button.ALIGN = ALIGN;

lv.ALIGN = ALIGN;
lv.PART = PART;
lv.FLAG = FLAG;
lv.STATE = STATE;
lv.COLOR_FORMAT = { RGB565: 18, RGB888: 16, ARGB8888: 17 };
lv.INDEV_STATE = { RELEASED: 0, PRESSED: 1 };
lv.DISPLAY_RENDER_MODE = { PARTIAL: 0, DIRECT: 1, FULL: 2 };

lv.color_hex = color_hex;
lv.Color = Color;
lv.Obj = Obj;
lv.Label = Label;
lv.List = List;
lv.Slider = Slider;
lv.Arc = Arc;
lv.Switch = Switch;
lv.display = null;

export default lv;
export { BinFont, SystemFont };
