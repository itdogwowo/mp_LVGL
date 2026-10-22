// projects/slave/pages/now_setting.js — ESP-NOW 設定頁（傳輸層）
//
// 對應 ui/lvgl/page/now_setting.py
//
// 為什麼要獨立一頁（todo/07_now_setting_ui.md §1）
// ══════════════════════════════════════════════════════════════════
// 舊版把「ESP-NOW 開關」跟「節點清單 ＋ 模式表」擠在 remote.py 一頁，造成三個
// 說不清楚的地方：
//   1. 限制說不清 —— 「已選 3/19」是射頻限制（ESP-NOW 硬體 peer 表 20 格），
//      不是「我最多能控 3 台」。UART/WS 上的節點根本不受這個約束。
//   2. FF 語意衝突 —— 射頻層的 FF 是「不指定對象，所有人收得到」；
//      應用層的「全選」是「我挑的每一台都送」。混在一張表必然誤解。
//   3. 持久化位置不同 —— 射頻清單是這台裝置的無線電設定（@now.*）；
//      遙控器清單是「我要控制誰」（@node.targets）。
// 所以：本頁 = 「這顆無線電要對誰講話」，remote.py = 「我要操作誰、播什麼」。
//
// 版面（320×240 橫屏）
// ══════════════════════════════════════════════════════════════════
//   y=5    標題 + 右側狀態訊息
//   y=22   ┌ 啟用 ┐ ┌ 頻道 ─────┐ ┌ 加密 ┐      h=46
//   y=72   「可選 (n)」        「已選 (m/19)」
//   y=88   ┌ 可選清單 ┐        ┌ 已選清單 ┐      h=114
//   y=208  [掃描][加入][移除][套用][清除]
//
// 兩張表（Windows 式，使用者定案）
// ══════════════════════════════════════════════════════════════════
//   可選 = 掃描到的 radio peer（PeerRegistry.snapshot()，任何總線上的都算）
//   已選 = 使用者挑的 MAC（@now.selected）＋ 永遠墊底的 FF 廣播
//
//   ★「套用」是唯一會動硬體 peer 表的按鈕（NowBus.apply_peers）。
//     掃描只累積「可選」、加入/移除只改 UI 狀態 —— 都不偷偷佔格子。
//     刻意的：poll() 對每個講過話的 MAC 被動學習（MAC 無法枚舉），
//     那些是雜訊，不該在使用者決定之前就吃掉 20 格裡的位子。
//
//   ★ 滿了不自動淘汰（使用者定案）：直接拒絕並提示「請先移除一些」。
//     舊版會自動踢掉最舊的 —— 那會讓使用者的清單無聲地變動。
//
// FF 與具體節點互斥（使用者定案）
// ══════════════════════════════════════════════════════════════════
//   已選裡有具體節點 → FF 退下；節點全部移除 → FF 自動回來。
//   理由：FF 的字面意義是「不指定對象」。既然已經指定了對象，還留著 FF 只會讓
//   每一次送出都順便吵到全場。FF 不列在「可選」裡 —— 它不是掃到的、也不能被
//   「加入」，它是預設值。
//
// MAC 的顯示格式
// ══════════════════════════════════════════════════════════════════
//   清單寬度只有 124px（可選）／184px（已選），塞不下 AA:BB:CC:DD:EE:FF。
//   兩張表統一只顯示後 3 bytes（AA:BB:CC）—— 同一個裝置在兩張表裡長得一樣，
//   才不會誤以為是兩個裝置。前 3 bytes 是 OUI（廠商碼），同批裝置本來就一樣，
//   砍掉不損失辨識度。完整 MAC 在加入/移除時印到 console。
//
// 資料來源（本頁不自己維護任何狀態，只有「未套用的 UI 編輯」是本地態）
// ══════════════════════════════════════════════════════════════════
//   bus.shared["peers"]        ← PeerRegistry.snapshot()（可選的來源）
//   bus.shared["now_setting"]  ← ConfigManager.now_state()（已選/加密，@now.*）
//   bus.shared["Network"]      ← ESP_now.enable = 授權旗標（不是射頻狀態）
//   bus.get_service("NowBus")  ← .connected = 射頻實際開著沒
//   bus.get_service("disp")    ← exec_cmd / make_cmd
//
// ⚠ 缺少 API: cfg_manager.save_now() / clear_now()（projects/slave/mocks.js 只有
//   get/set/save/now_state）→ 改用 set("now_setting", …) + save() 代替，
//   語義對齊 ConfigManager.save_now()/clear_now()：寫回 @now.* 那一份 shared 狀態。
// ⚠ 缺少 API: lv.js 的 lv.list.clean() 只刪 children、沒同步清 List._items，
//   而 List._layoutItems()（每幀由 paint 呼叫）是照 _items 排版的 → 重填後
//   內容會愈來愈往下飄。lv.js 不能改，所以在 _fill() 補一行等價於真機的 clean。
// ⚠ 簽名差異: u.mk_list(..., font=) 在 JS 是第 7 個位置參數（f），改用位置傳 u.ZH。
//
// 轉換對照（Python → JS）：
//   global x / nav / scr       → 模組層 let / const（直接賦值，不用 global）
//   @register(id=...)          → export const meta = {...}
//   函式定義                    → function 宣告
//   無參數匿名函式              → () => _f()
//   字串格式化                  → 模板字串 `${a}:${b}`
//   "0x{:04X}" 補零             → toString(16).toUpperCase().padStart(4, "0")
//   str(x).upper()             → String(x).toUpperCase()
//   list(x) / x.pop(i)         → Array.from(x) / x.splice(i, 1)[0]
//   空值判斷                    → a === null

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_LIST, ITEM_BUTTON, ITEM_SWITCH } from "@packages/lv-app/nav.js";
import { bus, dict } from "@packages/lv-app/bus.js";
import { cfg_manager, get_vbus } from "../mocks.js";

