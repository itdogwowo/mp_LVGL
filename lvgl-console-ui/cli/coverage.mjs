// lvgl-console-ui/cli/coverage.mjs — 檢查「某個目錄用到的字」在字型裡有沒有
//
//   node lvgl-console-ui/cli/coverage.mjs [目錄...] [--all]
//
// 為什麼需要：字型是**子集**（lv_font_conv 只收掃到的字），少一個字在裝置上
// 就是一個方框，而且只有翻到那一頁、剛好顯示那串字才會發現。
// 這個工具把「用到但字型沒有」的字一次列出來。
//
// 跟 assets.mjs 的差別：assets.mjs 掃「某個專案的 pages/」並檢查圖示；
// 這支可以指任何目錄（例如裝置的 mp_Net-Core/slave/ui/lvgl/*.py）。
//
//   --all   連註解也掃（預設只掃字串字面量；註解裡的字不會出現在畫面上）

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BinFont } from "../host/font.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FONT = path.join(HERE, "..", "assets", "fonts", "zh_hant_16.bin");

function loadFont() {
  const buf = fs.readFileSync(FONT);
  return new BinFont(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), "zh_hant_16");
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "__pycache__" || e.name === "node_modules") continue;
      walk(p, out);
    } else if (e.name.endsWith(".py") || e.name.endsWith(".js")) out.push(p);
  }
  return out;
}

/** 只取字串字面量：註解裡的字不會顯示在畫面上，掃進來只會製造假警報。 */
function literalText(src) {
  const out = [];
  const re = /(["'`])(?:\\.|(?!\1)[^\\\n])*\1/g;
  let m;
  while ((m = re.exec(src))) out.push(m[0]);
  return out.join("");
}

const MODE_ALL = process.argv.includes("--all");
const dirs = process.argv.slice(2).filter((a) => !a.startsWith("--"));
if (!dirs.length) dirs.push(path.join(HERE, "..", "projects"));

const font = loadFont();
const used = new Map(); // char → Set(file)
let files = 0;

for (const d of dirs) {
  if (!fs.existsSync(d)) {
    console.error(`[coverage] 目錄不存在：${d}`);
    process.exitCode = 2;
    continue;
  }
  for (const f of walk(d)) {
    files++;
    const src = fs.readFileSync(f, "utf8");
    const text = MODE_ALL ? src : literalText(src);
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (cp < 0x80) continue;
      if (!used.has(ch)) used.set(ch, new Set());
      used.get(ch).add(path.basename(f));
    }
  }
}

const missing = [...used.keys()].filter((ch) => !font.hasChar(ch)).sort();
console.log(`[coverage] 掃 ${files} 個檔，非 ASCII 字元 ${used.size} 個，字型 ${font.glyphCount} glyphs`);
if (!missing.length) {
  console.log("[coverage] OK — 全部都有");
} else {
  console.log(`[coverage] 缺 ${missing.length} 個：`);
  for (const ch of missing) {
    const cp = ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
    console.log(`  '${ch}' U+${cp}  ← ${[...used.get(ch)].join(", ")}`);
  }
  process.exitCode = 1;
}
