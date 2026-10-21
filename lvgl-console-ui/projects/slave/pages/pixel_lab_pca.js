// projects/slave/pages/pixel_lab_pca.js — PixelLab PCA（仿晶片直放、2×8、目標/掃描）
//
// 對應 ui/lvgl/page/pixel_lab_pca.py
//
// 版面：
//   左：目標清單（固定高度、可捲動）＋ 清單外的獨立「掃描」按鈕
//   右：I2C IO、直放晶片（左右各 8 格）、中央 Channel/百分比
// 資料：
//   pca9685_ctl（driver 建的控制表）→ 清單/掃描
//   PixelLabTask 直接寫選中的 PCA；本頁只設定 target/ch，不碰硬體
//
// ⚠ 缺少 API: lv.list.scroll_to_view / list_item.scroll_to_view
//    模擬器的 lv.list 沒有捲動實作；原檔本來就用 try/except 容忍 binding 缺這個方法，
//    這裡照抄同樣的 fallback：游標仍可移動、只是可視區不會跟著捲（維持原狀）。
// ⚠ 缺少 API: lv.list.clean() 只刪 children、不清 List._items → 已用 _list_clear() 代替
//    （不清 _items 的話，下一次 add_text 的新列會接在已刪掉的列後面，越排越下面、被 clip 掉）
// ⚠ 缺少 API: lv.list 的列在 lv.js 預設透明（bg_opa = 0）→ 已用 set_style_bg_opa(255) 補
//    （只換 bg_color 看不到藍底/琥珀底；真機由 theme 決定）

import lv from "@lvui/frameworks/lvgl/lv.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import * as u from "@packages/lv-app/ui_common.js";
import * as c from "./pixel_lab_common.js";

const CH_COUNT = 16;
const SCAN_TIMEOUT_MS = 8000;
const SEL_BG = 0xD2E3FC;
const CURSOR_BG = 0xFFF3CD;

// 裝置的 record 一定是 dict（有 .get）；模擬器的服務可能給一般物件 → 兩種都吃。
function _g(r, k, dflt = null) {
  if (r == null) return dflt;
  if (typeof r.get === "function") return r.get(k, dflt);
  return r[k] === undefined ? dflt : r[k];
}

