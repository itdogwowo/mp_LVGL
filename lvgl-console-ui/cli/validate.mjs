// lvgl-console-ui/cli/validate.mjs — 工程驗證（對應舊工作區的 validation-report.json）
//
//   node lvgl-console-ui/cli/validate.mjs            # 全部專案
//   node lvgl-console-ui/cli/validate.mjs slave      # 指定專案
//
// 為什麼要有這一步：模擬器跑得起來，不代表「這個工程是完整的」。
// 會壞的都是靜態的東西 —— 頁面 meta 重複 id、index.js 忘了 import、
// project.json 綁了不存在的 theme、字型缺字、圖示名打錯。
// 這些在瀏覽器裡只會表現成「某頁空白」或「某個字變方框」，很難查。
//
// 檢查項目：
//   1. projects.json / project.json 存在且欄位完整
//   2. project.json 綁的 theme 存在，版本相符
//   3. 每個 pages/*.js 都有 export const meta（id 唯一）與 export function build
//   4. pages/index.js 有 import 每一個頁面檔
//   5. 字型檔存在且能解析（BinFont）
//   6. 頁面字串的字都在字型子集裡（缺字＝真機方框）
//   7. 用到的圖示都在對照表與 icons_16.bin 裡
//
// 產物：validation-report.json（outcome / errors / warnings / hashes / checkedAt）
//       欄位刻意對齊舊工作區那份，之後要接 CI 或別的檢查器都認得。

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { BinFont } from "../host/font.js";
import { buildReport } from "./assets.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, ".."); // = lvgl-console-ui/（工具即根）
const OUT = path.join(ROOT, "validation-report.json");

const errors = [];
const warnings = [];
const hashes = {};
const projects = [];

const sha256 = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const rel = (p) => path.relative(ROOT, p).replace(/\\/g, "/");
const err = (project, check, message) => errors.push({ project, check, message });
const warn = (project, check, message) => warnings.push({ project, check, message });

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (e) {
    err(null, "json", `${rel(file)} 讀取失敗：${e.message}`);
    return null;
  }
}

/**
 * 從頁面原始碼抓 meta（驗證用；不執行模組，避免把瀏覽器相依帶進來）。
 * ⚠ 不要用「一定要換行再 `};`」的寫法：meta 常見多行且最後一個欄位與 `};` 同行。
 *   這裡允許一層巢狀大括號，兩種格式都吃。
 */
function parsePageMeta(src) {
  const block = src.match(/export const meta\s*=\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*;/);
  if (!block) return null;
  const text = block[0];
  const pick = (re) => text.match(re)?.[1] ?? null;
  return {
    id: pick(/\bid:\s*["']([^"']+)["']/),
    title: pick(/\btitle:\s*["']([^"']+)["']/),
    icon: pick(/\bicon:\s*["']([^"']+)["']/),
    order: Number(pick(/\border:\s*(-?[\d.]+)/) ?? 0),
    dev: /\bdev:\s*true/.test(text),
  };
}

// ── 1. 專案索引 ──
const indexFile = path.join(ROOT, "projects.json");
if (!fs.existsSync(indexFile)) {
  err(null, "projects", "找不到根目錄的 projects.json");
} else {
  hashes["projects.json"] = sha256(indexFile);
  const index = readJson(indexFile) ?? { projects: [] };
  const wanted = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const list = index.projects ?? [];

  if (!list.length) err(null, "projects", "projects.json 裡沒有任何專案");
  for (const p of list) {
    if (wanted.length && !wanted.includes(p.id)) continue;
    checkProject(p);
  }
}
finish();

