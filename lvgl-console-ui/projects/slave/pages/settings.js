// ui/page/settings.js — 系統設定頁（橫屏 320×240）
//
// 對應 ui/lvgl/page/settings.py。導覽用共用 nav helper：
//   enc 選 Wi-Fi 開關 → confirm 切換。
// update() 自己讀 bus：wifi enable / hostname / master_IP / ssid / slave_id / mac
//
// 轉換對照（這頁是第一個樣板，後面每頁都照這個形狀）：
//   global scr / _wifi_sw      → export let scr / let _wifi_sw
//   @register(...)             → export const meta = {...}
//   def build():               → export function build() {...}
//   lambda: ...                → () => ...
//   "{}.{}".format(a, b)       → `${a}:${b}`
//   for i, x in enumerate(l):  → l.forEach((x, i) => ...)

import lv from "@lvui/frameworks/lvgl/lv.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_SWITCH } from "@packages/lv-app/nav.js";

export const meta = {
  id: "settings",
  title: "系統設定",
  icon: "settings",
  desc: "網路·裝置資訊",
  order: 6,
  accent: 0x7f8c8d,
};

const nav = new Nav();
export let scr = null;
let _wifi_sw = null;
let _str_lbs = [];
let _last_txt = {};

// 唯讀字串欄位：（顯示標籤, 讀取函式）
const _STR_FIELDS = [
  ["主機名", () => _sys_str("hostname")],
  ["Master", () => `${_sys_str("master_IP")}:${_sys_cfg().get("master_port", 0)}`],
  ["Wi-Fi", () => _wifi_str("ssid")],
  ["裝置 ID", () => _sid()],
  ["MAC", () => _mac()],
];

export function build() {
  _str_lbs = [];
  _last_txt = {};
  nav.reset();

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);
  scr.set_style_bg_opa(255, 0);

  // Wi-Fi 開關（左上）
  const c1 = u.mk_card(scr, 12, 6, 148, 48);
  u.mk_icon(c1, "wifi", 10, 12, u.TEXT2);
  u.mk_label(c1, "Wi-Fi 啟用", 32, 14, u.TEXT, u.ZH);
  _wifi_sw = u.mk_switch(c1, 100, 12, false);
  nav.add(_wifi_sw, ITEM_SWITCH, { on_change: _toggle_wifi });

  // 裝置資訊（唯讀字串列表）：左欄 i<3（Wi-Fi 卡下方），右欄 i>=3（頂部）
  _STR_FIELDS.forEach(([label], i) => {
    const colX = i < 3 ? 12 : 166;
    const colY = i < 3 ? 62 + (i % 3) * 42 : 6 + (i - 3) * 42;
    const c = u.mk_card(scr, colX, colY, i < 3 ? 148 : u.W - 24 - 154, 38);
    u.mk_label(c, label, 8, 10, u.TEXT2, u.ZH);
    const lb = lv.label(c);
    lb.set_pos(8, 22);
    lb.set_style_text_color(u.C(u.TEXT), 0);
    if (u.ZH) lb.set_style_text_font(u.ZH, 0);
    lb.set_text("—");
    _str_lbs.push(lb);
  });

  nav.paint();
  return scr;
}

// ── bus 讀取（全部走 bus.shared，跟裝置同一條路徑）──
function _sys_cfg() {
  return bus.shared.get("System") || dict();
}

function _sys_str(key) {
  return String(_sys_cfg().get(key, "") || "—");
}

function _wifi_str(key) {
  const net = bus.shared.get("Network") || dict();
  const wifi = net.get("wifi", null) || dict();
  return String(wifi.get(key, "") || "—");
}

function _sid() {
  return String(bus.slave_id || "—");
}

function _mac() {
  const sid = _sid();
  if (sid.length >= 12) {
    const parts = [];
    for (let i = 0; i < 12; i += 2) parts.push(sid.slice(i, i + 2));
    return parts.join(":");
  }
  return sid;
}

function _toggle_wifi() {
  const next = !u.sw_get(_wifi_sw);
  u.sw_set(_wifi_sw, next);
  print(`[settings] wifi_enable -> ${next ? "ON" : "OFF"}`);
}

// ── 頁面接口（轉發給 nav）──
export function on_enter() {}
export function on_leave() {
  if (nav.is_editing()) nav.exit();
}
export function on_enc(d) {
  nav.enc(d);
}
export function on_confirm() {
  nav.confirm();
  return null;
}
export function on_exit() {
  return nav.exit();
}

export function update(run) {
  if (run % 20 !== 0) return;
  try {
    const net = bus.shared.get("Network") || dict();
    const wifi = net.get("wifi", null) || dict();
    const wenable = Number(wifi.get("enable", 0)) | 0;
    if (u.sw_get(_wifi_sw) !== Boolean(wenable)) u.sw_set(_wifi_sw, Boolean(wenable));
    _STR_FIELDS.forEach(([, fn], i) => {
      if (i < _str_lbs.length) {
        const txt = String(fn());
        if (_last_txt[i] !== txt) {
          _last_txt[i] = txt;
          _str_lbs[i].set_text(txt);
        }
      }
    });
  } catch (e) {
    /* 跟裝置一樣：讀不到就這一幀不更新，不要讓 UI 掛掉 */
  }
}
