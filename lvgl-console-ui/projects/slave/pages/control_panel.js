// projects/slave/pages/control_panel.js — 模式/亮度/倒數計時頁（橫屏 320×240）
//
// 對應 ui/lvgl/page/control_panel.py（1:1）
//
// 佈局：
//   左欄(x=6,w=104)：lv_list 顯示模式清單。enc 選 list → confirm 進編輯 →
//                    enc 上下選模式 → confirm/exit 退出（選中即寫 bus）。
//   右欄(x=116,w=198)：
//     上 亮度(slider)
//     中 倒數時間(arc 進度 + 中央時間文字)
//     下 Bit7/Bit6 旗標狀態 + 兩個切換按鈕
//
// 本機值 + 三態顏色（送出的即時回饋，不依賴 echo）：
//   本頁維護 _local_mode/_local_bright：操作立刻更新本機值並顯示，同時送
//   bus.shared["_display_cmd"]。echo(_display_mode/_display_brightness) 是最終答案：
//     - 列表：選中=藍；送出後 pending=琥珀；echo 出現 → 回藍
//     - LED（拍攝/可動）：灰=off；pending=琥珀（已送出）；echo 確認=綠
//   頁面不加超時：echo 不出現就一直琥珀等回覆，出現即定案。
//
// 協議（混搭環境：本頁是控制端也是被控制端）：
//   指令：_send_cmd() → bus.shared["_display_cmd"] = {mode, brightness}
//   狀態：bus.shared["_display_mode/_brightness/_time"]（action_task 執行後寫回）
//   control_panel dict 為本頁快取（is_running 等）

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_LIST, ITEM_SLIDER, ITEM_BUTTON } from "@packages/lv-app/nav.js";
import { bus, dict } from "../mocks.js";

const MODE_LABELS = ["模式 1", "模式 2", "模式 3", "模式 4", "模式 5"];
const _TIME_MAX = 255; // time 欄位上限（1 byte），arc 滿圓 = 255
const _BIT7 = 0x80; // 特殊模式旗標
const _BIT6 = 0x40; // 保留旗標（目標頂部/底部）
const _MODE_MASK = 0x3f;

export const meta = {
  id: "control_panel",
  title: "控制面板",
  icon: "sliders-horizontal",
  desc: "模式·亮度·計時",
  order: 1,
  accent: 0xf9ab00,
};

const nav = new Nav();
export let scr = null;
let _mode_list = null;
let _mode_btns = [];
let _bright_sl = null;
let _bright_lb = null;
let _time_lb = null;
let _time_arc = null;
let _run_lb = null;
let _bit7_led = null;
let _bit6_led = null;
let _last_txt = {};

// 倒數計時（本地非阻塞，不 sleep）：每輪取樣時戳與上次對比，
// 累積滿 1000ms 才 -1，餘數保留給下次 → frame 長短不齊也不漂移。
// 收到新幀（_display_time_seq 變更，即使值相同＝重新計時）即重置採納新值。
let _tick_last = 0; // 上次取樣時戳
let _tick_carry = 0; // 累積毫秒（滿 1000 扣一次，餘數留用）
let _tick_armed = false; // 已初始化（避免首輪以 0 當基準）
let _tick_seq = 0; // 上次見到的 _display_time_seq（變更＝外部送了新幀）
let _tick_raw = 0; // 上次採納的 bus 原始值（bus 值改變 → 重新開始）
let _tick_val = 0; // 目前倒數顯示值（本地遞減）
let _tick_running = false; // 是否倒數中

// 本機值（操作即時回饋，不依賴 echo）+ pending 標記
let _local_mode = 0; // 本機最後送出/採納的 mode byte
let _local_bright = 0; // 本機最後送出/採納的亮度
let _pend_mode = false; // mode 已送出、等 echo 定案
let _pend_bright = false; // brightness 已送出、等 echo 定案

