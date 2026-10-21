// projects/slave/pages/pca9685.js — PCA9685 控制器頁（橫屏 320×240）
//
// 對應 ui/lvgl/page/pca9685.py
//
// ══════════════════════════════════════════════════════════════════
// 版面（2026-10 使用者定案：遙控器式「左列表 / 右顯示」）
// ══════════════════════════════════════════════════════════════════
//   頂列    PCA9685 控制器
//   左欄    控制目標（lv.list）
//             0x70 廣播        ← 廣播：一次寫入全部板子（第一項）
//             ● 0x40           ← 單板：只寫這一顆
//             ○ 0x41           ← ○ = 掃描沒看到（離線）
//           藍底 = 已套用；琥珀底 = 游標（按確認才變藍）
//           [全熄] [掃描]
//   右欄    目標卡  0x70 廣播                  同步 3 台
//           通道卡  通道亮度                     0-4095
//                   00 ▓▓▓▓▓░░ 2048   08 ░░░░░░░    0
//                   ...（左 CH0-7、右 CH8-15，每列 = 編號＋長條＋數值）
//           數值卡  CH0  ──────●──────  2048
//
// 為什麼要這樣分：
//   - 列表 = 控制目標（遙控器選「對誰講話」）。清單同時包含廣播與每一顆實體板，
//     所以「廣播控制」和「單板控制」是同一個入口，不用另一個模式切換。
//   - 右邊 = 那個目標的 16 通道狀態。廣播時只顯示一組（所有板子收到相同內容，
//     顯示模式自然更簡單）；單板時顯示那一顆的快取。
//   - 層次 = 目標 → 通道 → 數值：
//       清單：encoder 移動「游標」（琥珀底），按確認才套用成控制目標（藍底），
//             套用後焦點自動移到通道方格（使用者定案 2026-10）。
//       方格：confirm 進通道選擇，encoder 選 CH0-15。
//       數值：最下面那條，confirm 進編輯、encoder 調 12-bit 亮度。
//     每一層都有自己的焦點框（nav 模組）。
//
// 資料/控制路徑：
//   bus.get_service("pca9685_ctl")  ← pca9685_drv 建的控制表（原始 PCA9685 物件）
//     record = {"i2c", "addr", "pca", "broadcast", "boards", "online"}
//   顯示：讀 `pca.buf[0..15]`（硬體側 12-bit）。
//   控制：單通道 `pca.set_channel(ch, v)`（只寫 4 bytes）；全熄用 `pca.show()`
//         （一次 64 bytes）。舊驅動沒有 set_channel 時自動退回
//         `pca.buf[ch] = v; pca.show()`。
//   廣播：record.broadcast = true 時，寫 0x70 之外同時更新 `boards` 對應的單板
//         record 快取，這樣切回單板時看到的值不會是上一個畫面。
//   ★ 顯示的是「控制物件的 buf」（本頁的控制快取），不是從 PCA 暫存器回讀；
//     播放端有自己的 controller 物件，所以播放中的最後一幀不會自動出現在這裡。
//
// ★ 不要在這裡自己建 I2C/PCA9685：硬體一律由 driver 建，UI 只讀 bus 服務。
// ★ 手動控制和自動播放（PixelTask/PixelStreamer）同時跑時，播放端每幀會覆寫
//   這裡寫的值（last-write-wins）。本頁適合播放停止時檢查/調整，或當測試工具。
// ★ 掃描鈕走 `_pca_actions` 佇列（在 task 執行，避免 I2C.scan() 卡 LVGL），
//   task 掃完會呼叫 `refresh_pca_ctl()` → 這裡的目標清單跟著增減。
// ★ 離開頁面不自動熄燈：這是控制器頁，使用者調好的亮度要留著（舊版的 on_leave
//   會送 stop/alloff，但那個 action 本來就沒有消費端）。
// ★ 舊版的「逐腳呼吸/全腳呼吸」與 bus.shared["pca9685"] 已移除：它們沒有消費端，
//   而且廣播/單板的控制路徑現在是直接寫 PCA 物件，不需要另外的狀態機。
//
// ⚠ 缺少 API: lv.list.clean() 只刪 children、不清 List._items → 已用 _list_clear() 代替
//   （不清的話，之後 add_text 的新列會接在已刪掉的列後面，越排越下面、被 clip 掉）
// ⚠ 缺少 API: lv.list 的列在 lv.js 預設透明（bg_opa = 0）→ 已用 set_style_bg_opa(255) 補
//   （只換 bg_color 看不到藍底/琥珀底；真機由 theme 決定）
// 註：record 在模擬器的 seed 可能是一般物件而不是 dict() → _g() 兩種都吃。

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_LIST, ITEM_SLIDER, ITEM_BUTTON } from "@packages/lv-app/nav.js";
import { bus, dict } from "@packages/lv-app/bus.js";