export const meta = {
  id: "now_setting",
  title: "ESP-NOW",
  icon: "sensors",
  desc: "頻道·加密·已選節點",
  order: 5,
  accent: 0x7B1FA2,
};

const REFRESH_EVERY = 10; // 每 N 幀刷新一次顯示
const SCAN_SPREAD_MS = 500; // 掃描抖動視窗（0 = 不抖動）。見 remote._do_scan 的長註解
const CH_MIN = 1;
const CH_MAX = 13; // Wi-Fi 2.4G 的可用頻道（ESP-NOW 跟著 Wi-Fi 走）

const BCAST_HEX = "FFFFFFFFFFFF"; // 廣播 MAC：永遠在「已選」墊底、不可加入/移除

const nav = new Nav();
export let scr = null;
let _opt_list = null; // 可選清單 widget
let _sel_list = null; // 已選清單 widget
let _opt_btns = [];
let _sel_btns = [];
let _opt_rows = []; // 可選的 MAC（大寫 hex，無冒號）
let _sel_macs = []; // 已選的 MAC（大寫 hex，無冒號；**不含 FF**）
let _oi = 0; // 可選清單的游標
let _si = 0; // 已選清單的游標
let _lb = {};
let _last = {};
let _sw_on = null;
let _sw_enc = null;
let _dirty = false; // 使用者改過「已選」但還沒按套用

// ══════════════════════════════════════════════════════════════════
//  取得服務 / 發指令（與 remote.py 同一套「兩個入口」，不要混用）
// ══════════════════════════════════════════════════════════════════

/** bus 本體（裝置在函式內 import lib.sys.sys_bus，這裡是模組層已 import 的 bus）。 */
function _kv() {
  return bus;
}

/** handler 的 ctx。`app` 由 bus 服務取得（app.py 註冊）—— 不能傳 null。 */
function _ctx() {
  const b = _kv();
  return { app: b.get_service("app"), transport: "ui" };
}

/** NowBus 服務（**關掉之後它仍然在 bus 上**，用 .connected 判斷狀態）。 */
function _now() {
  return _kv().get_service("NowBus");
}

function _cfg() {
  return cfg_manager;
}

/** ⚠ 缺少 API: cfg_manager.save_now()（mocks.js 只有 save）。
 *
 *  替代寫法：把整份 now_state 寫回 "now_setting"。真機的 save_now 也是
 *  「寫 kv → 把 now_state() 重推 shared」，所以在模擬器裡這一步等價。
 */
function _save_now(st) {
  cfg_manager.set("now_setting", st);
  return cfg_manager.save();
}

