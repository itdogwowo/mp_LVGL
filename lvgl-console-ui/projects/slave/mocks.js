// projects/slave/mocks.js — 這台「模擬板」上沒有的子系統
//
// 裝置頁面會 import 幾個 lib.sys 的模組（ConfigManager / proto / get_vbus）。
// 複刻時不可能把整條系統搬進來，所以這裡給最小替身：
//
//   原則：**回 null / no-op，不假裝成功**。
//   - bus.get_service("pca9685_ctl") 回 null ⇒ 頁面走它原本的「沒有這顆硬體」分支
//     （那些分支在裝置上本來就存在，正好拿來驗證防禦路徑）
//   - 需要「看起來有東西」的，一律放在 seed.js 的 bus.shared（那才是 UI 讀的資料）

import { bus, dict } from "@packages/lv-app/bus.js";

export { bus, dict };

/** ConfigManager 的最小替身：頁面只用 get / set / save / now_state。 */
export const cfg_manager = {
  _m: new Map(),
  get(key, dflt = null) {
    return this._m.has(key) ? this._m.get(key) : (bus.shared.get(key, dflt) ?? dflt);
  },
  set(key, value) {
    this._m.set(key, value);
    bus.shared.set(key, value);
    return value;
  },
  save() {
    return true;
  },
  now_state() {
    return bus.shared.get("now_setting") || dict({ selected: [], encrypt: 0, pmk: "", lmk: "" });
  },
  save_now() {
    return this.save();
  },
  clear_now() {
    return true;
  },
};

/** 跨板通道（裝置上由 sys_bus 提供）：模擬器沒有第二塊板，一律 null。 */
export function get_vbus(..._args) {
  return null;
}

/**
 * 把「板上其實有的服務」裝進 bus。
 *
 * 為什麼要裝：頁面在沒有服務時會走防禦分支（永遠「未授權」「無控制器」），
 * 複刻就變成一片空白。這裡補最小的服務，讓 UI 有東西可顯示，
 * 但**不改協議**：值還是寫進 bus.shared，跟真機同一條路。
 */
export function install_services() {
  // PeerRegistry：ESP-NOW 掃到的節點（形狀照 peer_registry.snapshot()）
  bus.register_service("peers", {
    snapshot: () => [
      dict({
        slave_id: "A1B2C3D4E5F6",
        cid: 2,
        mac: "A1:B2:C3:D4:E5:F6",
        ip: "192.168.4.12",
        name: "node-02",
        age_ms: 1200,
        hits: 3,
        ifaces: ["now"],
      }),
      dict({
        slave_id: "112233445566",
        cid: 7,
        mac: "11:22:33:44:55:66",
        ip: "",
        name: "node-07",
        age_ms: 4800,
        hits: 1,
        ifaces: ["now"],
      }),
      dict({
        slave_id: "AABBCCDDEEFF",
        cid: null,
        mac: "AA:BB:CC:DD:EE:FF",
        ip: "",
        name: "",
        age_ms: 900,
        hits: 0,
        ifaces: ["now"],
      }),
    ],
  });

  // NowBus：射頻（連線、頻道、peer 表）
  const now = {
    connected: true,
    encrypt: false,
    peer_count: 0,
    _ch: 6,
    peer_cap() {
      return this.encrypt ? 6 : 19;
    },
    _channel() {
      return this._ch;
    },
    apply_peers(list) {
      this.peer_count = list.length;
      return [list.length, 0, 0];
    },
    set_encrypt(on) {
      this.encrypt = Boolean(on);
      return true;
    },
    clear_peers() {
      const n = this.peer_count;
      this.peer_count = 0;
      return n;
    },
    set_channel(ch) {
      this._ch = ch;
      return true;
    },
  };
  bus.register_service("NowBus", now);

  // disp：指令接口（掃描 / 開關 / 換頻道）
  bus.register_service("disp", {
    exec_cmd(_cmd) {
      return true;
    },
    make_cmd(...args) {
      return args;
    },
  });

  // pca9685_ctl：driver 建的控制表（pca9685 頁與 pixel_lab_pca 頁共用同一份）
  const mkPca = (init = 0) => ({
    buf: Array(16).fill(init),
    set_channel(ch, v) {
      this.buf[ch] = v;
    },
    show() {},
  });
  bus.register_service("pca9685_ctl", [
    dict({ i2c: 0, addr: 0x70, broadcast: true, online: true, boards: [0x40, 0x41], pca: mkPca() }),
    dict({ i2c: 0, addr: 0x40, broadcast: false, online: true, boards: [], pca: mkPca() }),
    dict({ i2c: 0, addr: 0x41, broadcast: false, online: false, boards: [], pca: mkPca(300) }),
  ]);

  // app：頁面只需要它能被取到
  bus.register_service("app", {});
  return bus;
}

/** lib.sys.proto.Proto 的最小替身（只實作頁面會用到的形狀）。 */
export const Proto = {
  pack(bytes) {
    return bytes;
  },
  unpack(bytes) {
    return bytes;
  },
  cmd(...args) {
    return args;
  },
};

export default { bus, dict, cfg_manager, get_vbus, Proto };
