// projects/slave/pages/pixel_controller.js — Pixel 模式控制器頁（橫屏 320×240）
//
// 對應 ui/lvgl/page/pixel_controller.py
//
// 佈局（複製 control_panel 左列表/右控制區的骨架，聚焦「模式設置」）：
//   左欄 (x=4, w=96)：動態模式清單（從 gmode.mode_pool() 載入）。
//                    enc 選 list → confirm 進編輯 → enc 上下選 → 選中即送
//                    gmode.set_mode(id)。
//   右欄 (x=104)：
//      上  「獲取列表」按鈕（重新載入 gmode.mode_pool → 重建清單）
//      中  「可動」按鈕（鐵打模式 0x0200 = SERVO 組 mode 0，點擊直接設置；
//          取代原 control_panel 的 Bit6 可動 toggle）
//      下  當前模式顯示 + 亮度 slider（0-255，對應 MODE_SET.brightness）
//
// 協議對接（本頁是「本板 pixel 控制端」，只寫狀態不碰 gmode/hardware）：
//   模式設置：bus.shared["_pixel_cmd"] = {"mode": 16-bit id}
//             → PixelControlPanelTask 消費 → gmode.set_mode() → PixelTask 執行。
//   模式清單：gmode.mode_pool() = pixel_maps（PixelTask 載入）+ /audio/modes（純音效）。
//   亮度：bus.shared["_pixel_cmd"] = {"brightness": 0-255} → task 寫 st_pixel。
//
// 轉換對照：
//   struct.pack("<BBHB", ...) → Uint8Array.of(...)（B B H B 共 5 bytes，H 佔 2 bytes）
//   0x{:04X}                  → 0x + padStart(4, "0")
//   sorted(int(i) for ...)    → 轉數字（任何一個失敗就整個清空）、由小到大排序

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_LIST, ITEM_SLIDER, ITEM_BUTTON } from "@packages/lv-app/nav.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import { Proto, get_vbus } from "../mocks.js";

// 鐵打可動模式：16-bit 內部 id = (mode_type<<8)|mode_id = 0x02<<8 | 0 = 0x0200
// mode_type=2 (SERVO)、mode_id=0。臨時應急：點擊「可動」直接設置此模式。
const MOVABLE_ID = 0x0200;

const nav = new Nav();
export let scr = null;
let _mode_list = null;
let _mode_btns = [];
let _mode_ids = [];       // 有序 16-bit id（與 _mode_labels 一一對應）
let _mode_labels = [];    // 清單顯示文字
let _mode_names = [];     // 只存名稱（大卡第二行用）
let _cur_idx = 0;         // 目前選中索引（選中即設置）
let _bright_sl = null;
let _bright_lb = null;
let _ticks = [];          // 亮度刻度尺的 31 格（APA102 5-bit）
let _led_fetch = null;
let _led_mov = null;
let _arc = { x: 0, y: 0, sz: 110 }; // 大卡圓環的位置（置中時間要用）
let _time_arc = null;     // 倒數圓環（0..255）
let _time_lb = null;      // 中央 MM:SS
let _run_lb = null;       // 待機 / 計時中
let _cur_lb = null;       // 目前模式 id（右側資訊欄）
let _cur_name = null;     // 目前模式名稱（右側資訊欄）

// ── 倒數計時（與 control_panel 同一套：本地非阻塞、每 1000ms 扣 1）──
const _TIME_MAX = 255;
let _tick_last = 0;
let _tick_carry = 0;
let _tick_armed = false;
let _tick_seq = 0;
let _tick_raw = 0;
let _tick_val = 0;
let _tick_running = false;

