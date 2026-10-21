// ui/core/paint.js — 版面計算 + canvas 繪製
//
// 跟 lv.js 分開的理由：lv.js 只管「物件長什麼樣、有哪些屬性」，
// 這裡只管「怎麼變成像素」。轉換到裝置時，這一整個檔都不用帶過去
// —— 它是 LVGL 在真機上本來就有的東西。
//
// ── 座標模型（跟 LVGL 一致）────────────────────────────────────────────
//   obj.x / obj.y        相對 parent 的 content area（左上角）
//   obj._ax / obj._ay    算出來的絕對座標（只給繪製用，頁面不碰）
//
//   為什麼要分開：LVGL 裡 `lb.set_pos(14, 68)` 是「距 parent 內緣 14,68」，
//   不是螢幕座標。第一版直接用 x/y 畫，結果子物件全部疊到螢幕左上角
//   —— 卡片上的文字跑到卡片外面，看起來像「文字被裁掉」。

import { ALIGN, PART, FLAG, STATE } from "./lv.js";

const css = (c) => (c == null ? null : typeof c === "string" ? c : c.css());

// ══════════════════════════════════════════════════════════════════════
//  版面
// ══════════════════════════════════════════════════════════════════════

/**
 * 遞迴計算所有 widget 的絕對座標 / content area / 對齊 / 自動尺寸。
 *
 * 為什麼每一幀都重算而不是「改的時候標脏」：
 *   - 這棵樹只有 ~200 個節點，一次全走 <0.1ms
 *   - align 依賴 parent 尺寸、label 尺寸依賴（可繼承的）字型，
 *     快取很容易在某個角落失效，然後變成「有時候差 1px」的鬼故事
 */
export function computeLayout(obj, displayW, displayH, parentContent = null) {
  if (!obj) return;

  if (!obj.parent) {
    obj.x = 0;
    obj.y = 0;
    obj.w = displayW;
    obj.h = displayH;
  }

  // 1) 自動尺寸（label 量文字，字型可能來自 parent 繼承）
  if (obj._sizeToContent && typeof obj.measure === "function") {
    const m = obj.measure();
    obj.w = m.w;
    obj.h = m.h;
  }

  // 2) list 的項目寬度跟著 list 走（LVGL 的 flex column + width 100%）
  if (obj.objClass === "list" && obj._layoutItems) obj._layoutItems();

  // 3) 對齊：算成「相對 parent content」的 x/y
  if (obj.parent && obj._align && parentContent) {
    const p = parentContent;
    const { type, dx, dy } = obj._align;
    let x = 0;
    let y = 0;
    switch (type) {
      case ALIGN.TOP_MID:
        x = Math.round((p.w - obj.w) / 2);
        break;
      case ALIGN.TOP_RIGHT:
        x = p.w - obj.w;
        break;
      case ALIGN.BOTTOM_LEFT:
        y = p.h - obj.h;
        break;
      case ALIGN.BOTTOM_MID:
        x = Math.round((p.w - obj.w) / 2);
        y = p.h - obj.h;
        break;
      case ALIGN.BOTTOM_RIGHT:
        x = p.w - obj.w;
        y = p.h - obj.h;
        break;
      case ALIGN.LEFT_MID:
        y = Math.round((p.h - obj.h) / 2);
        break;
      case ALIGN.RIGHT_MID:
        x = p.w - obj.w;
        y = Math.round((p.h - obj.h) / 2);
        break;
      case ALIGN.CENTER:
        x = Math.round((p.w - obj.w) / 2);
        y = Math.round((p.h - obj.h) / 2);
        break;
      case ALIGN.TOP_LEFT:
      default:
        break;
    }
    obj.x = x + dx;
    obj.y = y + dy;
  }

  // 4) 絕對座標
  obj._ax = parentContent ? parentContent.x + obj.x : obj.x;
  obj._ay = parentContent ? parentContent.y + obj.y : obj.y;

  // 5) content area（扣 border + pad）—— 子物件相對這個區域
  const bw = obj.getStyle("border_width") ?? 0;
  const pad = obj.getPad();
  obj._content = {
    x: obj._ax + bw + pad.l,
    y: obj._ay + bw + pad.t,
    w: obj.w - 2 * bw - pad.l - pad.r,
    h: obj.h - 2 * bw - pad.t - pad.b,
  };

  for (const c of obj.children) computeLayout(c, displayW, displayH, obj._content);
}

// ══════════════════════════════════════════════════════════════════════
//  繪製工具
// ══════════════════════════════════════════════════════════════════════

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, Math.floor(w / 2), Math.floor(h / 2)));
  ctx.beginPath();
  if (rr <= 0) {
    ctx.rect(x, y, w, h);
    return;
  }
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.arcTo(x + w, y, x + w, y + rr, rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr);
  ctx.lineTo(x + rr, y + h);
  ctx.arcTo(x, y + h, x, y + h - rr, rr);
  ctx.lineTo(x, y + rr);
  ctx.arcTo(x, y, x + rr, y, rr);
  ctx.closePath();
}