/** ⚠ 缺少 API: cfg_manager.clear_now()（mocks.js 沒有）。
 *
 *  替代寫法：只把 ConfigManager._NOW_KEYS 那四個欄位歸零，再走 _save_now。
 *  刻意不換成一份全新的 dict —— seed 的 now_setting 還有 peers/channel 兩個
 *  這頁不擁有的 key，不能順手清掉別人的資料。
 */
function _clear_now() {
  const st = _cfg().now_state();
  st["selected"] = [];
  st["encrypt"] = 0;
  st["pmk"] = "";
  st["lmk"] = "";
  _save_now(st);
  return true;
}

/** **內部執行**（走 disp.exec_cmd —— 不經 Router、保證不外送）。
 *
 * 「開/關/換頻道」是**本機動作**（改的是自己的無線電），所以走這個入口，
 * 不是 _tx_bcast()。_tx_bcast() 是「我發起一幀給別人」。
 */
function _exec(cmd, args) {
  const b = _kv();
  const disp = b.get_service("disp");
  if (disp === null) {
    print("[now_set] 無 disp 服務");
    return false;
  }
  return disp.exec_cmd(cmd, args, _ctx());
}

/** 廣播發一幀（走 vBus → Router）。掃描用：我還不認識任何人。 */
function _tx_bcast(cmd, args) {
  const b = _kv();
  const disp = b.get_service("disp");
  if (disp === null) {
    print("[now_set] 無 disp 服務 → 無法發射");
    return false;
  }
  const frame = disp.make_cmd(cmd, args, 0xffff);
  if (frame === null || frame === undefined) {
    return false;
  }
  const vb = get_vbus();
  if (vb === null) {
    print("[now_set] 無 vBus → 無法發射");
    return false;
  }
  // make_cmd 回的是共享 buffer 的 view（下一次 pack 就覆蓋）→ inject 立即消費 ✓
  return Boolean(vb.inject(frame));
}

// ══════════════════════════════════════════════════════════════════
//  小工具
// ══════════════════════════════════════════════════════════════════

