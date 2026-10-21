// dev/inspector.js — 畫布上的元件檢視器（像 DevTools 的「選取元素」）
//
// 為什麼做得到：這棵樹是我們自己的，每個 widget 都有 `_ax/_ay/w/h` 絕對座標，
// 所以「游標底下是哪個元件」只是走一次樹（跟 canvas 無關，不需要 pixel picking）。
//
// 兩個關鍵：
//   1. 命中測試要**由上而下、子優先**（最後畫的在最上層）
//   2. 每個 widget 都有 `_src`（建立時截的 stack）⇒ 可以直接指出
//      「這是 pages/settings.js:44 建的」，不用猜

import { FLAG, ALIGN } from "@lvui/frameworks/lvgl/lv.js";

export const ALIGN_NAME = Object.fromEntries(Object.entries(ALIGN).map(([k, v]) => [v, k]));
export const FLAG_NAME = Object.fromEntries(Object.entries(FLAG).map(([k, v]) => [v, k]));

/** 這個 widget 在樹裡的路徑，例如：screen > obj #12 > label #42 */
export function pathOf(w) {
  const parts = [];
  let n = w;
  while (n) {
    const tag = n.parent ? `${n.objClass} #${n.oid}` : "screen";
    parts.unshift(tag);
    n = n.parent;
  }
  return parts.join(" › ");
}

/** 深度優先、子優先的命中測試。回傳最深（最上層）的 widget。 */
export function hitTest(obj, x, y) {
  if (!obj || obj._hidden || obj.has_flag(FLAG.HIDDEN)) return null;
  if (x < obj._ax || x >= obj._ax + obj.w || y < obj._ay || y >= obj._ay + obj.h) return null;
  for (let i = obj.children.length - 1; i >= 0; i--) {
    const r = hitTest(obj.children[i], x, y);
    if (r) return r;
  }
  return obj;
}

export function createInspector({ canvas, overlay, display, onSelect, onHover }) {
  const ctx = overlay.getContext("2d");
  let enabled = true;
  let hovered = null;
  let selected = null;
  let flashUntil = 0;
  let flashW = null;

  // overlay 跟 sim 同尺寸、同顯示大小（縮放改變時 boot 會呼叫 sync）
  const syncSize = () => {
    overlay.width = display.w;
    overlay.height = display.h;
    overlay.style.width = canvas.style.width;
    overlay.style.height = canvas.style.height;
    // 疊層位置跟著畫布走（bezel 內距在 CSS 是 var(--s3)=12px，這裡直接量）
    const cr = canvas.getBoundingClientRect();
    const br = overlay.parentElement.getBoundingClientRect();
    overlay.style.left = `${cr.left - br.left}px`;
    overlay.style.top = `${cr.top - br.top}px`;
  };
  syncSize();

  function toDevice(e) {
    const r = canvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * display.w);
    const y = Math.floor(((e.clientY - r.top) / r.height) * display.h);
    return { x, y };
  }

  function setHover(w) {
    if (w === hovered) return;
    hovered = w;
    onHover?.(w);
  }
  function select(w) {
    selected = w;
    onSelect?.(w);
  }

  canvas.addEventListener("pointermove", (e) => {
    if (!enabled) return;
    const { x, y } = toDevice(e);
    setHover(hitTest(display.screen, x, y));
  });

  canvas.addEventListener("pointerleave", () => setHover(null));

  canvas.addEventListener("click", (e) => {
    if (!enabled) return;
    const { x, y } = toDevice(e);
    const w = hitTest(display.screen, x, y);
    if (w) select(w);
  });

  /** 從元件樹點進來時用的：選取 + 閃一下（因為它可能被別的東西蓋住） */
  function selectAndFlash(w) {
    select(w);
    flashW = w;
    flashUntil = performance.now() + 900;
  }

  function rect(w, color, width, fill) {
    ctx.save();
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fillRect(w._ax, w._ay, w.w, w.h);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.strokeRect(w._ax + width / 2, w._ay + width / 2, Math.max(0, w.w - width), Math.max(0, w.h - width));
    ctx.restore();
  }

  function redraw() {
    ctx.clearRect(0, 0, display.w, display.h);
    if (!enabled) return;

    // 只畫框，不畫文字：文字疊在畫布上會蓋住 UI，而且元件貼邊時會被裁掉。
    // 文字一律走畫布外那條資訊列（#inspect-bar，boot.js 更新）。
    if (hovered && hovered !== selected) {
      rect(hovered, "rgba(255,77,157,0.9)", 1, "rgba(255,77,157,0.10)");
    }

    if (selected) {
      rect(selected, "rgba(76,141,255,0.95)", 2, "rgba(76,141,255,0.08)");
      // 四角抓手
      ctx.save();
      ctx.fillStyle = "rgba(76,141,255,0.95)";
      const s = 3;
      for (const [px, py] of [
        [selected._ax, selected._ay],
        [selected._ax + selected.w - s, selected._ay],
        [selected._ax, selected._ay + selected.h - s],
        [selected._ax + selected.w - s, selected._ay + selected.h - s],
      ]) {
        ctx.fillRect(px, py, s, s);
      }
      ctx.restore();
    }

    if (flashW && performance.now() < flashUntil) {
      const t = (Math.sin(performance.now() / 60) + 1) / 2;
      rect(flashW, `rgba(255,196,0,${0.5 + t * 0.5})`, 2, null);
    } else if (flashW) {
      flashW = null;
    }
  }

  return {
    hitTest: (x, y) => hitTest(display.screen, x, y),
    select: selectAndFlash,
    clear: () => select(null),
    redraw,
    sync: syncSize, // 視窗縮放後由 boot 呼叫
    set enabled(v) {
      enabled = !!v;
      if (!enabled) {
        setHover(null);
        ctx.clearRect(0, 0, display.w, display.h);
      }
    },
    get enabled() {
      return enabled;
    },
    get hovered() {
      return hovered;
    },
    get selected() {
      return selected;
    },
  };
}
