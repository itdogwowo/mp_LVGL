// app/nav.js — 共用導覽狀態機（對應 ui/lvgl/nav.py，行為一致）
//
// 兩層模型：
//   第一層 = 頁內選區域（焦點列表）：encoder 移動焦點，confirm 進入該項。
//   第二層 = 調值/改選項：slider/arc 用 encoder 調值、list 循環/移動、switch 切換。
//
// 頁面只註冊「項的清單」，框架處理 enc/confirm/exit 的狀態轉移 + 焦點視覺。
//
// 用法（跟 Python 一字不差）：
//   const nav = new Nav();
//   nav.reset();
//   nav.add(widget1, ITEM_INFO);
//   nav.add(sw, ITEM_SWITCH, { on_change: () => {...} });
//   nav.add(sl, ITEM_SLIDER, { on_change: (d) => {...} });
//   nav.paint();
//
//   export function on_enc(d) { nav.enc(d); }
//   export function on_confirm() { nav.confirm(); }
//   export function on_exit() { return nav.exit(); }
//   export function on_enter() { nav.focus(0); }

import { setFocus } from "./ui_common.js";

export const ITEM_INFO = 0;
export const ITEM_SWITCH = 1;
export const ITEM_ENUM = 2;
export const ITEM_SLIDER = 3;
export const ITEM_BUTTON = 4;
export const ITEM_LIST = 5; // confirm 進編輯（選擇），enc 上下移選項，confirm/exit 退出

// 可編輯態：confirm 進出編輯，enc 在編輯態呼叫 on_change(delta)
const EDITABLE = [ITEM_SLIDER, ITEM_LIST];

export class Nav {
  constructor() {
    this._items = []; // [{w, kind, on_change, on_focus}]
    this._fi = 0;
    this._editing = false;
  }

  // ── 註冊 ──
  reset() {
    for (const it of this._items) this._focusWidget(it.w, false, false);
    this._items = [];
    this._fi = 0;
    this._editing = false;
  }

  /**
   * @param {object} w       要畫焦點框的 widget
   * @param {number} kind    ITEM_*
   * @param {object} [opts]  { on_change(delta?), on_focus(focused) }
   */
  add(w, kind, opts = {}) {
    this._items.push({
      w,
      kind,
      on_change: opts.on_change ?? null,
      on_focus: opts.on_focus ?? null,
    });
  }

  focus(i = 0) {
    if (!this._items.length) return;
    this._fi = Math.max(0, Math.min(i | 0, this._items.length - 1));
    this._editing = false;
    this.paint();
  }

  // ── 焦點視覺 ──
  paint() {
    if (!this._items.length) return;
    this._fi = Math.max(0, Math.min(this._fi, this._items.length - 1));
    for (let i = 0; i < this._items.length; i++) {
      const it = this._items[i];
      const foc = i === this._fi;
      this._focusWidget(it.w, foc, this._editing && foc);
      if (it.on_focus) {
        try {
          it.on_focus(foc);
        } catch (e) {
          console.warn("[nav] on_focus err:", e);
        }
      }
    }
  }

  _focusWidget(w, foc, editing) {
    setFocus(w, foc, editing);
  }

  // ── 輸入 ──
  enc(d) {
    if (!this._items.length) return;
    if (this._editing) {
      const it = this._items[this._fi];
      if (it.on_change) {
        try {
          // 傳原始 delta（可能 ±N）：快速轉動不掉格
          it.on_change(d);
        } catch (e) {
          console.warn("[nav] enc_edit err:", e);
        }
      }
      return;
    }
    this._fi = (this._fi + d + this._items.length * 1000) % this._items.length;
    this.paint();
  }

  confirm() {
    if (!this._items.length) return;
    const it = this._items[this._fi];
    if (EDITABLE.includes(it.kind)) {
      this._editing = !this._editing;
      this.paint();
      return;
    }
    if (it.on_change) {
      try {
        it.on_change();
      } catch (e) {
        console.warn("[nav] confirm err:", e);
      }
    }
  }

  /** @returns {boolean} true = 消耗（留在頁面，例如退出編輯）；false = 回 launcher */
  exit() {
    if (this._editing) {
      this._editing = false;
      this.paint();
      return true;
    }
    return false;
  }

  // ── 查詢 ──
  is_editing() {
    return this._editing;
  }
  count() {
    return this._items.length;
  }
  current_kind() {
    return this._items.length ? this._items[this._fi].kind : null;
  }
}