/** Python 的 list == list 是逐項比較；JS 的 [] === [] 永遠是 false。 */
function _same(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return false;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/** `AABBCCDDEEFF` → `DD:EE:FF`（只留後 3 bytes，見檔頭「MAC 的顯示格式」）。 */
function _short(mac) {
  const m = String(mac || "").toUpperCase();
  if (m.length < 12) {
    return m || "??";
  }
  return `${m.slice(6, 8)}:${m.slice(8, 10)}:${m.slice(10, 12)}`;
}

/** `AABBCCDDEEFF` → `AA:BB:CC:DD:EE:FF`（印 console 用）。 */
function _full(mac) {
  const m = String(mac || "").toUpperCase();
  if (m.length < 12) {
    return m || "??";
  }
  const parts = [];
  for (let i = 0; i < 12; i += 2) parts.push(m.slice(i, i + 2));
  return parts.join(":");
}

/** peer 的 cid → `0x0002`；還不知道（掃到但沒回過 cid）→ `----`。
 *
 * ⚠ 不能寫成 `row.get("cid") and "0x…" or "----"` —— cid **合法值包含 0**，
 * 而 0 是 falsy，會讓「cid 真的是 0」被誤顯示成「不知道」。
 */
function _cid_txt(row) {
  const cid = row.get("cid");
  if (cid === null || cid === undefined) {
    return "----";
  }
  try {
    // Python 的 int("abc") 會 raise 走 except；JS 的 Number() 回 NaN，要自己擋
    const n = Math.trunc(Number(cid));
    if (!Number.isFinite(n)) {
      return "----";
    }
    return "0x" + (n & 0xffff).toString(16).toUpperCase().padStart(4, "0");
  } catch (e) {
    return "----";
  }
}

/** 目前加密設定下的「已選」上限（不含廣播那一格）。取不到服務時用 19。 */
function _cap() {
  const now = _now();
  try {
    return now !== null ? Math.trunc(Number(now.peer_cap())) : 19;
  } catch (e) {
    return 19;
  }
}

/** 射頻**實際**開著沒（`connected`，不是「服務存不存在」）。 */
function _radio_on() {
  const now = _now();
  try {
    return Boolean(now !== null && now.connected);
  } catch (e) {
    return false;
  }
}

/** `Network.ESP_now.enable` —— **授權旗標**，不是射頻狀態。
 *
 * 兩者的差別是本頁最常見的誤判來源：
 *   旗標 = 0 → `on_now_init` 會**拒絕**開（不偷偷開），開關怎麼撥都沒用
 *   旗標 = 1 但 connected 是關的 → 有授權，只是還沒開起來
 */
function _flag_on() {
  const nw = _kv().shared.get("Network") || dict();
  try {
    return Boolean(Math.trunc(Number((nw.get("ESP_now") || dict()).get("enable", 0))));
  } catch (e) {
    return false;
  }
}

function _channel() {
  const now = _now();
  try {
    return now !== null ? now._channel() : null;
  } catch (e) {
    return null;
  }
}

/** 只有值真的變了才 set_text（省掉每幀重畫）。 */
function _set(key, txt) {
  if (_last[key] === txt) {
    return;
  }
  _last[key] = txt;
  const lb = _lb[key];
  if (lb === null || lb === undefined) {
    return;
  }
  try {
    lb.set_text(txt);
  } catch (e) {
    /* 跟裝置一樣：這一幀不更新 */
  }
}

function _msg(txt) {
  print("[now_set]", txt);
  _set("msg", txt);
}

// ══════════════════════════════════════════════════════════════════
//  動作
// ══════════════════════════════════════════════════════════════════

/** 廣播 `0x100D` 點名；回覆由 PeerRegistry 自動登記 → 變成「可選」。
 *
 * ★ 掃描**不寫方向**（`0x1016` 才是唯一決定方向的指令）。
 *   舊版 `on_identify_req` 會把 reply_cid 記成 master_cid，所以一次掃描
 *   = 射程內所有對端都把本板認成 master（無聲搶奪）。那個寫入已移除。
 *
 * ★ `timeout_ms` = 抖動視窗：廣播點名會讓所有對端**同一瞬間**回話，
 *   在空中是硬碰撞、會整批掉。帶上這個值讓各對端隨機延遲 [0, 500]ms 才回。
 *   真的被撞掉的節點：再按一次掃描即可（不做自動重試）。
 */
function _do_scan() {
  const b = _kv();
  const ok = _tx_bcast(0x100d, {
    reply_cid: Math.trunc(Number(b.cid ?? 0xffff)) & 0xffff,
    timeout_ms: SCAN_SPREAD_MS,
  });
  _msg(`掃描 ${ok ? "已送出" : "失敗"}`);
  _refresh_opt(true);
}

/** 可選 → 已選（**只改 UI 狀態**，硬體表要按「套用」才會動）。 */
function _do_add() {
  if (!(0 <= _oi && _oi < _opt_rows.length)) {
    _msg("沒有可加入的項目");
    return;
  }
  const mac = _opt_rows[_oi];
  if (_sel_macs.includes(mac)) {
    _msg(`${_short(mac)} 已在已選`);
    return;
  }
  if (_sel_macs.length >= _cap()) {
    // ★ 不自動淘汰（使用者定案）：講清楚要做什麼，不要幫使用者決定踢掉誰
    _msg(`已滿 ${_sel_macs.length}/${_cap()} → 請先移除一些`);
    return;
  }
  _sel_macs.push(mac);
  _dirty = true;
  print(`[now_set] + ${_full(mac)}`);
  _msg(`加入 ${_short(mac)} （記得按套用）`);
  _refresh_sel(true);
}

/** 已選 → 拿掉（**只改 UI 狀態**）。 */
function _do_remove() {
  if (!(0 <= _si && _si < _sel_macs.length)) {
    _msg(_sel_macs.length ? "沒有可移除的項目" : "廣播不可移除（它是預設）");
    return;
  }
  const mac = _sel_macs.splice(_si, 1)[0];
  _dirty = true;
  print(`[now_set] - ${_full(mac)}`);
  _msg(`移除 ${_short(mac)} （記得按套用）`);
  _refresh_sel(true);
}

/** ★ 唯一會動硬體 peer 表的按鈕。
 *
 * 順序很重要：**先** apply_peers() 真的改硬體，成功才 save_now() 落盤。
 * 反過來的話，硬體失敗（例如超過上限）會留下一份「DB 說有、硬體沒有」的
 * 清單 —— 開機時又會照著那份清單重建一次失敗的狀態。
 */
function _do_apply() {
  const now = _now();
  if (now === null) {
    _msg("無 NowBus 服務 → 無法套用");
    return;
  }
  const [added, removed, failed] = now.apply_peers(Array.from(_sel_macs));
  if (failed && !added && !removed) {
    // apply_peers 的「超過上限」也是走這條（回 0,0,N）
    _msg(`套用失敗（${failed} 台）→ 請先移除一些`);
    return;
  }
  const st = _cfg().now_state();
  st["selected"] = Array.from(_sel_macs);
  _save_now(st);
  _dirty = false;
  _msg(`套用：+${added} -${removed} 失敗${failed} 現有${now.peer_count ?? "?"}`);
}

/** 清除所有記錄 —— **只清 ESP-NOW 的**（使用者定案）。
 *
 * 硬體 peer 表（clear_peers）＋ @now.*（clear_now）。
 * @peer.*（節點記錄）與 @node.*（配對方向）**不動** ——
 * 清無線電設定不該把「我控制誰」也一起忘掉。
 */
function _do_clear() {
  const now = _now();
  let n = 0;
  if (now !== null) {
    try {
      n = now.clear_peers();
    } catch (e) {
      print("[now_set] clear_peers 失敗:", e);
    }
  }
  _clear_now();
  _sel_macs = [];
  _dirty = false;
  _msg(`清除：射頻 ${n} 筆（節點記錄/方向保留）`);
  _refresh_sel(true);
}

/** 啟用開關 → `0x1301 NOW_INIT{action}`（0=查詢 1=開 2=關）。
 *
 * ⚠ **必須明確送 action=1/2**：`0x1301` 不給參數（或送 0）是**查詢**，
 * 不會開啟 ESP-NOW（欄位型別的原生預設值就是 0）。
 */
function _toggle_enable() {
  const want = !u.sw_get(_sw_on);
  u.sw_set(_sw_on, want);
  _exec(0x1301, { action: want ? 1 : 2 });
  _sync_switches(); // 以**實際**狀態回寫（可能與剛才撥的不同）
  if (want && !_radio_on()) {
    _msg(!_flag_on() ? "開不起來：授權旗標 = 0" : "開不起來：射頻未就緒");
  } else {
    _msg(`ESP-NOW ${_radio_on() ? "ON" : "OFF"}`);
  }
}

/** 加密開關 → `NowBus.set_encrypt()`。
 *
 * ★ 沒有金鑰**不給開**（set_encrypt 自己會擋）：加密開著硬體收得下，
 *   但對端沒有同一組 PMK/LMK 就解不開 ——「加得進去、卻什麼都收不到」
 *   是最難查的那種失敗。寧可擋在這裡並說清楚。
 *
 * 金鑰（16-byte hex）目前只能從 `@now.pmk` / `@now.lmk` 來；
 * LVGL 沒有鍵盤 → 匯入方式見 todo/07 §2.5（網頁 UI 或 /now_keys.json）。
 */
function _toggle_encrypt() {
  const want = !u.sw_get(_sw_enc);
  const now = _now();
  if (now === null) {
    u.sw_set(_sw_enc, false);
    _msg("無 NowBus 服務");
    return;
  }
  const st = _cfg().now_state();
  if (want && !(st.get("pmk") && st.get("lmk"))) {
    u.sw_set(_sw_enc, false);
    _msg("沒有金鑰（pmk/lmk）→ 不開加密");
    return;
  }
  const ok = now.set_encrypt(want, st.get("pmk") || null, st.get("lmk") || null);
  u.sw_set(_sw_enc, Boolean(ok));
  if (ok) {
    st["encrypt"] = want ? 1 : 0;
    _save_now(st);
    // 上限從 19 變 6（或反之）→ 現有清單可能超標，但**不自動淘汰**
    _dirty = true;
    _msg(
      `加密 ${want ? "ON" : "OFF"} （上限 ${_cap()}）` +
        `${_sel_macs.length > _cap() ? "！已選超標，請移除" : ""}`
    );
    _refresh_sel(true);
  } else {
    _msg("加密切換失敗");
  }
}

/** 頻道 ◀ / ▶ → `0x1301{action:3, channel}`（執行期可換，**不需重啟**）。
 *
 * 真機 10/10 驗過（changelog §33）。Master 換頻道不必重啟；
 * Slave 由 Master 用 `0x1016` 覆蓋即可 —— 這是使用者定案的語意。
 */
function _ch_step(d) {
  let ch = _channel();
  if (ch === null) {
    ch = CH_MIN;
  }
  let nch = ch + d;
  if (nch < CH_MIN) {
    nch = CH_MAX;
  } else if (nch > CH_MAX) {
    nch = CH_MIN;
  }
  _exec(0x1301, { action: 3, channel: nch });
  _set("ch", `ch${_channel() !== null ? _channel() : nch}`);
}

/** 可選清單編輯態：encoder 移動游標。 */
function _on_opt_move(dd) {
  const n = _opt_btns.length;
  if (n) {
    // Python 的 % 對負數也回正；JS 的 % 會留負號，所以要補一次
    _oi = (((_oi + dd) % n) + n) % n;
    u.list_select(_opt_btns, _oi, u.PRIMARY);
  }
}

/** 已選清單編輯態：encoder 移動游標（第 0 列是 FF 時不可移除）。 */
function _on_sel_move(dd) {
  const n = _sel_btns.length;
  if (n) {
    _si = (((_si + dd) % n) + n) % n;
    u.list_select(_sel_btns, _si, u.PRIMARY);
  }
}

// ══════════════════════════════════════════════════════════════════
//  建立畫面
// ══════════════════════════════════════════════════════════════════

function _panel(parent, x, y, w, h) {
  const c = lv.obj(parent);
  c.set_size(w, h);
  c.set_pos(x, y);
  c.set_style_bg_color(u.C(u.SURFACE), 0);
  c.set_style_radius(8, 0);
  c.set_style_border_width(0, 0);
  c.set_style_pad_all(0, 0);
  try {
    c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  } catch (e) {
    /* 舊 binding 沒這個 flag；跟裝置一樣吞掉 */
  }
  return c;
}

/** 重建清單內容。`mk_list` 只 append，所以要先 `clean()`。 */
function _fill(lst, labels) {
  try {
    lst.clean();
    // ⚠ 缺少 API: lv.js 的 clean() 只刪 children，沒清 List._items；
    //   而 _layoutItems() 每幀照 _items 排版 → 重填的列會接在已刪掉的列後面。
    //   真機的 lv.list.clean() 是整個清掉，這裡補一步等價動作（不改 lv.js）。
    if (Array.isArray(lst._items)) lst._items.length = 0;
  } catch (e) {
    /* 跟裝置一樣：清不掉就繼續 */
  }
  const out = [];
  for (const txt of labels) {
    try {
      const btn = lst.add_text(txt);
      // ★ 用 u.ZH 而不是 F_NUM_S：這張表有中文（「FF  廣播  ←預設」），
      //   而 Montserrat 是純拉丁字型 → 中文會變空格子。
      if (u.ZH) btn.set_style_text_font(u.ZH, 0);
      out.push(btn);
    } catch (e) {
      continue;
    }
  }
  return out;
}

export function build() {
  nav.reset();
  _lb = {};
  _last = {};
  _oi = 0;
  _si = 0;
  _dirty = false;
  _sel_macs = Array.from(_cfg().now_state().get("selected") || []);

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);

  u.mk_label(scr, "ESP-NOW 設定", 8, 5, u.TEXT, u.ZH);
  _lb["msg"] = u.mk_label(scr, "", 122, 6, u.TEXT3, u.ZH);

  // ── 三張卡：啟用 / 頻道 / 加密 ──
  //   ★ 卡片內的標籤與元件都要留垂直間距：卡片高 46，標題佔 4..20，
  //     元件從 y=20 起、高 24 → 20..44 ✓。舊版 remote.py 就是沒算這個
  //     （開關 44×24 擺在 y=224，224+24=248 > 240，下緣被螢幕切掉）。
  //   ★ 橫向也要算：開關 44 寬，擺在 x=6 → 佔到 50，右邊只剩「卡寬-50」。
  //     卡寬是照「最長的那串字」訂的，不是平均分：
  //       啟用卡 112 → 52..112 剛好放得下「未授權」3 個中文字
  //       頻道卡 104 → 26+6 + 標籤 36 + 26 的右鈕，收到 98
  //       加密卡  88 → 52..88 放「19格」
  //     三張卡合計 112+4+104+4+88 = 312，左右各留 4（螢幕 320）。
  const c_on = _panel(scr, 4, 22, 112, 46);
  u.mk_label(c_on, "啟用", 6, 4, u.TEXT3, u.ZH);
  _sw_on = u.mk_switch(c_on, 6, 20, false);
  nav.add(_sw_on, ITEM_SWITCH, { on_change: _toggle_enable });
  _lb["flag"] = u.mk_label(c_on, "—", 52, 24, u.TEXT3, u.ZH);

  const c_ch = _panel(scr, 120, 22, 104, 46);
  u.mk_label(c_ch, "頻道", 6, 4, u.TEXT3, u.ZH);
  const b_l = u.mk_btn(c_ch, "<", 6, 22, 26, 20, "secondary");
  nav.add(b_l, ITEM_BUTTON, { on_change: () => _ch_step(-1) });
  // ★ 用 u.ZH：內容含破折號「—」，Montserrat 不一定有；而且 ch— 會顯示
  //   在還沒同步到頻道之前。u.ZH 同時涵蓋 ASCII 與中文。
  _lb["ch"] = u.mk_label(c_ch, "ch—", 36, 24, u.TEXT, u.ZH);
  const b_r = u.mk_btn(c_ch, ">", 72, 22, 26, 20, "secondary");
  nav.add(b_r, ITEM_BUTTON, { on_change: () => _ch_step(1) });

  const c_enc = _panel(scr, 228, 22, 88, 46);
  u.mk_label(c_enc, "加密", 6, 4, u.TEXT3, u.ZH);
  _sw_enc = u.mk_switch(c_enc, 6, 20, false);
  nav.add(_sw_enc, ITEM_SWITCH, { on_change: _toggle_encrypt });
  _lb["cap"] = u.mk_label(c_enc, "—", 52, 24, u.TEXT3, u.ZH);

  // ── 兩張表 ──
  //   「可選」不含 FF：它不是掃到的、也不能被加入，它是已選的預設值。
  u.mk_label(scr, "可選", 6, 72, u.TEXT3, u.ZH);
  _lb["optn"] = u.mk_label(scr, "(0)", 40, 72, u.TEXT2, u.ZH);
  const l_opt = u.mk_list(scr, 4, 88, 124, 114, ["(按掃描)"], u.ZH);
  _opt_list = l_opt[0];
  _opt_btns = l_opt[1];
  nav.add(_opt_list, ITEM_LIST, { on_change: _on_opt_move });

  u.mk_label(scr, "已選", 134, 72, u.TEXT3, u.ZH);
  _lb["seln"] = u.mk_label(scr, "(0/19)", 168, 72, u.TEXT2, u.ZH);
  const l_sel = u.mk_list(scr, 132, 88, 184, 114, ["FF  廣播"], u.ZH);
  _sel_list = l_sel[0];
  _sel_btns = l_sel[1];
  nav.add(_sel_list, ITEM_LIST, { on_change: _on_sel_move });

  // ── 底列：5 顆按鈕（60*5 + 3*4 = 312）──
  const bw = 60;
  const gap = 3;
  const bx = 4;
  const y = 208;
  const b1 = u.mk_btn(scr, "掃描", bx, y, bw, 22, "primary");
  nav.add(b1, ITEM_BUTTON, { on_change: _do_scan });
  const b2 = u.mk_btn(scr, "加入", bx + (bw + gap), y, bw, 22, "secondary");
  nav.add(b2, ITEM_BUTTON, { on_change: _do_add });
  const b3 = u.mk_btn(scr, "移除", bx + 2 * (bw + gap), y, bw, 22, "secondary");
  nav.add(b3, ITEM_BUTTON, { on_change: _do_remove });
  const b4 = u.mk_btn(scr, "套用", bx + 3 * (bw + gap), y, bw, 22, "primary");
  nav.add(b4, ITEM_BUTTON, { on_change: _do_apply });
  const b5 = u.mk_btn(scr, "清除", bx + 4 * (bw + gap), y, bw, 22, "danger");
  nav.add(b5, ITEM_BUTTON, { on_change: _do_clear });

  u.fade_in(_opt_list, 5, 280, 40);
  u.fade_in(_sel_list, 5, 280, 120);

  _refresh_opt(true);
  _refresh_sel(true);
  _sync_switches();
  nav.paint();
  return scr;
}

