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
// 游標捲動：lv.js 的 List 已實作 scroll_to_view（游標超出可視區時捲動）。
//    照原檔用 try/catch 容忍 binding 差異（先試 item 版、失敗改 list 版）。
//    晶片表因列高固定（14px），維持「先判斷底端能不能塞下、塞不下直接跳過」的門檻。
//
// ⚠ 與原檔不同的地方：
//   1. 晶片內部排版（尺寸沿用設計的 104×138，不改大小）：
//      原檔格子 x=18/91、寬 14 → 右排 91+14=105 超出 104 的晶片（被裁 2px），
//      腳位 x=0/100 又壓在格子上。這裡改成兩排對稱（14..28 / 76..90）、腳位不越界，
//      讀數「00」改 22px 並置中（原本 28px 放在 x=52，會偏右壓到右排）。
//   2. 左卡清單 y：16 → 30（原檔清單 16 就壓到「目標」標籤 4..23，
//      加上 focus 外框再往外 3px，字的下緣會被切掉）
//   3. 底部：「同步 N 台」從卡內 (6,116) 移到 (6,170)，「掃描」移到最底 (6,204)
//   晶片大小只有一個係數 S（現在 1.0＝設計尺寸），其餘尺寸全部由它推導。
//   → 轉回 MicroPython 時，pixel_lab_pca.py 的這幾個座標要一起改，否則兩邊不一致。

import lv from "@lvui/frameworks/lvgl/lv.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import * as u from "@packages/lv-app/ui_common.js";
import * as c from "./pixel_lab_common.js";

const CH_COUNT = 16;
// 「全部通道」：PCA9685 的 ALL_LED 暫存器寫一次就套用到 0..15。
// 游標用 -1 表示「全部」（只存在 UI 層），寫進 state 時轉成 0xFF。
const ALL_CH = 0xff;
const CURSOR_ALL = -1;
const SCAN_TIMEOUT_MS = 8000;
const SEL_BG = 0xD2E3FC;
const CURSOR_BG = 0xFFF3CD;

