// lvgl-console-ui/cli/serve.mjs — 零相依靜態伺服器
//
//   cd lvgl-console-ui
//   node cli/serve.mjs               → http://127.0.0.1:8610/
//   node cli/serve.mjs 9000          → 換 port
//   node cli/serve.mjs --open        → 順便開瀏覽器（npm run dev 就是這個）
//
// ■ 這個資料夾就是根：index.html / projects.json / packages / projects 全在它下面。
//   所以網址是 `/`，不是 `/lvgl-console-ui/`。repo 裡其他東西（tools/simlab、
//   ESP32 demo …）跟這套系統無關，不需要被 serve。
//
// 兩個即時 API（不落地、不會過期）：
//   GET /api/assets-report?project=<id>   字元/圖示盤點
//   GET /api/projects                     專案索引

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { exec } from "node:child_process";
import { fileURLToPath } from "node:url";
import { buildReport } from "./assets.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, ".."); // = lvgl-console-ui/

// 參數可以任意順序：數字 = port、--open = 開瀏覽器
const ARGS = process.argv.slice(2);
const PORT = Number(ARGS.find((a) => /^\d+$/.test(a)) ?? 8610);
const HOST = "127.0.0.1";
const OPEN = ARGS.includes("--open");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".bin": "application/octet-stream",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};

function send(res, status, body, type = "text/plain; charset=utf-8") {
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(String(body), "utf8");
  res.writeHead(status, { "content-type": type, "cache-control": "no-store", "content-length": buf.length });
  res.end(buf);
}

const sendJson = (res, obj) => send(res, 200, JSON.stringify(obj), "application/json; charset=utf-8");

const server = http.createServer((req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    const urlPath = decodeURIComponent(url.pathname);

    // ── API ──
    if (urlPath === "/api/assets-report") {
      sendJson(res, buildReport(url.searchParams.get("project") ?? undefined));
      return;
    }
    if (urlPath === "/api/projects") {
      sendJson(res, JSON.parse(fs.readFileSync(path.join(ROOT, "projects.json"), "utf8")));
      return;
    }

    // ── 靜態（ROOT = lvgl-console-ui/）──
    let file = path.normalize(path.join(ROOT, urlPath === "/" ? "/index.html" : urlPath));
    if (!file.startsWith(ROOT)) {
      send(res, 403, "forbidden");
      return;
    }
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!fs.existsSync(file)) {
      send(res, 404, `404 ${urlPath}`);
      return;
    }
    const ext = path.extname(file).toLowerCase();
    send(res, 200, fs.readFileSync(file), MIME[ext] ?? "application/octet-stream");
  } catch (e) {
    send(res, 500, String(e?.stack || e));
  }
});

server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error(`[serve] port ${PORT} 已被占用。`);
    console.error(`[serve] 可能已經開著了 → 直接開 http://${HOST}:${PORT}/`);
    console.error(`[serve] 或換一個 port：node cli/serve.mjs ${PORT + 1}`);
  } else {
    console.error("[serve] 啟動失敗：", e.message);
  }
  process.exitCode = 1;
});

server.listen(PORT, HOST, () => {
  const url = `http://${HOST}:${PORT}/`;
  console.log(`[serve] root = ${ROOT}`);
  console.log(`[serve] ${url}`);
  console.log("[serve] Ctrl+C 停止");
  if (OPEN) {
    // 等 listen 完才開瀏覽器，避免第一次連線被拒
    const cmd =
      process.platform === "win32"
        ? `start "" "${url}"`
        : process.platform === "darwin"
          ? `open "${url}"`
          : `xdg-open "${url}"`;
    exec(cmd, () => {});
  }
});
