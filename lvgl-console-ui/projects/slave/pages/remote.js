// projects/slave/pages/remote.js — 遙控器頁（橫屏 320×240）
//
// 對應 ui/lvgl/page/remote.py
//
// 角色：面板是**遙控器** —— 只發指令，不自己執行
//       （ports/S3/ESP32-S3-Control_Panel_V2/README.md）。
//
// 版面：
//   左欄 節點清單（可捲）——「選中 = 操作對象」
//   右欄 身份（cID/MAC/目標）+ 模式表（source / 前幾筆）+ 選中節點細節
//   底列 [掃描][綁定][解除][取得清單][取得細節]
//
// ★ 2026-10（使用者定案）：**晶片開關已從本頁移除**。
//   本頁是**應用層**（我要操作誰、播什麼），開關是**傳輸層**（射頻怎麼出去），
//   兩層的數量限制與持久化位置都不同，混在一頁會讓「這清單在限制什麼」說不清：
//     Wi-Fi 開關    → settings.py（系統設定）已經有一顆，本頁那份是**重複的**
//     ESP-NOW 開關  → 搬到新頁 now_setting.py（傳輸層設定）
//   舊版把兩顆開關擺在 (10,224) / (168,224)、標籤擺在 x=34 / 192 ——
//   但 mk_switch 是 **44×24**，所以標籤正好**壓在開關上面**；
//   而且 y=224+24=248 早就超出 240 高的螢幕，下緣被切掉。
//   移除後底列空出來的 42px 還給了左欄清單與 c3 面板。
//
// 資料全部來自既有狀態（**本頁不自己維護任何狀態**）：
//   bus.shared["peers"]       ← PeerRegistry.snapshot()（第一個消費者）
//   bus.shared["node"]        ← ConfigManager.publish_node()（身份/角色/目標）
//   bus.shared["mode_table"]  ← ConfigManager.publish_modes()（儲存模式/清單）
//   bus.get_service("disp")   ← P3 註冊的指令接口（exec_cmd / make_cmd）
//
// 動作 → 全部走指令（沒有直接改狀態、沒有直接碰硬體）：
//   掃描        make_cmd(0x100D) → **廣播**（還不認識任何人，只能對所有人講話）
//   綁定/解除   exec_cmd(0x1016) → 方向確認（handler 負責持久化）
//   取得清單    make_cmd(0x3101) → 定向
//   取得細節    make_cmd(0x3107) → 定向（逐一，節流由接收端處理）
//
// ★ 廣播 vs 定向的判準：
//     「不認識對方」→ 廣播（掃描）。「已經認識」→ 定向（其餘全部）。
//   掃描是唯一「廣播出去、單播回來」的動作：回覆走 NowBus.write()，
//   也就是射頻層回給**剛剛講話的那個人**，不是回給 NC4 header 裡的 addr。
//   ⚠ 所以「廣播不回」不等於「廣播沒回覆」—— 這兩件事容易混淆。
//
// ★ 發射路徑（2026-10 定案）：**本頁不碰實體管子、不碰 MAC**。
//   兩個入口要分流：
//     ① 內部執行 → disp.exec_cmd(...)（不經 Router，保證不外送）
//     ② 對外發出 → 產生幀（含 addr）→ vbus.inject(frame) → Router 決定走哪條管子
//   舊版直接 now.add_peer(mac) / now.write_to(mac, frame) / now.broadcast(frame)
//   —— 那是把 ESP-NOW 的實作細節寫進 UI，換一條管子就不能用（已移除）。
//
// ⚠ 缺少 API / 模擬器差異：
//   - lv.list.clean() 只刪 children、沒有清 List 內部的 _items（真機 LVGL 會清乾淨）
//     → 已補 `_peer_list._items.length = 0`；不補的話重進頁面每一列會被往下推。
//   - mocks 的 cfg_manager 沒有 save_node()（真機在綁定/解除後落盤）
//     → 已用 typeof 守衛，沒有就跳過。
//   - lv.js 的 list item 預設 bg_opa=0（真機主題是 COVER）→ _sync_list 補
//     set_style_bg_opa(255)，否則「選中底色」完全看不到。
//   - bus.cid / bus.targets / bus.role 在模擬器是 Bus 實例上的動態屬性（類別沒有），
//     讀不到時用 0xFFFF / [] / null 當預設，跟真機 getattr 的預設一致。

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
// 本頁已無開關 → 不需要 ITEM_SWITCH。
import { Nav, ITEM_LIST, ITEM_BUTTON } from "@packages/lv-app/nav.js";
import { bus, dict, cfg_manager, get_vbus } from "../mocks.js";

export const meta = { id: "remote", title: "遙控器", icon: "wifi",
                      desc: "配對·節點·模式", order: 4, accent: 0x188038 };