/** 把 MM:SS 置中到圓環裡（用字型實測寬度，不用估）。 */
function _center_time() {
  if (_time_lb === null) {
    return;
  }
  try {
    const txt = _time_lb.get_text ? _time_lb.get_text() : "00:00";
    const w = Math.round(u.F_NUM_XL.measure(txt));
    _time_lb.set_pos(
      _arc.x + Math.round((_arc.sz - w) / 2),
      _arc.y + Math.round((_arc.sz - u.F_NUM_XL.lineHeight) / 2)
    );
  } catch (e) {
    /* 量不到就維持原位 */
  }
}

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
 * 本地非阻塞倒數：每輪取樣時戳，累積滿 1000ms 才 -1，餘數保留。
 * `_display_time_seq` 一變（外部送新幀）就重新採納。
 */
function _tick_countdown() {
  let raw = Math.trunc(Number(bus.shared.get("_display_time", 0)));
  raw = Math.max(0, Math.min(_TIME_MAX, raw));
  const seq = Math.trunc(Number(bus.shared.get("_display_time_seq", 0)));
  const now = Date.now();

  if (!_tick_armed || seq !== _tick_seq || raw !== _tick_raw) {
    _tick_last = now;
    _tick_carry = 0;
    _tick_armed = true;
    _tick_seq = seq;
    _tick_raw = raw;
    _tick_val = raw;
    _tick_running = raw > 0;
    return raw;
  }

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

/** 0x0000..0xFFFF 的固定 4 位大寫十六進位（對齊 Python 的 {:04X}）。 */
function _hex04(v) {
  return Math.trunc(Number(v)).toString(16).toUpperCase().padStart(4, "0");
}

/** Python dict.get 的替身：Dict 走 get()，一般物件走索引。 */
function _dget(d, k, dflt = null) {
  if (d == null) return dflt;
  if (typeof d.get === "function") return d.get(k, dflt);
  const v = d[k];
  return v === undefined ? dflt : v;
}

export const meta = {
  id: "pixel_controller",
  title: "Pixel 控制",
  icon: "sliders-horizontal",
  desc: "模式設置·列表·可動",
  order: 0,
  accent: 0x1A73E8,
};

export function build() {
  nav.reset();
  _cur_idx = 0;
  _mode_ids = [];
  _mode_labels = [];

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);

  // 左欄：動態模式清單（初次先放一個空項，載入後重建）
  const lx = 4;
  const lw = 96;
  // 右欄從 108 起：跟清單留 8px（4 的倍數），清單焦點框 3px 也不會貼到字
  const rx = lx + lw + 8;
  const rw = u.W - 4 - rx; // 208
  const pair = u.mk_list(scr, lx, 4, lw, u.H - 8, ["(載入中)"], u.ZH);
  _mode_list = pair[0];
  _mode_btns = pair[1];
  // 列文字「0x0200 可動」實測 89px，list 內距 4 → 只有 88px 可用（會被切 1px）。
  // 內距收成 1（跟 item 的 pad 一致），可用 94px。
  try {
    _mode_list.set_style_pad_all(1, 0);
  } catch (e) {
    /* 沒有這個 binding 就跳過 */
  }
  nav.add(_mode_list, ITEM_LIST, { on_change: _sel_mode_delta });

  // 右欄：透明容器、8px 節奏（4 的倍數：4 / 104 / 128 / 176 / 204）
  //   1 圓環 + 中央 MM:SS（96，28px）
  //   2 亮度（標籤 + 數值 + 滑桿）
  //   3 LED + 獲取 / 可動、右側 ▲▼
  //   階層：**只有「獲取」是填色主動作**，可動與 ▲▼ 都是外框次要動作
  const cArc = _panel(scr, rx, 4, rw, 96);
  const arc_sz = 96;
  const arc_x = Math.floor(rw / 2 - arc_sz / 2);
  _arc = { x: arc_x, y: 0, sz: arc_sz };
  _time_arc = u.mk_arc(cArc, arc_x, 0, arc_sz, u.PRIMARY, 0, _TIME_MAX, 9);
  _time_arc.set_value(_TIME_MAX);
  _time_lb = lv.label(cArc);
  _time_lb.set_pos(arc_x, Math.floor(arc_sz / 2) - 14);
  _time_lb.set_style_text_font(u.F_NUM_XL, 0);
  _time_lb.set_style_text_color(u.C(u.TEXT), 0);
  _time_lb.set_text("00:00");
  _center_time();

  // 亮度（圓弧下面）— 0–31，對應 APA102 的 5-bit 全域亮度
  const _bright_init = 31;
  // 容器往上/下各留 6px：焦點框最外緣 = outline_pad(3) + lineWidth/2(1.5) = 6px，
  // 只留 4px 還是會被父層裁掉 2px —— 這就是「被剪裁」的真正數字。
  const cBright = _panel(scr, rx, 94, rw, 64);
  // 「亮度」標籤與數值都拿掉：31 格刻度尺本身就說明一切（亮幾格 = 現在幾級）
  _bright_lb = null;

  // 亮度刻度尺：31 格 = APA102 的 5-bit（0–31）。亮幾格就是目前亮度。
  // 為什麼不用 slider：一格 = 旋鈕一格，讀「亮到第幾格」比讀數字快，也更像儀器。
  // 旋鈕還是接在一個「透明 slider」上（刻度只是視覺），焦點框因此剛好圈住整把尺。
  const TICK_W = 4;
  const RULER_H = 16;
  const RULER_Y = 34; // abs 128（容器上移 6 後，視覺位置不變）
  const PITCH = Math.floor(rw / 31); // 208 / 31 = 6（4px 格 + 2px 隙）
  const ruler_x = Math.round((rw - (PITCH * 31 - (PITCH - TICK_W))) / 2);
  _ticks = [];
  // 透明 slider 比刻度尺「大一圈」：(ruler_x-4, RULER_Y-4) + (184+8, 24)。
  // 這樣焦點框離刻度 4px 才不會看起來像「切到」刻度。
  const RULER_W = PITCH * 31 - (PITCH - TICK_W);
  _bright_sl = u.mk_slider(cBright, ruler_x - 4, RULER_Y - 4, RULER_W + 8, 0, 31, _bright_init);
  _bright_sl.set_size(RULER_W + 8, 24);
  _bright_sl.set_style_radius(2, 0); // 圓角小一點：不然 24 高 + pad 會變成一顆膠囊
  for (const part of [lv.PART.MAIN, lv.PART.INDICATOR, lv.PART.KNOB]) {
    _bright_sl.set_style_bg_opa(0, part);
  }
  nav.add(_bright_sl, ITEM_SLIDER, { on_change: _adj_bright });
  for (let i = 0; i < 31; i++) {
    const t = lv.obj(cBright);
    t.set_size(TICK_W, RULER_H);
    t.set_pos(ruler_x + i * PITCH, RULER_Y);
    t.set_style_radius(1, 0);
    t.set_style_border_width(0, 0);
    t.set_style_pad_all(0, 0);
    t.set_style_bg_opa(255, 0);
    t.set_style_bg_color(u.C(u.TRACK), 0);
    t.remove_flag(lv.obj.FLAG.CLICKABLE);
    _ticks.push(t);
  }
  _paint_ruler(_bright_init);

  // 底部：LED + 獲取 / LED + 可動、右側 ▲▼（24 高 = 3×8；上下各留 6px 給焦點框）
  const cBtn = _panel(scr, rx, 166, rw, 72);
  _led_fetch = u.mk_led(cBtn, 0, 16, 12, false);
  const btn_fetch = u.mk_btn(cBtn, "獲取", 18, 10, 90, 24, "primary");
  nav.add(btn_fetch, ITEM_BUTTON, { on_change: _fetch_modes });
  _led_mov = u.mk_led(cBtn, 0, 44, 12, false);
  const btn_mov = u.mk_btn(cBtn, "可動", 18, 38, 90, 24, "secondary");
  nav.add(btn_mov, ITEM_BUTTON, { on_change: _apply_movable });
  // ▲▼ 靠右但留 6px：框最外緣 6px，貼邊就會被切
  const btn_up = u.mk_btn(cBtn, "▲", rw - 40, 10, 34, 24, "secondary");
  nav.add(btn_up, ITEM_BUTTON, { on_change: () => _sel_mode_delta(-1) });
  const btn_dn = u.mk_btn(cBtn, "▼", rw - 40, 38, 34, 24, "secondary");
  nav.add(btn_dn, ITEM_BUTTON, { on_change: () => _sel_mode_delta(1) });

  // 計時狀態 / 目前模式：資訊列已移除，這裡留 null 讓 update()/ _show_mode() 走守衛
  _run_lb = null;
  _cur_lb = null;
  _cur_name = null;

  _load_modes(true);
  nav.paint();
  return scr;
}