// ══════════════════════════════════════════════════════════════════
//  刷新
// ══════════════════════════════════════════════════════════════════

/** 「可選」← `PeerRegistry.snapshot()`（任何總線上的節點都算）。
 *
 * ★ 只有帶 `mac` 的才進得來 —— 射頻 peer 表是 MAC 索引的，
 *   沒有 MAC 的節點（例如只從 UDP 聽到的）在這裡沒有意義。
 */
function _refresh_opt(force = false) {
  const reg = _kv().get_service("peers");
  let rows = [];
  if (reg !== null) {
    try {
      rows = (reg.snapshot() || []).filter((r) => r.get("mac"));
    } catch (e) {
      rows = [];
    }
  }
  const macs = rows.map((r) => String(r["mac"]).toUpperCase());
  let labels = rows.map((r, i) => `${_short(macs[i])}  ${_cid_txt(r)}`);
  if (!labels.length) {
    labels = ["(按掃描)"];
  }
  if (!force && _same(labels, _last["opt"])) {
    _opt_rows = macs;
    return;
  }
  _last["opt"] = labels;
  _opt_rows = macs;
  _opt_btns = _fill(_opt_list, labels);
  _oi = Math.max(0, Math.min(_oi, Math.max(0, _opt_btns.length - 1)));
  if (_opt_btns.length) {
    u.list_select(_opt_btns, _oi, u.PRIMARY);
  }
  _set("optn", `(${macs.length})`);
}