const REFRESH_EVERY = 10;       // 每 N 幀刷新一次顯示（run % N）
const SCAN_SPREAD_MS = 500;     // 掃描的抖動視窗（0 = 不抖動）。見 _do_scan
// ★ RECENT_MS / STALE_MS 已**不再用來上色**（2026-10：時間衰減的顯示
//   結構不適合這裡，改成看「關係狀態」，見 _row_color）。
//   留著是因為 _peer_label 的除錯輸出還會參考，而且門檻值本身沒變。
const RECENT_MS = 10000;        // 多久內聽到算「剛見過」（除錯 / 未來用）
const STALE_MS = 60000;         // 多久沒聽到算「很久」（除錯 / 未來用）
let _scan_at = 0;               // 最後一次按「掃描」的 Date.now()（0 = 還沒掃過）
                                // ★ 這是「紅色」的判準：掃描過了卻沒回話 = 叫了不應

const SEL_BG = 0xd2e3fc;        // 選中列的底色（淺藍）—— 刻意不用 PRIMARY 的深藍，
                                // 否則狀態色（綠/黃/紅）在上面讀不出來
const BULLET = "\u25CF";        // ● —— ★ 這個字元**必須在字型子集裡**
                                //   （見 temp/gen_font.py 的 EXTRA 與 guide §6）
const MODE_ROWS = 4;            // 模式表顯示幾筆（行距 19 = u.ZH 行高）

const nav = new Nav();
export let scr = null;
let _peer_list = null;
let _peer_btns = [];
let _peer_rows = [];            // PeerRegistry.snapshot() 的內容（選中索引對應）
let _sel = 0;                   // 選中的節點索引
let _lb = {};                   // 顯示用 label 快取
let _last = {};                 // 內容比對（避免每幀 set_text）
let _btn_bind = null;

// ══════════════════════════════════════════════════════════════════
//  共用小工具
// ══════════════════════════════════════════════════════════════════

/** 取 bus（等同裝置的 from lib.sys.sys_bus import bus；mocks 轉出同一個實例）。 */
function _kv() {
  return bus;
}

/** cid 的顯示格式（Python 是 "0x{:04X}"）。 */
function _hex4(v) {
  return "0x" + (Math.trunc(Number(v)) & 0xffff).toString(16).toUpperCase().padStart(4, "0");
}

