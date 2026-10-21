// lvgl-console-ui/cli/assets.mjs — 字元 / 圖示盤點
//
//   node lvgl-console-ui/cli/assets.mjs                # 預設專案
//   node lvgl-console-ui/cli/assets.mjs slave          # 指定專案
//   node lvgl-console-ui/cli/assets.mjs slave --print-cmd
//
// 舊 Asset Studio 掃的是 HTML 設計稿（data-lucide + 非 ASCII 字元）；
// 現在原始碼是 JS 頁面，所以掃 projects/<id>/pages/*.js：
//   1. 字串字面量裡的非 ASCII 字元（註解不算 —— 註解不會顯示在畫面上）
//   2. 圖示名：mk_icon(x,"name")、meta.icon、以及任何剛好是對照表 key 的字串
//
// 這支同時被 serve.mjs 的 /api/assets-report 呼叫（面板資料永遠即時）。

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { BinFont } from "../host/font.js";
import { ICONS } from "../packages/lv-app/lv_icons.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, ".."); // = lvgl-console-ui/（工具即根）
const FONT_ZH = path.join(ROOT, "assets", "fonts", "zh_hant_16.bin");
const FONT_ICON = path.join(ROOT, "assets", "fonts", "icons_16.bin");

// 動態字串常見符號（跟舊 zhfont.py 的 COMMON_SYMBOLS 一致）
const COMMON_SYMBOLS = "°℃·±×÷→←↑↓…─／　—";

function loadBin(p, name) {
  const buf = fs.readFileSync(p);
  return new BinFont(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), name);
}

function projectIndex() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "projects.json"), "utf8")).projects;
}

function projectDir(id) {
  const list = projectIndex();
  const p = id ? list.find((x) => x.id === id) : list.find((x) => x.default) || list[0];
  if (!p) throw new Error(`找不到專案：${id ?? "(default)"}`);
  return { meta: p, dir: path.join(ROOT, p.path), id: p.id };
}

function listPages(dir) {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".js") && f !== "index.js")
    .map((f) => path.join(dir, f));
}

/** 字串字面量（含樣板字串）。 */
function literals(src) {
  const out = [];
  const re = /(["'`])(?:\\.|(?!\1)[^\\\n])*\1/g;
  let m;
  while ((m = re.exec(src))) out.push(m[0]);
  return out.join("\n");
}

function scanChars(files) {
  const used = new Map();
  for (const f of files) {
    const src = fs.readFileSync(f, "utf8");
    for (const ch of literals(src)) {
      const cp = ch.codePointAt(0);
      if (cp < 0x80) continue;
      if (!used.has(ch)) used.set(ch, new Set());
      used.get(ch).add(path.basename(f));
    }
  }
  return used;
}

function scanIcons(files) {
  const used = new Map();
  const add = (name, file) => {
    if (!used.has(name)) used.set(name, new Set());
    used.get(name).add(path.basename(file));
  };
  for (const f of files) {
    const src = fs.readFileSync(f, "utf8");
    for (const m of src.matchAll(/mk_icon\(\s*[^,]+,\s*["']([a-z0-9-]+)["']/g)) add(m[1], f);
    for (const m of src.matchAll(/\bicon:\s*["']([a-z0-9-]+)["']/g)) add(m[1], f);
    for (const m of src.matchAll(/(["'])([a-z0-9-]+)\1/g)) if (m[2] in ICONS) add(m[2], f);
  }
  return used;
}

/** 碼點 → lv_font_conv 的 -r 參數（連續的合併成區間）。 */
function toRanges(codepoints) {
  const cps = [...new Set(codepoints)].sort((a, b) => a - b);
  if (!cps.length) return "0x20-0x7F";
  const hex = (n) => "0x" + n.toString(16).toUpperCase();
  const parts = [];
  let start = cps[0];
  let prev = cps[0];
  for (let i = 1; i <= cps.length; i++) {
    const cp = cps[i];
    if (cp === prev + 1) {
      prev = cp;
      continue;
    }
    parts.push(start === prev ? hex(start) : `${hex(start)}-${hex(prev)}`);
    start = prev = cp;
  }
  return "0x20-0x7F," + parts.join(",");
}

/**
 * @param {string} [projectId] 專案 id；省略＝projects.json 的 default
 * @returns 盤點報告（CLI 印出來、serve 的 /api/assets-report 也回同一份）
 */
export function buildReport(projectId) {
  const { id, dir, meta } = projectDir(projectId);
  const files = listPages(path.join(dir, "pages"));

  const zh = loadBin(FONT_ZH, "zh_hant_16");
  const iconBin = loadBin(FONT_ICON, "icons_16");

  const charMap = scanChars(files);
  const iconMap = scanIcons(files);

  const charList = [...charMap.keys()].sort((a, b) => a.codePointAt(0) - b.codePointAt(0));
  const missingChars = charList
    .filter((ch) => !zh.hasChar(ch))
    .map((ch) => ({
      ch,
      cp: "U+" + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0"),
      files: [...charMap.get(ch)],
    }));

  const usedIcons = [...iconMap.keys()].sort();
  const unknownIcons = usedIcons.filter((n) => !(n in ICONS));
  const missingInBin = usedIcons.filter((n) => n in ICONS && !iconBin.hasChar(ICONS[n]));
  const unusedIcons = Object.keys(ICONS).filter((n) => !iconMap.has(n)).sort();

  const allChars = new Set([...charList, ...COMMON_SYMBOLS]);
  const ranges = toRanges([...allChars].map((c) => c.codePointAt(0)));
  const command =
    `npx lv_font_conv --font <你的字型.ttf> --size 16 --format bin --bpp 4 ` +
    `-r ${ranges} --no-compress -o zh_hant_16.bin`;

  return {
    project: { id, title: meta.title ?? id },
    generated_at: new Date().toISOString(),
    source: files.map((f) => `projects/${id}/pages/${path.basename(f)}`),
    chars: { total: charList.length, all: charList.join(""), missing: missingChars },
    icons: {
      used: usedIcons,
      unknown: unknownIcons,
      missing_in_bin: missingInBin,
      unused: unusedIcons,
      total_in_map: Object.keys(ICONS).length,
    },
    command,
  };
}

// ── CLI ──
const isDirect = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isDirect) {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const report = buildReport(args[0]);
  if (process.argv.includes("--print-cmd")) {
    console.log(report.command);
    process.exit(0);
  }
  const { chars, icons } = report;
  console.log(`[assets] 專案 ${report.project.id} · 掃 ${report.source.length} 個頁面`);
  console.log(`[assets] 字元 ${chars.total} 個（非 ASCII，只算字串）→ 缺 ${chars.missing.length}`);
  for (const m of chars.missing) console.log(`   缺 '${m.ch}' ${m.cp}  ← ${m.files.join(", ")}`);
  console.log(`[assets] 圖示 ${icons.used.length} 個 / 對照表 ${icons.total_in_map}`);
  if (icons.unknown.length) console.log(`   ⚠ 對照表沒有：${icons.unknown.join(", ")}`);
  if (icons.missing_in_bin.length) console.log(`   ⚠ icons_16.bin 沒有：${icons.missing_in_bin.join(", ")}`);
  if (icons.unused.length) console.log(`   · 對照表未使用：${icons.unused.join(", ")}`);
  console.log(`[assets] 補字型的命令：\n  ${report.command}`);
  process.exitCode = chars.missing.length || icons.missing_in_bin.length || icons.unknown.length ? 1 : 0;
}