export const meta = { id: "pca9685", title: "PCA9685", icon: "sun",
                      desc: "目標·16 通道·廣播", order: 2, accent: 0x1A73E8 };

const CH_COUNT = 16;
const STEP = 32; // 每個 encoder 格的亮度步進（12-bit / 4095）
const REFRESH_EVERY = 10; // 每 N 幀刷新一次（run % N）
const SCAN_TIMEOUT_MS = 8000; // > 單一死線最壞 ~5.6s，掃描中狀態不會提早消失
// nav 項的固定順序（build() 的 nav.add 次序）：目標清單、通道方格、數值卡、全熄、掃描
const ITEM_TARGET = 0;
const ITEM_GRID = 1;

const SEL_BG = 0xd2e3fc; // 「已套用」目標列的底色（與 remote.py 相同：淺藍底，狀態色仍可讀）
const CURSOR_BG = 0xfff3cd; // 「游標候選」列的底色（淺琥珀）—— 轉動只移動它，按確認才變 SEL_BG

// 方格列（右欄通道卡）的幾何
const ROW_H = 16;
const BAR_X = 22;
const BAR_Y = 4;
const BAR_W = 38;
const BAR_H = 7;
const VAL_X = 62;

const nav = new Nav();
export let scr = null;
let _target_list = null;
let _target_btns = [];
let _targets = []; // pca9685_ctl 的內容（選中索引對應）
let _sel = 0; // 已套用的控制目標索引（右欄顯示的、寫入的對象）
let _cursor = 0; // 清單上的游標候選索引（轉動 encoder 只動它）
let _target_focused = false; // 焦點是否在「控制目標」清單上
let _sel_ch = 0; // 選中的通道（0..15）

let _header = null;
let _grid = null;
let _val_card = null;
let _target_lb = null;
let _status_lb = null;
let _ch_lb = null;
let _slider = null;
let _val_lb = null;
let _rows = []; // [{box,num,fill,val}]（16 個，順序 = 通道）
let _off_btn = null;
let _scan_btn = null;

let _last_vals = new Array(CH_COUNT).fill(0);
let _last_sig = null;
let _last_lb = dict(); // 文字快取（避免每幀 set_text）
let _scan_pending = false;
let _scan_at = 0;

// ══════════════════════════════════════════════════════════════════
//  小工具（純語法層）
// ══════════════════════════════════════════════════════════════════
// 裝置的 record 一定是 dict（有 .get）；模擬器的 seed 可能給一般物件 → 兩種都吃。
function _g(r, k, dflt = null) {
  if (r == null) return dflt;
  if (typeof r.get === "function") return r.get(k, dflt);
  return r[k] === undefined ? dflt : r[k];
}

function _hex2(v) {
  return Math.trunc(Number(v)).toString(16).toUpperCase().padStart(2, "0");
}

// Python 的 "%4d"（靠右、補空白）
function _pad4(v) {
  return String(v).padStart(4, " ");
}