/** Python 的 list == list 是逐元素比較，JS 的 === 比參考。 */
function _same_list(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ══════════════════════════════════════════════════════════════════
//  發射（本頁只產生指令，不直呼 NowBus）
// ══════════════════════════════════════════════════════════════════

/**
 * handler 的 ctx。`app` 由 bus 服務取得（app.py 註冊）—— 不能傳 null，
 * 因為多個 handler（如 on_now_init）會 `if not ctx.get("app"): return`。
 */
function _ctx() {
  const b = _kv();
  return { app: b.get_service("app"), transport: "ui" };
}

/**
 * 取得 vBus（本機發起的注入點）。取不到回 null。
 * 實作在 lib/sys/sys_bus.get_vbus() —— 所有 UI 頁 / task 共用同一個查找順序。
 */
function _vbus() {
  return get_vbus();
}

/**
 * 產生一個指令並**本機發起**（注入 vBus → 走 Router）。回 true / false。
 *
 * ★ **本頁不碰實體管子、不碰 MAC**：
 *     UI 只做兩件事 —— 產生指令（含 addr）丟進 vBus；其餘由 Router 決定
 *     「執行 or 發射、走哪條管子」，由**管子自己**解析 addr 成實體位址。
 *   舊版直接呼叫 now.add_peer(mac) / now.write_to(mac, frame) /
 *   now.broadcast(frame) —— 那是把 ESP-NOW 的實作細節寫進 UI，換一條管子
 *   就不能用（todo/05 §3.1 記載的現況違反）。
 *
 * peer 為 null → addr = 0xFFFF（廣播；用途：掃描這種「不知道對象」的指令）
 * peer 是 dict → addr = 對方 cid（定向）
 *
 * ⚠ 走 Router 的前提是 config.json 的 Router.routes 有
 *   { "in": "self", "out": ["now"] }（面板 config 已經有了）。
 *   Router enable=0 時 gate() 直接回 V_OK → 幀仍然照原路徑進來解碼，
 *   所以**不轉發**（＝發不出去）—— 這一點由 §12 真機清單第 7 項驗證。
 */
function _tx(cmd, args, peer = null) {
  const b = _kv();
  const disp = b.get_service("disp");
  if (disp === null || disp === undefined) {
    print("[remote] 無 disp 服務 → 無法發射");
    return false;
  }
  let addr = 0xffff;
  if (peer) {
    const cid = peer.get("cid");
    if (cid !== null && cid !== undefined) addr = Math.trunc(Number(cid)) & 0xffff;
  }
  const frame = disp.make_cmd(cmd, args, addr);
  if (frame === null || frame === undefined) return false;
  const vb = _vbus();
  if (vb === null || vb === undefined) {
    print("[remote] 無 vBus → 無法發射");
    return false;
  }
  // make_cmd 回的是共享 buffer 的 view（下一次 pack 就覆蓋）→ inject 立即消費 ✓
  return Boolean(vb.inject(frame));
}

/** 目前選中的節點（沒有回 null）。 */
function _selected() {
  if (_sel >= 0 && _sel < _peer_rows.length) return _peer_rows[_sel];
  return null;
}

/**
 * **內部執行**一個指令（走 disp.exec_cmd —— 不經 Router、保證不外送）。
 *
 * ★ 這是「兩個入口」的另一半：
 *     _exec() = 「我呼叫一個函式」（args 已是 dict，不經編解碼）
 *     _tx()   = 「我發起一幀」（經 Router，可能被轉發出去）
 *   app.py header 明說「兩者場合不同，不要混用」。
 */
function _exec(cmd, args) {
  const b = _kv();
  const disp = b.get_service("disp");
  if (disp === null || disp === undefined) return false;
  return disp.exec_cmd(cmd, args, _ctx());
}

// ══════════════════════════════════════════════════════════════════
//  動作（全部走指令）
// ══════════════════════════════════════════════════════════════════

/**
 * 0x100D IDENTIFY_REQ（廣播）—— 回覆會自動被 PeerRegistry 登記。
 *
 * 為什麼是**廣播**（而不是先想辦法定向）：掃描的定義就是「我還不認識任何人」。
 * ESP-NOW 的位址是 MAC，**無法枚舉** → 沒有「掃一遍位址空間」這種事，
 * 只能廣播出去、讓願意回話的對端回話。
 *
 * 為什麼回得來：對端的回覆走 NowBus.write() =「射頻層回給剛剛講話的人」，
 * 所以是**單播**回本板（不是廣播）。前提是對端在收幀時學到了本板的 MAC
 * ——NowBus.poll() 的 learn_peer()，兩端對稱。
 *
 * 副作用：**沒有**（2026-10 修正）。掃描只問「你是誰」，**不改方向**。
 * 以前 on_identify_req 會把 reply_cid 記成 master_cid，所以一次廣播
 * 掃描 = 射程內**所有**對端都把本板認成 master（無聲搶奪：第二台遙控器
 * 只要按一下掃描就搶走全部，第一台完全不知道）。那個寫入已移除 ——
 * 方向只由「綁定」的 0x1016 決定。
 *
 * ★ timeout_ms = SCAN_SPREAD_MS（2026-10 新增）：**抖動視窗**。
 *   廣播點名會讓射程內所有對端在**同一瞬間**回話 —— 在 ESP-NOW 空中／
 *   RS485 匯流排上是**硬碰撞**，會整批掉。帶上這個值，各對端會各自隨機
 *   延遲 [0, timeout_ms] 才回，把「同時」攤成「序列」。
 *   **0 或缺席 = 不抖動**（舊對端的行為）→ 追加欄位，向後相容。
 *   真的被撞掉的節點：**再按一次掃描**即可（不做自動重試）。
 */
function _do_scan() {
  const b = _kv();
  const ok = _tx(0x100d, {
    reply_cid: Math.trunc(Number(b.cid ?? 0xffff)) & 0xffff,
    timeout_ms: SCAN_SPREAD_MS,
  });
  if (ok) {
    // ★ 記下「我什麼時候問的」——清單的紅色靠它判斷「叫了不應」。
    //   沒送出去就不記，否則會把全部節點誤標成紅。
    _scan_at = Date.now();
  }
  print("[remote] 掃描 →", ok);
}

/**
 * 把選中的節點綁定為目標（**本板是控制方**）。
 *
 * ★ 方向很重要 —— 0x1016 SET_MASTER 有兩種用法：
 *     我**發**它（payload = 我的 cid）→ 告訴對方「你的 master 是我」
 *     我**收**它（payload = 對方 cid）→ 我把對方當上級（action handler 處理，role=slave）
 *   面板是遙控器 → 這裡走**發**的那一邊。
 *
 * 兩步（2026-10 起；通道建立已自動化）：
 *   ① 方向：發 SET_MASTER(我的 cid) 告訴對方回覆要回給我
 *   ② 本地：把節點記進 @node.targets 並設 active（master_cid 不動 —— 那是「我的上級」）
 *
 * ★ 原本還有一步「配對：now.add_peer(p["mac"]) 建立通道」——
 *   那是**傳輸層的實作細節**（ESP-NOW 才需要 add_peer），已從 UI 移除：
 *   幀走 vBus → Router → 射頻管，由 NowBus **自己**在送出前確保通道。
 */
function _do_bind() {
  const b = _kv();
  const p = _selected();
  if (p === null) {
    print("[remote] 沒有選中的節點");
    return;
  }
  const cid = p.get("cid");
  if (cid === null || cid === undefined) {
    // ★ 舊版這裡**靜默 return** —— 畫面上完全沒反應，看起來像「綁定沒用」。
    //   會走到這裡通常是：這筆是從 0x1002 公告學到的（公告不帶 cid），
    //   而掃描的回覆（0x100E）還沒到，或那台根本沒回。
    //   → 明確告訴使用者「先掃描」，而且清單會是紅的。
    print(
      `[remote] 綁定失敗：${String(p.get("slave_id") || "").slice(-6) || "?"} 還沒有 cid` +
        " —— 先按「掃描」讓它回 0x100E"
    );
    return;
  }
  // ① 方向：告訴對方「你的 master 是我」
  const my_cid = Math.trunc(Number(b.cid ?? 0xffff)) & 0xffff;
  _tx(0x1016, { master_cid: my_cid }, p);
  // ③ 本地：記住目標（active = 當前發射對象）
  //   ★ **只存 cid**（2026-10）：cid 是協議層的定址鍵（發射時填幀頭 addr），
  //     射頻層的 MAC 由 PeerRegistry.by_cid() 查 —— **單一事實**，
  //     與 sys_bus.py / ConfigManager.py 原本就寫明的設計一致。
  //     額外好處：cid 撞號時不會有兩份互相矛盾的 MAC。
  const tgt = dict({
    cid: Math.trunc(Number(cid)) & 0xffff,
    name: String(p.get("name") || "").trim() || String(p.get("slave_id") || "").slice(-6),
    active: true,
  });
  const targets = (b.targets || []).filter((t) => t.get("cid") !== tgt["cid"]);
  for (const t of targets) t["active"] = false;
  targets.push(tgt);
  b.targets = targets;
  b.role = "master";
  try {
    // ⚠ mocks 沒有 save_node()：真機這裡會把 node.role / node.targets 寫回 btree。
    if (typeof cfg_manager.save_node === "function") cfg_manager.save_node();
  } catch (e) {
    print("[remote] 綁定持久化失敗:", e);
  }
  print(`[remote] 綁定 ${_hex4(tgt["cid"])}（已告知方向 + 記入 targets）`);
}

/**
 * 從 targets 移除選中的節點；沒有目標了就回到未定。
 *
 * ★ **雙邊一致（2026-10）**：配對是**兩邊的狀態** —— 本機的 @node.targets
 *   與對方的 master_cid。只改本機的話，對方會永遠把回應送給一台已經不要它
 *   的主控。
 *   所以移除前先對每一台被解除的對象發 0x1016{master_cid: 0xFFFF} = **解除**
 *   （見 net_actions.on_set_master：解除會清對方的 master_cid/master_mac/role
 *     並**重新開放認領**，所以它不必等重開機就能被新主控接手）。
 */
function _do_unbind() {
  const b = _kv();
  const p = _selected();
  const old_targets = [...(b.targets || [])];
  let cur = [...old_targets];
  if (!cur.length) {
    print("[remote] 目前沒有目標");
    return;
  }
  if (p !== null && p.get("cid") !== null && p.get("cid") !== undefined) {
    const cid = Math.trunc(Number(p.get("cid"))) & 0xffff;
    let next = cur.filter((t) => t.get("cid") !== cid);
    if (next.length === cur.length) {
      // 選中的節點不是目標 → 退而解除「目前 active」那一個（比較符合直覺）
      next = cur.filter((t) => !t.get("active"));
      print("[remote] 選中的不是目標 → 解除目前 active");
    }
    cur = next;
  } else {
    cur = []; // 沒選中 → 全部清掉
  }

  // ① 先通知每一個「被解除」的對方（用 cid 集合比對 —— 不要用 `t not in cur`，
  //   dict 的 `in` 是逐值相等，兩個 target 內容剛好相同時會漏判；cid 才是身分）
  const kept = new Set(cur.map((t) => Math.trunc(Number(t.get("cid") || 0)) & 0xffff));
  const removed = old_targets.filter(
    (t) => !kept.has(Math.trunc(Number(t.get("cid") || 0)) & 0xffff)
  );
  for (const t of removed) {
    const ok = _tx(0x1016, { master_cid: 0xffff }, t);
    print(`[remote] 解除通知 ${_hex4(t.get("cid") || 0)} → ${ok}`);
  }

  // ② 再改本機
  if (cur.length && !cur.some((t) => t.get("active"))) {
    cur[0]["active"] = true; // 至少留一個 active
  }
  b.targets = cur;
  b.role = cur.length ? "master" : null;
  try {
    if (typeof cfg_manager.save_node === "function") cfg_manager.save_node();
  } catch (e) {
    /* 跟裝置一樣：持久化失敗不影響 UI */
  }
  print(`[remote] 解除綁定 → 剩 ${cur.length} 個目標`);
}

/** 0x3101 MODE_LIST_QUERY（定向給選中的節點）→ 0x3102 寫入模式表。 */
function _do_fetch_list() {
  const p = _selected();
  if (p === null) {
    print("[remote] 沒有選中的節點 → 無法查詢");
    return;
  }
  print("[remote] 取得模式清單 →", _tx(0x3101, { mode_type: 0 }, p));
}

/**
 * 0x3107 MODE_DETAIL_QUERY（逐一，定向）→ 0x3108 寫入模式表。
 *
 * 逐一發射；落盤由接收端節流處理（見 ConfigManager.flush_modes）。
 */
function _do_fetch_details() {
  const p = _selected();
  if (p === null) {
    print("[remote] 沒有選中的節點 → 無法查詢");
    return;
  }
  const b = _kv();
  const tbl = b.shared.get("mode_table") || dict();
  const ids = (tbl.get("entries") || []).map((e) => e["id"]);
  if (!ids.length) {
    print("[remote] 模式表是空的 → 先取得清單");
    return;
  }
  let ok = 0;
  for (const mid of ids) {
    if (_tx(0x3107, { mode_type: (mid >> 8) & 0xff, mode_id: mid & 0xff }, p)) ok += 1;
  }
  print(`[remote] 取得細節 ${ok}/${ids.length}`);
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
  c.remove_flag(lv.obj.FLAG.SCROLLABLE);
  return c;
}

export function build() {
  nav.reset();
  _sel = 0;
  _lb = {};
  _last = {};
  _peer_rows = [];

  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);

  u.mk_label(scr, "遙控器", 8, 5, u.TEXT, u.ZH);

  // ── 左欄：節點清單（選中 = 操作對象）──
  //   ★ 2026-10（使用者定案）：「在線/離線」不再用右邊的文字講，
  //     改成**這一欄每一行自己的顏色**（綠=剛聽到 / 黃=有點久 / 紅=很久沒聽到）。
  //     理由：右邊那格一次只能講**一個**節點，清單有兩台以上就看不到了；
  //     而且那格很貴（要吃掉模式表的空間）。
  const lx = 4;
  const lw = 124;
  [_peer_list, _peer_btns] = u.mk_list(scr, lx, 24, lw, 184, ["(尚無節點)"], u.ZH);
  nav.add(_peer_list, ITEM_LIST, { on_change: _on_list_move });

  // ── 右欄上：身份 ──
  //   ★★ 行高**實測**：u.ZH = **19px**、F_NUM_S = 16px。
  //      （不是「中文字 16px 寬」那個數字 —— 那是字寬，行高是 19。）
  //      上一版把標籤從 F_NUM_S 換成 u.ZH 卻沒改行距（還是 y=45、面板 h=58），
  //      於是「目標」那一行底端 45+19=64 > 58 → **下緣被框架切掉**（使用者回報）。
  //   ★ 現在把「目標」搬到標題列（同一行右半），省下一整行 19px。
  const rx = lx + lw + 6;
  const rw = u.W - 4 - rx;
  const c1 = _panel(scr, rx, 24, rw, 56);
  u.mk_label(c1, "身份", 6, 2, u.TEXT3, u.ZH); // 2..21
  _lb["dst"] = u.mk_label(c1, "—", 44, 2, u.PRIMARY, u.ZH);
  _lb["cid"] = u.mk_label(c1, "—", 6, 22, u.TEXT, u.F_NUM_S); // 22..38
  _lb["mac"] = u.mk_label(c1, "—", 6, 38, u.TEXT2, u.F_NUM_S); // 38..54 ≤ 56 ✓

  // ── 右欄中：選中節點（一行）──
  //   ★ 用 u.ZH：沒選取時顯示「選一個節點」，那是中文。
  //     1 行 19px + 邊距 → h=22。
  const c3 = _panel(scr, rx, 86, rw, 22);
  _lb["sel"] = u.mk_label(c3, "選一個節點", 6, 2, u.TEXT3, u.ZH);

  // ── 右欄下：模式表 ──
  //   行距 **19**（= u.ZH 行高）。4 列：19 / 38 / 57 / 76，最後一列底 95 ≤ 96 ✓
  //   （想在這裡塞更多列，就得把中文字型換成 12px 版本）
  const c2 = _panel(scr, rx, 114, rw, 96);
  _lb["msrc"] = u.mk_label(c2, "模式 —", 6, 2, u.TEXT3, u.ZH);
  for (let i = 0; i < 4; i++) {
    _lb[`m${i}`] = u.mk_label(c2, "", 6, 19 + i * 19, u.TEXT2, u.ZH);
  }

  // ── 底列：動作按鈕（5 顆）──
  //   y 從 198 → 210：晶片開關（原本 224 起、還被切掉 8px）移除後往下挪，
  //   清單 24..206、c2 到 206 → 按鈕下移到 212（212+22=234 ≤ 240）。
  const bw = 60;
  const gap = 3;
  const bx = 4;
  const y = 212;
  const b1 = u.mk_btn(scr, "掃描", bx, y, bw, 22, "primary");
  nav.add(b1, ITEM_BUTTON, { on_change: _do_scan });
  _btn_bind = u.mk_btn(scr, "綁定", bx + (bw + gap), y, bw, 22, "secondary");
  nav.add(_btn_bind, ITEM_BUTTON, { on_change: _do_bind });
  const b3 = u.mk_btn(scr, "解除", bx + 2 * (bw + gap), y, bw, 22, "secondary");
  nav.add(b3, ITEM_BUTTON, { on_change: _do_unbind });
  const b4 = u.mk_btn(scr, "取清單", bx + 3 * (bw + gap), y, bw, 22, "secondary");
  nav.add(b4, ITEM_BUTTON, { on_change: _do_fetch_list });
  const b5 = u.mk_btn(scr, "取細節", bx + 4 * (bw + gap), y, bw, 22, "secondary");
  nav.add(b5, ITEM_BUTTON, { on_change: _do_fetch_details });

  // ★ 這裡原本有兩顆晶片開關（Wi-Fi / ESP-NOW）。
  //   已移除：Wi-Fi 那份與 settings.py 重複；ESP-NOW 搬到 now_setting.py。
  //   原因與當年的排版 bug 記在本檔開頭的檔頭註解。

  u.fade_in(_peer_list, 5, 280, 40);
  u.fade_in(c1, 5, 280, 120);
  u.fade_in(c2, 5, 280, 200);

  _refresh_peers(true);
  _refresh_info();
  nav.paint();
  return scr;
}

