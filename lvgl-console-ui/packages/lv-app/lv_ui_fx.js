// shell/lv_ui_fx.js — 動效 helper（對應 ui/lvgl/src/lv_ui_fx.py）
//
// 這幾支是設計稿 CSS 動效的對應：
//   pulse()    ← pulse / live-ping       呼吸閃爍（狀態燈、livedot）
//   fade_in()  ← rise / fade-in          載入淡入 + 往上位移
//   bar_grow() ← bar-grow                數值/進度成長
//
// 裝置上的坑（Python 版註解寫的）：binding 是 lv.anim_t() 不是 lv.anim()、
// set_time 不存在要用 set_duration、無限重複是 0xFFFF。
// 我們的 Anim 兩種都收，所以同一段程式碼兩邊都跑得動。

import lv from "@lvui/frameworks/lvgl/lv.js";

const REPEAT_INF = 0xffff;

function animClass() {
  return lv.anim_t ?? null;
}

function start(a) {
  try {
    a.init();
  } catch (e) {
    /* noop */
  }
  a.start();
  return a;
}

/** 呼吸閃爍：opa 在 min/max 間往返，永續播放。 */
export function pulse(wid, period = 1500, minOpa = 110, maxOpa = 255) {
  const AC = animClass();
  if (!AC) {
    wid.set_style_opa(maxOpa, 0);
    return null;
  }
  const half = Math.max(80, Math.floor(period / 2));
  const a = new AC();
  a.set_var(wid);
  a.set_values(maxOpa, minOpa);
  a.set_duration(half);
  a.set_reverse_duration(half);
  a.set_repeat_count(REPEAT_INF);
  a.set_custom_exec_cb((_a, v) => wid.set_style_opa(Math.trunc(v), 0));
  return start(a);
}

/** 載入淡入 + 向上位移。 */
export function fade_in(wid, dy = 6, timeMs = 300, delayMs = 0) {
  const AC = animClass();
  const x = wid.get_x();
  const y = wid.get_y();
  if (!AC) {
    wid.set_style_opa(255, 0);
    return null;
  }
  const a = new AC();
  a.set_var(wid);
  a.set_values(y + dy, y);
  a.set_duration(timeMs);
  a.set_delay(delayMs);
  a.set_custom_exec_cb((_a, v) => wid.set_pos(x, Math.trunc(v)));
  start(a);

  const b = new AC();
  b.set_var(wid);
  b.set_values(0, 255);
  b.set_duration(timeMs);
  b.set_delay(delayMs);
  b.set_custom_exec_cb((_a, v) => wid.set_style_opa(Math.trunc(v), 0));
  start(b);
  return [a, b];
}

/** 進度/數值成長動畫。 */
export function bar_grow(bar, fromVal = 0, toVal = null, timeMs = 400) {
  const AC = animClass();
  const to = toVal ?? bar.get_value();
  if (!AC) {
    bar.set_value(to, 0);
    return null;
  }
  const a = new AC();
  a.set_var(bar);
  a.set_values(fromVal, to);
  a.set_duration(timeMs);
  a.set_custom_exec_cb((_a, v) => bar.set_value(Math.trunc(v), 0));
  return start(a);
}

/** 依狀態切換文字/元件顏色（CSS :hover/:active/:focus 的對應）。 */
export function set_state_colors(wid, on, colorOn, colorOff, part = 0) {
  wid.set_style_text_color(lv.color_hex(on ? colorOn : colorOff), part);
}

export default { pulse, fade_in, bar_grow, set_state_colors };
