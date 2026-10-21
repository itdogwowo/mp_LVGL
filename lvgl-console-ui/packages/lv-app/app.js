// app/app.js — 動態註冊式 UI 主程式（對應 ui/lvgl/app.py）
//
// 採「扁平設計」：build_all() 一次性預建所有 screen，widget 永駐，
// go() 只換 screen 不 rebuild。跟裝置同一個策略，好處是轉換後行為一致：
//   省掉 widget 生命週期的 rebuild 問題，啟動時所有 widget 就位。
//
// 平台解耦：硬體全部透過 platform 物件注入，本檔不 import 任何硬體。
//   platform = { enc_delta(), confirm(), exit(), tick(), take(), show() }

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as registry from "./registry.js";
import * as launcher from "./launcher.js";

export let platform = null;
export let cur = null;
let _last_scr = null;
let _run = 0;
/** page_id → 預建的 screen（reuse 模式，widget 永駐） */
export const _screens = {};

export function init(plat) {
  platform = plat;
}

export function build_all() {
  _screens.launcher = launcher.build();
  for (const pid of Object.keys(registry.PAGES)) {
    try {
      _screens[pid] = registry.PAGES[pid].build();
    } catch (e) {
      console.warn(`[app] build skip ${pid}:`, e);
    }
  }
  console.log(`[app] build_all: ${Object.keys(_screens).length} screen(s) pre-built`);
}

function _page(name = cur) {
  if (name === "launcher") return launcher;
  const meta = registry.get(name);
  if (meta !== null) return meta.mod;
  return launcher;
}

export function go(name) {
  if (name === cur) return;
  if (name !== "launcher" && !(name in registry.PAGES)) return;
  if (!(name in _screens)) return; // 沒預建過（理論上 build_all 後都有）

  const old = _page();
  if (old && typeof old.on_leave === "function") old.on_leave();

  const scr = _screens[name];
  try {
    lv.screen_load(scr);
  } catch (e) {
    /* noop */
  }
  _last_scr = scr;

  cur = name;
  print(`[nav] -> ${name}`);
  const next = _page();
  if (next && typeof next.on_enter === "function") next.on_enter();
}

/**
 * 單幀處理。
 *
 * ★ 三段各自 try：enc/confirm/exit 都是「讀後即清」的消費式邊緣，
 *   一旦取走就沒了。以前 on_enc / on_confirm 任一拋例外，這一幀的返回鍵
 *   就整個消失（畫面停在原頁、再按也沒用），症狀跟「返回鍵壞掉」一樣。
 */
export function step() {
  const d = platform.enc_delta();
  const c = platform.confirm();
  const ex = platform.exit();
  const m = _page();

  if (d !== 0 && typeof m.on_enc === "function") {
    try {
      m.on_enc(d);
    } catch (e) {
      console.warn("[nav] on_enc err:", e);
    }
  }

  if (c && typeof m.on_confirm === "function") {
    let target = null;
    try {
      target = m.on_confirm();
    } catch (e) {
      console.warn("[nav] on_confirm err:", e);
    }
    if (target) go(target);
  }

  if (ex && cur !== "launcher") {
    // 重新取當前頁：on_confirm 可能已經 go() 到別頁，退出要作用在新的那一頁
    const p = _page();
    let consumed = false;
    if (typeof p.on_exit === "function") {
      try {
        consumed = p.on_exit() === true;
      } catch (e) {
        console.warn("[nav] on_exit err:", e);
        consumed = false;
      }
    }
    print(`[nav] exit -> ${cur}${consumed ? " consumed" : ""}`);
    if (!consumed) go("launcher");
  }

  if (typeof m.update === "function") m.update(_run);
  _run++;

  platform.tick();
  for (const rect of platform.take()) platform.show(...rect);
  return 1;
}

/** 目前跑了幾幀（除錯/儀表用）。 */
export function runCount() {
  return _run;
}