export function build() {
  _last_txt = {};
  _tick_reset();
  nav.reset();
  _init_local();

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);
  scr.set_style_bg_opa(255, 0);

  // 左欄：模式清單（lv_list，字體放大用 F_NUM_M）
  const lx = 4;
  const lw = 96;
  const rx = lx + lw + 4;
  const rw = u.W - 4 - rx;
  [_mode_list, _mode_btns] = u.mk_list(scr, lx, 4, lw, u.H - 8, MODE_LABELS, u.F_NUM_M);
  nav.add(_mode_list, ITEM_LIST, { on_change: _sel_mode_delta });

  // 右欄上：亮度（無邊框卡片，省空間）
  const c2 = _panel(scr, rx, 4, rw, 50);
  u.mk_label(c2, "亮度", 6, 4, u.TEXT2, u.ZH);
  _bright_lb = lv.label(c2);
  _bright_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4);
  _bright_lb.set_style_text_font(u.F_NUM_M, 0);
  _bright_lb.set_style_text_color(u.C(u.PRIMARY), 0);
  _bright_lb.set_text("0");
  _bright_sl = u.mk_slider(c2, 6, 30, rw - 12, 0, 36, 0);
  nav.add(_bright_sl, ITEM_SLIDER, { on_change: _adj_bright });

  // 右欄下：倒數時間 + 模式旗標 + 快捷（合併一區）
  //   上半：大 arc 置中 + 中央時間（F_NUM_XL）
  //   下排：狀態 / LED+切換 / 上一個下一個模式
  const c3 = _panel(scr, rx, 58, rw, u.H - 4 - 58);
  const arc_sz = 110;
  const arc_x = Math.floor(rw / 2 - arc_sz / 2);
  const arc_y = 6;
  _time_arc = u.mk_arc(c3, arc_x, arc_y, arc_sz, u.PRIMARY, 0, _TIME_MAX);
  _time_arc.set_value(_TIME_MAX);
  _time_lb = lv.label(c3);
  _time_lb.set_pos(arc_x + Math.floor(arc_sz / 2) - 34, arc_y + Math.floor(arc_sz / 2) - 14);
  _time_lb.set_style_text_font(u.F_NUM_XL, 0);
  _time_lb.set_style_text_color(u.C(u.TEXT), 0);
  _time_lb.set_text("00:00");
  // 狀態（arc 右上角）
  _run_lb = lv.label(c3);
  _run_lb.align(lv.ALIGN.TOP_RIGHT, -6, 8);
  _run_lb.set_style_text_font(u.F_NUM_M, 0);
  _run_lb.set_style_text_color(u.C(u.TEXT3), 0);
  _run_lb.set_text("待機");

  // 下排：左 LED+標籤按鈕（拍攝/可動，點擊切換）、右 模式快捷（▲▼）
  const row_y = arc_y + arc_sz + 8;
  _bit7_led = u.mk_led(c3, 8, row_y + 4, 12, false);
  const btn7 = u.mk_btn(c3, "拍攝", 26, row_y, 56, 22, "secondary");
  nav.add(btn7, ITEM_BUTTON, { on_change: _toggle_bit7 });
  _bit6_led = u.mk_led(c3, 8, row_y + 30, 12, false);
  const btn6 = u.mk_btn(c3, "可動", 26, row_y + 26, 56, 22, "secondary");
  nav.add(btn6, ITEM_BUTTON, { on_change: _toggle_bit6 });
  // 模式快捷（右側：上下排列，對齊 list 上下選的語意）
  const btn_up = u.mk_btn(c3, "▲", rw - 40, row_y, 34, 22, "primary");
  nav.add(btn_up, ITEM_BUTTON, { on_change: () => _sel_mode_delta(-1) });
  const btn_dn = u.mk_btn(c3, "▼", rw - 40, row_y + 26, 34, 22, "primary");
  nav.add(btn_dn, ITEM_BUTTON, { on_change: () => _sel_mode_delta(1) });

  u.fade_in(_mode_list, 5, 280, 40);
  u.fade_in(c2, 5, 280, 120);
  u.fade_in(c3, 5, 280, 200);

  _sync_list();
  nav.paint();
  return scr;
}

/** 以 bus 現值初始化本機值（啟動時 echo 即為實際狀態，無 pending）。 */
function _init_local() {
  _local_mode = Math.trunc(Number(bus.shared.get("_display_mode", 0))) & 0xff;
  _local_bright = Math.max(0, Math.min(36, Math.trunc(Number(bus.shared.get("_display_brightness", 0)))));
  _pend_mode = false;
  _pend_bright = false;
}

/** 輕量分區：無邊框、淡底色、pad 0（比 mk_card 省邊框空間）。 */
function _panel(parent, x, y, w, h) {
  const c = lv.obj(parent);
  c.set_size(w, h);
  c.set_pos(x, y);
  c.set_style_bg_color(u.C(u.SURFACE), 0);
  c.set_style_bg_opa(255, 0);
  c.set_style_radius(8, 0);
  c.set_style_border_width(0, 0);
  c.set_style_pad_all(0, 0);
  c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return c;
}