/**
 * 版面容器：**透明、無框、無圓角**。
 *
 * 原本它是白色圓角「卡片」（SURFACE + radius 8），但這一頁的內容（滑桿、
 * 圓環、按鈕）本身已經有清楚的形狀，再加一層卡片只會多一圈邊界。
 * 現在它只負責「把一組元件放在同一個座標系」，畫面上看不到它。
 */
function _panel(parent, x, y, w, h) {
  const c = lv.obj(parent);
  c.set_size(w, h);
  c.set_pos(x, y);
  c.set_style_bg_opa(0, 0); // 透明
  c.set_style_radius(0, 0);
  c.set_style_border_width(0, 0);
  c.set_style_pad_all(0, 0);
  c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return c;
}

// ═══ 模式池載入 / 列表重建 ═══

function _get_gmode() {
  return bus.get_service("gmode");
}

/** 從池裡取 mode dict（容忍 key 是 int 或 str）。 */
function _mode_by_id(pool, mid) {
  if (pool == null) return null;
  let m = _dget(pool, mid, null);
  if (m == null) {
    try {
      m = _dget(pool, String(mid), null);
    } catch (e) {
      m = null;
    }
  }
  return m;
}

/** 從 gmode.mode_pool() 載入模式清單，重建左欄列表。 */
function _load_modes(initial = false) {
  const gmode = _get_gmode();
  let pool;
  if (gmode !== null) {
    try {
      pool = gmode.mode_pool();
    } catch (e) {
      pool = bus.shared.get("pixel_maps", dict());
    }
  } else {
    pool = bus.shared.get("pixel_maps", dict());
  }

  let ids = [];
  try {
    const keys = pool && typeof pool.keys === "function" ? pool.keys() : Object.keys(pool || {});
    // Python 是 sorted(int(i) for ...) 包在 try 裡：任何一個 key 轉不了就整個清空
    ids = Array.from(keys)
      .map((i) => {
        const n = Math.trunc(Number(i));
        if (!Number.isFinite(n)) throw new Error("bad mode id");
        return n;
      })
      .sort((a, b) => a - b);
  } catch (e) {
    ids = [];
  }

  _mode_ids = ids;
  _mode_labels = [];
  _mode_names = [];
  for (const mid of ids) {
    const m = _mode_by_id(pool, mid) || dict();
    const name = _dget(m, "name", "");
    _mode_names.push(name || "");
    if (name) {
      _mode_labels.push(`0x${_hex04(mid)} ${name}`);
    } else {
      _mode_labels.push(`0x${_hex04(mid)}`);
    }
  }
  if (!_mode_ids.length) {
    _mode_labels = ["(無模式)"];
    _mode_names = [""];
  }
  _cur_idx = 0;
  _refresh_list();
  // 初始畫面先顯示第一個模式（只更新顯示，不送指令）
  if (_mode_ids.length) {
    _show_mode(_mode_ids[0]);
  }
  if (!initial) {
    print(`[PixelCtrl] 模式列表載入: ${ids.length} 個`);
  }
}