/** 「已選」← `@now.selected` ＋ FF 墊底。
 *
 * ★ FF 與具體節點**互斥**（使用者定案）：有節點 → FF 退下；
 *   節點全移除 → FF 自動回來。見檔頭。
 */
function _refresh_sel(force = false) {
  const labels = !_sel_macs.length
    ? ["FF  廣播  ←預設"]
    : _sel_macs.map((m) => String(_short(m)));
  if (!force && _same(labels, _last["sel"])) {
    return;
  }
  _last["sel"] = labels;
  _sel_btns = _fill(_sel_list, labels);
  _si = Math.max(0, Math.min(_si, Math.max(0, _sel_btns.length - 1)));
  if (_sel_btns.length) {
    u.list_select(_sel_btns, _si, u.PRIMARY);
  }
  const over = _sel_macs.length > _cap();
  _set("seln", `(${_sel_macs.length}/${_cap()})${over ? " 超標!" : _dirty ? " *" : ""}`);
}

/** 單向同步（服務 → UI）：UI 只是顯示器，狀態來源是服務/設定。
 *
 * 不這樣做的話，頁面會顯示「上次點擊的狀態」而不是實際狀態 ——
 * 最常見的就是「旗標 = 0 → on_now_init 拒絕開」時開關還停在 ON（騙人）。
 */