// ═══ bus 讀寫（與 action_task_1 共享 _display_* 欄位）═══

/**
 * 發指令給 action_task_1 via bus.shared["_display_cmd"]。
 * 同板直寫；跨板時由 waiting_to_trash_actions.on_ctl 翻譯進同一欄位。
 */
function _send_cmd(mode = null, brightness = null) {
  const cmd = dict({});
  if (mode !== null) cmd["mode"] = Math.trunc(Number(mode)) & 0xff;
  if (brightness !== null) cmd["brightness"] = Math.trunc(Number(brightness));
  if (cmd.keys().length) bus.shared["_display_cmd"] = cmd;
}

/**
 * 讀 bus 的 _display_mode 回傳（被控制端/跨板 echo）。
 * 欄位不存在（尚未有回覆）→ 回 null，不得視為已確認。
 */
function _echo_mode() {
  if (!("_display_mode" in bus.shared)) return null;
  return Math.trunc(Number(bus.shared["_display_mode"])) & 0xff;
}

/** 本機 mode byte（最後送出/採納值，不依賴 echo）。 */
function _mode_byte() {
  return _local_mode;
}

/**
 * 更新本機 mode + 送指令，標 pending（等 echo 定案後回藍/還原）。
 * 順手同步 list 高亮與 LED → 點擊當下立刻顯示琥珀。
 */
function _set_mode_byte(v) {
  _local_mode = Math.trunc(Number(v)) & 0xff;
  _pend_mode = true;
  _send_cmd(_local_mode, null);
  _sync_list();
  _refresh_bits();
}

/** 本頁自用快取 dict（非協議欄位，如 is_running）。 */
function _state() {
  let s = bus.shared.get("control_panel");
  if (!s || typeof s.get !== "function") {
    s = dict({});
    bus.shared["control_panel"] = s;
  }
  return s;
}

/**
 * 依本機 mode byte 低 6 bit 同步 list 選中高亮。
 * 編輯態或 pending → 琥珀（已送出/移動中）；其餘 → 主題藍（選中）。
 */
function _sync_list() {
  let cur = _mode_byte() & _MODE_MASK;
  cur = cur % MODE_LABELS.length;
  const color = nav.is_editing() || _pend_mode ? u.WARNING : u.PRIMARY;
  u.list_select(_mode_btns, cur, color);
}

/** 編輯態 enc：上下移模式選擇（只改低 6 bit，保留旗標）。 */
function _sel_mode_delta(dd) {
  const mb = _mode_byte();
  const flags = mb & ~_MODE_MASK;
  const val = ((mb & _MODE_MASK) + dd + MODE_LABELS.length * 1000) % MODE_LABELS.length;
  _set_mode_byte(flags | val);
  _sync_list();
}

function _toggle_bit7() {
  _set_mode_byte(_mode_byte() ^ _BIT7);
  _refresh_bits();
}

function _toggle_bit6() {
  _set_mode_byte(_mode_byte() ^ _BIT6);
  _refresh_bits();
}

/**
 * LED 三態：pending 時以本機送出值顯示（亮=琥珀等回覆）；
 * 無 pending 以 echo 為準（亮=綠已確認；echo 尚未回 → 灰）。
 */
function _refresh_bits() {
  const mb = _local_mode;
  const echo = _echo_mode();
  for (const [led, flag] of [
    [_bit7_led, _BIT7],
    [_bit6_led, _BIT6],
  ]) {
    if (_pend_mode) u.led_set(led, Boolean(mb & flag), u.WARNING);
    else u.led_set(led, echo !== null ? Boolean(echo & flag) : false, u.SUCCESS);
  }
}

/** 編輯態 enc：調亮度。更新本機值+立即顯示，送指令標 pending 等回覆。 */
function _adj_bright(dd) {
  const v = Math.max(0, Math.min(36, _local_bright + dd));
  _local_bright = v;
  _pend_bright = true;
  _bright_sl.set_value(v, 0);
  _bright_lb.set_text(String(v));
  _send_cmd(null, v);
}

// ====== 頁面接口（轉發給 nav） ======

export function on_enter() {}

export function on_leave() {
  if (nav.is_editing()) {
    nav.exit();
    _sync_list();
  }
}

export function on_enc(d) {
  nav.enc(d);
  if (nav.current_kind() === ITEM_LIST) _sync_list();
}

