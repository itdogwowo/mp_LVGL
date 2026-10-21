// ui/core/display.js — canvas display driver（對應裝置的 lvgl_init.LvglDisp）
//
// 裝置上：LVGL 渲染到 PARTIAL draw buffer → flush_cb → SPI。
// 這裡：LVGL 鏡像層的樹 → canvas 2D。沒有 draw buffer、沒有 dirty rect、
//       沒有 RGB565 轉換 —— 那些都是「送到面板」的代價，瀏覽器不需要付。
//
// 尺寸固定 320×240（橫屏），跟 lvgl_init.py 的 _W/_H 一致；
// 這個數字會被 ui_common.init() 讀進 u.W/u.H，頁面靠它排版。

import lv from "@lvui/frameworks/lvgl/lv.js";
import { computeLayout, paintTree } from "@lvui/frameworks/lvgl/paint.js";

export class Display {
  constructor(canvas, { w = 320, h = 240, scale = 2 } = {}) {
    this.canvas = canvas;
    this.w = w;
    this.h = h;
    // 對齊裝置的 LvglDisp：那邊的介面是 plat.W / plat.H（ui_common.init 讀它）
    this.W = w;
    this.H = h;
    canvas.width = w;
    canvas.height = h;

    this.ctx = canvas.getContext("2d", { alpha: false });
    this.ctx.imageSmoothingEnabled = false;
    this.screen = null;

    this.scale = 1;
    this.setScale(scale); // 邏輯像素整數放大（image-rendering: pixelated）

    // LVGL 的顯示物件會有一個「預設 screen」（theme 的底色）
    this.baseColor = "#ffffff";

    // 效能儀表（給開發台顯示用）
    this.lastRenderMs = 0;
    this.frames = 0;

    lv.display = this;
  }

  set_screen(scr) {
    this.screen = scr;
  }

  /**
   * 設定顯示倍率（整數）。
   * 為什麼要留這個方法：開發台會依視窗大小自動挑倍率（見 boot.js 的 fitDevice），
   * 視窗放大時裝置也跟著放大，而不是固定 2× 留一大片空白。
   */
  setScale(scale) {
    this.scale = Math.max(1, Math.round(scale));
    this.canvas.style.width = `${this.w * this.scale}px`;
    this.canvas.style.height = `${this.h * this.scale}px`;
    return this.scale;
  }

  /** 一幀：清畫面 → 版面 → 繪製。 */
  render() {
    const t0 = performance.now();
    const { ctx, w, h } = this;

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = this.baseColor;
    ctx.fillRect(0, 0, w, h);

    if (this.screen) {
      computeLayout(this.screen, w, h);
      paintTree(ctx, this.screen);
    }
    ctx.restore();

    this.lastRenderMs = performance.now() - t0;
    this.frames++;
  }
}

export function createDisplay(canvas, opts) {
  return new Display(canvas, opts);
}
