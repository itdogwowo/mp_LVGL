// projects/slave/pages/pixel_lab_common.js — PixelLab 三頁共用的小工具
//
// 對應 ui/lvgl/page/pixel_lab_common.py
//
// 這裡只放「頁面共用」的狀態/小元件，不放 Pixel 計算（計算在 tasks/pixel_lab_task.py）。
// 三頁都透過 bus.shared["pixel_lab"] 設定 mode/active/index/ch/target，
// 由 PixelLabTask 低優先消費；owner 不是 test 時 task 會停止並顯示「被接手」。
//
// 這個檔**沒有 meta、不要 register**：它只是被 pixel_lab_apa/rgb/pca import 的模組。
//
// 轉換對照：
//   global a, b            → 模組層 let（本檔只有狀態在 bus.shared，模組層沒有 global）
//   isinstance(x, dict)    → _is_dict(x)（bus.shared 內是 Dict，具備 get()）
//   time.ticks_ms()        → Date.now()
//   Python 的 "{}%" 字串格式化 → `${p}%`
//   (a + d) % n            → wrap(a + d, n)（Python 的 % 對負數回非負，JS 會回負數）

import lv from "@lvui/frameworks/lvgl/lv.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import * as u from "@packages/lv-app/ui_common.js";

/** bus.shared 裡的 Python dict 替身（Dict）判斷；缺值／型別不對就重建。 */
function _is_dict(v) {
  return v !== null && typeof v === "object" && typeof v.get === "function";
}

/** Python 的 int() 替身：非數字字串／undefined 回預設值，不要讓 NaN 傳進版面。 */
function _int(v, dflt = 0) {
  const n = Math.trunc(Number(v));
  return Number.isFinite(n) ? n : dflt;
}

/** Python 的 % 對負數也回非負；JS 的 % 會回負數 ⇒ 游標環繞統一走這支。 */
export function wrap(i, n) {
  if (!n) return 0;
  return ((Math.trunc(i) % n) + n) % n;
}

export function state() {
  let st = bus.shared.get("pixel_lab");
  if (!_is_dict(st)) {
    st = dict({
      active: 0, mode: "apa", index: 0, ch: 0,
      target: 0x70, target_bus: 0, hb: 0,
    });
    bus.shared["pixel_lab"] = st;
  }
  return st;
}

export function view() {
  const v = bus.shared.get("pixel_lab_view");
  return _is_dict(v) ? v : dict();
}

export function touch() {
  const st = state();
  st["hb"] = Date.now();
}

export function open_page(mode) {
  const st = state();
  st["mode"] = mode;
  st["active"] = 1;
  st["hb"] = Date.now();
}

export function close_page() {
  const st = state();
  st["active"] = 0;
  st["hb"] = Date.now();
}

export function status_text(v) {
  if (v.get("busy")) {
    return ["被接手", u.WARNING];
  }
  if (v.get("active")) {
    return ["使用中", u.SUCCESS];
  }
  return ["待機", u.TEXT3];
}

export function pct(v) {
  try {
    const n = Math.trunc(Number(v));
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
  } catch (e) {
    return 0;
  }
}

/** 垂直亮度方塊：track + fill。回傳 [track, fill]。 */
export function mk_vbar(parent, x, y, w, h, color) {
  const track = lv.obj(parent);
  track.set_size(w, h);
  track.set_pos(x, y);
  track.set_style_bg_color(u.C(u.TRACK), 0);
  track.set_style_radius(7, 0);
  track.set_style_border_color(u.C(u.BORDER), 0);
  track.set_style_border_width(1, 0);
  track.set_style_pad_all(0, 0);
  track.remove_flag(lv.obj.FLAG.SCROLLABLE);

  const fill = lv.obj(track);
  fill.set_size(w - 4, 1);
  fill.set_pos(2, h - 3);
  fill.set_style_bg_color(u.C(color), 0);
  fill.set_style_radius(5, 0);
  fill.set_style_border_width(0, 0);
  fill.set_style_pad_all(0, 0);
  fill.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return [track, fill];
}

/** p=0..100；填滿高度依 p 改變；0 也留 1px 讓 track 不被動態隱藏。 */
export function set_vbar(fill, w, h, p, color, color_empty = null) {
  p = pct(p);
  let fh = Math.trunc(((h - 4) * p) / 100.0);
  if (fh < 1) {
    fh = 1;
  }
  try {
    fill.set_size(w - 4, fh);
    fill.set_pos(2, h - 2 - fh);
    fill.set_style_bg_color(u.C(p > 0 || !color_empty ? color : color_empty), 0);
  } catch (e) {
    /* 跟裝置一樣：fill 還沒建好就跳過 */
  }
}

export function set_label(lb, text, color = null) {
  try {
    lb.set_text(text);
    if (color != null) {
      lb.set_style_text_color(u.C(color), 0);
    }
  } catch (e) {
    /* 跟裝置一樣：label 不在就跳過 */
  }
}

/** APA / RGB 共用版型：IO、選取 index、呼吸/選中兩個亮度方塊。 */
export class SimplePage {
  constructor(mode, title, subtitle, accent) {
    this.mode = mode;
    this.title = title;
    this.subtitle = subtitle;
    this.accent = accent;
    this.scr = null;
    this._io_lb = null;
    this._idx_lb = null;
    this._status_lb = null;
    this._bars = [];
    this._count = 0;
    this._cursor = 0;
    this._last_run = -99;
  }

