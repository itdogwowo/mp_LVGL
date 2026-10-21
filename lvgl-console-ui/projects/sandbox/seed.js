// dev/seed.js — 模擬環境的假資料（bus.shared 的初始狀態）
//
// 真機上這些值由 boot/task 寫進 bus；瀏覽器沒有 board，所以在這裡放一份
// **看得出來在動**的資料，讓頁面不必改一行就能顯示內容。
// 之後要驗證頁面，改這個檔（或 devtools 裡 sim.bus.shared.set(...)）即可。

import { bus, dict } from "@packages/lv-app/bus.js";

export function seed() {
  bus.shared.update({
    System: dict({
      hostname: "slave-01",
      master_IP: "192.168.4.1",
      master_port: 9000,
    }),
    Network: dict({
      wifi: dict({
        enable: 0,
        ssid: "demo-ap",
      }),
    }),
  });
  return bus;
}
