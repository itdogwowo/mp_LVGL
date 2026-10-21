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
//
// ⚠ 缺少 API: lv.list.clean() 只刪 children、不清 List._items → 已用 _list_clear() 代替
//    （不清 _items 的話，下一次 add_text 的新列會接在已刪掉的列後面，越排越下面、被 clip 掉）

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
let _cur_idx = 0;         // 目前選中索引（選中即設置）
let _bright_sl = null;
let _bright_lb = null;
let _cur_lb = null;       // 目前模式顯示

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

export const meta = {
  id: "pixel_controller",
  title: "Pixel 控制",
  icon: "sliders-horizontal",
  desc: "模式設置·列表·可動",
  order: 2,
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
  const rx = lx + lw + 4;
  const rw = u.W - 4 - rx;
  const pair = u.mk_list(scr, lx, 4, lw, u.H - 8, ["(載入中)"], u.F_NUM_M);
  _mode_list = pair[0];
  _mode_btns = pair[1];
  nav.add(_mode_list, ITEM_LIST, { on_change: _sel_mode_delta });

  // 右欄上：動作區（獲取列表 + 可動）
  const c2 = _panel(scr, rx, 4, rw, 54);
  u.mk_label(c2, "動作", 6, 4, u.TEXT2, u.ZH);
  const btn_fetch = u.mk_btn(c2, "獲取列表", 6, 26, 74, 22, "primary");
  nav.add(btn_fetch, ITEM_BUTTON, { on_change: _fetch_modes });
  const btn_mov = u.mk_btn(c2, "可動", 88, 26, 74, 22, "secondary");
  nav.add(btn_mov, ITEM_BUTTON, { on_change: _apply_movable });

  // 右欄中：目前模式顯示
  const c3 = _panel(scr, rx, 62, rw, 34);
  u.mk_label(c3, "目前", 6, 4, u.TEXT2, u.ZH);
  _cur_lb = lv.label(c3);
  _cur_lb.align(lv.ALIGN.RIGHT_MID, -6, 0);
  _cur_lb.set_style_text_font(u.F_NUM_M, 0);
  _cur_lb.set_style_text_color(u.C(u.PRIMARY), 0);
  _cur_lb.set_text("—");

  // 右欄下：亮度 slider（0-255，對應 MODE_SET.brightness）
  const c4 = _panel(scr, rx, 100, rw, 50);
  u.mk_label(c4, "亮度", 6, 4, u.TEXT2, u.ZH);
  _bright_lb = lv.label(c4);
  _bright_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4);
  _bright_lb.set_style_text_font(u.F_NUM_M, 0);
  _bright_lb.set_style_text_color(u.C(u.PRIMARY), 0);
  _bright_lb.set_text("255");
  _bright_sl = u.mk_slider(c4, 6, 28, rw - 12, 0, 255, 255);
  nav.add(_bright_sl, ITEM_SLIDER, { on_change: _adj_bright });

  _load_modes(true);
  nav.paint();
  return scr;
}

/** 輕量分區（與 control_panel._panel 相同）。 */
function _panel(parent, x, y, w, h) {
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
  for (const mid of ids) {
    const m = _mode_by_id(pool, mid) || dict();
    const name = _dget(m, "name", "");
    if (name) {
      _mode_labels.push(`0x${_hex04(mid)} ${name}`);
    } else {
      _mode_labels.push(`0x${_hex04(mid)}`);
    }
  }
  if (!_mode_ids.length) {
    _mode_labels = ["(無模式)"];
  }
  _cur_idx = 0;
  _refresh_list();
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
    _list_clear(_mode_list);
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
    if (u.F_NUM_M) {
      try {
        b.set_style_text_font(u.F_NUM_M, 0);
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

/** 臨時：選中即發 ESP-NOW，不寫狀態、不經 task。 */
function _set_mode(mid) {
  _send_mode_broadcast(mid);
  if (_cur_lb !== null) {
    try {
      _cur_lb.set_text(`0x${_hex04(Math.trunc(mid) & 0xffff)}`);
    } catch (e) {
      /* label 不在就跳過 */
    }
  }
}

/** 「可動」按鈕：點擊即發 ESP-NOW MODE_SET 0x0200（SERVO 組 mode 0）。 */
function _apply_movable() {
  print(`[PixelCtrl] 可動 → 0x${_hex04(MOVABLE_ID)}`);
  _send_mode_broadcast(MOVABLE_ID);
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
}

/** 亮度 slider 編輯態 enc：0-255，寫 _pixel_cmd 由 task 套用（與 MODE_SET.brightness 同源）。 */
function _adj_bright(dd) {
  const v = Math.max(0, Math.min(255, _bright_sl.get_value() + dd));
  _bright_sl.set_value(v, 0);
  _bright_lb.set_text(String(v));
  bus.shared["_pixel_cmd"] = dict({ brightness: v });
}

// ====== 頁面接口（轉發給 nav）======

export function on_enter() {}

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
  // 本頁無需週期性拉取（模式清單由「獲取列表」手動觸發；目前模式在設置時即時顯示）
}