// 裝置的 record 一定是 dict（有 .get）；模擬器的服務可能給一般物件 → 兩種都吃。
function _g(r, k, dflt = null) {
  if (r == null) return dflt;
  if (typeof r.get === "function") return r.get(k, dflt);
  return r[k] === undefined ? dflt : r[k];
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
    this._pins_lb = null;
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
      const raw = Math.trunc(Number(st.get("ch", 0) || 0)) & 0xff;
      // 0xFF = ALL_LED = 全部通道（回 -1，給 UI 當「全部」用）
      if (raw === ALL_CH) {
        return CURSOR_ALL;
      }
      return c.wrap(raw, CH_COUNT);
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
      this._list.clean(); // lv.js 的 clean() 會連 _items 一起清（跟真機一致）
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
    // 列高是「字高 + item pad」，pad 是 add_text 之後才設的 →
    // 全部加完要重排一次，否則列距還是預設值（3 列就超出清單被裁掉）。
    try {
      this._list._layoutItems();
    } catch (e) {
      /* 沒有這個方法就跳過 */
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
    // 清單從 y=30 開始：原檔 y=16 會壓到上面「目標」那行字（標籤 4..23），
    // 而且清單的 focus 外框還會再往外 3px（outline_pad），剛好切到字的下緣。
    // 30 之後留 7px 給外框，字不會被壓到。
    const pair = u.mk_list(left, 2, 30, 100, 88, ["(載入中)"], u.ZH);
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
    // 兩行（行高 19）：IO 在 6、接腳在 25 → 文字佔到 44
    u.mk_label(right, "IO", 12, 6, u.TEXT3, u.ZH);
    this._io_lb = u.mk_label(right, "—", 40, 6, u.TEXT, u.ZH);
    this._pins_lb = u.mk_label(right, "", 12, 25, u.TEXT3, u.ZH);

    // ── 晶片（設計尺寸 → 實際）────────────────────────────
    //
    // 這頁的設計是在「實際的兩倍」上畫的（設計高度 100、實際只有 50），
    // 也就是原始那組數字（104×138、圓角 10、格子 14、間距 16、腳位 4）
    // 是**設計尺寸**，不是要縮，是要按設計放大。
    // S = 1.0 就是「照設計尺寸」；其餘全部由它推導，要微調只改這一個數字。
    const S = 1.0;
    const CHIP_W = Math.round(104 * S); // 104
    const CHIP_H = Math.round(138 * S); // 138
    const CELL = Math.round(14 * S); // 14
    const PITCH = Math.round(16 * S); // 16
    const PIN_W = Math.max(2, Math.round(4 * S)); // 4
    const PAD = Math.round(4 * S); // 4
    // 讀數字級跟著晶片寬度走（12 / 16 / 22px），不要寫死
    const NUM_FONT = CHIP_W >= 96 ? u.F_NUM_L : CHIP_W >= 72 ? u.F_NUM_M : u.F_NUM_S;
    this._cell = CELL;
    // 置中要扣掉 1px 邊框：卡片內容區 = w-2，直接 (w-CHIP_W)/2 會右偏 2px。
    const chipX = Math.round((right.w - 2 - CHIP_W) / 2);
    // 卡片內高 192、晶片 138 → 上下各留 6：文字 6..44、晶片 48..186（abs 87..225）
    const chipY = 48;
    const chip = lv.obj(right);
    chip.set_size(CHIP_W, CHIP_H);
    chip.set_pos(chipX, chipY);
    chip.set_style_bg_color(u.C(0xFBFCFE), 0);
    chip.set_style_radius(Math.round(10 * S), 0); // 10
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
      notch.set_size(4, 4);
      notch.set_pos(4, 3);
      notch.set_style_radius(2, 0);
      notch.set_style_bg_color(u.C(u.TEXT3), 0);
      notch.set_style_border_width(0, 0);
      notch.set_style_pad_all(0, 0);
    } catch (e) {
      notch = null;
    }

    // side pins：**伸出晶片外**（真 IC 的腳是外露的；畫在晶片裡面會像虛線邊框）。
    //   ⚠ 不能掛在 chip 底下：子物件會被父物件的裁切區剪掉（負座標直接消失），
    //   所以掛在卡片 right 上，用晶片的相對位置算。
    for (let i = 0; i < 8; i++) {
      const y = chipY + PAD + 2 + i * PITCH + Math.round((CELL - 2) / 2);
      for (const x of [chipX - PIN_W, chipX + CHIP_W]) {
        try {
          const pin = lv.obj(right);
          pin.set_size(PIN_W, 1);
          pin.set_pos(x, y);
          pin.set_style_bg_color(u.C(0xB4BDC9), 0);
          pin.set_style_border_width(0, 0);
          pin.set_style_pad_all(0, 0);
        } catch (e) {
          /* 裝飾用的腳，建不出來不影響功能 */
        }
      }
    }

    // 2 columns × 8 squares（尺寸/間距由 CELL/PITCH 推導，兩排對稱）
    //   margin 取 0.13 × 寬（104 → 14）：兩排 14..28 / 76..90，
    //   中間 48px 留給讀數，22px 的「00」約 25 寬，置中後左右各還有 11px。
    this._squares = [];
    const margin = Math.max(3, Math.round(CHIP_W * 0.13));
    const COL_X = [margin, CHIP_W - margin - CELL];
    for (let idx = 0; idx < CH_COUNT; idx++) {
      const col = idx < 8 ? 0 : 1;
      const row = idx % 8;
      const x = COL_X[col];
      const y = PAD + 1 + row * PITCH;
      const [track, fill] = c.mk_vbar(chip, x, y, CELL, CELL, 0xD97706);
      this._squares.push({ track: track, fill: fill, idx: idx, x: x, y: y });
    }

    // center channel + selected %（用字型實際量到的寬度置中；-1 是 1px 邊框偏移）
    const numW = Math.round(NUM_FONT.measure("00"));
    const pctW = Math.round(u.F_NUM_S.measure("0%"));
    const numY = Math.round(CHIP_H / 2) - Math.round(NUM_FONT.lineHeight * 0.75);
    this._ch_lb = u.mk_label(chip, "00", Math.round((CHIP_W - numW) / 2) - 1, numY, 0xD97706, NUM_FONT);
    this._pct_lb = u.mk_label(chip, "0%", Math.round((CHIP_W - pctW) / 2) - 1, numY + NUM_FONT.lineHeight + 2, u.TEXT2, u.F_NUM_S);

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
    // 晶片本體不再畫大框：整個 104×138 被 3px 藍框包住，看起來像「整顆被選取」。
    // 進入晶片區的提示改由「游標框」表示（見 _paint_selected）。
    try {
      u.set_focus(this._chip, false);
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

  /**
   * 晶片上只允許**一個**框，跟著焦點走：
   *   focus 0（清單）      → 不畫框（還沒選目標，沒有「已選」這回事）
   *   focus 1（選通道）    → 琥珀框：游標在單格就框那一格；游標在「全部」就框**晶片本體**
   *   focus 2（掃描）      → 藍框，停在剛套用的位置（單格或晶片本體）
   * 「全部」用晶片本體表示（一個框），不要 16 個框一起亮——那看起來很雜。
   */
  _set_chip_frame(color) {
    try {
      if (color === null) {
        this._chip.set_style_outline_width(0, 0);
      } else {
        this._chip.set_style_outline_color(u.C(color), 0);
        this._chip.set_style_outline_width(2, 0);
        this._chip.set_style_outline_pad(2, 0);
      }
    } catch (e) {
      /* 晶片不在就跳過 */
    }
  }

  _paint_selected() {
    const ch = this._applied_ch();
    const cur = this._ch_cursor;
    const allCursor = this._focus === 1 && cur === CURSOR_ALL;
    const allApplied = this._focus === 2 && ch === CURSOR_ALL;
    this._set_chip_frame(allCursor ? u.WARNING : allApplied ? u.PRIMARY : null);
    for (const s of this._squares) {
      try {
        let color = null;
        if (this._focus === 1 && cur !== CURSOR_ALL && s["idx"] === cur) {
          color = u.WARNING;
        } else if (this._focus === 2 && ch !== CURSOR_ALL && s["idx"] === ch) {
          color = u.PRIMARY;
        }
        if (color === null) {
          s["track"].set_style_outline_width(0, 0);
        } else {
          s["track"].set_style_outline_color(u.C(color), 0);
          s["track"].set_style_outline_width(2, 0);
          s["track"].set_style_outline_pad(1, 0);
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
    const sel = c.pct(v.get("sel_pct", 0));
    for (const s of this._squares) {
      const i = s["idx"];
      let p = base;
      if (Array.isArray(pcts) && i < pcts.length) {
        p = c.pct(pcts[i]);
      }
      // 亮色/亮度一律跟游標（游標 = -1 時＝全部通道，16 格一起亮）
      const isCur = cur === CURSOR_ALL || i === cur;
      if (isCur) {
        p = sel;
      }
      const color = isCur ? 0xD97706 : 0xF0C98A;
      try {
        c.set_vbar(s["fill"], this._cell, this._cell, p, color);
      } catch (e) {
        /* 格子 fill 不在就跳過 */
      }
    }
    // 中央顯示游標（全部 → ALL）；enter 後才會套用到 task。
    try {
      this._ch_lb.set_text(cur === CURSOR_ALL ? "ALL" : String(cur).padStart(2, "0"));
    } catch (e) {
      /* label 不在就跳過 */
    }
    let pct = v.get("sel_pct", 0);
    if (cur !== CURSOR_ALL && cur !== ch && Array.isArray(pcts) && cur < pcts.length) {
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
    // 第一次進來：游標停在「全部通道」（＝ALL_LED），不是 00。
    this._ch_cursor = CURSOR_ALL;
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
    const step = Math.trunc(d);
    if (this._focus === 0) {
      const n = this._targets.length;
      if (n) {
        this._cursor = c.wrap(this._cursor + step, n);
        c.touch();
        this._sync_list();
      }
    } else if (this._focus === 1) {
      // 游標順序：ALL → 00 → 01 … → 15 → ALL（繞一圈，隨時可以再選回「全部」）
      const n = CH_COUNT + 1;
      const pos = this._ch_cursor === CURSOR_ALL ? 0 : this._ch_cursor + 1;
      const next = (((pos + step) % n) + n) % n;
      this._ch_cursor = next === 0 ? CURSOR_ALL : next - 1;
      c.touch();
      this._paint_selected();
      this._paint_squares(c.view());
    }
  }

  on_confirm() {
    if (this._focus === 0) {
      // enter：真正選取目標，然後換到 channel 區（游標先停在「全部」）。
      this._commit();
      this._focus = 1;
      this._ch_cursor = CURSOR_ALL;
      this._paint_focus();
      this._paint_squares(c.view());
      c.touch();
    } else if (this._focus === 1) {
      // enter：真正選取 channel（「全部」→ 0xFF，代表 ALL_LED 一次寫 16 個通道）。
      const st = c.state();
      st["ch"] = this._ch_cursor === CURSOR_ALL ? ALL_CH : c.wrap(this._ch_cursor, CH_COUNT);
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
    c.set_label(this._pins_lb, v.get("pins") || "");
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
  icon: "gauge",
  desc: "PCA9685",
  order: 1,
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