function _sync_switches() {
  try {
    const on = _radio_on();
    if (u.sw_get(_sw_on) !== on) {
      u.sw_set(_sw_on, on);
    }
  } catch (e) {
    /* 服務不在就先不動開關 */
  }
  const st = _kv().shared.get("now_setting") || dict();
  const now = _now();
  let enc;
  try {
    enc = now !== null ? Boolean(now.encrypt) : Boolean(st.get("encrypt"));
  } catch (e) {
    enc = Boolean(st.get("encrypt"));
  }
  try {
    if (u.sw_get(_sw_enc) !== enc) {
      u.sw_set(_sw_enc, enc);
    }
  } catch (e) {
    /* 同上 */
  }
  const ch = _channel();
  _set("ch", ch !== null ? `ch${ch}` : "ch—");
  _set("cap", `${_cap()}格`);
  _set("flag", _flag_on() ? "授權" : "未授權");
}

/** 每幀被 app 呼叫。只每 REFRESH_EVERY 幀做一次。 */
export function update(run) {
  if (run % REFRESH_EVERY) {
    return;
  }
  _refresh_opt();
  // 使用者改過但還沒套用 → 不要用 DB 蓋掉他的編輯
  if (!_dirty) {
    const st = _kv().shared.get("now_setting") || dict();
    const cur = (st.get("selected") || []).map((x) => String(x).toUpperCase());
    if (cur.length && !_same(cur, _sel_macs)) {
      _sel_macs = cur;
      _refresh_sel(true);
    }
  }
  _sync_switches();
}

// ══════════════════════════════════════════════════════════════════
//  頁面接口（app.py 呼叫）
// ══════════════════════════════════════════════════════════════════

export function on_enter() {
  _refresh_opt(true);
  _refresh_sel(true);
  _sync_switches();
}

export function on_leave() {}

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