export function on_confirm() {
  nav.confirm();
  _sync_list();
  return null;
}

export function on_exit() {
  const consumed = nav.exit();
  _sync_list();
  return consumed;
}

/** 重設倒數追蹤（進入頁面時），下次 update 以 bus 現值重新開始。 */
function _tick_reset() {
  _tick_last = 0;
  _tick_carry = 0;
  _tick_armed = false;
  _tick_seq = 0;
  _tick_raw = 0;
  _tick_val = 0;
  _tick_running = false;
}

/**
 * 本地非阻塞倒數（不 sleep、不中斷主迴圈）：
 * 每輪取樣時戳與上次對比，累積滿 1000ms 就 -1，餘數留給下次 →
 * 每幀長短不一也維持精準 1 秒/秒。
 * _display_time_seq 一變（收到新幀，即使值相同＝重新計時指令）即重置採納。
 */
function _tick_countdown() {
  let raw = Math.trunc(Number(bus.shared.get("_display_time", 0)));
  raw = Math.max(0, Math.min(_TIME_MAX, raw));
  const seq = Math.trunc(Number(bus.shared.get("_display_time_seq", 0)));
  const now = Date.now();

  if (!_tick_armed || seq !== _tick_seq || raw !== _tick_raw) {
    // 收到新幀（seq 變）或值變：採納新值重新開始（同值重送也重置）
    _tick_last = now;
    _tick_carry = 0;
    _tick_armed = true;
    _tick_seq = seq;
    _tick_raw = raw;
    _tick_val = raw;
    _tick_running = Boolean(_state().get("is_running", raw > 0));
    return raw;
  }

  // 同值持續（本地倒數中，外部未再送新幀）：累積時差扣減
  _tick_carry += now - _tick_last;
  _tick_last = now;
  if (_tick_running && _tick_val > 0) {
    while (_tick_carry >= 1000) {
      _tick_carry -= 1000;
      _tick_val -= 1;
      if (_tick_val <= 0) {
        _tick_carry = 0;
        _tick_running = false;
        break;
      }
    }
  }
  return Math.max(0, _tick_val);
}

export function update(run) {
  if (run % 10 !== 0) return;
  try {
    // mode / brightness echo 定案（有 pending 等回覆；無 pending 才採納外部值）
    _sync_echo_mode();
    _sync_echo_bright();
    _refresh_bits();

    // 倒數時間（arc + 文字）：本地非阻塞倒數
    const t = _tick_countdown();
    const mtxt = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
    if (_last_txt.time !== mtxt) {
      _last_txt.time = mtxt;
      _time_lb.set_text(mtxt);
    }
    try {
      _time_arc.set_value(t, 0);
    } catch (e) {
      /* 跟裝置一樣：arc 不支援就跳過 */
    }

    // 計時狀態（與倒數同一狀態源）
    const r = _tick_running;
    const rtxt = r ? "計時中" : "待機";
    if (_last_txt.run !== rtxt) {
      _last_txt.run = rtxt;
      _run_lb.set_text(rtxt);
      _run_lb.set_style_text_color(u.C(r ? u.SUCCESS : u.TEXT3), 0);
    }
  } catch (e) {
    /* 跟裝置一樣：這一幀讀不到就跳過 */
  }
}

/**
 * mode echo 定案：echo 出現即為最終答案。
 * 一致 → 成功（pending 清，列表回藍停在該位置）。
 * 不一致 → 超時/未成功（採納 echo 還原，pending 清）。
 * echo 欄位不存在 → 尚未有回覆，維持琥珀。
 */
function _sync_echo_mode() {
  const echo = _echo_mode();
  if (echo === null) {
    _refresh_bits();
    return;
  }
  _pend_mode = false;
  if (echo !== _local_mode) _local_mode = echo;
  _sync_list();
  _refresh_bits();
}

/**
 * 亮度 echo 定案（同 mode）：出現即為最終答案，一致保留、不一致還原；
 * 欄位不存在 → 維持琥珀。顯示一律以本機值為準。
 */
function _sync_echo_bright() {
  if (!("_display_brightness" in bus.shared)) return;
  const echo = Math.trunc(Number(bus.shared["_display_brightness"]));
  _pend_bright = false;
  if (echo !== _local_bright && echo >= 0 && echo <= 36) _local_bright = echo;
  if (_bright_sl.get_value() !== _local_bright) {
    _bright_sl.set_value(_local_bright, 0);
    _bright_lb.set_text(String(_local_bright));
  }
}