// ══════════════════════════════════════════════════════════════════
//  刷新
// ══════════════════════════════════════════════════════════════════

/** 這一筆是不是我認的目標（在 @node.targets 裡）。 */
function _is_target(r) {
  const node = _kv().shared.get("node") || dict();
  const cid = r.get("cid");
  const sid = String(r.get("slave_id") || "").toUpperCase();
  for (const t of node.get("targets") || []) {
    const tc = t.get("cid");
    if (cid !== null && cid !== undefined && tc !== null && tc !== undefined) {
      // 壞值就跳過（Python 是 try/except int()）
      if (Math.trunc(Number(tc)) === Math.trunc(Number(cid))) return true;
    }
    if (sid && String(t.get("slave_id") || "").toUpperCase() === sid) return true;
  }
  return false;
}

/**
 * 列的顏色 = **關係狀態**，不是時間。
 *
 * ★ 使用者 2026-10 定案：舊版拿 age_ms 做綠→黃→紅的**時間衰減**，
 *   那個結構不適合表達這裡要講的事。
 *
 * 為什麼時間衰減不對：
 *   「掃描成功」建立的是一個**關係**（我知道你是誰、你在哪個 MAC），
 *   那個關係不會因為 10 秒過去就失效。用 age 上色會變成
 *   「按掃描 → 綠 → 幾秒後自己變琥珀 → 再變紅」，
 *   看的人只會困惑：我又沒做什麼，它為什麼變了？
 *   （而且對端只是**沒有再講話**，不代表它離線。）
 *
 * 所以改成問「**我跟它是什麼關係**」——三個狀態都是**穩定**的，
 * 只在使用者真的改變關係時才變：
 *
 *     綠   SUCCESS  = 我認的目標（在 @node.targets 裡）
 *     琥珀 WARNING  = 這次開機見過它，但還沒綁
 *     灰   TEXT3    = 只有歷史記錄（從 DB 還原），這次開機還沒見到
 *
 * 變色的時機因此只有兩個：**掃描到它**（灰→琥珀）、**綁定它**（琥珀→綠）。
 * 兩個都是使用者自己造成的動作。
 */
