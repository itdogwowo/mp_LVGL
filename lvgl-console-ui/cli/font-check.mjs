// lvgl-console-ui/cli/font-check.mjs — 驗證 .bin 字型解析（node 直接跑，不需要瀏覽器）
//
//   node lvgl-console-ui/cli/font-check.mjs
//
// 檢查重點（都是轉換時會咬人的量）：
//   1. 表頭數值是否落在合理範圍（size/ascent/descent/bpp）
//   2. 中文字寬是否 16 px（全形），ASCII 是否 <=16
//   3. 常用字串的總寬度（對照真機目測）
//   4. 每個 glyph 的 ofsY 是否落在 [0, lineHeight) —— 超出代表 y 方向解錯
//   5. 反推 head.min_y / max_y 必須完全相符（方向解錯就會差很多）
import fs from "node:fs";
import { BinFont } from "../host/font.js";

function load(p) {
  const buf = fs.readFileSync(new URL(p, import.meta.url));
  return new BinFont(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), p.split("/").pop());
}

function report(font, sample) {
  console.log(`\n=== ${font.name} ===`);
  console.log(
    `size=${font.size} ascent=${font.ascent} descent=${font.descent} lineH=${font.lineHeight} ` +
      `bpp=${font.bpp} xy=${font.xyBits} wh=${font.whBits} adv=${font.advanceWidthBits} glyphs=${font.glyphCount}`
  );

  let minOfsY = 1e9;
  let maxOfsY = -1e9;
  let minRawBottom = 1e9;
  let maxRawTop = -1e9;
  for (const g of font._glyphs) {
    if (!g) continue;
    minOfsY = Math.min(minOfsY, g.ofsY);
    maxOfsY = Math.max(maxOfsY, g.ofsY);
    minRawBottom = Math.min(minRawBottom, font.ascent - g.ofsY - g.h);
    maxRawTop = Math.max(maxRawTop, font.ascent - g.ofsY);
  }
  const headOk = minRawBottom === font.minY && maxRawTop === font.maxY;
  console.log(
    `ofsY range=[${minOfsY}, ${maxOfsY}]  head.min_y/max_y=${font.minY}/${font.maxY} ` +
      `反推=${minRawBottom}/${maxRawTop} ${headOk ? "OK" : "✗ 方向解錯"}`
  );

  for (const ch of sample) {
    const g = font.glyph(ch.codePointAt(0));
    if (!g) {
      console.log(`  '${ch}' U+${ch.codePointAt(0).toString(16).toUpperCase()} → 缺字`);
      continue;
    }
    console.log(`  '${ch}' adv=${g.adv} ofsX=${g.ofsX} ofsY=${g.ofsY} ${g.w}x${g.h}`);
  }
  for (const s of ["控制面板", "亮度", "1234567890", "00:00", "100%"]) {
    console.log(`  "${s}" → ${font.measure(s)}px`);
  }
}

report(load("../assets/fonts/zh_hant_16.bin"), ["A", "0", "控", "制", "·", "→"]);
report(load("../assets/fonts/icons_16.bin"), ["\uE429", "\uE5CB", "\uE8B8"]);