/** 依序畫：陰影 → 底 → 邊框。outline 由 drawOutline() 另外畫。 */
function drawBox(ctx, o) {
  const x = o._ax;
  const y = o._ay;
  const radius = o.getStyle("radius") ?? 0;
  const bgColor = o.getStyle("bg_color");
  const bgOpa = o.getStyle("bg_opa") ?? 255;
  const bw = o.getStyle("border_width") ?? 0;
  const bColor = o.getStyle("border_color");
  const bOpa = o.getStyle("border_opa") ?? 255;
  const shW = o.getStyle("shadow_width") ?? 0;
  const shColor = o.getStyle("shadow_color");
  const shOpa = o.getStyle("shadow_opa") ?? 128;

  if (shW > 0 && shColor) {
    ctx.save();
    ctx.globalAlpha *= shOpa / 255;
    ctx.shadowColor = css(shColor);
    ctx.shadowBlur = shW * 2;
    ctx.shadowOffsetX = o.getStyle("shadow_ofs_x") ?? 0;
    ctx.shadowOffsetY = o.getStyle("shadow_ofs_y") ?? 0;
    ctx.fillStyle = css(shColor);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
  }

  if (bgColor && bgOpa > 0) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(bgColor);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
  }

  if (bw > 0 && bColor) {
    ctx.save();
    ctx.globalAlpha *= bOpa / 255;
    ctx.strokeStyle = css(bColor);
    ctx.lineWidth = bw;
    // LVGL 的 border 畫在物件**內側**：路徑內縮 bw/2
    roundRect(ctx, x + bw / 2, y + bw / 2, o.w - bw, o.h - bw, Math.max(0, radius - bw / 2));
    ctx.stroke();
    ctx.restore();
  }
}

/**
 * outline（焦點框）：畫在物件外側。
 *
 * ⚠️ 一定要獨立成一個函式、對**每一種** widget 都呼叫：
 *    第一版只在 drawBox（obj/label）裡畫，結果 slider/switch 這些自繪 widget
 *    的焦點框永遠不出現 —— 在裝置上會變成「這顆按鈕到底有沒有被選中」看不出來。
 */
function drawOutline(ctx, o) {
  const ow = o.getStyle("outline_width") ?? 0;
  const oColor = o.getStyle("outline_color");
  if (!(ow > 0 && oColor)) return;
  const oPad = o.getStyle("outline_pad") ?? 0;
  const radius = o.getStyle("radius") ?? 0;
  ctx.save();
  ctx.strokeStyle = css(oColor);
  ctx.lineWidth = ow;
  const d = oPad + ow / 2;
  roundRect(ctx, o._ax - d, o._ay - d, o.w + 2 * d, o.h + 2 * d, radius + d);
  ctx.stroke();
  ctx.restore();
}

function drawLabel(ctx, o) {
  const font = o.getStyle("text_font");
  if (!font) return;
  const color = o.getStyle("text_color") ?? "#000000";
  const opa = o.getStyle("text_opa") ?? 255;
  const ls = o.getStyle("text_letter_space") ?? 0;
  const lineSpace = o.getStyle("text_line_space") ?? 0;
  const lines = o._lines ?? [o._text];
  const lh = font.lineHeight;
  const align = o.getStyle("text_align") ?? 0; // 0=left, 1=center, 2=right
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let lx = o._ax;
    if (align === 1) lx = o._ax + Math.round((o.w - font.measure(line)) / 2);
    else if (align === 2) lx = o._ax + o.w - font.measure(line);
    font.draw(ctx, line, lx, o._ay + i * (lh + lineSpace), css(color), opa, ls);
  }
}

function drawSlider(ctx, o) {
  const x = o._ax;
  const y = o._ay;
  const radius = o.getStyle("radius") ?? 0;
  const bgColor = o.getStyle("bg_color");
  const bgOpa = o.getStyle("bg_opa") ?? 255;
  const ind = o._styles.get(PART.INDICATOR);
  const indColor = ind?.get("bg_color");
  const indRadius = ind?.get("radius") ?? radius;
  const knob = o._styles.get(PART.KNOB);
  const knobColor = knob?.get("bg_color") ?? indColor;
  const knobPad = knob?.get("pad_all") ?? 4;
  const knobD = o.h + 2 * knobPad;
  const ratio = o.getRatio();
  const travel = Math.max(0, o.w - knobD);
  const knobX = ratio * travel;

  if (bgColor) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(bgColor);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
    const bw = o.getStyle("border_width") ?? 0;
    if (bw > 0 && o.getStyle("border_color")) {
      ctx.save();
      ctx.strokeStyle = css(o.getStyle("border_color"));
      ctx.lineWidth = bw;
      roundRect(ctx, x + bw / 2, y + bw / 2, o.w - bw, o.h - bw, radius);
      ctx.stroke();
      ctx.restore();
    }
  }

  if (indColor && ratio > 0) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(indColor);
    roundRect(ctx, x, y, knobX + knobD / 2, o.h, indRadius);
    ctx.fill();
    ctx.restore();
  }

  if (knobColor) {
    const r = knobD / 2;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x + knobX + r, y + o.h / 2, r, 0, Math.PI * 2);
    ctx.fillStyle = css(knobColor);
    ctx.fill();
    ctx.restore();
  }
}