/** 清空並重建左欄 lv.list 內容（保持同一 widget，nav 引用不變）。 */
function _refresh_list() {
  if (_mode_list === null) {
    return;
  }
  try {
    _mode_list.clean(); // lv.js 的 clean() 會連 _items 一起清（跟真機一致）
  } catch (e) {
    /* 清單已不在就跳過 */
  }
  _mode_btns = [];
  for (const txt of _mode_labels) {
    let b;
    try {
      b = _mode_list.add_text(txt);
    } catch (e) {
      continue;
    }
    // 列文字是「0x0200 可動」→ 含中文，字型要用 ZH（用 F_NUM_M 會變方框）
    if (u.ZH) {
      try {
        b.set_style_text_font(u.ZH, 0);
      } catch (e) {
        /* 這個 binding 不支援 item 字型就跳過 */
      }
    }
    _mode_btns.push(b);
  }
  _cur_idx = Math.max(0, Math.min(_cur_idx, Math.max(0, _mode_btns.length - 1)));
  _sync_list();
}

/** 依目前選中索引高亮列表。 */
function _sync_list() {
  if (!_mode_btns.length) {
    return;
  }
  u.list_select(_mode_btns, _cur_idx, u.PRIMARY);
  // 游標超出可視區時把該列捲進來（binding 沒有這個方法就跳過，跟裝置一樣）
  try {
    _mode_list.scroll_to_view(_mode_btns[Math.max(0, Math.min(_cur_idx, _mode_btns.length - 1))]);
  } catch (e) {
    /* 沒有 scroll_to_view 的 binding 就跳過 */
  }
}