function _row_color(r) {
  if (_is_target(r)) return u.SUCCESS; // 綠：我認的目標
  const age = r.get("age_ms");
  if (!_scan_at) {
    // 還沒按過掃描 → 我還沒問過，不知道它在不在
    return age !== null && age !== undefined ? u.WARNING : u.TEXT3;
  }
  // ★ 掃描過了：看它有沒有在**這一次**掃描之後回話。
  //   age_ms = 距離上次收到它的毫秒數；since = 距離我按下掃描的毫秒數。
  //   回話發生在掃描之後 → age < since。
  //   （age_ms 本身是「黏」的 —— 一旦見過就永遠有值，所以不能只看它有沒有值。）
  const since = Date.now() - _scan_at;
  if (age !== null && age !== undefined && age <= since) {
    return u.WARNING; // 琥珀：這次掃到了
  }
  return u.DANGER; // ★ 紅：叫了，它不應
}

/**
 * 節點清單的一行：`● 0x0002 test-peer`。
 *
 * ★ ● 只在**重新生成過的字型**裡有（見 doc/02_guides/06_lvgl_ui.md §6 與
 *   temp/gen_font.py 的 EXTRA）。舊字型沒有 ● → 會變空格子，
 *   所以那時候這裡用的是 ASCII 的 `*`。換回 ● 時務必確認字型已經重生成。
 */