  build() {
    const scr = lv.obj(null);
    scr.set_style_bg_color(u.C(u.BG), 0);
    this.scr = scr;

    u.mk_label(scr, this.title, 6, 2, u.TEXT, u.ZH);
    u.mk_label(scr, this.subtitle, 6, 21, u.TEXT3, u.ZH);
    this._status_lb = u.mk_label(scr, "待機", 0, 5, u.TEXT3, u.ZH);
    try {
      this._status_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4);
    } catch (e) {
      /* 沒有 align 的 binding 就維持左上 */
    }

    const card = u.mk_card(scr, 6, 38, 308, 194);
    const line = lv.obj(card);
    line.set_size(3, 190);
    line.set_pos(0, 2);
    line.set_style_bg_color(u.C(this.accent), 0);
    line.set_style_radius(2, 0);
    line.set_style_border_width(0, 0);
    line.set_style_pad_all(0, 0);
    try {
      line.remove_flag(lv.obj.FLAG.SCROLLABLE);
    } catch (e) {
      /* 沒有這個 flag 的 binding 就跳過 */
    }

    u.mk_label(card, "IO", 12, 8, u.TEXT3, u.ZH);
    this._io_lb = u.mk_label(card, "—", 12, 20, u.TEXT, u.ZH);

    u.mk_label(card, "選取 INDEX", 12, 52, u.TEXT3, u.ZH);
    this._idx_lb = u.mk_label(card, "0", 12, 62, this.accent, u.F_NUM_XL);

    // 兩個垂直亮度方塊
    u.mk_label(card, "呼吸", 196, 30, u.TEXT3, u.ZH);
    u.mk_label(card, "選中", 244, 30, u.TEXT3, u.ZH);
    for (const x of [196, 244]) {
      const [track, fill] = mk_vbar(card, x, 44, 34, 126, this.accent);
      const plb = u.mk_label(card, "0%", x + 5, 150, u.TEXT3, u.F_NUM_S);
      this._bars.push({ track: track, fill: fill, pct: plb, x: x, y: 44, w: 34, h: 126 });
    }
    // base fill 用淡色、selected 用主色
    try {
      this._bars[0]["fill"].set_style_bg_color(u.C(this.mode === "apa" ? 0xE7E2F8 : 0xD9F3E9), 0);
    } catch (e) {
      /* 第一條 bar 還沒建好就跳過 */
    }
    return scr;
  }

  on_enter() {
    open_page(this.mode);
    const st = state();
    this._cursor = _int(st.get("index", 0), 0);
    if (this._count > 0 && this._cursor >= this._count) {
      this._cursor = 0;
    }
    touch();
    this._paint_index(this._cursor);
  }

  on_leave() {
    close_page();
  }

  on_enc(d) {
    // 左右只移動游標/數字；真正選取要按 enter。
    if (!d) {
      return;
    }
    const n = this._count > 0 ? this._count : 1;
    this._cursor = wrap(this._cursor + Math.trunc(d), n);
    touch();
    this._paint_index(this._cursor);
  }

  on_confirm() {
    // enter 才把游標 commit 給 task。
    const st = state();
    st["index"] = Math.trunc(this._cursor);
    touch();
    this._paint_index(this._cursor);
    return null;
  }

  on_exit() {
    return false;
  }

  _paint_index(idx) {
    set_label(this._idx_lb, String(Math.trunc(idx)));
  }

  _paint_bar(i, p) {
    const b = this._bars[i];
    const color = i === 1 ? this.accent : (this.mode === "apa" ? 0xC9BFF0 : 0x9FE1C8);
    set_vbar(b["fill"], b["w"], b["h"], p, color);
    // 百分比放在 fill 頂端附近
    p = pct(p);
    try {
      b["pct"].set_pos(b["x"] + 4, b["y"] + b["h"] - 4 - Math.trunc(((b["h"] - 4) * p) / 100.0) + 2);
    } catch (e) {
      /* 百分比 label 不在就只更新數字 */
    }
    set_label(b["pct"], `${p}%`, i === 1 ? this.accent : u.TEXT2);
  }

  update(run) {
    // hb 約 200ms 一次；task lease 3s
    if (run - this._last_run >= 10) {
      this._last_run = run;
      touch();
    }
    const v = view();
    let c = 0;
    try {
      c = _int(v.get("count", 0), 0);
    } catch (e) {
      c = 0;
    }
    if (c > 0 && c !== this._count) {
      this._count = c;
      if (this._cursor >= c) {
        this._cursor = c - 1;
      }
      const st = state();
      const idx = _int(st.get("index", 0), 0);
      if (idx >= c) {
        st["index"] = c - 1;
      }
      this._paint_index(this._cursor);
    }
    const [txt, col] = status_text(v);
    set_label(this._status_lb, txt, col);
    set_label(this._io_lb, v.get("io") || "—");
    // 不從 view 覆蓋 _cursor：左右只改數字，enter 才 commit。
    this._paint_bar(0, v.get("base_pct", 0));
    this._paint_bar(1, v.get("sel_pct", 0));
  }

  // 給模組層使用的別名
  paint_index(idx) {
    this._paint_index(idx);
  }
}
