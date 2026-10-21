// ui/core/anim.js — LVGL anim_t 的鏡像
//
// 裝置上的用法（src/lv_ui_fx.py）：
//   a = lv.anim_t()
//   a.set_var(wid); a.set_values(255, 110); a.set_duration(750)
//   a.set_reverse_duration(750); a.set_repeat_count(0xFFFF)
//   a.set_custom_exec_cb(lambda _a, v: wid.set_style_opa(int(v), 0))
//   a.init(); a.start()
//
// 這裡保留完全一樣的方法名，只把 `lambda` 換成箭頭函式。
//
// 時間由 lv.tick_inc(ms) 推進（對應裝置的 lv.tick_inc）。
// 沒有 thread、沒有 timer：全部在 rAF 的每一幀推進一次。

import lv from "./lv.js";

const REPEAT_INFINITE = 0xffff;

export class Anim {
  constructor() {
    this.var = null;
    this._v0 = 0;
    this._v1 = 0;
    this.duration = 0;
    this.delay = 0;
    this.reverseDuration = 0;
    this.repeatCount = 1;
    this.cb = null;
    this.elapsed = 0;
    this.running = false;
    this._done = false;
  }

  set_var(v) {
    this.var = v;
    return this;
  }
  set_values(a, b) {
    this._v0 = a;
    this._v1 = b;
    return this;
  }
  // LVGL 9 用 set_duration；舊版叫 set_time
  set_duration(ms) {
    this.duration = Math.max(1, ms | 0);
    return this;
  }
  set_time(ms) {
    return this.set_duration(ms);
  }
  set_delay(ms) {
    this.delay = Math.max(0, ms | 0);
    return this;
  }
  set_reverse_duration(ms) {
    this.reverseDuration = Math.max(0, ms | 0);
    return this;
  }
  set_repeat_count(n) {
    this.repeatCount = n;
    return this;
  }
  set_custom_exec_cb(fn) {
    this.cb = fn;
    return this;
  }
  set_path_cb(fn) {
    this.path = fn;
    return this;
  }

  /** 相容 binding 的 init()（實際沒做事，只是讓程式碼看起來一樣）。 */
  init() {
    return this;
  }

  start() {
    this.elapsed = 0;
    this.running = true;
    this._done = false;
    anims.add(this);
    return this;
  }

  stop() {
    this.running = false;
    anims.delete(this);
    return this;
  }

  /** 週期長度（不含 delay）。 */
  get cycle() {
    return this.duration + this.reverseDuration;
  }

  _apply(v) {
    if (this.cb) this.cb(this, v);
  }

  /** 推進 dt ms；回傳 false = 已結束。 */
  tick(dt) {
    if (!this.running) return false;
    this.elapsed += dt;

    // delay 階段
    if (this.elapsed < this.delay) return true;

    let t = this.elapsed - this.delay;
    const cycle = this.cycle;

    // 重複次數：0xFFFF = 無限
    let cycles = 0;
    if (this.repeatCount !== REPEAT_INFINITE && cycle > 0) {
      cycles = Math.floor(t / cycle);
      if (cycles >= this.repeatCount) {
        // 最後一次直接停在終值
        this._apply(this.reverseDuration > 0 ? this._v0 : this._v1);
        this.running = false;
        anims.delete(this);
        this._done = true;
        return false;
      }
    }
    t = cycle > 0 ? t % cycle : 0;

    if (t <= this.duration) {
      const p = this.duration ? t / this.duration : 1;
      this._apply(this._v0 + (this._v1 - this._v0) * p);
    } else if (this.reverseDuration > 0) {
      const p = (t - this.duration) / this.reverseDuration;
      this._apply(this._v1 + (this._v0 - this._v1) * p);
    } else {
      this._apply(this._v1);
    }
    return true;
  }
}

const anims = new Set();

/** 由 lv.tick_inc(ms) 呼叫（display 的每一幀）。 */
export function tickAnims(ms) {
  if (!anims.size) return;
  for (const a of [...anims]) a.tick(ms);
}

lv.anim_t = Anim;
lv.on_tick(tickAnims);
export default Anim;