function _peer_label(r) {
  const cid = r.get("cid");
  const cs = cid !== null && cid !== undefined ? _hex4(cid) : "-----";
  const nm =
    String(r.get("name") || "").trim() || String(r.get("slave_id") || "").slice(-6);
  return `${BULLET} ${cs} ${nm}`;
}

/** 從 PeerRegistry.snapshot() 重建清單（內容有變才動 widget）。 */
function _refresh_peers(force = false) {
  const b = _kv();
  const reg = b.get_service("peers");
  let rows = [];
  if (reg !== null && reg !== undefined) {
    try {
      rows = reg.snapshot();
    } catch (e) {
      rows = [];
    }
  }
  const labels = rows.map((r) => _peer_label(r));
  if (!labels.length) labels.push("(尚無節點)");
  if (!force && _same_list(labels, _last["peers"])) {
    _peer_rows = rows;
    _sync_list(); // ★ 文字沒變不代表顏色沒變（age 一直在跑）
    return;
  }
  _last["peers"] = labels;
  _peer_rows = rows;
  try {
    _peer_list.clean();
  } catch (e) {
    /* 跟裝置一樣：清不掉就跳過，下一幀再試 */
  }
  // ⚠ lv.js 的 List.clean() 只刪 children，沒有同步清 List 內部的 _items。
  //   真機 LVGL 的 clean 會一起清掉；不補這行，重進頁面每一列都會被往下推。
  if (_peer_list._items) _peer_list._items.length = 0;
  _peer_btns = [];
  for (const txt of labels) {
    try {
      const btn = _peer_list.add_text(txt);
      if (u.ZH) btn.set_style_text_font(u.ZH, 0);
      _peer_btns.push(btn);
    } catch (e) {
      /* 單一列失敗不拖垮整個清單 */
    }
  }
  _sel = Math.max(0, Math.min(_sel, Math.max(0, _peer_btns.length - 1)));
  _sync_list();
}

