# vendor.py — 離線資源下載
#
# 把工具依賴的外部資源下載到 workspace/cache/vendor/,之後全離線操作:
#   lucide.min.js           設計稿圖示（原 unpkg CDN）
#   tailwind.index.global.js  tailwind browser runtime（原 jsdelivr CDN）
#   sim/                    模擬器（sim.lvgl.io v9.0 javascript port）
#
# 下載只做一次;無網時 fallback（log 警告,不崩潰）。
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import CACHE_DIR

VENDOR_DIR = CACHE_DIR / "vendor"
SIM_DIR = VENDOR_DIR / "sim"

# (本地檔名, 遠端 URL)
VENDOR_FILES = [
    ("lucide.min.js",
     "https://unpkg.com/lucide@1.8.0/dist/umd/lucide.min.js"),
    ("tailwind.index.global.js",
     "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.1/dist/index.global.js"),
]

SIM_URL = "https://sim.lvgl.io/v9.0/micropython/ports/javascript/"
SIM_INDEX = "index.html"

_ATTR_RE = re.compile(r'(?:src|href)="([^"]+)"')


def _fetch(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _download(url: str, dest: Path, log) -> bool:
    try:
        data = _fetch(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log and log(f"↓ {url.split('/')[-1] if len(url) < 90 else url[:90]}… "
                    f"({len(data)//1024} KB)")
        return True
    except Exception as e:
        log and log(f"  ✗ 下載失敗 {url}: {e}")
        return False


def is_ready() -> bool:
    """vendor 全部就緒（可離線）。含模擬器 runtime（lvgl.html/micropython/wasm）。"""
    ok = all((VENDOR_DIR / n).exists() for n, _u in VENDOR_FILES)
    runtime = [
        SIM_DIR / "lvgl.html",
        SIM_DIR / "micropython.js",
        SIM_DIR / "firmware.wasm",
    ]
    return ok and (SIM_DIR / SIM_INDEX).exists() and all(p.exists() for p in runtime)


# 模擬器 index.html 的 CDN URL → 本地相對路徑（相對於 /sim/）
_CDN_MAP = [
    ("https://cdnjs.cloudflare.com/ajax/libs/bootstrap/4.5.3/css/bootstrap.min.css",
     "./ajax/libs/bootstrap/4.5.3/css/bootstrap.min.css"),
    ("https://cdnjs.cloudflare.com/ajax/libs/bootstrap/4.5.3/js/bootstrap.min.js",
     "./ajax/libs/bootstrap/4.5.3/js/bootstrap.min.js"),
    ("https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.9.0/css/all.min.css",
     "./ajax/libs/font-awesome/5.9.0/css/all.min.css"),
    ("https://cdnjs.cloudflare.com/ajax/libs/lz-string/1.4.4/lz-string.js",
     "./ajax/libs/lz-string/1.4.4/lz-string.js"),
    ("https://cdnjs.cloudflare.com/ajax/libs/axios/0.19.0/axios.min.js",
     "./ajax/libs/axios/0.19.0/axios.min.js"),
    ("https://cdnjs.cloudflare.com/ajax/libs/popper.js/2.4.0/umd/popper.min.js",
     "./ajax/libs/popper.js/2.4.0/umd/popper.min.js"),
    ("https://code.jquery.com/jquery-1.12.4.js",
     "./jquery-1.12.4.js"),
]


def _rewrite_sim_index(log) -> None:
    """把模擬器 index.html 的 CDN 引用改寫成本地路徑(可離線載入)。"""
    idx = SIM_DIR / SIM_INDEX
    if not idx.exists():
        return
    txt = idx.read_text(encoding="utf-8", errors="replace")
    changed = 0
    for cdn, local in _CDN_MAP:
        if cdn in txt:
            txt = txt.replace(cdn, local)
            changed += 1
    # Google Fonts 下載失敗 → 移除（缺字型只影響樣式,不影響載入）
    txt = re.sub(r'<link[^>]*fonts\.googleapis\.com[^>]*>', "", txt)
    idx.write_text(txt, encoding="utf-8")
    if changed:
        log and log(f"模擬器 index: {changed} 個 CDN 引用已改本地")


def ensure_vendor(log=None, force_patch=False) -> dict:
    """確保 vendor 資源已下載,回傳狀態。

    force_patch=True 時即使 lvgl.html/index.html 已存在也重新 patch（新版程式碼改寫
    注入 JS）。
    """
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    status = {"lucide": False, "tailwind": False, "sim": False}
    for name, url in VENDOR_FILES:
        dest = VENDOR_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            status["lucide" if name.startswith("lucide")
                   else "tailwind"] = True
            continue
        status["lucide" if name.startswith("lucide")
               else "tailwind"] = _download(url, dest, log)
    status["sim"] = _download_sim(log)
    if force_patch:
        status["sim"] = status["sim"] and _patch_lvgl_html(log=log) is not False
    _rewrite_sim_index(log)
    return status


def _patch_lvgl_html(log=None) -> bool:
    """補寫（或重寫）lvgl.html 的 CDN patch + MEMFS seed。回傳 True=有更動。

    用於 vendor.ensure_vendor(force_patch=True) 或使用者在 UI 按「重新下載模擬器」
    後要補最新注入 JS 時呼叫。邏輯等同 _download_sim() 裡「改寫 lvgl.html 的 CDN →
    本地」那段。為避免重入,把 patch 後的 lvgl.html 第一行內嵌 tag
    `<!-- LVGL-UI-STUDIO-PATCHED -->`,下次重入可以偵測。
    """
    lvgl = SIM_DIR / "lvgl.html"
    if not lvgl.exists():
        return False
    txt = lvgl.read_text(encoding="utf-8", errors="replace")
    orig = txt
    _TAG = "<!-- LVGL-UI-STUDIO-PATCHED -->"
    # 先移除舊 tag（如果存在舊版注入）,確保能重複 patch
    if _TAG in txt:
        # 簡單暴力：移除 BEGIN LVGL UI STUDIO → END LVGL UI STUDIO 整段（含前後空白）
        import re as _re
        txt = _re.sub(
            r"\s*// --- BEGIN LVGL UI STUDIO: seed MEMFS with /sim driver&lib \.py ---.*?"
            r"// --- END LVGL UI STUDIO ---\s*",
            "\n",
            txt,
            flags=_re.DOTALL,
        )
    for cdn, local in [
        ("https://cdnjs.cloudflare.com/ajax/libs/BrowserFS/2.0.0/browserfs.js",
         "./ajax/libs/BrowserFS/2.0.0/browserfs.js"),
        ("https://cdnjs.cloudflare.com/ajax/libs/lz-string/1.4.4/lz-string.js",
         "./ajax/libs/lz-string/1.4.4/lz-string.js"),
        ("https://code.jquery.com/jquery-1.12.4.js", "./jquery-1.12.4.js"),
    ]:
        txt = txt.replace(cdn, local)
    txt = txt.replace(
        "sys.path.append('https://raw.githubusercontent.com/"
        "littlevgl/lv_binding_micropython/${lvBindingsCommitHash}/driver/js')",
        "sys.path.append('/sim/driver/js')")
    txt = txt.replace(
        "sys.path.append('https://raw.githubusercontent.com/"
        "littlevgl/lv_binding_micropython/${lvBindingsCommitHash}/lib')",
        "sys.path.append('/sim/lib')")
    _py_fetch_inject = r'''
// --- BEGIN LVGL UI STUDIO: seed MEMFS with /sim driver&lib .py ---
            (function () {
              var simBase = location.href.substring(0, location.href.lastIndexOf('/'));
              if (!simBase.endsWith('/')) simBase = simBase + '/';
              // driver/lib 是靜態檔：先查 sessionStorage（跨 reload 免抓），再查 MEMFS
              // （同頁面重複執行免抓），都沒有才同步 XHR fetch。
              var CACHE_KEY = 'lvglsim:' + simBase + ':';
              function syncFetchText(url) {
                try {
                  var x = new XMLHttpRequest();
                  x.open('GET', url, false);
                  try { x.responseType = 'text'; } catch (e) {}
                  x.send(null);
                  if (x.status === 200 || x.status === 0) return x.responseText;
                } catch (e) {}
                return null;
              }
              function ensureDir(path) {
                var parts = path.split('/').filter(Boolean);
                var cur = '/';
                for (var i = 0; i < parts.length; i++) {
                  cur = cur + parts[i] + '/';
                  try { FS.mkdir(cur.replace(/\/$/, '')); } catch (e) { if (e && e.code !== 'EEXIST') { throw e; } }
                }
              }
              function writePy(vfsPath, url) {
                try { if (FS.analyzePath(vfsPath).exists) return true; } catch (e) {}
                var text = null;
                try { text = sessionStorage.getItem(CACHE_KEY + vfsPath); } catch (e) {}
                if (text == null) text = syncFetchText(url);
                if (text == null) return false;
                ensureDir(vfsPath.substring(0, vfsPath.lastIndexOf('/')));
                try { FS.createDataFile('/', vfsPath.substring(1), text, true, true); }
                catch (e) { if (e && e.code !== 'EEXIST') return false; }
                try { sessionStorage.setItem(CACHE_KEY + vfsPath, text); } catch (e) {}
                return true;
              }
              var files = [
                ['/sim/lib/display_driver.py',        simBase + 'lib/display_driver.py'],
                ['/sim/lib/display_driver_utils.py',  simBase + 'lib/display_driver_utils.py'],
                ['/sim/lib/fs_driver.py',             simBase + 'lib/fs_driver.py'],
                ['/sim/lib/lv_colors.py',             simBase + 'lib/lv_colors.py'],
                ['/sim/lib/lv_utils.py',              simBase + 'lib/lv_utils.py'],
                ['/sim/lib/tpcal.py',                 simBase + 'lib/tpcal.py'],
                ['/sim/lib/utils.py',                 simBase + 'lib/utils.py'],
                ['/sim/driver/js/lv_timer.py',        simBase + 'driver/js/lv_timer.py'],
              ];
              var ok = 0;
              for (var i = 0; i < files.length; i++) {
                if (writePy(files[i][0], files[i][1])) ok++;
              }
              window.__lvgl_sim_seed_ok = ok;
              console.log("[MEMFS] seeded " + ok + "/" + files.length + " driver/lib .py (sim base=" + simBase + ")");
              // 板端 ui_common 開 '/ui/lvgl/src/*.bin'（字體/圖示）。Python 端 urequests
              // 在 wasm 無 socket 抓不了，這裡用 JS 同步 XHR 從 dlib fetch 寫入 MEMFS。
              try { ensureDir('/ui/lvgl/src'); } catch (e) {}
              (function () {
                var designName = (_simConfig && _simConfig.design) || "";
                if (!designName) return;
                function syncFetchBin(url) {
                  // 同步 XHR 的 arraybuffer 在 iframe 內不可靠（status 200 但 response 空），
                  // 改用 wasm_file_api 同款的「latin1 字串 + charCodeAt」二進位讀法。
                  try {
                    var x = new XMLHttpRequest();
                    x.open('GET', url, false);
                    try { x.overrideMimeType('text/plain; charset=x-user-defined'); } catch (e) {}
                    x.send(null);
                    var txt = x.responseText || '';
                    var len = txt.length;
                    if (x.status === 200 && len > 0) {
                      var out = new Uint8Array(len);
                      for (var i = 0; i < len; i++) out[i] = txt.charCodeAt(i) & 0xff;
                      return { status: x.status, len: len, resp: out };
                    }
                    return { status: x.status, len: 0, resp: null };
                  } catch (e) {
                    return { status: -1, len: -1, err: String(e) };
                  }
                }
                function writeBin(vfsPath, data) {
                  ensureDir(vfsPath.substring(0, vfsPath.lastIndexOf('/')));
                  try { FS.unlink(vfsPath); } catch (e) {}
                  try {
                    FS.createDataFile('/', vfsPath.substring(1), new Uint8Array(data), true, true);
                    return true;
                  } catch (e) { return false; }
                }
                function binToB64(u8) {
                  var s = '';
                  for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                  try { return btoa(s); } catch (e) { return null; }
                }
                function b64ToBin(b64) {
                  var s = atob(b64), out = new Uint8Array(s.length);
                  for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 0xff;
                  return out;
                }
                var binNames = ['zh_hant_16.bin', 'icons_16.bin'];
                var srcCands = [
                  location.origin + '/dlib/' + designName + '/lvgl/ui/src/',
                  location.origin + '/dlib/' + designName + '/ui/src/',
                  location.origin + '/dlib/' + designName + '/src/',
                ];
                var binLog = ['design=' + designName];
                for (var bi = 0; bi < binNames.length; bi++) {
                  // 已寫入（同頁面重複執行）→ 跳過；sessionStorage 快取（跨 reload 免抓）
                  var vp = '/ui/lvgl/src/' + binNames[bi];
                  try { if (FS.analyzePath(vp).exists) { binLog.push(binNames[bi] + ' MEMFS'); continue; } } catch (e) {}
                  var cached = null;
                  try { cached = sessionStorage.getItem('lvglsim:' + designName + ':' + binNames[bi]); } catch (e) {}
                  if (cached != null && cached.length > 0) {
                    try {
                      var cdata = b64ToBin(cached);
                      if (writeBin(vp, cdata)) {
                        binLog.push(binNames[bi] + ' CACHE ' + cdata.length);
                        console.log("[bin] cached " + binNames[bi] + " (" + cdata.length + " bytes)");
                        continue;
                      }
                    } catch (e) {}
                  }
                  for (var si2 = 0; si2 < srcCands.length; si2++) {
                    var r = syncFetchBin(srcCands[si2] + binNames[bi]);
                    binLog.push(binNames[bi] + '[' + si2 + '] status=' + r.status + ' len=' + r.len + (r.err ? ' err=' + r.err : ''));
                    if (r.resp && writeBin(vp, r.resp)) {
                      binLog.push(binNames[bi] + ' WRITTEN ' + r.len);
                      console.log("[bin] seeded " + binNames[bi] + " (" + r.len + " bytes)");
                      try { sessionStorage.setItem('lvglsim:' + designName + ':' + binNames[bi], binToB64(r.resp)); } catch (e) {}
                      break;
                    }
                  }
                }
                try {
                  FS.writeFile('/__bin_log', binLog.join('\n') || 'none');
                } catch (e) {}
              })();

              // --- LVGL UI STUDIO: dlib ui .py 預載（加速 framework 啟動） ---
              // framework 的 Python urequests 在 wasm 走同步 bridge 很慢；JS 逐檔 XHR
              // 在隱藏 iframe 也慢（~280ms/請求）。改為一次請求 /api/design/simfiles
              // 拿全部 ui .py 內容，寫進 /_wsp/{design}/（含 src/、page/）再寫
              // .preloaded 標記 — Python 端見到標記就完全跳過 preload。
              (function () {
                var designName = (_simConfig && _simConfig.design) || "";
                if (!designName) return;
                var wspRoot = '/_wsp/' + designName;
                function fetchText(url) {
                  try {
                    var x = new XMLHttpRequest();
                    x.open('GET', url, false);
                    x.send(null);
                    if (x.status === 200) return x.responseText;
                  } catch (e) {}
                  return null;
                }
                try { ensureDir(wspRoot + '/src'); ensureDir(wspRoot + '/page'); } catch (e) {}
                var text = fetchText(location.origin + '/api/design/simfiles?design=' + encodeURIComponent(designName));
                var total = 0;
                if (text != null) {
                  try {
                    var data = JSON.parse(text);
                    if (data && data.ok && data.files) {
                      var keys = Object.keys(data.files);
                      for (var ki = 0; ki < keys.length; ki++) {
                        var rel = keys[ki];
                        var fname = rel.substring(rel.lastIndexOf('/') + 1);
                        var sub = rel.indexOf('/') >= 0 ? rel.substring(0, rel.lastIndexOf('/')) : '';
                        var dir = (sub === 'src' || sub === 'page') ? '/' + sub : '';
                        try { FS.writeFile(wspRoot + dir + '/' + fname, data.files[rel]); total++; }
                        catch (e) {}
                      }
                    }
                  } catch (e) {}
                }
                if (total > 0) { try { FS.writeFile(wspRoot + '/.preloaded', String(total)); } catch (e) {} }
                console.log("[wsp] preloaded " + total + " ui .py -> " + wspRoot);
              })();

              // --- wasm_file_api shim：firmware 把 display_driver 等 driver 當「online module」，
              // import 時走 wasm_file_open/exists 去抓檔（不查 MEMFS/sys.path）。自架沒有
              // ?script= 參數，相對路徑抓檔失敗 → ImportError。這裡覆寫兩個函式：先查 MEMFS
              // （seed 的 /sim/ 與 framework preload 的 /_wsp/），命中就回傳本地檔，否則走原邏輯。
              if (typeof window.wasm_file_open === 'function' && typeof FS !== 'undefined') {
                // MEMFS log（Python 端 open('/__shim_log') 可讀）:診斷 shim 是否被呼叫
                function shimLog(msg) {
                  try {
                    var prev = '';
                    try { prev = FS.readFile('/__shim_log', { encoding: 'utf8' }); } catch (e) {}
                    FS.writeFile('/__shim_log', prev + msg + '\n');
                  } catch (e) {}
                }
                function memfsResolve(rel) {
                  var clean = String(rel).replace(/^:+/, '').replace(/^\/+/, '');
                  if (!clean) return null;
                  var base = clean.split('/').pop();
                  var cands = [
                    '/' + clean,
                    '/sim/lib/' + base,
                    '/sim/driver/js/' + base,
                    '/sim/' + clean,
                  ];
                  // framework shim 的 preload 目錄：/_wsp/{design}/{根,src,page}/
                  try {
                    var wspRoot = FS.analyzePath('/_wsp');
                    if (wspRoot.exists) {
                      var designDirs = FS.readdir('/_wsp');
                      for (var di = 0; di < designDirs.length; di++) {
                        var dn = designDirs[di];
                        if (dn === '.' || dn === '..') continue;
                        var subs = ['', '/src', '/page'];
                        for (var si = 0; si < subs.length; si++) {
                          var p = '/_wsp/' + dn + subs[si] + '/' + base;
                          try { if (FS.analyzePath(p).exists) return p; } catch (e) {}
                        }
                      }
                    }
                  } catch (e) {}
                  for (var ci = 0; ci < cands.length; ci++) {
                    try { if (FS.analyzePath(cands[ci]).exists) return cands[ci]; } catch (e) {}
                  }
                  return null;
                }
                // firmware 的 importer 對「點號 package 名」（ui.lvgl.registry）不拆解，
                // 直接找 ui.lvgl.registry.py 檔（404）。實務上板端 .py 都用平級檔名
                // （registry.py / control_panel.py），所以把點號名正規化成「最後一段」。
                // URL 版本也拆最後一段檔名的點號（.../ui/ui.lvgl.registry.py → .../ui/registry.py）。
                function normalizeModuleName(raw) {
                  var n = String(raw);
                  var isHttp = /^https?:\/\//i.test(n);
                  var prefix = '';
                  if (!isHttp && n.charAt(0) === ':') { prefix = ':'; n = n.slice(1); }
                  var slashIdx = n.lastIndexOf('/');
                  var dir = slashIdx >= 0 ? n.slice(0, slashIdx + 1) : '';
                  var fname = slashIdx >= 0 ? n.slice(slashIdx + 1) : n;
                  var stem = fname.endsWith('.py') ? fname.slice(0, -3) : fname;
                  var last = stem.split('.').pop();
                  if (last === stem) return raw;  // 無點號，不變
                  return prefix + dir + last + '.py';
                }
                var origExists = window.wasm_file_exists;
                var origOpen = window.wasm_file_open;
                // 裸模組名（無斜線、無 http）MEMFS 沒有 → 直接快速失敗。
                // 原 wasm_file_api 對相對路徑根本無法解析（無 ?script=），只會對
                // 一串候選 URL 逐個 404（uos/os/urequests 等非 builtin import 的
                // 請求風暴），快速失敗省掉整串探測。
                function bareLocalFail(norm) {
                  return norm.indexOf('/') < 0 && !/^https?:/i.test(norm);
                }
                window.wasm_file_exists = function (name, flag) {
                  var norm = normalizeModuleName(name);
                  try {
                    var hit = memfsResolve(norm);
                    shimLog('exists name=' + JSON.stringify(name) + ' norm=' + JSON.stringify(norm) + ' hit=' + hit);
                    if (hit) return 1;
                  } catch (e) {}
                  if (bareLocalFail(norm)) return -1;
                  return origExists ? origExists(norm, flag) : -1;
                };
                window.wasm_file_open = function (name, dest) {
                  var norm = normalizeModuleName(name);
                  var hit = null;
                  try { hit = memfsResolve(norm); } catch (e) {}
                  shimLog('open name=' + JSON.stringify(name) + ' norm=' + JSON.stringify(norm) + ' dest=' + JSON.stringify(dest) + ' hit=' + hit);
                  if (hit) {
                    try {
                      var data = FS.readFile(hit);
                      // 完全模仿原始 wasm_file_open 的回傳語意：
                      //   dest 有值 → 寫到 dest，回傳 length
                      //   dest 無值 → 寫到 /cache_{id}（id 遞增），回傳 id
                      // firmware 用回傳值當 handle 去讀 /cache_{id}。
                      var r = (typeof dest === 'string' && dest) ? dest : null;
                      window.urls.id += 1;
                      var a = data.length;
                      if (!r) { r = 'cache_' + window.urls.id; a = window.urls.id; }
                      try { FS.unlink('/' + r); } catch (e) {}
                      FS.createDataFile('/', r, data, true, true);
                      shimLog('  open SERVED len=' + data.length + ' dest=' + r + ' ret=' + a);
                      return a;
                    } catch (e) { shimLog('  open serve-err ' + e); }
                  }
                  if (bareLocalFail(norm)) return -1;
                  return origOpen ? origOpen(norm, dest) : -1;
                };
                try { FS.writeFile('/__shim_installed', 'ok'); } catch (e) {}
                shimLog('SHIM INSTALLED at ' + Date.now());
                console.log("[wasm_file_api] MEMFS-first shim installed");
              } else {
                console.log("[wasm_file_api] shim NOT installed: wasm_file_open=" + typeof window.wasm_file_open + " FS=" + typeof FS);
              }
            })();
            // --- END LVGL UI STUDIO ---
'''
    # 只在第一次 patch 時注入（若已注入過則不重複）
    if "seed MEMFS with" not in txt:
        txt = txt.replace(
            "mp_js_init(requestedMemory);",
            "mp_js_init(requestedMemory);\n" + _py_fetch_inject)
    if not txt.startswith(_TAG):
        txt = _TAG + "\n" + txt
    changed = (txt != orig)
    if changed:
        lvgl.write_text(txt, encoding="utf-8")
        log and log("lvgl.html CDN 引用已改本地")
    return changed


def _download_sim(log) -> bool:
    """遞迴下載模擬器(index.html + 它引用的所有資源,含相對路徑)。"""
    if (SIM_DIR / SIM_INDEX).exists() and (SIM_DIR / "app.").exists() or False:
        pass
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    log and log("下載模擬器(sim.lvgl.io v9.0)…")
    try:
        html = _fetch(SIM_URL + SIM_INDEX)
    except Exception as e:
        log and log(f"  ✗ 模擬器 index 下載失敗: {e}")
        return False
    (SIM_DIR / SIM_INDEX).write_bytes(html)

    # 收集所有資源 URL(絕對 + 相對),含 inline 內的 src
    refs: set[str] = set()
    for m in _ATTR_RE.finditer(html.decode("utf-8", "replace")):
        u = m.group(1).strip()
        if not u or u in ("#",) or u.startswith(("javascript:", "mailto:", "tel:", "about:")):
            continue
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http"):
            refs.add(u)
        elif u.startswith("./") or u.startswith("../") or (not u.startswith("#")):
            # 相對路徑 → 相對 index 所在目錄
            base = SIM_URL.rstrip("/") + "/"
            refs.add(urllib.parse.urljoin(base, u))

    # 排除文件網址(如 docs.lvgl.io)與 github 頁面
    skip_hosts = ("docs.lvgl.io", "github.com")
    refs = {u for u in refs if not any(h in u for h in skip_hosts)}

    if not refs:
        log and log("  ⚠ 模擬器 index 未發現外部資源（可能全內嵌）")
    for u in sorted(refs):
        dest = _sim_local_path(u)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        _download(u, dest, log)

    # 清掉誤抓的 html 頁面(非檔案資源)
    for f in SIM_DIR.rglob("*"):
        if f.is_file() and f.stat().st_size == 0 and f.name != SIM_INDEX:
            f.unlink()

    # ── 模擬器 runtime（lvgl.html + micropython + wasm + BrowserFS） ──
    runtime_files = ["lvgl.html", "micropython.js", "wasm_file_api.js",
                     "firmware.wasm"]
    for name in runtime_files:
        dest = SIM_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        _download(SIM_URL + name, dest, log)
    bfs = SIM_DIR / "ajax/libs/BrowserFS/2.0.0/browserfs.js"
    if not bfs.exists():
        _download("https://cdnjs.cloudflare.com/ajax/libs/BrowserFS/2.0.0/browserfs.js",
                  bfs, log)

        # 改寫 lvgl.html 的 CDN → 本地（委派幂等版:已 patch 過就跳過,避免每次重啟重複插入 seed 區塊）
    _patch_lvgl_html(log)
    # MicroPython driver/lib（模擬器 import 用,離線）
    _download_sim_driver(log)
    return (SIM_DIR / SIM_INDEX).exists()


# lvgl.html 啟動會 import 的 driver/lib（GitHub lv_binding_micropython commit 5e80637）
_SIM_COMMIT = "5e8063717ae81c9ea7fc97c45879479541721f04"
_SIM_DRIVER = {
    "driver/js": ["lv_timer.py"],
    "lib": ["display_driver.py", "display_driver_utils.py", "fs_driver.py",
            "lv_colors.py", "lv_utils.py", "tpcal.py", "utils.py"],
}


def _download_sim_driver(log) -> None:
    """下載模擬器 import 的 MicroPython driver/lib 到本地（離線用）。"""
    base = ("https://raw.githubusercontent.com/littlevgl/"
            f"lv_binding_micropython/{_SIM_COMMIT}/")
    for sub, files in _SIM_DRIVER.items():
        d = SIM_DIR / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = d / f
            if dest.exists() and dest.stat().st_size > 0:
                continue
            _download(base + sub + "/" + f, dest, log)


def _sim_local_path(url: str) -> Path:
    """把模擬器資源 URL 對映到本地路徑（剝掉版本/port 前綴,保留檔名結構）。

    https://sim.lvgl.io/v9.0/micropython/ports/javascript/app.js
        → sim/app.js
    https://cdnjs.cloudflare.com/ajax/libs/bootstrap/4.5.3/css/bootstrap.min.css
        → sim/4.5.3/css/bootstrap.min.css
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lstrip("/")
    parts = path.split("/")
    # 剝掉 sim.lvgl.io 的 vX.Y.Z/micropython/ports/javascript 前綴
    while parts and parts[0] not in ("micropython", "javascript"):
        if parts[0] in ("v9.0", "v8.3", "v7.11", "v6.1") or (
                parts[0].startswith("v") and "." in parts[0]):
            parts.pop(0)
        elif parts[0] == "micropython":
            break
        else:
            # cdn 的資源:保留 cdn 路徑(cdnjs.cloudflare.com/ajax/libs/...)
            break
    # 移除 micropython/ports/javascript 前綴
    while parts and parts[0] in ("micropython", "ports", "javascript"):
        parts.pop(0)
    rel = "/".join(parts) if parts else "resource"
    return SIM_DIR / rel


def sim_index_path() -> Path | None:
    if (SIM_DIR / SIM_INDEX).exists():
        return SIM_DIR / SIM_INDEX
    return None


def vendor_paths() -> dict:
    """回傳本地 vendor 路徑（給 server 提供 /cache/vendor/...）。"""
    return {
        "lucide": VENDOR_DIR / "lucide.min.js",
        "tailwind": VENDOR_DIR / "tailwind.index.global.js",
        "sim": SIM_DIR,
    }
