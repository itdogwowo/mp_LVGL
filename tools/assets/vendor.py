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


def ensure_vendor(log=None) -> dict:
    """確保 vendor 資源已下載,回傳狀態。"""
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
    _rewrite_sim_index(log)
    return status


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

    # 改寫 lvgl.html 的 CDN → 本地
    lvgl = SIM_DIR / "lvgl.html"
    if lvgl.exists():
        txt = lvgl.read_text(encoding="utf-8", errors="replace")
        for cdn, local in [
            ("https://cdnjs.cloudflare.com/ajax/libs/BrowserFS/2.0.0/browserfs.js",
             "./ajax/libs/BrowserFS/2.0.0/browserfs.js"),
            ("https://cdnjs.cloudflare.com/ajax/libs/lz-string/1.4.4/lz-string.js",
             "./ajax/libs/lz-string/1.4.4/lz-string.js"),
            ("https://code.jquery.com/jquery-1.12.4.js", "./jquery-1.12.4.js"),
        ]:
            txt = txt.replace(cdn, local)
        lvgl.write_text(txt, encoding="utf-8")
        log and log("lvgl.html CDN 引用已改本地")
    return (SIM_DIR / SIM_INDEX).exists()


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