// Python 的 list 比較（a != b）
function _vals_eq(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function _list_clear(lst) {
  // ⚠ lv.js 的 clean() 只刪 children；List._items 留著會讓下一次 add_text 從舊位置
  //   續排（新版子排在已刪除的列後面）→ 這裡連 _items 一起清。
  try {
    lst.clean();
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
  if (lst && lst._items) lst._items.length = 0;
}

// ══════════════════════════════════════════════════════════════════
//  建立畫面
// ══════════════════════════════════════════════════════════════════
function _panel(parent, x, y, w, h) {
  // 無邊框分區（與 pixel_controller._panel 相同）。
  const c = lv.obj(parent);
  c.set_size(w, h);
  c.set_pos(x, y);
  c.set_style_bg_color(u.C(u.SURFACE), 0);
  c.set_style_radius(8, 0);
  c.set_style_border_width(0, 0);
  c.set_style_pad_all(0, 0);
  c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return c;
}

function _mk_row(parent, ch, x, y) {
  // 一列通道：編號 + 長條（track/fill）+ 12-bit 數值。
  const box = lv.obj(parent);
  box.set_size(94, ROW_H);
  box.set_pos(x, y);
  box.set_style_bg_color(u.C(u.SURFACE), 0);
  box.set_style_radius(4, 0);
  box.set_style_border_width(0, 0);
  box.set_style_pad_all(0, 0);
  box.remove_flag(lv.obj.FLAG.SCROLLABLE);

  const num = u.mk_label(box, String(ch).padStart(2, "0"), 3, 0, u.TEXT3, u.F_NUM_S);

  const track = lv.obj(box);
  track.set_size(BAR_W, BAR_H);
  track.set_pos(BAR_X, BAR_Y);
  track.set_style_bg_color(u.C(u.TRACK), 0);
  track.set_style_radius(3, 0);
  track.set_style_border_width(0, 0);
  track.set_style_pad_all(0, 0);
  track.remove_flag(lv.obj.FLAG.SCROLLABLE);

  const fill = lv.obj(track);
  fill.set_size(1, BAR_H);
  fill.set_pos(0, 0);
  fill.set_style_bg_color(u.C(u.TRACK), 0);
  fill.set_style_radius(3, 0);
  fill.set_style_border_width(0, 0);
  fill.set_style_pad_all(0, 0);
  fill.remove_flag(lv.obj.FLAG.SCROLLABLE);

  const val = u.mk_label(box, "   0", VAL_X, 0, u.TEXT3, u.F_NUM_S);
  return { box, num, fill, val };
}

export function build() {
  nav.reset();
  _target_btns = [];
  _targets = [];
  _sel = 0;
  _cursor = 0;
  _target_focused = false;
  _sel_ch = 0;
  _rows = [];
  _last_vals = new Array(CH_COUNT).fill(0);
  _last_sig = null;
  _last_lb = dict();
  _scan_pending = false;
  _scan_at = 0;

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);

  // ── 頂列 ──
  u.mk_label(scr, "PCA9685 控制器", 6, 2, u.TEXT, u.ZH);

  // ── 左欄：控制目標 + 兩顆動作鈕 ──
  u.mk_label(scr, "控制目標", 6, 24, u.TEXT3, u.ZH);
  const lst = u.mk_list(scr, 4, 50, 106, 156, ["(載入中)"], u.ZH);
  _target_list = lst[0];
  _target_btns = lst[1];
  // 預設 list 的左右內距吃掉寬度（廣播列「0x70 廣播」很長）→ 縮小。
  try {
    _target_list.set_style_pad_all(2, 0);
  } catch (e) {
    /* 舊 binding 沒有這個 method：跳過 */
  }
  // 兩顆按鈕放左下角：焦點框（outline 6px）才不會被螢幕邊緣切掉。
  _off_btn = u.mk_btn(scr, "全熄", 4, 212, 51, 20, "danger");
  _scan_btn = u.mk_btn(scr, "掃描", 59, 212, 51, 20, "secondary");

  // ── 右欄：目標卡 ──
  _header = _panel(scr, 118, 24, 198, 30);
  _target_lb = u.mk_label(_header, "—", 6, 5, u.TEXT, u.ZH);
  _status_lb = u.mk_label(_header, "", 0, 5, u.TEXT3, u.ZH);
  _status_lb.align(lv.ALIGN.TOP_RIGHT, -6, 5);

  // ── 右欄：16 通道卡（左 CH0-7、右 CH8-15）──
  _grid = _panel(scr, 118, 60, 198, 150);
  u.mk_label(_grid, "通道亮度", 6, 0, u.TEXT2, u.ZH);
  const note = u.mk_label(_grid, "0-4095", -6, 2, u.TEXT3, u.F_NUM_S);
  note.align(lv.ALIGN.TOP_RIGHT, -6, 2);
  for (let col = 0; col < 2; col++) {
    for (let row = 0; row < 8; row++) {
      const ch = col * 8 + row;
      const x = col === 0 ? 4 : 102;
      _rows.push(_mk_row(_grid, ch, x, 20 + row * ROW_H));
    }
  }

  // ── 右欄：選中通道的數值卡（slider 只是顯示；導覽由 nav 的 ITEM_SLIDER 做）──
  _val_card = _panel(scr, 118, 214, 198, 18);
  _ch_lb = u.mk_label(_val_card, "CH0", 6, 1, u.TEXT, u.F_NUM_S);
  // slider x=48：左邊留給「CH15」（4 個半形 ≈ 32px）＋旋鈕的半徑；
  // 右邊到 150，數值標籤從 160 開始，旋鈕在最右也不會壓到數字。
  _slider = u.mk_slider(_val_card, 48, 5, 102, 0, 4095, 0);
  _val_lb = u.mk_label(_val_card, "   0", 160, 1, u.PRIMARY, u.F_NUM_S);

  // ── 導覽項（層次：目標 → 通道 → 數值 → 全熄 → 掃描）──
  nav.add(_target_list, ITEM_LIST, { on_change: _on_target_move,
                                     on_focus: _on_target_focus });
  nav.add(_grid, ITEM_LIST, { on_change: _on_channel_move });
  nav.add(_val_card, ITEM_SLIDER, { on_change: _on_value_adjust,
                                    on_focus: _on_value_focus });
  nav.add(_off_btn, ITEM_BUTTON, { on_change: _all_off });
  nav.add(_scan_btn, ITEM_BUTTON, { on_change: _do_scan });

  try {
    _refresh_targets(true);
  } catch (e) {
    print("[pca9685] build refresh err:", e);
  }
  nav.paint();
  return scr;
}

// ══════════════════════════════════════════════════════════════════
//  資料來源
// ══════════════════════════════════════════════════════════════════
function _ctl() {
  // pca9685_drv 的控制表（不是播放端的 pca9685_list）。
  //
  // ★ 回傳淺拷貝：task 端 refresh 會用 `_CTL[:] = new` 原地換內容，拷貝一份可以
  //   避免 UI 在迭代時剛好被換掉。
  // ★ 排序：廣播一定排第一（舊頁面的「目標 = 廣播」預設值），其餘按 (bus, 位址)。
  //   driver 是「先實體、後廣播」的順序，UI 這裡統一成「先廣播、後實體」——
  //   使用者一進來看到的第一項就是廣播。
  const s = bus.get_service("pca9685_ctl");
  if (!Array.isArray(s)) return [];
  const out = s.slice();
  try {
    out.sort((ra, rb) => {
      const ba = _g(ra, "broadcast") ? 0 : 1;
      const bb = _g(rb, "broadcast") ? 0 : 1;
      if (ba !== bb) return ba - bb;
      const ia = Math.trunc(Number(_g(ra, "i2c", 0)));
      const ib = Math.trunc(Number(_g(rb, "i2c", 0)));
      if (ia !== ib) return ia - ib;
      return Math.trunc(Number(_g(ra, "addr", 0))) - Math.trunc(Number(_g(rb, "addr", 0)));
    });
  } catch (e) {
    /* 跟裝置一樣：壞資料排不了就照原順序 */
  }
  return out;
}

function _ctl_exists() {
  return bus.get_service("pca9685_ctl") !== null;
}

function _sig(ts) {
  // 控制表的「內容簽章」：只有這些欄位變了才重建清單。
  // （Python 回 tuple；這裡用 JSON 字串比對，等價）
  const out = [];
  for (const r of ts) {
    out.push([_g(r, "i2c"), _g(r, "addr"), Boolean(_g(r, "online")),
              (_g(r, "boards") || []).length]);
  }
  return JSON.stringify(out);
}

function _cur_rec() {
  if (_sel >= 0 && _sel < _targets.length) return _targets[_sel];
  return null;
}

function _cur_key() {
  const r = _cur_rec();
  if (r === null) return null;
  // Python 回 (i2c, addr) tuple；字串 key 對比較等價
  return `${_g(r, "i2c")}|${_g(r, "addr")}`;
}

function _multi_bus() {
  const buses = [];
  for (const r of _targets) {
    const b = _g(r, "i2c");
    if (!buses.includes(b)) buses.push(b);
  }
  return buses.length > 1;
}

function _row_text(r) {
  // 清單一行。
  //
  // 廣播列：`0x70 廣播`（不加狀態圓點 —— 「廣播」兩個字已經夠長，而且它的在線
  //   狀態由右欄標題的「同步 N 台 / 離線」負責）。
  // 單板列：`● 0x40`（● = 掃描有看到、○ = 離線）。
  // 多 bus 才附 `B0`；此時廣播列變成 `0x70 廣播 B0`（仍在 106px 內）。
  let s = `0x${_hex2(_g(r, "addr", 0))}`;
  if (_g(r, "broadcast")) {
    s += " 廣播";
  } else {
    s = `${_g(r, "online") ? "●" : "○"} ${s}`;
  }
  if (_multi_bus()) s += ` B${Math.trunc(Number(_g(r, "i2c", 0)))}`;
  return s;
}

function _read_vals(rec) {
  // 讀該目標的 16 通道（12-bit）。沒有物件 → 全 0。
  const vals = new Array(CH_COUNT).fill(0);
  const pca = rec ? _g(rec, "pca") : null;
  const buf = pca == null ? null : pca.buf;
  if (buf == null) return vals;
  try {
    for (let i = 0; i < CH_COUNT; i++) vals[i] = (Math.trunc(Number(buf[i])) | 0) & 0xfff;
  } catch (e) {
    return new Array(CH_COUNT).fill(0);
  }
  return vals;
}

// ══════════════════════════════════════════════════════════════════
//  目標清單
// ══════════════════════════════════════════════════════════════════
function _refresh_targets(force = false) {
  if (_target_list === null) return;
  const ts = _ctl();
  const sig = _sig(ts);
  const changed = sig !== _last_sig;
  if (!(force || changed)) {
    _targets = ts;
    _sync_list();
    return;
  }

  const old_key = _cur_key();
  _last_sig = sig;
  _targets = ts;
  if (changed) _scan_pending = false; // 掃描結果回來了

  let labels = ts.map((r) => _row_text(r));
  if (!labels.length) labels = ["(無控制器)"];
  _list_clear(_target_list);
  _target_btns = [];
  for (const txt of labels) {
    try {
      const b = _target_list.add_text(txt);
      if (u.ZH) b.set_style_text_font(u.ZH, 0);
      try {
        // 縮小列的左右內距：多 bus 的「0x70 廣播 B0」很長，預設內距會讓最後一個
        // 字被切掉。背景色仍由 _sync_list() 覆蓋整個列。
        b.set_style_pad_all(1, 0);
      } catch (e) {
        /* 舊 binding 沒有這個 method：跳過 */
      }
      _target_btns.push(b);
    } catch (e) {
      continue;
    }
  }

  // 選中項：優先保留原本那個 (bus, addr)；不見了 → 退回廣播，再退第一個。
  _sel = 0;
  let found_old = false;
  if (old_key !== null) {
    for (let i = 0; i < ts.length; i++) {
      if (`${_g(ts[i], "i2c")}|${_g(ts[i], "addr")}` === old_key) {
        _sel = i;
        found_old = true;
        break;
      }
    }
  }
  if (!found_old) {
    for (let i = 0; i < ts.length; i++) {
      if (_g(ts[i], "addr") === 0x70) {
        _sel = i;
        break;
      }
    }
  }

  // 清單重建（進頁/掃描）→ 游標回到已套用的目標，避免指向不存在的索引。
  _cursor = _sel;
  _sync_list();
  _refresh_selected(true);
}

function _sync_list() {
  // 清單兩種底色（互不干擾）＋文字色。
  //
  // 底色：
  //   CURSOR_BG（淺琥珀） = 游標候選（轉動 encoder 只動這一格）
  //   SEL_BG（淺藍）      = 已套用的控制目標（右欄顯示/寫入的對象）
  // 文字色：廣播藍 / 在線綠 / 離線灰。
  const n = _target_btns.length;
  for (let i = 0; i < n; i++) {
    const b = _target_btns[i];
    const rec = i < _targets.length ? _targets[i] : null;
    let color;
    let bg;
    if (rec === null) {
      color = u.TEXT3;
      bg = u.BG;
    } else {
      color = _g(rec, "broadcast") ? u.PRIMARY : (_g(rec, "online") ? u.SUCCESS : u.TEXT3);
      if (_target_focused && i === _cursor) {
        bg = CURSOR_BG; // 游標候選
      } else if (i === _sel) {
        bg = SEL_BG; // 已套用
      } else {
        bg = u.BG;
      }
    }
    try {
      // ⚠ 模擬器的 list 列預設透明（bg_opa = 0）→ 一起設，否則藍底/琥珀底看不到。
      b.set_style_bg_opa(255, 0);
      b.set_style_bg_color(u.C(bg), 0);
      b.set_style_text_color(u.C(color), 0);
    } catch (e) {
      /* 跟裝置一樣：失敗就跳過 */
    }
  }
}

// ══════════════════════════════════════════════════════════════════
//  右欄顯示
// ══════════════════════════════════════════════════════════════════
function _set_lb(key, lb, txt, color = null) {
  // 文字快取：只有真的變了才 set_text（省 LVGL 重繪）。
  const sig = `${txt}|${color}`;
  if (_last_lb.get(key) === sig) return;
  _last_lb.set(key, sig);
  if (lb === null) return;
  try {
    lb.set_text(txt);
    if (color !== null) lb.set_style_text_color(u.C(color), 0);
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
}

function _refresh_selected(force = false) {
  const rec = _cur_rec();

  if (rec === null) {
    _set_lb("target", _target_lb, "—", u.TEXT3);
    if (!_ctl_exists()) {
      _set_lb("status", _status_lb, "PCA 未啟用", u.TEXT3);
    } else {
      _set_lb("status", _status_lb, "無裝置", u.DANGER);
    }
    if (force || !_vals_eq(_last_vals, new Array(CH_COUNT).fill(0))) {
      for (let i = 0; i < CH_COUNT; i++) _set_row(i, 0);
      _last_vals = new Array(CH_COUNT).fill(0);
    }
    if (force || !nav.is_editing()) _sync_slider();
    return;
  }

  // ── 目標卡 ──
  let name = `0x${_hex2(_g(rec, "addr", 0))}`;
  if (_g(rec, "broadcast")) name += " 廣播";
  if (_multi_bus()) name += `  B${Math.trunc(Number(_g(rec, "i2c", 0)))}`;
  _set_lb("target", _target_lb, name, u.TEXT);

  if (_target_focused) {
    // 游標在清單上 = 還沒套用；右欄仍是「已套用」的目標，按確認才換。
    _set_lb("status", _status_lb, "按確認選擇", u.WARNING);
  } else if (_scan_pending) {
    _set_lb("status", _status_lb, "掃描中…", u.WARNING);
  } else if (_g(rec, "broadcast")) {
    const n = (_g(rec, "boards") || []).length;
    if (n && _g(rec, "online")) {
      _set_lb("status", _status_lb, `同步 ${n} 台`, u.SUCCESS);
    } else if (n) {
      _set_lb("status", _status_lb, "離線", u.DANGER);
    } else {
      _set_lb("status", _status_lb, "無實體板", u.DANGER);
    }
  } else if (_g(rec, "online")) {
    _set_lb("status", _status_lb, "在線", u.SUCCESS);
  } else {
    _set_lb("status", _status_lb, "離線", u.DANGER);
  }

  // ── 16 通道 ──
  const vals = _read_vals(rec);
  if (force || !_vals_eq(vals, _last_vals)) {
    for (let i = 0; i < CH_COUNT; i++) _set_row(i, vals[i]);
    _last_vals = vals;
  }

  if (force || !nav.is_editing()) _sync_slider();
}

function _set_row(i, v) {
  // 更新一列的長條長度與數值（v = 0..4095）。
  if (i < 0 || i >= _rows.length) return;
  v = Math.max(0, Math.min(4095, Math.trunc(Number(v))));
  const r = _rows[i];

  let w = Math.trunc((BAR_W * v) / 4095);
  try {
    if (v <= 0) {
      // 0 也留 1px：不動態隱藏 widget，避免 add_flag/clear_flag 的版本差異
      r.fill.set_style_bg_color(u.C(u.TRACK), 0);
      r.fill.set_size(1, BAR_H);
    } else {
      // 非 0 至少 1px 的 PRIMARY：很小的值（例如 1）也看得到「有亮」
      if (w < 1) w = 1;
      r.fill.set_style_bg_color(u.C(u.PRIMARY), 0);
      r.fill.set_size(w, BAR_H);
    }
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }

  const sel = i === _sel_ch;
  try {
    r.val.set_text(_pad4(v));
    r.val.set_style_text_color(
      u.C(sel ? u.PRIMARY : (v ? u.TEXT2 : u.TEXT3)), 0);
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
}

function _paint_selection() {
  // 只重畫「哪一列被選中」（不重寫長條）。
  const has = _cur_rec() !== null; // 沒有目標時不要假裝 CH0 被選中
  for (let i = 0; i < _rows.length; i++) {
    const r = _rows[i];
    const sel = has && i === _sel_ch;
    try {
      r.box.set_style_bg_color(u.C(sel ? u.FOCUS_BG : u.SURFACE), 0);
      r.num.set_style_text_color(u.C(sel ? u.PRIMARY : u.TEXT3), 0);
    } catch (e) {
      /* 跟裝置一樣：失敗就跳過 */
    }
    const v = i < _last_vals.length ? _last_vals[i] : 0;
    try {
      r.val.set_style_text_color(
        u.C(sel ? u.PRIMARY : (v ? u.TEXT2 : u.TEXT3)), 0);
    } catch (e) {
      /* 跟裝置一樣：失敗就跳過 */
    }
  }
}

function _sync_slider() {
  // 把數值卡同步到「目前目標的目前通道」。
  const rec = _cur_rec();
  let v = 0;
  if (rec !== null) v = _read_vals(rec)[_sel_ch];
  _set_lb("ch", _ch_lb, `CH${_sel_ch}`, u.TEXT);
  _set_lb("val", _val_lb, _pad4(v), u.PRIMARY);
  try {
    _slider.set_value(v, 0);
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
  _paint_selection();
}

// ══════════════════════════════════════════════════════════════════
//  控制
// ══════════════════════════════════════════════════════════════════
function _write(rec, ch, v) {
  // 寫一個通道。廣播時同步各單板快取。
  //
  // ★ 優先用 PCA9685.set_channel(ch, v)：只寫該通道的 4 bytes（約 0.5 ms）。
  //   舊版/show() 一次寫 64 bytes（約 6 ms @100 kHz）—— 每轉一格都寫會讓 UI 頓。
  //   若部署到的驅動還沒有 set_channel（例如舊的 port 完整副本），退回 buf+show()。
  const pca = rec ? _g(rec, "pca") : null;
  if (pca == null) return;
  v = Math.max(0, Math.min(4095, Math.trunc(Number(v))));
  try {
    if (typeof pca.set_channel === "function") {
      pca.set_channel(ch, v);
    } else {
      pca.buf[ch] = v;
      pca.show();
    }
  } catch (e) {
    print("[pca9685] write err:", e);
    return;
  }
  // 廣播：把同一筆值寫進各單板的「顯示快取」（不再逐一 show()，
  // 實體板已經由 0x70 廣播收到；這裡只是讓切回單板時的數值一致）。
  if (_g(rec, "broadcast")) {
    const boards = _g(rec, "boards") || [];
    for (const peer of _targets) {
      if (peer === rec || _g(peer, "broadcast")) continue;
      if (_g(peer, "i2c") !== _g(rec, "i2c")) continue;
      if (!boards.includes(_g(peer, "addr"))) continue;
      try {
        _g(peer, "pca").buf[ch] = v;
      } catch (e) {
        /* 跟裝置一樣：沒有快取就跳過 */
      }
    }
  }
}

function _fill(rec, v) {
  // 一次填滿 16 通道再 show()（全部熄滅用）。
  const pca = rec ? _g(rec, "pca") : null;
  if (pca == null) return;
  v = Math.max(0, Math.min(4095, Math.trunc(Number(v))));
  for (let ch = 0; ch < CH_COUNT; ch++) {
    try {
      pca.buf[ch] = v;
    } catch (e) {
      /* 跟裝置一樣：失敗就跳過 */
    }
  }
  if (_g(rec, "broadcast")) {
    const boards = _g(rec, "boards") || [];
    for (const peer of _targets) {
      if (peer === rec || _g(peer, "broadcast")) continue;
      if (_g(peer, "i2c") !== _g(rec, "i2c")) continue;
      if (!boards.includes(_g(peer, "addr"))) continue;
      for (let ch = 0; ch < CH_COUNT; ch++) {
        try {
          _g(peer, "pca").buf[ch] = v;
        } catch (e) {
          /* 跟裝置一樣：失敗就跳過 */
        }
      }
    }
  }
  try {
    pca.show();
  } catch (e) {
    print("[pca9685] show err:", e);
  }
  for (let ch = 0; ch < CH_COUNT; ch++) _set_row(ch, v);
  _last_vals = new Array(CH_COUNT).fill(v);
  _sync_slider();
}

function _all_off() {
  const rec = _cur_rec();
  if (rec === null) return;
  _fill(rec, 0);
  print("[pca9685] all off ->", `0x${_hex2(_g(rec, "addr", 0))}`);
}

function _post(event) {
  let q = bus.shared.get("_pca_actions");
  if (!Array.isArray(q)) q = [];
  q.push(event);
  bus.shared["_pca_actions"] = q;
}

function _do_scan() {
  _post({ action: "scan" });
  _scan_pending = true;
  _scan_at = Date.now();
  _refresh_selected(true);
  print("[pca9685] scan requested");
}

function _poll_scan() {
  if (!_scan_pending) return;
  let since;
  try {
    since = Date.now() - _scan_at;
  } catch (e) {
    since = SCAN_TIMEOUT_MS + 1;
  }
  if (since > SCAN_TIMEOUT_MS) _scan_pending = false;
}

// ══════════════════════════════════════════════════════════════════
//  導覽回呼（層次 1/2/3）
// ══════════════════════════════════════════════════════════════════
function _on_target_focus(focused) {
  // 焦點進/出「控制目標」清單。
  //
  // 清單的互動是「游標 + 確認才套用」：
  //   - 進來：游標先對齊已套用的目標（琥珀底）。
  //   - 離開：右欄/標題恢復正常狀態（藍底 = 已套用）。
  _target_focused = Boolean(focused);
  if (focused) _cursor = _sel;
  _sync_list();
  _refresh_selected();
}

function _commit_target() {
  // 把游標候選變成真正的控制目標（右欄立即切換）。
  if (_cursor >= 0 && _cursor < _targets.length) _sel = _cursor;
  _sync_list();
  _refresh_selected(true);
}

function _on_target_move(dd) {
  // 清單上的 encoder：只移動游標，**不**改控制目標。
  //
  // 使用者定案（2026-10）：轉動 = 預覽；按一下確認才是真正選擇。
  // 所以這裡只動 `_cursor`，`_sel`（右欄/寫入對象）保持不變。
  const n = _targets.length;
  if (!n) return;
  _cursor = ((_cursor + dd) % n + n) % n;
  _sync_list();
}

function _on_channel_move(dd) {
  // 方格編輯態：換通道（數值卡與焦點跟著換）。
  _sel_ch = ((_sel_ch + dd) % CH_COUNT + CH_COUNT) % CH_COUNT;
  _sync_slider();
}

function _on_value_adjust(dd) {
  // 數值卡編輯態：調目前通道的 12-bit 亮度（每次轉動即寫硬體）。
  const rec = _cur_rec();
  if (rec === null) return;
  let cur;
  try {
    cur = Math.trunc(Number(_slider.get_value()));
  } catch (e) {
    cur = 0;
  }
  const v = Math.max(0, Math.min(4095, cur + Math.trunc(Number(dd)) * STEP));
  try {
    _slider.set_value(v, 0);
  } catch (e) {
    /* 跟裝置一樣：失敗就跳過 */
  }
  _set_lb("val", _val_lb, _pad4(v), u.PRIMARY);
  _set_row(_sel_ch, v);
  if (_sel_ch < _last_vals.length) _last_vals[_sel_ch] = v;
  _write(rec, _sel_ch, v);
}

function _on_value_focus(focused) {
  // 焦點移到數值卡時，先同步成目前通道的值（避免顯示上一個通道）。
  if (focused) _sync_slider();
}

// ══════════════════════════════════════════════════════════════════
//  頁面接口
// ══════════════════════════════════════════════════════════════════
export function on_enter() {
  try {
    _refresh_targets(true);
  } catch (e) {
    // on_enter 由 app.go 直接呼叫（沒有 try）→ 這裡一定要自己擋，
    // 否則一筆壞資料就會讓「換頁」整個炸掉。
    print("[pca9685] enter refresh err:", e);
  }
  nav.focus(ITEM_TARGET); // 每次進頁都從「控制目標」開始
}

export function on_leave() {
  if (nav.is_editing()) {
    nav.exit();
    _sync_list();
  }
}

export function on_enc(d) {
  // 焦點在「控制目標」時，encoder **只移動游標**（琥珀底），不改 _sel。
  // 這是使用者定案：轉動 = 預覽、確認 = 真正選擇。
  // 沒有目標時不攔截 → 讓 encoder 能把焦點移到方格/掃描鈕。
  if (_target_focused && _targets.length) {
    _on_target_move(d);
    return;
  }
  nav.enc(d);
  if (nav.current_kind() === ITEM_LIST) _sync_list();
}

export function on_confirm() {
  // 清單上的確認 = 真正選擇：套用游標 → 焦點直接移到通道方格。
  // （不進 nav 的 ITEM_LIST 編輯態，所以只按一次就完成選擇。）
  if (_target_focused) {
    nav.focus(ITEM_GRID); // 套用後直接跳到通道方格；on_focus(false) 恢復一般狀態
    _commit_target();
    return null;
  }
  nav.confirm();
  if (nav.current_kind() === ITEM_LIST) _sync_list();
  if (!nav.is_editing()) _sync_slider();
  return null;
}

export function on_exit() {
  if (_target_focused && _cursor !== _sel) {
    // 游標還沒套用 → 返回鍵先取消（留在頁面）；再按一次才回 launcher。
    _cursor = _sel;
    _sync_list();
    _refresh_selected(true);
    return true;
  }
  const consumed = nav.exit();
  if (nav.current_kind() === ITEM_LIST) _sync_list();
  if (!nav.is_editing()) _sync_slider();
  return consumed;
}

export function update(run) {
  if (run % REFRESH_EVERY !== 0) return;
  try {
    _poll_scan();
    _refresh_targets();
    _refresh_selected();
  } catch (e) {
    print("[pca9685] update err:", e);
  }
}
