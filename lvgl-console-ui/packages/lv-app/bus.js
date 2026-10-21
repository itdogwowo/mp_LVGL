// ui/bus.js — 裝置 bus 系統的最小鏡像
//
// 頁面拿的是 `from lib.sys_bus import bus`，實際用到三件事：
//   1. bus.shared[...]           共用的狀態字典（_display_mode / _display_cmd / mode_table …）
//   2. bus.get_service("lcd")    硬體服務（UI 層只是轉手，不在這裡實作）
//   3. consume_input(...)        輸入（enc 累加 delta / pin 去抖邊緣，**讀後即清**）
//
// 這個檔的目的不是模擬整條 bus，而是讓「頁面邏輯」在瀏覽器裡跑得起來，
// 而且**語義跟真機一樣**（尤其是 consume_input 的累加與清除 —— 那是旋鈕
// 不掉格、按鍵不重複觸發的關鍵）。

/**
 * Python dict 的最小替身：支援 d[k] / d[k]=v / k in d / d.get(k, default)。
 *
 * 為什麼要包一層，而不是直接用 JS 物件：
 *   頁面在裝置上寫的是 `bus.shared.get("_display_mode", 0)`、
 *   `bus.shared["_display_cmd"] = cmd`。如果 JS 這邊改成一般物件，
 *   頁面就得改寫成 `.field`/`?.`，轉換回去時又是一次人工翻譯
 *   —— 能夠「兩邊同一行」是這個專案最重要的資產，為此值得包一層。
 */
export class Dict {
  constructor(init = null) {
    const map = new Map();
    Object.defineProperty(this, "_m", { value: map, enumerable: false });
    if (init) for (const [k, v] of Object.entries(init)) map.set(k, v);
    return new Proxy(this, {
      get(t, p) {
        if (typeof p === "symbol") return t[p];
        if (p in t) return t[p];
        return map.get(p);
      },
      set(t, p, v) {
        if (p in t) return false;
        map.set(p, v);
        return true;
      },
      has(t, p) {
        return p in t || map.has(p);
      },
      deleteProperty(t, p) {
        map.delete(p);
        return true;
      },
      ownKeys() {
        return [...map.keys()];
      },
      getOwnPropertyDescriptor(t, p) {
        return { configurable: true, enumerable: true, value: map.get(p) };
      },
    });
  }
  get(k, dflt = undefined) {
    return this._m.has(k) ? this._m.get(k) : dflt;
  }
  set(k, v) {
    this._m.set(k, v);
    return this;
  }
  has(k) {
    return this._m.has(k);
  }
  delete(k) {
    return this._m.delete(k);
  }
  keys() {
    return [...this._m.keys()];
  }
  items() {
    return [...this._m.entries()];
  }
  update(obj) {
    const src = obj instanceof Dict ? Object.fromEntries(obj._m) : obj;
    for (const [k, v] of Object.entries(src)) this._m.set(k, v);
    return this;
  }
}

/** 建立 Dict 的簡寫：dict({a:1}) */
export function dict(init) {
  return new Dict(init);
}

export class Bus {
  constructor() {
    this.shared = new Dict();
    this._services = new Map();
    this._enc = [0]; // idx → 待消費的累加 delta
    this._pin = new Map(); // key → 0/1（去抖後的按壓邊緣）
    this._log = [];
    /** 裝置 ID（真機由 boot 產生；模擬環境用固定值方便對照） */
    this.slave_id = "A1B2C3D4E5F6";
  }

  // ── service ──
  get_service(name) {
    return this._services.has(name) ? this._services.get(name) : null;
  }
  register_service(name, obj) {
    this._services.set(name, obj);
    return obj;
  }
  has_lcd() {
    // 瀏覽器裡沒有真的 LCD；UI 層只需要「可以跑」。
    return true;
  }

  // ── 輸入注入（harness / 腳本用） ──
  push_enc(delta, idx = 0) {
    this._enc[idx] = (this._enc[idx] || 0) + delta;
  }
  /** 按壓邊緣：只有「按下」那一刻算一次，跟裝置的去抖邊緣一致。 */
  push_pin(key) {
    this._pin.set(key, 1);
  }

  // ── 輸入消費（呼叫端＝board.py 的 _make_snapshot_inputs） ──
  consume_input(kind, opts = {}) {
    if (kind === "enc") {
      const i = opts.idx ?? 0;
      const v = this._enc[i] || 0;
      this._enc[i] = 0;
      return v;
    }
    if (kind === "pin") {
      const k = opts.key;
      const v = this._pin.get(k) ? 1 : 0;
      this._pin.set(k, 0);
      return v;
    }
    return 0;
  }

  /** 除錯用：還有多少待消費輸入。 */
  pending() {
    return { enc: [...this._enc], pin: [...this._pin.entries()].filter(([, v]) => v) };
  }
}

export const bus = new Bus();
export default bus;