/**
 * 每一行的顏色 =「多久沒聽到它」。選中那一行再用底色標。
 *
 * ★ 不用 u.list_select()：它會**同時**設底色與文字色，會把狀態色蓋掉。
 *   這裡拆開 —— 底色管「選中」，文字色管「在線狀態」，兩件事互不干擾。
 *
 * ★ 一定要**每次都做**（不能只在文字變了才做）：age_ms 一直在跑，
 *   文字不變但顏色要從綠變黃再變紅。
 */
function _sync_list() {
  const n = _peer_btns.length;
  for (let i = 0; i < n; i++) {
    const b = _peer_btns[i];
    const r = i < _peer_rows.length ? _peer_rows[i] : null;
    const sel = i === _sel;
    try {
      // ★★ 文字色**永遠**是狀態色（綠/黃/紅），選中只用**底色**標。
      //   舊版選中時把文字改成白色 → 使用者回報「藍底灰字，看不出狀態」。
      //   改成淺藍底之後，三個狀態色在底色上都還讀得出來。
      b.set_style_bg_color(u.C(sel ? SEL_BG : u.BG), 0);
      // ⚠ 真機 list item 的 bg_opa 來自主題（COVER）；lv.js 的 ListBtn 預設 0，
      //   只設顏色不會顯示 → 這裡補上，否則「選中」完全看不到。
      b.set_style_bg_opa(255, 0);
      b.set_style_text_color(u.C(_row_color(r || dict())), 0);
    } catch (e) {
      /* 單列樣式失敗不影響其他列 */
    }
  }
}

/** 只有在文字變了才 set_text（省 LVGL 重繪）。 */
function _set(key, txt, color = null) {
  if (_last[key] === txt) return;
  _last[key] = txt;
  const lb = _lb[key];
  if (lb === null || lb === undefined) return;
  try {
    lb.set_text(txt);
    if (color !== null && color !== undefined) lb.set_style_text_color(u.C(color), 0);
  } catch (e) {
    /* label 被刪掉也不影響其他欄位 */
  }
}