// ═══ 動作 ═══

/**
 * 把「播放模式 `0x3105`（廣播）」**本機發起**出去。
 *
 * ── 2026-10 改寫 ────────────────────────────────────────────────────
 * 舊版（函式名與內容都留著歷史痕跡）**直接抓 `now._esp`（私有屬性）自己
 * `send()`**，連 `NowBus` 的 `connected` 檢查、統計、Router 全部繞過；
 * 服務不存在時還自己 `espnow.ESPNow()` 開一個（會撞 `ESP_ERR_ESPNOW_EXIST`）。
 * 那是最嚴重的一種「傳輸層細節外流到 UI」—— 比 `remote.py` 舊版更糟
 * （它至少還經過 `NowBus`）。
 *
 * 現在：**只產生幀 → `inject()` 進 vBus**，由 Router 決定「執行 or 發射、
 * 走哪條管子」，由**管子自己**把幀頭 `addr = 0xFFFF` 解析成廣播。
 * 見 `todo/05_node_pairing.md` §3.1 / D14/D16。
 */
function _send_mode_broadcast(mid) {
  mid = Math.trunc(mid) & 0xffff;
  const mode_type = (mid >> 8) & 0xff;
  const mode_id = mid & 0xff;
  // struct.pack("<BBHB", type, id, delay=0, bri=0xFF)：B B H(2 bytes) B = 5 bytes
  const payload = Uint8Array.of(mode_type, mode_id, 0, 0, 0xff);

  const vb = get_vbus();
  if (vb === null) {
    print("[PixelCtrl] 無 vBus（排程任務未上線？）→ 無法發射");
    return false;
  }
  // Proto.pack 回的是共享 buffer 的 view（下一次 pack 就覆蓋）→ inject 立即消費 ✓
  const ok = Boolean(vb.inject(Proto.pack(0x3105, payload, { addr: 0xffff })));

  print(`[PixelCtrl] 0x3105 type=${mode_type} id=${mode_id} (0x${_hex04(mid)}) 已注入 vBus=${ok}`);
  return ok;
}

/** 只更新「目前模式」的顯示（不送指令）。id 與名稱同一行：`0x0200 可動` */
function _show_mode(mid) {
  if (_cur_lb !== null) {
    try {
      const i = _mode_ids.indexOf(Math.trunc(mid));
      const name = i >= 0 && _mode_names[i] ? ` ${_mode_names[i]}` : "";
      _cur_lb.set_text(`0x${_hex04(Math.trunc(mid) & 0xffff)}${name}`);
    } catch (e) {
      /* label 不在就跳過 */
    }
  }
}

