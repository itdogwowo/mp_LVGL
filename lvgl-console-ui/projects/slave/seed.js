// projects/slave/seed.js — 這塊板的「開機狀態」（bus.shared 的初始資料 + 假子系統）
//
// 真機上這些值由 boot / task / driver 寫入；模擬器沒有那些東西，所以在這裡補：
//   1. bus.shared 的資料（頁面唯一會讀的東西）
//   2. 板上其實存在的服務（peers / NowBus / disp）→ 見 mocks.install_services()
//   3. **假 action_task**：把頁面送出的 _display_cmd 套用到 _display_*
//      → pixel_controller 的倒數計時才看得到反應
//
// ⚠ 這支不會被轉換到真機（真機的這些東西都是真的）。

import { bus, dict, install_services } from "./mocks.js";

export function seed() {
  bus.shared.update({
    System: dict({
      hostname: "slave-01",
      master_IP: "192.168.4.1",
      master_port: 9000,
    }),
    Network: dict({
      wifi: dict({ enable: 0, ssid: "demo-ap" }),
      // ESP-NOW 授權旗標（不是射頻狀態；射頻狀態看 NowBus.connected）
      ESP_now: dict({ enable: 1 }),
    }),

    // 自己的身份（remote / now_setting 讀；形狀照 ConfigManager.publish_node()）
    node: dict({
      cid: 0x0001,
      mac: "24EC4A2C65B8",
      hostname: "slave-01",
      role: "master",
      master_cid: 0xffff,
      master_mac: null,
      bound: false,
      targets: [dict({ cid: 0x0002, name: "peer-a", active: true, slave_id: "AABBCCDDEEFF" })],
    }),

    // pixel_controller 的協議欄位（控制端送指令 / 被控制端回 echo）
    _display_mode: 0,
    _display_brightness: 18,
    _display_time: 90,
    _display_time_seq: 1,

    // now_setting 的持久狀態（對齊 ConfigManager.now_state()）
    now_setting: dict({ selected: [], encrypt: 0, pmk: "", lmk: "" }),

    // 模式表（remote 的「模式表」面板讀 source / entries）
    mode_table: dict({
      source: "ram",
      count: 3,
      entries: [
        dict({ id: 0x0101, hex: "0x0101", name: "Red" }),
        dict({ id: 0x0202, hex: "0x0202", name: "Green" }),
        dict({ id: 0x0303, hex: "0x0303", name: "Blue" }),
      ],
    }),
    peers: dict({}),
    pixel_maps: _pixel_maps(),
    pca9685: dict({}),
    _pca_actions: [],

    // pixel_lab：頁面自己會補 mode/active/hb/target/ch；這裡只放初始游標
    pixel_lab: dict({ active: 0, mode: "apa", index: 0, ch: 0, target: 0x70, target_bus: 0, hb: 0 }),

    // pixel_lab_view：三個 lab 頁共用的「目前效果」快照（沒有它只會停在「待機 / 0%」）
    pixel_lab_view: dict({
      mode: "apa",
      active: 1,
      busy: 0,
      io: "SPI1",
      count: 8,
      base_pct: 30,
      sel_pct: 80,
      // 16 條通道亮度（0..100）：前 8 條給值，後 8 條 0
      ch_pcts: [10, 20, 30, 40, 50, 60, 70, 80, 0, 0, 0, 0, 0, 0, 0, 0],
    }),
  });

  // Bus 實例上的動態屬性（真機由 ConfigManager 發布；頁面用 getattr 的預設值讀）
  bus.cid = 0x0001;
  bus.role = "master";
  bus.targets = [dict({ cid: 0x0002, name: "peer-a", active: true })];

  install_services();
  _fake_action_task();
  _fake_pixel_lab_task();
  return bus;
}

/**
 * 假 PixelLabTask：把 pixel_lab 的 mode/active 鏡射到 pixel_lab_view。
 *
 * 為什麼需要：三個 lab 頁都只在 `view.mode === 自己的模式` 時才更新晶片/亮度，
 * 而 view 是 **task 寫的**（真機由 PixelLabTask 發布）。模擬器沒有那個 task，
 * view.mode 會一直停在 seed 的舊值 → 頁面永遠走「還沒開始」分支（0%、灰格子）。
 * 這裡只做「鏡射 + io 名稱」，不碰頁面邏輯。
 */
function _fake_pixel_lab_task() {
  setInterval(() => {
    const st = bus.shared.get("pixel_lab");
    const v = bus.shared.get("pixel_lab_view");
    if (!st || !v || typeof v.get !== "function") return;
    const mode = st.get("mode") || "apa";
    v["mode"] = mode;
    v["active"] = st.get("active") || 0;
    v["busy"] = 0;
    v["io"] = mode === "pca" ? "I2C0" : "SPI1";
    // 實際接腳：PCA9685 走 I2C0（SDA=8 / SCL=9，見驅動的 init_i2c）
    v["pins"] = mode === "pca" ? "SDA 8 · SCL 9" : "MOSI 11 · SCK 12";
  }, 120);
}

/**
 * pixel_maps：pixel_controller 左欄的模式清單（PixelTask 載入的地圖）。
 *
 * ⚠️ key 一定要用 int（頁面用 0x3105 這種數字查）；用物件字面量會變字串 key，
 *    Dict 的 Map 查不到 → 清單會是空的。
 */
function _pixel_maps() {
  const m = dict({});
  m.set(0x3105, dict({ name: "流動" }));
  m.set(0x0200, dict({ name: "可動" }));
  m.set(0x0301, dict({ name: "呼吸" }));
  return m;
}

/**
 * 假 action_task_1：監看 bus.shared["_display_cmd"]，套用到 _display_*。
 * 裝置上是：_consume_display_cmd() → set_display_state() → UART → 寫回 echo。
 * 這裡只做「套用 + 寫回」，延遲 80ms（約 2 幀 50ms 的量級）。
 */
function _fake_action_task() {
  let last = null;
  setInterval(() => {
    const cmd = bus.shared.get("_display_cmd");
    if (!cmd || cmd === last) return;
    last = cmd;

    const mode = cmd.get("mode", null);
    const brightness = cmd.get("brightness", null);

    if (mode !== null) {
      bus.shared["_display_mode"] = mode;
      // 新的一幀 → seq +1（pixel_controller 靠它判斷「重新計時」）
      bus.shared["_display_time_seq"] = (bus.shared.get("_display_time_seq", 0) | 0) + 1;
    }
    if (brightness !== null) bus.shared["_display_brightness"] = brightness;
  }, 80);
}