function checkProject(entry) {
  const dir = path.join(ROOT, entry.path ?? `projects/${entry.id}`);
  const pjFile = path.join(dir, "project.json");
  if (!fs.existsSync(pjFile)) {
    err(entry.id, "project.json", `找不到 ${rel(pjFile)}`);
    return;
  }
  hashes[rel(pjFile)] = sha256(pjFile);
  const pj = readJson(pjFile);
  if (!pj) return;

  if (!pj.display?.w || !pj.display?.h) warn(entry.id, "project.json", "display.w/h 未設定，會用 320×240 預設");

  // 2. theme 綁定
  const themeId = pj.theme?.id ?? "traework";
  const themeFile = path.join(ROOT, "packages", "themes", themeId, "index.js");
  if (!fs.existsSync(themeFile)) {
    err(entry.id, "theme", `theme '${themeId}' 不存在（${rel(themeFile)}）`);
  } else {
    hashes[rel(themeFile)] = sha256(themeFile);
    const themeSrc = fs.readFileSync(themeFile, "utf8");
    const themeVersion = themeSrc.match(/export const version\s*=\s*["']([^"']+)["']/)?.[1];
    if (pj.theme?.version && themeVersion && pj.theme.version !== themeVersion) {
      err(entry.id, "theme", `版本不合：project 綁 ${pj.theme.version}，theme 是 ${themeVersion}`);
    }
  }

  // 3. 頁面
  const pagesDir = path.join(dir, pj.pages ?? "pages");
  if (!fs.existsSync(pagesDir)) {
    err(entry.id, "pages", `找不到頁面目錄 ${rel(pagesDir)}`);
    return;
  }
  const files = fs.readdirSync(pagesDir).filter((f) => f.endsWith(".js") && f !== "index.js");
  const indexSrc = fs.existsSync(path.join(pagesDir, "index.js"))
    ? fs.readFileSync(path.join(pagesDir, "index.js"), "utf8")
    : "";
  if (!indexSrc) err(entry.id, "pages", "pages/index.js 不存在（沒有它就不會註冊任何頁面）");

  const metas = [];
  const ids = new Set();
  for (const f of files) {
    const file = path.join(pagesDir, f);
    hashes[rel(file)] = sha256(file);
    // 共用模組（*_common.js / *_util.js）不是頁面：沒有 meta，也不該在 index.js 註冊
    if (/_(common|util)\.js$/.test(f)) {
      if (indexSrc.includes(f)) err(entry.id, "pages", `共用模組 ${f} 不該在 index.js 註冊`);
      continue;
    }
    const src = fs.readFileSync(file, "utf8");
    const meta = parsePageMeta(src);
    if (!meta || !meta.id) {
      err(entry.id, "page", `${f} 缺少 export const meta { id }`);
      continue;
    }
    if (ids.has(meta.id)) err(entry.id, "page", `${f} 的 id '${meta.id}' 重複`);
    ids.add(meta.id);
    if (!/export function build\s*\(/.test(src)) err(entry.id, "page", `${f} 缺少 export function build()`);
    if (!indexSrc.includes(`"./${f}"`)) err(entry.id, "pages", `pages/index.js 沒有 import "./${f}"`);
    metas.push({ file: f, ...meta });
  }

  // 4. 字型與資產
  const zhPath = path.join(ROOT, "assets", "fonts", "zh_hant_16.bin");
  const iconPath = path.join(ROOT, "assets", "fonts", "icons_16.bin");
  for (const f of [zhPath, iconPath]) {
    if (!fs.existsSync(f)) {
      err(entry.id, "font", `字型不存在 ${rel(f)}`);
      continue;
    }
    try {
      const buf = fs.readFileSync(f);
      new BinFont(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), path.basename(f));
    } catch (e) {
      err(entry.id, "font", `${path.basename(f)} 解析失敗：${e.message}`);
    }
  }

  try {
    const report = buildReport(entry.id);
    for (const m of report.chars.missing) {
      err(entry.id, "glyph", `缺字 '${m.ch}' ${m.cp}（${m.files.join(", ")}）→ 真機方框`);
    }
    for (const n of report.icons.unknown) err(entry.id, "icon", `圖示 '${n}' 不在對照表`);
    for (const n of report.icons.missing_in_bin) err(entry.id, "icon", `圖示 '${n}' 不在 icons_16.bin`);
    if (report.icons.unused.length) {
      warn(entry.id, "icon", `對照表有 ${report.icons.unused.length} 個圖示沒用到（不是錯誤）`);
    }
    projects.push({
      id: entry.id,
      title: pj.title ?? entry.title ?? entry.id,
      theme: `${pj.theme?.id ?? "traework"}@${pj.theme?.version ?? "?"}`,
      pages: metas.sort((a, b) => a.order - b.order),
      chars: report.chars.total,
      icons: report.icons.used.length,
    });
  } catch (e) {
    err(entry.id, "assets", `盤點失敗：${e.message}`);
  }
}

function finish() {
  const report = {
    schema: "validation-report/1",
    generated_at: new Date().toISOString(),
    outcome: errors.length ? "failed" : "passed",
    errorCount: errors.length,
    warningCount: warnings.length,
    errors,
    warnings,
    projects,
    hashes,
    checkedAt: new Date().toISOString(),
  };
  fs.writeFileSync(OUT, JSON.stringify(report, null, 2), "utf8");
  console.log(`[validate] ${report.outcome.toUpperCase()} · ${errors.length} error(s) · ${warnings.length} warning(s)`);
  for (const e of errors) console.log(`   ✗ [${e.project ?? "-"}] ${e.check}: ${e.message}`);
  for (const w of warnings) console.log(`   ! [${w.project ?? "-"}] ${w.check}: ${w.message}`);
  for (const p of projects) {
    console.log(`   · ${p.id} → ${p.pages.length} page(s), theme ${p.theme}, ${p.chars} chars, ${p.icons} icons`);
  }
  console.log(`[validate] → ${rel(OUT)}`);
  process.exitCode = errors.length ? 1 : 0;
}