/** 臨時：選中即發 ESP-NOW，不寫狀態、不經 task。 */
function _set_mode(mid) {
  _send_mode_broadcast(mid);
  _show_mode(mid);
}

/** 「可動」按鈕：點擊即發 ESP-NOW MODE_SET 0x0200（SERVO 組 mode 0）。 */
function _apply_movable() {
  print(`[PixelCtrl] 可動 → 0x${_hex04(MOVABLE_ID)}`);
  _send_mode_broadcast(MOVABLE_ID);
  if (_led_mov !== null) {
    try {
      u.led_set(_led_mov, true, u.SUCCESS);
    } catch (e) {
      /* LED 不在就跳過 */
    }
  }
}

/** 列表編輯態 enc：上下移選中（移動即設置，對齊 control_panel 語意）。 */
function _sel_mode_delta(dd) {
  if (!_mode_ids.length) {
    return;
  }
  const n = _mode_ids.length;
  _cur_idx = ((_cur_idx + Math.trunc(dd)) % n + n) % n;
  _sync_list();
  _set_mode(_mode_ids[_cur_idx]);
}

/** 「獲取列表」按鈕：重新載入模式池。 */
function _fetch_modes() {
  _load_modes(false);
  if (_led_fetch !== null) {
    try {
      u.led_set(_led_fetch, true, u.SUCCESS);
    } catch (e) {
      /* LED 不在就跳過 */
    }
  }
}

/**
 * 亮度 slider 編輯態 enc：**0–31**（APA102 的 5-bit 全域亮度）。
 * 送去 `_pixel_cmd.brightness` 的就是 0–31 原值，task 直接寫進 APA 的亮度欄位即可。
 */
function _adj_bright(dd) {
  const v = Math.max(0, Math.min(31, _bright_sl.get_value() + dd));
  _bright_sl.set_value(v, 0);
  _paint_ruler(v);
  bus.shared["_pixel_cmd"] = dict({ brightness: v });
}

/** 把刻度尺畫成「亮幾格」：第 0..v-1 格是藍色，其餘是軌道灰。 */
function _paint_ruler(v) {
  const n = Math.max(0, Math.min(31, Math.round(v)));
  for (let i = 0; i < _ticks.length; i++) {
    try {
      _ticks[i].set_style_bg_color(u.C(i < n ? u.PRIMARY : u.TRACK), 0);
    } catch (e) {
      /* 元件已回收就跳過 */
    }
  }
}

// ====== 頁面接口（轉發給 nav）======

export function on_enter() {
  // 每次進來重新採納 bus 的計時值（跟 control_panel 一樣）
  _tick_reset();
}

export function on_leave() {
  if (nav.is_editing()) {
    nav.exit();
    _sync_list();
  }
}

export function on_enc(d) {
  nav.enc(d);
  if (nav.current_kind() === ITEM_LIST) {
    _sync_list();
  }
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

export function update(run) {
  if (run % 10 !== 0) {
    return;
  }
  // 倒數計時（本地 non-blocking；外部送新幀時 seq 變 → 重新採納）
  try {
    const t = _tick_countdown();
    const txt = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
    if (_time_lb !== null && _time_lb.get_text() !== txt) {
      _time_lb.set_text(txt);
      _center_time();
    }
    if (_time_arc !== null) {
      _time_arc.set_value(t, 0);
    }
    if (_run_lb !== null) {
      const rtxt = _tick_running ? "計時中" : "待機";
      if (_run_lb.get_text() !== rtxt) {
        _run_lb.set_text(rtxt);
        _run_lb.set_style_text_color(u.C(_tick_running ? u.SUCCESS : u.TEXT3), 0);
      }
    }
  } catch (e) {
    /* 跟裝置一樣：這一幀讀不到就跳過 */
  }
}