function drawArc(ctx, o) {
  const cx = o._ax + o.w / 2;
  const cy = o._ay + o.h / 2;
  const main = o._styles.get(PART.MAIN);
  const ind = o._styles.get(PART.INDICATOR);
  const wMain = main?.get("arc_width") ?? 6;
  const wInd = ind?.get("arc_width") ?? wMain;
  const r = Math.min(o.w, o.h) / 2 - Math.max(wMain, wInd) / 2;
  const colorMain = main?.get("arc_color");
  const colorInd = ind?.get("arc_color");
  const start = ((o._bgStart ?? 135) % 360) * (Math.PI / 180);
  const sweepDeg = (((o._bgEnd ?? 45) - (o._bgStart ?? 135) + 360) % 360) || 360;
  const sweep = sweepDeg * (Math.PI / 180);

  ctx.save();
  ctx.lineCap = "butt";
  if (colorMain) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, start, start + sweep);
    ctx.lineWidth = wMain;
    ctx.strokeStyle = css(colorMain);
    ctx.stroke();
  }
  if (colorInd) {
    const ratio = o.getRatio();
    if (ratio > 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, start, start + sweep * ratio);
      ctx.lineWidth = wInd;
      ctx.strokeStyle = css(colorInd);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawSwitch(ctx, o) {
  const x = o._ax;
  const y = o._ay;
  const radius = o.getStyle("radius") ?? o.h / 2;
  const bg = o.getStyle("bg_color");
  const bgOpa = o.getStyle("bg_opa") ?? 255;
  const ind = o._styles.get(PART.INDICATOR)?.get("bg_color");
  const knob = o._styles.get(PART.KNOB)?.get("bg_color") ?? { css: () => "#ffffff" };
  const checked = o.has_state(STATE.CHECKED);
  const knobD = Math.max(0, o.h - 4);
  const knobX = checked ? o.w - knobD - 2 : 2;

  if (bg) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(bg);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
  }
  if (ind && checked) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(ind);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
  }
  ctx.save();
  ctx.beginPath();
  ctx.arc(x + knobX + knobD / 2, y + o.h / 2, knobD / 2, 0, Math.PI * 2);
  ctx.fillStyle = css(knob);
  ctx.fill();
  ctx.restore();
}

function drawBar(ctx, o) {
  const x = o._ax;
  const y = o._ay;
  const radius = o.getStyle("radius") ?? 0;
  const bg = o.getStyle("bg_color");
  const bgOpa = o.getStyle("bg_opa") ?? 255;
  const ind = o._styles.get(PART.INDICATOR)?.get("bg_color");
  const ratio = o.getRatio();
  if (bg) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(bg);
    roundRect(ctx, x, y, o.w, o.h, radius);
    ctx.fill();
    ctx.restore();
  }
  if (ind && ratio > 0) {
    ctx.save();
    ctx.globalAlpha *= bgOpa / 255;
    ctx.fillStyle = css(ind);
    roundRect(ctx, x, y, o.w * ratio, o.h, radius);
    ctx.fill();
    ctx.restore();
  }
}

/** 主入口：畫一棵樹。 */
export function paintTree(ctx, o) {
  if (!o) return;
  if (o._hidden || o.has_flag(FLAG.HIDDEN)) return;

  const opa = o.getStyle("opa") ?? 255;
  const saved = opa < 255;
  if (saved) {
    ctx.save();
    ctx.globalAlpha *= opa / 255;
  }

  switch (o.objClass) {
    case "label":
      drawLabel(ctx, o);
      break;
    case "slider":
      drawSlider(ctx, o);
      break;
    case "arc":
      drawArc(ctx, o);
      break;
    case "switch":
      drawSwitch(ctx, o);
      break;
    case "bar":
      drawBar(ctx, o);
      break;
    default:
      drawBox(ctx, o);
      break;
  }

  // 焦點框（outline）對每一種 widget 都要畫 —— 見 drawOutline 的註解
  drawOutline(ctx, o);

  if (o.children.length) {
    ctx.save();
    // LVGL 的物件預設會 clip 子物件到自己的 bounds
    if (!o.has_flag(FLAG.OVERFLOW_VISIBLE)) {
      if (o.getStyle("clip_corner")) {
        roundRect(ctx, o._ax, o._ay, o.w, o.h, o.getStyle("radius") ?? 0);
        ctx.clip();
      } else {
        ctx.beginPath();
        ctx.rect(o._ax, o._ay, o.w, o.h);
        ctx.clip();
      }
    }
    for (const c of o.children) paintTree(ctx, c);
    ctx.restore();
  }

  if (saved) ctx.restore();
}