function _list_clear(lst) {
  // ⚠ lv.js 的 clean() 只刪 children；List._items 留著會讓下一次 add_text 從舊位置
  //   續排（新列排在已刪除的列後面）→ 這裡連 _items 一起清。
  try {
    lst.clean();
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
  if (lst && lst._items) lst._items.length = 0;
}

/** 兩組 [i2c, addr] 的逐值比較（Python tuple == tuple；JS 陣列不能直接 ==）。 */
function _key_eq(a, b) {
  if (a === null || b === null) return a === b;
  return a[0] === b[0] && a[1] === b[1];
}

export class PcaPage {
  constructor() {
    this.scr = null;
    this._list = null;
    this._btns = [];
    this._targets = [];
    this._sel = 0;
    this._cursor = 0;
    this._sig = null;
    this._scan_pending = false;
    this._scan_at = 0;
    this._focus = 0;
    this._ch_cursor = 0;
    this._last_run = -99;
    this._status_lb = null;
    this._io_lb = null;
    this._sync_lb = null;
    this._scan_btn = null;
    this._chip = null;
    this._squares = [];
    this._ch_lb = null;
    this._pct_lb = null;
  }

  // ── 資料 ────────────────────────────────────────────
  _ctl() {
    const s = bus.get_service("pca9685_ctl");
    if (!Array.isArray(s)) {
      return [];
    }
    const out = s.slice();
    try {
      out.sort((a, b) => {
        const ba = _g(a, "broadcast") ? 0 : 1;
        const bb = _g(b, "broadcast") ? 0 : 1;
        if (ba !== bb) return ba - bb;
        const ia = Math.trunc(Number(_g(a, "i2c", 0)));
        const ib = Math.trunc(Number(_g(b, "i2c", 0)));
        if (ia !== ib) return ia - ib;
        return Math.trunc(Number(_g(a, "addr", 0))) - Math.trunc(Number(_g(b, "addr", 0)));
      });
    } catch (e) {
      /* 跟裝置一樣：排序失敗就沿用原順序 */
    }
    return out;
  }

  _sig_of(ts) {
    // Python 用 tuple 逐值比較；JS 用 JSON 字串當簽章，效果同樣是「內容變才重建」
    const out = [];
    for (const r of ts) {
      out.push([
        _g(r, "i2c"),
        _g(r, "addr"),
        Boolean(_g(r, "online")),
        (_g(r, "boards") || []).length,
      ]);
    }
    return JSON.stringify(out);
  }

  _row_text(r) {
    let s = `0x${Math.trunc(Number(_g(r, "addr", 0))).toString(16).toUpperCase().padStart(2, "0")}`;
    if (_g(r, "broadcast")) {
      s += " 廣播";
    } else {
      s = `${_g(r, "online") ? "●" : "○"} ${s}`;
    }
    return s;
  }

  _applied_ch() {
    try {
      const st = c.state();
      return c.wrap(Math.trunc(Number(st.get("ch", 0) || 0)), CH_COUNT);
    } catch (e) {
      return 0;
    }
  }

  _cur_rec() {
    if (this._sel >= 0 && this._sel < this._targets.length) {
      return this._targets[this._sel];
    }
    return null;
  }

  _key(r) {
    if (r === null) {
      return null;
    }
    return [
      Math.trunc(Number(_g(r, "i2c", 0) || 0)),
      Math.trunc(Number(_g(r, "addr", 0) || 0)),
    ];
  }

  _commit_state() {
    const st = c.state();
    const rec = this._cur_rec();
    if (rec === null) {
      st["target"] = 0x70;
      st["target_bus"] = 0;
    } else {
      st["target"] = Math.trunc(Number(_g(rec, "addr", 0) || 0));
      st["target_bus"] = Math.trunc(Number(_g(rec, "i2c", 0) || 0));
    }
    c.touch();
  }

  _refresh_targets(force = false) {
    if (this._list === null) {
      return;
    }
    const ts = this._ctl();
    const sig = this._sig_of(ts);
    if (!(force || sig !== this._sig)) {
      this._targets = ts;
      this._sync_list();
      return;
    }
    const old_key = this._key(this._cur_rec());
    const changed = sig !== this._sig;
    this._sig = sig;
    this._targets = ts;
    if (changed) {
      // 掃描結果回來了（清單內容有變）→ 結束「掃描中…」
      this._scan_pending = false;
    }
    let labels = ts.map((r) => this._row_text(r));
    if (!labels.length) {
      labels = ["(無控制器)"];
    }
    try {
      _list_clear(this._list);
    } catch (e) {
      /* 清單已不在就跳過 */
    }
    this._btns = [];
    for (const txt of labels) {
      try {
        const b = this._list.add_text(txt);
        if (u.ZH) {
          b.set_style_text_font(u.ZH, 0);
        }
        try {
          b.set_style_pad_all(1, 0);
        } catch (e) {
          /* 這個 binding 沒有 item pad 就跳過 */
        }
        this._btns.push(b);
      } catch (e) {
        continue;
      }
    }

    this._sel = 0;
    let found = false;
    if (old_key !== null) {
      for (let i = 0; i < ts.length; i++) {
        if (_key_eq(this._key(ts[i]), old_key)) {
          this._sel = i;
          found = true;
          break;
        }
      }
    }
    if (!found) {
      for (let i = 0; i < ts.length; i++) {
        if (Math.trunc(Number(_g(ts[i], "addr", 0) || 0)) === 0x70) {
          this._sel = i;
          break;
        }
      }
    }
    this._cursor = this._sel;
    this._sync_list();
    this._commit_state();
  }

  _sync_list() {
    const n = this._btns.length;
    for (let i = 0; i < n; i++) {
      const b = this._btns[i];
      const rec = i < this._targets.length ? this._targets[i] : null;
      let fg, bg;
      if (rec === null) {
        fg = u.TEXT3;
        bg = u.BG;
      } else {
        if (_g(rec, "broadcast")) {
          fg = u.PRIMARY;
        } else {
          fg = _g(rec, "online") ? u.SUCCESS : u.TEXT3;
        }
        if (i === this._cursor) {
          bg = CURSOR_BG;
        } else if (i === this._sel) {
          bg = SEL_BG;
        } else {
          bg = u.BG;
        }
      }
      try {
        // ⚠ 模擬器的 list 列預設透明（bg_opa = 0）→ 一起設，否則藍底/琥珀底看不到。
        b.set_style_bg_opa(255, 0);
        b.set_style_bg_color(u.C(bg), 0);
        b.set_style_text_color(u.C(fg), 0);
      } catch (e) {
        /* item 還沒有 style 就跳過 */
      }
    }
    this._scroll();
  }

  _scroll() {
    if (this._list === null || !this._btns.length) {
      return;
    }
    const i = Math.max(0, Math.min(this._cursor, this._btns.length - 1));
    const b = this._btns[i];
    try {
      this._list.scroll_to_view(b);
      return;
    } catch (e) {
      /* 模擬器的 list 沒有 scroll_to_view，往下試 item 版本 */
    }
    // 某些 binding 只提供 child.scroll_to_view()；有就用，沒有就維持原狀
    try {
      b.scroll_to_view();
    } catch (e) {
      /* 兩種都沒有就維持原狀（原檔的容忍路徑） */
    }
  }

  _commit() {
    if (!this._btns.length) {
      return;
    }
    this._sel = Math.max(0, Math.min(this._cursor, this._targets.length - 1));
    this._commit_state();
    this._sync_list();
  }

  // ── 掃描（清單外按鈕）──────────────────────────────
  _do_scan() {
    if (this._scan_pending) {
      return;
    }
    let q = bus.shared.get("_pca_actions");
    if (!Array.isArray(q)) {
      q = [];
      bus.shared["_pca_actions"] = q;
    }
    q.push(dict({ action: "scan" }));
    this._scan_pending = true;
    this._scan_at = Date.now();
    this._paint_sync();
  }

  _poll_scan() {
    if (!this._scan_pending) {
      return;
    }
    let since;
    try {
      since = Date.now() - this._scan_at;
    } catch (e) {
      since = SCAN_TIMEOUT_MS + 1;
    }
    if (since > SCAN_TIMEOUT_MS) {
      this._scan_pending = false;
    }
  }

  // ── 建立畫面 ────────────────────────────────────────
  build() {
    const scr = lv.obj(null);
    scr.set_style_bg_color(u.C(u.BG), 0);
    this.scr = scr;

    u.mk_label(scr, "PixelLab PCA", 6, 2, u.TEXT, u.ZH);
    u.mk_label(scr, "PCA9685", 6, 21, u.TEXT3, u.ZH);
    this._status_lb = u.mk_label(scr, "待機", 0, 5, u.TEXT3, u.ZH);
    try {
      this._status_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4);
    } catch (e) {
      /* 沒有 align 的 binding 就維持左上 */
    }

    // ── 左：固定高度清單卡 + 清單外的掃描 ──
    const left = u.mk_card(scr, 6, 38, 104, 128);
    u.mk_label(left, "目標", 6, 4, u.TEXT3, u.ZH);
    const pair = u.mk_list(left, 2, 16, 100, 96, ["(載入中)"], u.ZH);
    this._list = pair[0];
    this._btns = pair[1];
    try {
      this._list.set_style_pad_all(1, 0);
    } catch (e) {
      /* list 不支援就跳過 */
    }
    // 底部配置（與原檔不同，依使用者要求）：
    //   原本「同步 N 台」擠在清單卡裡 (6,116)、掃描在 (6,174) 下面留一大片空白。
    //   現在：同步數量移到原本掃描的位置（視線會先看到），掃描貼到最底 (204)。
    this._sync_lb = u.mk_label(scr, "", 6, 170, u.SUCCESS, u.ZH);
    this._scan_btn = u.mk_btn(scr, "掃描", 6, 204, 104, 28, "secondary");

    // ── 右：IO + 直放晶片 ──
    const right = u.mk_card(scr, 116, 38, 198, 194);
    const line = lv.obj(right);
    line.set_size(3, 190);
    line.set_pos(0, 2);
    line.set_style_bg_color(u.C(0xD97706), 0);
    line.set_style_radius(2, 0);
    line.set_style_border_width(0, 0);
    line.set_style_pad_all(0, 0);
    try {
      line.remove_flag(lv.obj.FLAG.SCROLLABLE);
    } catch (e) {
      /* 沒有這個 flag 的 binding 就跳過 */
    }
    u.mk_label(right, "IO", 12, 8, u.TEXT3, u.ZH);
    this._io_lb = u.mk_label(right, "—", 12, 20, u.TEXT, u.ZH);

    // chip body (vertical)
    const chip = lv.obj(right);
    chip.set_size(104, 138);
    chip.set_pos(44, 40);
    chip.set_style_bg_color(u.C(0xFBFCFE), 0);
    chip.set_style_radius(10, 0);
    chip.set_style_border_color(u.C(0xCBD5E1), 0);
    chip.set_style_border_width(1, 0);
    chip.set_style_pad_all(0, 0);
    try {
      chip.remove_flag(lv.obj.FLAG.SCROLLABLE);
    } catch (e) {
      /* 沒有這個 flag 的 binding 就跳過 */
    }
    this._chip = chip;

    // notch
    let notch = null;
    try {
      notch = lv.obj(chip);
      notch.set_size(5, 5);
      notch.set_pos(5, 4);
      notch.set_style_radius(3, 0);
      notch.set_style_bg_color(u.C(u.TEXT3), 0);
      notch.set_style_border_width(0, 0);
      notch.set_style_pad_all(0, 0);
    } catch (e) {
      notch = null;
    }

    // side pins (inside chip edges; decorative)
    for (let i = 0; i < 8; i++) {
      const y = 10 + i * 16;
      for (const x of [0, 100]) {
        try {
          const pin = lv.obj(chip);
          pin.set_size(4, 1);
          pin.set_pos(x, y);
          pin.set_style_bg_color(u.C(0xB4BDC9), 0);
          pin.set_style_border_width(0, 0);
          pin.set_style_pad_all(0, 0);
        } catch (e) {
          /* 裝飾用的腳，建不出來不影響功能 */
        }
      }
    }

    // 2 columns × 8 squares
    this._squares = [];
    for (let idx = 0; idx < CH_COUNT; idx++) {
      const col = idx < 8 ? 0 : 1;
      const row = idx % 8;
      const x = col === 0 ? 18 : 91;
      const y = 10 + row * 16;
      const [track, fill] = c.mk_vbar(chip, x, y, 14, 14, 0xD97706);
      this._squares.push({ track: track, fill: fill, idx: idx, x: x, y: y });
    }

    // center channel + selected %
    this._ch_lb = u.mk_label(chip, "00", 52, 32, 0xD97706, u.F_NUM_XL);
    this._pct_lb = u.mk_label(chip, "0%", 52, 72, u.TEXT2, u.F_NUM_S);

    // focus frame on the chip
    this._paint_focus();
    return scr;
  }

  // ── focus / squares ─────────────────────────────────
  _paint_focus() {
    try {
      u.set_focus(this._list, this._focus === 0);
    } catch (e) {
      /* 沒有 set_focus 的 binding 就跳過 */
    }
    try {
      u.set_focus(this._chip, this._focus === 1);
    } catch (e) {
      /* 同上 */
    }
    try {
      u.set_focus(this._scan_btn, this._focus === 2);
    } catch (e) {
      /* 同上 */
    }
    this._paint_selected();
  }

  _paint_selected() {
    // 主色框 = 真正套用的 channel；左/右游標用 warning 框預覽。
    const ch = this._applied_ch();
    const cur = this._focus === 1 ? this._ch_cursor : ch;
    for (const s of this._squares) {
      try {
        if (s["idx"] === ch) {
          s["track"].set_style_outline_color(u.C(u.PRIMARY), 0);
          s["track"].set_style_outline_width(2, 0);
          s["track"].set_style_outline_pad(1, 0);
        } else if (s["idx"] === cur) {
          s["track"].set_style_outline_color(u.C(u.WARNING), 0);
          s["track"].set_style_outline_width(1, 0);
          s["track"].set_style_outline_pad(1, 0);
        } else {
          s["track"].set_style_outline_width(0, 0);
        }
      } catch (e) {
        /* 格子還沒建好就跳過 */
      }
    }
  }

  _paint_squares(v) {
    const pcts = v.get("ch_pcts");
    const base = c.pct(v.get("base_pct", 0));
    const ch = this._applied_ch();
    const cur = this._focus === 1 ? this._ch_cursor : ch;
    for (const s of this._squares) {
      const i = s["idx"];
      let p = base;
      if (Array.isArray(pcts) && i < pcts.length) {
        p = c.pct(pcts[i]);
      }
      if (i === ch) {
        p = c.pct(v.get("sel_pct", p));
      }
      const color = i === ch ? 0xD97706 : 0xF0C98A;
      try {
        c.set_vbar(s["fill"], 14, 14, p, color);
      } catch (e) {
        /* 格子 fill 不在就跳過 */
      }
    }
    // 中央是游標數字（左/右會動）；enter 後才會套用到 task。
    try {
      this._ch_lb.set_text(String(cur).padStart(2, "0"));
    } catch (e) {
      /* label 不在就跳過 */
    }
    let pct = v.get("sel_pct", 0);
    if (cur !== ch && Array.isArray(pcts) && cur < pcts.length) {
      pct = pcts[cur];
    }
    try {
      this._pct_lb.set_text(`${c.pct(pct)}%`);
    } catch (e) {
      /* label 不在就跳過 */
    }
    this._paint_selected();
  }

  _paint_sync() {
    if (this._sync_lb === null) {
      return;
    }
    if (this._scan_pending) {
      c.set_label(this._sync_lb, "掃描中…", u.WARNING);
      return;
    }
    const rec = this._cur_rec();
    if (rec === null) {
      c.set_label(this._sync_lb, "無裝置", u.DANGER);
    } else if (_g(rec, "broadcast")) {
      const n = (_g(rec, "boards") || []).length;
      if (n && _g(rec, "online")) {
        c.set_label(this._sync_lb, `同步 ${n} 台`, u.SUCCESS);
      } else if (n) {
        c.set_label(this._sync_lb, "離線", u.DANGER);
      } else {
        c.set_label(this._sync_lb, "無實體板", u.DANGER);
      }
    } else {
      c.set_label(this._sync_lb, _g(rec, "online") ? "在線" : "離線",
        _g(rec, "online") ? u.SUCCESS : u.DANGER);
    }
  }

  // ── 頁面接口 ────────────────────────────────────────
  on_enter() {
    this._focus = 0;
    this._ch_cursor = this._applied_ch();
    this._refresh_targets(true);
    c.open_page("pca");
    c.touch();
    this._paint_focus();
    this._paint_sync();
  }

  on_leave() {
    c.close_page();
    this._focus = 0;
  }

  on_enc(d) {
    if (!d) {
      return;
    }
    if (this._focus === 0) {
      const n = this._targets.length;
      if (n) {
        this._cursor = c.wrap(this._cursor + Math.trunc(d), n);
        c.touch();
        this._sync_list();
      }
    } else if (this._focus === 1) {
      // 左右只移動 channel 游標；enter 才寫入 state 給 task。
      this._ch_cursor = c.wrap(this._ch_cursor + Math.trunc(d), CH_COUNT);
      c.touch();
      this._paint_selected();
      this._paint_squares(c.view());
    }
  }

  on_confirm() {
    if (this._focus === 0) {
      // enter：真正選取目標，然後換到 channel 區。
      this._commit();
      this._focus = 1;
      this._ch_cursor = this._applied_ch();
      this._paint_focus();
      this._paint_squares(c.view());
      c.touch();
    } else if (this._focus === 1) {
      // enter：真正選取 channel。
      const st = c.state();
      st["ch"] = c.wrap(this._ch_cursor, CH_COUNT);
      c.touch();
      this._focus = 2;
      this._paint_focus();
      this._paint_squares(c.view());
    } else {
      this._do_scan();
    }
    return null;
  }

  on_exit() {
    // exit =「返回上一層」，不是直接離開：
    //   掃描(2) → channel(1) → 目標清單(0) → launcher。
    // 回 true = 本頁消耗（只退一層）；回 false = 已到最上層，app 才回 launcher。
    if (this._focus === 2) {
      this._focus = 1;
      this._paint_focus();
      this._paint_squares(c.view());
      return true;
    }
    if (this._focus === 1) {
      this._focus = 0;
      this._paint_focus();
      return true;
    }
    return false;
  }

  update(run) {
    if (run - this._last_run >= 10) {
      this._last_run = run;
      c.touch();
    }
    this._poll_scan();
    this._refresh_targets();
    const v = c.view();
    const [txt, col] = c.status_text(v);
    c.set_label(this._status_lb, txt, col);
    c.set_label(this._io_lb, v.get("io") || "—");
    this._paint_sync();
    if (v.get("mode") === "pca") {
      this._paint_squares(v);
    } else {
      // 尚未開始/被接手：保持最後顯示，但焦點/清單仍更新
      this._paint_selected();
    }
  }
}

const _page = new PcaPage();
export let scr = null;

export const meta = {
  id: "pixel_lab_pca",
  title: "PixelLab PCA",
  icon: "sun",
  desc: "PCA9685 · 目標/16 通道",
  order: 4,
  accent: 0xD97706,
};

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