function _refresh_info() {
  const b = _kv();
  const node = b.shared.get("node") || dict();
  // 身份
  const cid = node.get("cid");
  const mac = String(node.get("mac") || "").slice(-12);
  const now = b.get_service("NowBus");
  let ch = null;
  try {
    ch = now !== null && now !== undefined ? now._channel() : null;
  } catch (e) {
    ch = null;
  }
  //   ★ 晶片狀態放這一行（本頁只顯示、不控制）：ch6 = ESP-NOW 開著且在 ch6。
  //     關掉時顯示 ESP-NOW OFF（開關在 now_setting.py；Wi-Fi 在 settings.py）。
  _set(
    "cid",
    `cID ${cid !== null && cid !== undefined ? _hex4(cid) : "—"}  ` +
      `${_now_is_on() && ch !== null && ch !== undefined ? `ch${ch}` : "ESP-NOW OFF"}`
  );
  // ★ Wi-Fi 狀態**不再顯示在本頁**（2026-10 使用者定案）。
  //   兩個理由：
  //     ① 它是**傳輸層**的事，本頁是應用層（傳輸層設定在 settings.py /
  //        now_setting.py）。上一輪把開關搬走時漏了這個唯讀指示。
  //     ② 它讓這一行變成 `MAC 24EC4A2C65B8  Wi-Fi OFF`（27 字 ≈ 189px），
  //        而 c1 面板只有 182px → **超出框架**（使用者回報）。
  _set("mac", `MAC ${mac || "—"}`);
  // 目標：目前 active 的那一筆（targets 是清單；master_cid 是「我的上級」，不同事）
  const tgts = node.get("targets") || [];
  let act = null;
  for (const t of tgts) {
    if (t.get("active")) {
      act = t;
      break;
    }
  }
  if (act === null && tgts.length) act = tgts[0];
  //   ★ 這一行現在住在 c1 的**標題列右半**（x=44，跟「身份」同一行）。
  //     空間只有 182-44 = 138px ≈ 17 個半形字，所以刻意精簡：
  //     「目標 0x0001 1/1」= 2 中文(32) + 11 半形(88) = 120 ✓
  if (act !== null) {
    _set(
      "dst",
      `目標 ${_hex4(act.get("cid") || 0)} ${tgts.indexOf(act) + 1}/${tgts.length}`
    );
  } else {
    _set("dst", "目標 未綁定");
  }
  // 選中節點 —— **只剩一行**（2026-10 使用者定案）。
  //   ★ 舊版把「最後 Nms 前 ●在線」寫在這裡，但那一格一次只能講一個節點，
  //     清單有兩台以上就看不到其他人的狀態；而且它吃掉模式表的空間。
  //     現在狀態改用**左欄每一行的顏色**表示（見 _row_color / _sync_list），
  //     這裡只回答「我選了誰」。
  //   ★ 使用者要的是「**ID ＋ address ＋ 連接方法**都要看得到」。
  //     c3 只有 182px 寬、一行，所以精簡成 3 欄：
  //       0x0002  2C65B8  NOW-Bus
  //       └ cid   └ address(後 6 碼)  └ 走哪條管子
  //     全形中文會把寬度吃光 → 這一行刻意**全用 ASCII**（含「未選取」也一樣），
  //     這樣用 u.ZH 或 F_NUM_S 都不會出現方格。
  const p = _selected();
  if (p === null) {
    _set("sel", "-- 未選取 --");
  } else {
    const ifaces = p.get("ifaces") || [];
    const ifc = ifaces.length ? ifaces : ["-"];
    _set(
      "sel",
      `${p.get("cid") !== null && p.get("cid") !== undefined ? _hex4(p.get("cid")) : "-----"}  ` +
        `${String(p.get("slave_id") || "").slice(-6) || "------"}  ` +
        `${String(ifc[0]).slice(0, 8)}`
    );
  }
  // 模式表
  const tbl = b.shared.get("mode_table") || dict();
  const src = tbl.get("source") || "—";
  const ents = tbl.get("entries") || [];
  _set("msrc", `模式 ${src} (${ents.length})`);
  //   3 筆 → **6 筆**（2026-10 使用者定案）：c3 從 3 行縮成 1 行之後，
  //   讓出來的高度全部給這裡。
  for (let i = 0; i < MODE_ROWS; i++) {
    if (i < ents.length) {
      const e = ents[i];
      _set(`m${i}`, `${e.get("hex", "")} ${e.get("name", "")}`);
    } else {
      _set(`m${i}`, "");
    }
  }
  // ★ 晶片開關的單向同步（wifi enable / NowBus.connected）已隨開關一起移除。
  //   那兩顆開關現在住在 settings.py（Wi-Fi）與 now_setting.py（ESP-NOW），
  //   同步邏輯跟著開關走 —— 留在這裡只會是沒有人呼叫的死碼。
}

/**
 * ESP-NOW 現在是不是真的開著（給頁面顯示用；**開關本身在 now_setting.py**）。
 *
 * ★ 判準是 connected，不是「服務存不存在」。
 *   0x1301 NOW_INIT{action:2} 關掉之後，NowBus 服務**仍然在 bus 上**
 *   （刻意的，見 now_actions.on_now_init）—— 只把 connected 變 false。
 *   所以用 now 存不存在判斷的話，關掉之後會誤報成 ON。
 */
function _now_is_on() {
  const now = _kv().get_service("NowBus");
  try {
    return Boolean(now !== null && now !== undefined && now.connected);
  } catch (e) {
    return false;
  }
}

// ══════════════════════════════════════════════════════════════════
//  頁面接口
// ══════════════════════════════════════════════════════════════════

/** 清單編輯態：encoder 移動 → 更新選中索引（nav 只把 delta 交給頁面）。 */
function _on_list_move(dd) {
  const n = _peer_btns.length;
  if (n) _sel = ((_sel + dd) % n + n) % n; // Python 的 % 恆為正，JS 不是
  _sync_list();
}

export function on_enter() {
  _refresh_peers(true);
  _refresh_info();
}

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

export function update(run) {
  if (run % REFRESH_EVERY !== 0) return;
  try {
    _refresh_peers();
    _refresh_info();
  } catch (e) {
    /* 跟裝置一樣：這一幀讀不到就跳過，不要讓 UI 掛掉 */
  }
}
