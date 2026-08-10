# designlib.py — design 庫管理
#
# tools/design/ 下可放多個 design,每個是一個資料夾,內含:
#   design.json    meta（名稱/解析度/頁面清單/互動 API 清單）
#   *.html / *.css 設計稿檔案
#
# design.json 由本模組掃描自動產生/更新,也可供 GUI 編輯:
#   {
#     "name": "LVGL 控制台",
#     "width": 320, "height": 240,
#     "pages": [{"id","title","file","tag"}, ...],
#     "interactions": [{"id","type","label"}, ...]
#   }
#
# 互動 API:掃 html 的 data-dom-id + <button> + <input>,
# 每個是一個「與 MPY 交互」的獨立按鈕/輸入點。
from __future__ import annotations

import re
import shutil
import string
from pathlib import Path

from . import TOOLS_DIR

DESIGN_LIB = TOOLS_DIR / "design"

# ── 資產分區：網頁設計（HTML 設計稿）vs LVGL 程式（.mpy 模擬代碼） ─────────────
# 所有在 design 根目錄出現的 HTML/CSS/圖資/design.json 一律視為「網頁設計區」。
# LVGL 程式碼嚴格只能出現在 LVGL_CODE_DIRS 指定的子目錄中，絕不混入根目錄。
# 匯入 ZIP 時，只會清理 & 寫入 LVGL_CODE_DIRS，不會碰到根目錄的 HTML/CSS。

LVGL_CODE_DIRS: tuple[str, ...] = ("lvgl", "ui")
# 根目錄副檔名若符合 WEB_ASSET_EXTS，屬於網頁設計資產，不允許刪除
WEB_ASSET_EXTS: tuple[str, ...] = (
    ".html", ".htm", ".css", ".js", ".mjs",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".wav", ".ogg", ".webm", ".mp4",
    ".json", ".txt", ".md", ".map",
)


def is_web_asset(path: Path, design_root: Path) -> bool:
    """判斷某個檔案/資料夾是不是「網頁設計區」資產（不得被 LVGL 匯入覆蓋）。

    規則：
      - 任何 design 根目錄下、副檔名屬於 WEB_ASSET_EXTS 的檔案 = 網頁資產
      - design 根目錄下副檔名不屬於 LVGL code 的檔案（如 .bin 資源）= 網頁資產
      - 不在 LVGL_CODE_DIRS 子目錄裡的檔案/目錄，若父輩是根目錄，歸屬網頁區
      - LVGL_CODE_DIRS 子目錄下的所有東西 = 程式碼區（可刪可換）
    """
    try:
        rel = path.relative_to(design_root).as_posix()
    except ValueError:
        return False
    if rel in ("", ".", "design.json"):
        return True
    head = rel.split("/", 1)[0]
    if head in LVGL_CODE_DIRS:
        return False
    return True


def web_assets_exist(design_name: str) -> bool:
    d = DESIGN_LIB / design_name
    return d.exists() and any(
        (p.suffix.lower() in WEB_ASSET_EXTS)
        for p in d.iterdir() if p.is_file())


def lvgl_code_exists(design_name: str) -> bool:
    d = DESIGN_LIB / design_name
    return d.exists() and any((d / s).exists() for s in LVGL_CODE_DIRS)


def design_kind(design_name: str) -> str:
    """回傳 'html' | 'lvgl' | 'mixed' | 'empty' """
    w = web_assets_exist(design_name)
    l = lvgl_code_exists(design_name)
    if w and l:
        return "mixed"
    if w:
        return "html"
    if l:
        return "lvgl"
    return "empty"


def clear_lvgl_code_only(design_name: str, keep_web_assets: bool = True) -> None:
    """只清理 LVGL 程式碼區，保留網頁設計區 & design.json。

    - 刪除 LVGL_CODE_DIRS（"lvgl"/"ui"）整個子目錄
    - 清理 design 根目錄中不屬於 WEB_ASSET_EXTS（也就是誤植的 .py / .bin 等）
      只在 keep_web_assets=True 且沒有同名 LVGL 目錄已存在時執行根目錄掃蕩
    """
    d = DESIGN_LIB / design_name
    if not d.exists():
        return
    for name in LVGL_CODE_DIRS:
        target = d / name
        if target.exists():
            shutil.rmtree(target)
    if keep_web_assets:
        for p in list(d.iterdir()):
            if p.name == "design.json":
                continue
            if p.name in LVGL_CODE_DIRS:
                continue  # 已經清掉了
            if p.is_file():
                if p.suffix.lower() not in WEB_ASSET_EXTS:
                    p.unlink()
            else:
                # 根目錄下未知的資料夾 → 只有當裡面沒有 HTML 設計稿時才清理
                has_web = any(
                    (sp.is_file() and sp.suffix.lower() in WEB_ASSET_EXTS)
                    for sp in p.rglob("*"))
                if not has_web:
                    shutil.rmtree(p)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_DOMID_RE = re.compile(r'data-dom-id="([^"]+)"')
# @register(id="...", title="...", icon="...") — 從產出的 page/*.py 抽頁面 meta
_REGISTER_RE = re.compile(
    r'@register\(\s*id="([^"]+)",\s*title="([^"]+)"(?:,\s*icon="([^"]*)")?')
_BUTTON_RE = re.compile(r"<button\b[^>]*>")
_INPUT_RE = re.compile(
    r"<(?:input|textarea|select)\b[^>]*(?:name|id)=\"([^\"]+)\"[^>]*>")
_SELECT_RE = re.compile(r'<select\b[^>]*>\s*<option')
_SLIDER_RE = re.compile(r'<input[^>]*type="range"')

_STYLE_RE = re.compile(r"<style([^>]*)>([\s\S]*?)</style>")
_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.I)
_SCRIPT_RE = re.compile(r"<script([^>]*)>([\s\S]*?)</script>", re.I)
_SRC_RE = re.compile(r'src="([^"]+)"')
_SCOPE = ".ds-scope"


def scope_css(css: str) -> str:
    """把全域選擇器(:root/html/body)限域到 .ds-scope,避免污染工具頁。

    :root      → .ds-scope
    html, body → .ds-scope（前面不是 . / _ / word char 才算,避免誤改 .ds-notif__body）
    body.xxx   → .ds-scope.xxx
    position:fixed → position:absolute（嵌入後不逃出 canvas）
    """
    css = re.sub(r"(?<![\w.-]):root\b", _SCOPE, css)
    css = re.sub(r"(?<![\w.-])\bhtml\b", _SCOPE, css)
    css = re.sub(r"(?<![\w.-])\bbody\b", _SCOPE, css)
    # 全域覆蓋偽元素(工作台紋理等)在嵌入後只蓋 canvas 不蓋工具頁
    css = css.replace("position: fixed;", "position: absolute;")
    return css


def extract_render(design_name: str, page_file: str) -> dict | None:
    """讀設計稿 html,拆成可原生嵌入工具頁的片段。

    回傳:
      html      body 內容
      styles    限域後的 <style> 列表
      scripts   外部 script 的本地/原 URL 列表
      inline    內嵌 script 內容列表
    """
    d = DESIGN_LIB / design_name
    p = d / Path(page_file).name
    if not p.exists():
        return None
    text = _read(p)

    meta = read_design(design_name) or {}
    styles: list[str] = []
    scripts: list[str] = []
    inline: list[str] = []

    for m in _STYLE_RE.finditer(text):
        attrs, css = m.groups()
        styles.append("<style{}>{}</style>".format(attrs, scope_css(css)))

    for m in _SCRIPT_RE.finditer(text):
        attrs, body = m.groups()
        src = _SRC_RE.search(attrs)
        if src:
            u = src.group(1)
            if u.startswith("http"):
                local = _vendor_rewrite(u)
                scripts.append(local or u)
            else:
                scripts.append("/dlib/{}/{}".format(design_name, u.lstrip("/")))
        elif body.strip():
            inline.append(body.strip())

    bm = _BODY_RE.search(text)
    html = bm.group(1) if bm else ""

    return {
        "name": meta.get("name", design_name),
        "width": meta.get("width", 320),
        "height": meta.get("height", 240),
        "html": html,
        "styles": styles,
        "scripts": scripts,
        "inline": inline,
    }


def _vendor_rewrite(url: str) -> str | None:
    """已知 CDN → 本地 vendor 路徑;其餘回 None。"""
    if "lucide" in url and url.endswith(".js"):
        return "/cache/vendor/lucide.min.js"
    if "tailwindcss" in url or "tailwind" in url:
        return "/cache/vendor/tailwind.index.global.js"
    return None


def render_full_html(design_name: str, page_file: str) -> str | None:
    """把設計稿改寫成「完整離線 HTML」（script 指本地 vendor,供 iframe 開）。

    與 extract_render 不同:回傳完整 HTML 文件,iframe 直接載入,
    不會污染工具主頁面,但 script 已改本地路徑。
    """
    d = DESIGN_LIB / design_name
    p = d / Path(page_file).name
    if not p.exists():
        return None
    text = _read(p)

    def _repl(m):
        attrs, body = m.groups()
        src = _SRC_RE.search(attrs)
        if src:
            u = src.group(1)
            if u.startswith("http"):
                local = _vendor_rewrite(u)
                if local:
                    attrs = _SRC_RE.sub(lambda mm: 'src="{}"'.format(local), attrs)
            elif not u.startswith("/"):
                # 相對路徑資源 → 指回 dlib（同 design 目錄）
                attrs = _SRC_RE.sub(
                    lambda mm: 'src="/dlib/{}/{}"'.format(design_name, u.lstrip("./")),
                    attrs)
        return "<script{}>{}</script>".format(attrs, body)

    text = _SCRIPT_RE.sub(_repl, text)
    return text


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------- 掃描 ----------
def scan_html_files(design_dir: Path) -> dict:
    """掃描一個 design 資料夾:頁面清單 + 互動 API + 檔案清單。"""
    htmls = sorted(p for p in design_dir.glob("*.html"))
    # launcher 優先（檔名含 launcher,否則第一個）
    htmls.sort(key=lambda p: (p.name != "launcher.html", p.name))

    pages = []
    for i, p in enumerate(htmls):
        title = p.stem
        m = _TITLE_RE.search(_read(p))
        if m:
            title = m.group(1).strip()
        pages.append({
            "id": "page-" + p.stem,
            "title": title,
            "file": p.name,
            "tag": "launcher" if p.name == "launcher.html" else "feature",
        })

    interactions: list[dict] = []
    seen = set()
    for p in htmls:
        txt = _read(p)
        for dom in _DOMID_RE.findall(txt):
            if dom not in seen:
                seen.add(dom)
                label = dom
                interactions.append({
                    "id": dom,
                    "type": "button",
                    "label": label,
                    "file": p.name,
                })
        for m in _INPUT_RE.finditer(txt):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                kind = "slider" if "type=\"range\"" in m.group(0) else "input"
                interactions.append({
                    "id": name,
                    "type": kind,
                    "label": name,
                    "file": p.name,
                })
        # 無 name/id 的 range 輸入（如 ds-slider）
        for m in _SLIDER_RE.finditer(txt):
            snippet = txt[max(0, m.start() - 60):m.end()]
            mm = re.search(r'id="([^"]+)"', snippet)
            if mm and mm.group(1) not in seen:
                seen.add(mm.group(1))
                interactions.append({
                    "id": mm.group(1),
                    "type": "slider",
                    "label": mm.group(1),
                    "file": p.name,
                })

    return {
        "pages": pages,
        "interactions": interactions,
        "files": sorted(f.name for f in design_dir.iterdir() if f.is_file()),
    }


def scan_lvgl_pages(design_dir: Path) -> list[dict]:
    """code-only design（無 html,由外部專案導入 lvgl/ui 或 ui 或直接平鋪）:
    從 lvgl/ui/page/*.py、ui/page/*.py 或根 page/*.py 的 @register 抽出頁面清單。"""
    ui_dirs = [
        design_dir / "lvgl" / "ui",
        design_dir / "ui",
        design_dir,  # 最後 fallback: ui/ 整個被展開到 design 根
    ]
    pages: list[dict] = []
    ui = next((u for u in ui_dirs if u.exists() and (
        (u / "launcher.py").is_file() or (u / "page").is_dir())), None)
    if ui is None:
        return pages
    is_root = (ui == design_dir)
    if (ui / "launcher.py").exists():
        rel_ui = "" if is_root else ui.relative_to(design_dir).as_posix()
        pages.append({
            "id": "launcher",
            "title": "功能選擇",
            "file": (f"{rel_ui}/launcher.py").lstrip("/") if rel_ui else "launcher.py",
            "tag": "launcher",
        })
    page_dir = ui / "page"
    if page_dir.exists():
        rel_ui = "" if is_root else ui.relative_to(design_dir).as_posix()
        prefix = f"{rel_ui}/page/" if rel_ui else "page/"
        for p in sorted(page_dir.glob("*.py")):
            if p.name == "__init__.py":
                continue
            m = _REGISTER_RE.search(_read(p))
            if not m:
                continue
            pages.append({
                "id": m.group(1),
                "title": m.group(2),
                "icon": m.group(3) or "",
                "file": prefix + p.name,
                "tag": "feature",
            })
    return pages


def read_design(name: str) -> dict | None:
    d = DESIGN_LIB / name
    jf = d / "design.json"
    if not jf.exists():
        return None
    import json

    try:
        meta = json.loads(jf.read_text(encoding="utf-8"))
        meta["name"] = meta.get("name", name)
        meta.setdefault("width", 320)
        meta.setdefault("height", 240)
        meta.setdefault("pages", [])
        meta.setdefault("interactions", [])
        meta["dir"] = str(d)
        return meta
    except (OSError, ValueError):
        return None


def _ui_candidates(design_name: str) -> tuple[Path, Path | None]:
    """回傳 (lv 根, ui 目錄)；優先 lvgl/ui, 其次平鋪 ui/, 最後 design 根本身。"""
    d = DESIGN_LIB / design_name
    for ui_path in [d / "lvgl" / "ui", d / "ui"]:
        if ui_path.exists():
            return (ui_path.parent.parent if ui_path.parent.name == "ui" else d), ui_path
    # Fallback: 當 design 根本身就是 ui 展開（有 launcher.py + page/)
    if (d / "launcher.py").exists() or (d / "page").exists():
        return d, d
    return d / "lvgl", None


def lvgl_path(design_name: str) -> Path:
    """該 design 的 LVGL 輸出路徑（lvgl/ 根；若僅 ui/ 平鋪則回 design 根）。"""
    lv, _ = _ui_candidates(design_name)
    return lv


def lvgl_src_path(design_name: str) -> Path:
    """資源進 ui 內:板上只上傳 ui/ 一個資料夾即根目錄。"""
    lv, ui = _ui_candidates(design_name)
    if ui is None:
        return lvgl_path(design_name) / "ui" / "src"
    return ui / "src"


def lvgl_status(design_name: str) -> dict:
    """回傳該 design 的 lvgl 產出狀態（框架/資源是否已生成）。"""
    lv, ui = _ui_candidates(design_name)
    src = ui / "src" if ui else None
    return {
        "exists": lv.exists() and ui is not None,
        "ui_files": sorted(p.name for p in ui.glob("*.py")) if ui else [],
        "src_files": sorted(p.name for p in src.iterdir()) if src and src.exists() else [],
    }


# ---------- 模擬器展示代碼生成 ----------
# 自包含展示碼:不依賴 ui_common/字體,直接在模擬器跑出「設計稿的互動點」。
SIMCODE_TEMPLATE = '''# {title} · {page_title}（由 LVGL UI Asset Studio 自動生成,可編輯）
# 模擬器展示碼:依 design.json 的互動 API 建立按鈕/滑桿。
import display_driver
import lvgl as lv

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0xF5F5F5), 0)

title = lv.label(scr)
title.set_text("{page_title}")
title.align(lv.ALIGN.TOP_MID, 0, 8)

_widgets = []


def _on_click(e, name):
    print("[click]", name)


{widgets_code}
lv.screen_load(scr)
'''

_WIDGET_BUTTON = '''b{i} = lv.button(scr)
b{i}.set_size(140, 40)
b{i}.set_pos(20, {y})
b{i}.set_style_bg_color(lv.color_hex(0x1A73E8), 0)
b{i}.add_event_cb(lambda e, n="{id}": _on_click(e, n), lv.EVENT.CLICKED, None)
_l = lv.label(b{i})
_l.set_text("{id}")
_l.align(lv.ALIGN.CENTER, 0, 0)
_widgets.append(b{i})
'''

_WIDGET_SLIDER = '''lb{i} = lv.label(scr)
lb{i}.set_text("{id}")
lb{i}.set_pos(20, {y})
s{i} = lv.slider(scr)
s{i}.set_range(0, 100)
s{i}.set_value(50, 0)
s{i}.set_pos(20, {y} + 22)
s{i}.set_size(140, 10)
s{i}.add_event_cb(lambda e: print("[slider]", "{id}", s{i}.get_value()), lv.EVENT.VALUE_CHANGED, None)
_widgets.append(s{i})
'''


def simcode(design_name: str, page_file: str) -> str:
    """生成模擬器展示代碼(自包含,含該頁的互動元素)。"""
    meta = read_design(design_name) or {}
    pages = meta.get("pages", [])
    page = next((p for p in pages if p["file"] == Path(page_file).name), None)
    if page is None and pages:
        page = pages[0]
    page_title = page.get("title", page_file) if page else page_file

    # 該頁的互動元素
    iap = [i for i in meta.get("interactions", [])
           if i.get("file") == Path(page_file).name]

    widgets_code = []
    for i, item in enumerate(iap):
        y = 52 + (i % 4) * 46
        if item.get("type") in ("input", "slider"):
            widgets_code.append(
                _WIDGET_SLIDER.format(i=i, id=item["id"], y=y))
        else:
            widgets_code.append(
                _WIDGET_BUTTON.format(i=i, id=item["id"], y=y))
    if not widgets_code:
        widgets_code.append('# 此頁無互動元素,可自行加入 widget')

    return SIMCODE_TEMPLATE.format(
        title=meta.get("name", design_name),
        page_title=page_title,
        widgets_code="\n".join(widgets_code))


# ui 框架模式:在模擬器跑 design 的 ui/app（純 UI,不碰 machine）
FRAMEWORK_CODE = """# ui framework shim — WebAssembly simulator <> ESP32 UI project translation layer.
#
# 解決三大不相容：
#   1. MicroPython wasm importer 對「import ui.lvgl.xxx」package 形式不穩定
#      → 在 sys.modules 預裝虛擬 package，attribute access 自動轉平級模組。
#   2. 板端服務（lib.sys_bus.bus、lib.hw_manager、I2C/SPI/LCD）不存在
#      → WebStubBus + _BusAdapter + _consume_input shim，讓 lvgl_init / board 能直接跑
#   3. URL sys.path（http://...）wasm imp 不總是能 lookup 到檔案
#      → 在 import 之前先 _preload() 把所有 dlib 的 .py 同步 fetch 寫進 MEMFS（/_wsp/${design}），
#        sys.path 使用本機 MEMFS 路徑（而非 URL）。
# ----------------------------------------------------------------------------
import imp as _imp, usys as _sys
_W, _H = ${width}, ${height}

# 0) 路徑：把所有 dlib_* URL 的 .py 同步拉到 MEMFS
try:
    import uos as _os
except Exception:
    try:
        import os as _os
    except Exception:
        _os = None


def _mkdirs(p):
    if not p or not _os:
        return
    parts = []
    for seg in p.split('/'):
        if not seg:
            continue
        parts.append(seg)
        d = '/' + '/'.join(parts)
        try:
            _os.mkdir(d)
        except Exception:
            pass


def _get_url(url):
    try:
        import urequests as _rq
        r = _rq.get(url)
        try:
            if r.status_code != 200:
                return None
            try:
                data = r.content
            except Exception:
                data = r.text
                if isinstance(data, str):
                    data = data.encode('utf-8')
            return data
        finally:
            try: r.close()
            except Exception: pass
    except Exception:
        return None


_DLIB_URLS = ['${dlib_ui}', '${dlib_src}', '${dlib_page}', '${dlib_lvgl_root}']
_WSP = '/_wsp/${design}'
_WSP_PATHS = [_WSP + '/src', _WSP + '/page', _WSP]
if _os is None:
    # 沒有檔系統就直接塞 URL path（舊作法 fallback）
    for _u in _DLIB_URLS:
        if _u and _u not in _sys.path:
            _sys.path.insert(0, _u)
else:
    for _p in _WSP_PATHS:
        _mkdirs(_p)
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    print("[fw] MEMFS wsp:", _WSP_PATHS)


def _preload_file(url, fname):
    """url 單一 .py → 寫到 /_wsp/${design}/{fname}。"""
    if _os is None or not url or not fname:
        return False
    data = _get_url(url)
    if data is None:
        return False
    target = _WSP + '/' + fname
    try:
        f = open(target, 'wb')
        try: f.write(data)
        finally: f.close()
        return True
    except Exception:
        return False


def _preload_dir(dir_url, rel_prefix):
    """抓 dir_url/index.html 解析出 <a> 連結，把所有 *.py fetch 到 MEMFS。
    我們的 _serve_dlib 會 autoindex，因此 dir_url 回來有 <a href="..."> 可解析。"""
    if _os is None or not dir_url:
        return 0
    html = _get_url(dir_url + '/')
    if html is None:
        html = _get_url(dir_url)
    if html is None:
        return 0
    try:
        s = html.decode('utf-8', errors='replace') if isinstance(html, (bytes, bytearray)) else str(html)
    except Exception:
        return 0
    import ure as _re
    try:
        import re as _re
    except Exception:
        pass
    # 解析 <a href="xxx.py">
    try:
        pat = _re.compile(r'href="([^"]+\.py)"')
    except Exception:
        return 0
    cnt = 0
    last = 0
    while True:
        try:
            m = pat.search(s, last)
        except Exception:
            break
        if not m:
            break
        last = m.end()
        href = m.group(1)
        if href.startswith('http://') or href.startswith('https://'):
            furl = href
        elif href.startswith('/'):
            # 絕對
            origin = dir_url.split('/', 3)[0] + '//' + dir_url.split('/', 3)[2]
            furl = origin + href
        else:
            base = dir_url[:-1] if dir_url.endswith('/') else dir_url
            furl = base + '/' + href
        # 取出檔名: href 最尾 xxx.py
        idx = href.rfind('/')
        fname = href[idx+1:] if idx >= 0 else href
        # 如果 rel_prefix（如 src/ 或 page/）指定，要寫到 wsp 子目錄
        if rel_prefix:
            target_name = rel_prefix + '/' + fname
        else:
            target_name = fname
        if _preload_file(furl, target_name):
            cnt += 1
    return cnt


if _os is not None:
    total = 0
    total += _preload_dir('${dlib_ui}', '')        # ui 根模組直接放 wsp 根（registry/app/launcher）
    total += _preload_dir('${dlib_src}', 'src')
    total += _preload_dir('${dlib_page}', 'page')
    # lvgl_root 跟 ui 一樣時，不要重複抓
    if '${dlib_lvgl_root}' not in ('${dlib_ui}', ''):
        total += _preload_dir('${dlib_lvgl_root}', '')
    print("[fw] preload .py files:", total)

del _mkdirs, _get_url, _preload_file, _preload_dir, _WSP, _WSP_PATHS, _DLIB_URLS


# ----------------------------------------------------------------------------
# 1) 虛擬 package 轉址：import ui.lvgl.FOO  → import FOO（平級）
# ----------------------------------------------------------------------------
import display_driver  # sim.lvgl.io SDL/wasm driver
import lvgl as _lv


class _VirtualPkg:
    __name__ = ""
    __path__ = []
    __package__ = ""

    def __init__(self, name, aliases=None, prefixes=None):
        self.__name__ = name
        self.__path__ = ["<shim:/{}>".format(name)]
        self.__package__ = name
        self._aliases = aliases or {}
        self._prefixes = prefixes or []
        self._cache = {}

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        if attr in self._cache:
            return self._cache[attr]
        real = self._aliases.get(attr)
        if isinstance(real, str):
            try:
                real = __import__(real, None, None, ["*"])
            except Exception:
                real = None
        if real is None:
            tried = []
            for prefix in list(self._prefixes) + [""]:
                cand = (prefix + "." + attr) if prefix else attr
                tried.append(cand)
                try:
                    real = __import__(cand, None, None, ["*"])
                    break
                except Exception:
                    real = None
        if real is None:
            raise AttributeError("no attr '{}' in pkg {} (tried {})".format(
                attr, self.__name__, tried))
        self._cache[attr] = real
        return real


def _install(dotted, leaf=None):
    parts = dotted.split(".")
    parent = None
    built = []
    for i, seg in enumerate(parts):
        built.append(seg)
        full = ".".join(built)
        is_leaf = (i == len(parts) - 1)
        if is_leaf and isinstance(leaf, _VirtualPkg):
            pkg = leaf
        elif is_leaf and isinstance(leaf, dict):
            pkg = _VirtualPkg(full, aliases=leaf)
        elif is_leaf and isinstance(leaf, (list, tuple)):
            pkg = _VirtualPkg(full, prefixes=list(leaf))
        else:
            if full in _sys.modules and not isinstance(_sys.modules.get(full), _VirtualPkg):
                parent = _sys.modules[full]
                continue
            pkg = _VirtualPkg(full)
        _sys.modules[full] = pkg
        if isinstance(parent, _VirtualPkg):
            parent._cache[seg] = pkg
        parent = pkg
    return parent


_install("ui", ["", "src", "page", "lvgl"])
_install("ui.lvgl", ["", "src", "page"])
_install("lvgl", ["", "src", "page", "ui"])

# ----------------------------------------------------------------------------
# 2) lib.sys_bus.bus + lib.hw_manager Web stub
# ----------------------------------------------------------------------------
class _BusAdapter:
    def write_cmd_data(self, cmd, data): pass
    def set_window(self, x1, y1, x2, y2): self._win = (x1,y1,x2,y2)
    def write_data_async(self, data): self._pending = bytes(data)
    def flush(self): pass


class _StubLcd:
    def __init__(self): self._bus = _BusAdapter(); self.width = _W; self.height = _H; self.rotation = 0


class _Shared(dict):
    def __missing__(self, k): return None


class _WebStubBus:
    def __init__(self):
        self._services = {"lcd": _StubLcd()}
        self.shared = _Shared()
    def get_service(self, n): return self._services.get(n)
    def register_service(self, n, s): self._services[n] = s
    def has_lcd(self): return "lcd" in self._services


_sys_bus_mod = _VirtualPkg("lib.sys_bus", aliases={"bus": "__web_bus__"})
_install("lib", {})
_sys.modules["lib"]._cache["sys_bus"] = _sys_bus_mod
_sys.modules["lib.sys_bus"] = _sys_bus_mod
_sys.modules["__web_bus__"] = _WebStubBus()


def _consume_input(kind, idx=None, key=None):
    try: ib = _sys.modules["input_bus"]
    except Exception: return None
    if kind == "enc": return ib.enc_consume() or 0
    if kind == "pin":
        if key == "encC": return 1 if ib.consume_flag("c") else 0
        if key == "btn":  return 1 if ib.consume_flag("e") else 0
    return None


_consume_mod = type("_", (), {"__call__": staticmethod(_consume_input)})()
_hw_mgr_mod = _VirtualPkg("lib.hw_manager", aliases={
    "consume_input": "_hw_consume_shim", "HwSampleTask": None})
_sys.modules["lib"]._cache["hw_manager"] = _hw_mgr_mod
_sys.modules["lib.hw_manager"] = _hw_mgr_mod
_sys.modules["_hw_consume_shim"] = _consume_mod

# ----------------------------------------------------------------------------
# 3) input_bus（對接前端 ◀ ▶ 確認 返回）
# ----------------------------------------------------------------------------
class _IB:
    pass
_ib = _IB(); _ib._ev = []
def _push(c): _ib._ev.append(c)
def _poll():
    b = _ib._ev[:]; del _ib._ev[:]; return b
def _enc_consume():
    t = 0
    for c in _poll():
        if c == "l": t -= 1
        elif c == "r": t += 1
        else: _ib._ev.append(c)
    return t
def _consume_flag(k):
    rest = []; found = False
    for c in _poll():
        if (not found) and c == k: found = True
        else: rest.append(c)
    _ib._ev = rest + _ib._ev
    return found
_ib.push = _push; _ib.poll = _poll
_ib.enc_consume = _enc_consume; _ib.consume_flag = _consume_flag
_sys.modules["input_bus"] = _ib

# ----------------------------------------------------------------------------
# 4) LVGL display init + 動態載入 pages + app啟動
# ----------------------------------------------------------------------------
def _safe_import(name):
    try: return __import__(name, None, None, ["*"])
    except Exception as e:
        print("[fw] import {} fail: {}".format(name, e))
        return None

_reg = _safe_import("registry")
_app = _safe_import("app")
_launcher = _safe_import("launcher")

def _preimport_pages():
    cnt = 0
    try:
        import uos as _os
    except Exception:
        try:
            import os as _os
        except Exception:
            _os = None
    for _pd in ['/_wsp/${design}/page', '${dlib_page}', '/page']:
        if not _pd or _os is None:
            continue
        try:
            items = sorted(_os.listdir(_pd))
        except Exception:
            continue
        for it in items:
            if not it.endswith(".py") or it.startswith("_"):
                continue
            mn = it[:-3]
            if mn == "__init__":
                continue
            if _safe_import(mn) is not None:
                cnt += 1
    print("[fw] preimport: {} page modules".format(cnt))

_preimport_pages()

# LVGL display init（一次）
try:
    if not _lv.is_initialized(): _lv.init()
    _d = _lv.display_create(_W, _H)
    try: _d.set_color_format(18)  # RGB565
    except Exception: pass
    try:
        _buf = bytearray(_W * 40 * 2)
        _d.set_buffers(_buf, None, len(_buf), 0)  # PARTIAL
    except Exception: pass
    def _flush_cb(drv, area, cp):
        try: drv.flush_ready()
        except Exception: pass
    try: _d.set_flush_cb(_flush_cb)
    except Exception: pass
    print("[fw] lv display ready {}x{}".format(_W, _H))
except Exception as e:
    print("[fw] lv display init skip:", e)

def _tick():
    _lv.tick_inc(5); _lv.task_handler()
def _take(): return []
def _show(*a): pass
def _enc_delta(): return _ib.enc_consume() or 0
def _confirm(): return _ib.consume_flag("c")
def _exit(): return _ib.consume_flag("e")


class _Plat: W = _W; H = _H


def _start():
    if _app is None: print("[fw] _app missing"); return
    _uic = _safe_import("ui_common")
    if _uic is not None:
        try: _uic.init(_Plat)
        except Exception as e: print("[fw] uic.init warn:", e)
        try: _uic.init_fonts()
        except Exception as e: print("[fw] uic fonts warn:", e)
    try:
        _app.build_all()
    except Exception as e:
        print("[fw] build_all fail:", e)
    _app.init({
        "tick": _tick, "take": _take, "show": _show,
        "enc_delta": _enc_delta, "confirm": _confirm, "exit": _exit,
    })
    _app.go("launcher")
    _ib.step = _app.step
    _ib.go = _app.go
    print("[fw] started ◀▶=enc | Enter=confirm | Esc=exit")

_start()
"""


def render_framework_code(
    origin: str,
    design: str,
    width: int,
    height: int,
    dlib_ui: str,
    dlib_src: str,
    dlib_page: str,
    dlib_lvgl_root: str,
) -> str:
    """用 $var 模板語法渲染 FRAMEWORK_CODE，避免 dict/set 字面量的 { } 與 .format() 衝突。"""
    # safe_substitute：遇到未定義 $var 會保留原樣，不報 KeyError
    return string.Template(FRAMEWORK_CODE).safe_substitute(
        origin=origin,
        design=design,
        width=str(int(width)),
        height=str(int(height)),
        dlib_ui=dlib_ui,
        dlib_src=dlib_src,
        dlib_page=dlib_page,
        dlib_lvgl_root=dlib_lvgl_root,
    )


# design.json 保存欄位白名單（read 出來的 dir 不寫回）
_META_KEYS = ("name", "width", "height", "pages", "interactions", "source")


def write_design(name: str, meta: dict) -> None:
    import json

    d = DESIGN_LIB / name
    d.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in meta.items() if k in _META_KEYS}
    (d / "design.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def list_designs() -> list[dict]:
    if not DESIGN_LIB.exists():
        return []
    out = []
    for d in sorted(DESIGN_LIB.iterdir()):
        if not d.is_dir():
            continue
        meta = read_design(d.name) or {
            "name": d.name, "width": 320, "height": 240,
            "pages": [], "interactions": [], "dir": str(d),
        }
        meta["has_meta"] = (d / "design.json").exists()
        meta["kind"] = design_kind(d.name)
        out.append(meta)
    return out


def create_design(name: str, title: str = "", width: int = 320,
                  height: int = 240) -> dict:
    """建立新 design（資料夾 + 初始 design.json）。"""
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", name.strip()).strip("-")
    if not safe:
        raise ValueError("design 名稱不能為空")
    d = DESIGN_LIB / safe
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": title or safe,
        "width": int(width),
        "height": int(height),
        "pages": [],
        "interactions": [],
    }
    write_design(safe, meta)
    return read_design(safe)


def scan_design(name: str) -> dict:
    """重新掃描 design 資料夾,更新 design.json 的頁面/互動。

    同時處理 HTML 設計稿頁面 與 LVGL code-only 頁面,兩者合併列出,
    避免 HTML 與 LVGL 程式頁面互相覆蓋。
    """
    d = DESIGN_LIB / name
    meta = read_design(name) or {
        "name": name, "width": 320, "height": 240,
    }
    scanned = scan_html_files(d)
    lvgl_pages: list[dict] = []
    lvgl_ui_exists = (
        (d / "lvgl" / "ui").exists()
        or (d / "ui").exists()
        or (d / "page").exists()
    )
    if lvgl_ui_exists:
        lvgl_pages = scan_lvgl_pages(d)

    existing_pages = list(meta.get("pages", []))

    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for p in scanned["pages"] + lvgl_pages + existing_pages:
        key = (p.get("tag", "feature"), p.get("id", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(p)
    meta["pages"] = merged
    meta["interactions"] = scanned["interactions"] or meta.get("interactions", [])
    write_design(name, meta)
    return read_design(name)


def migrate_legacy(source_dir: Path, design_name: str = "lvgl-console-ui",
                   title: str = "LVGL 控制台") -> dict | None:
    """把舊 workspace/design 的檔案遷移成一個 design。"""
    if not source_dir.exists():
        return None
    d = DESIGN_LIB / design_name
    d.mkdir(parents=True, exist_ok=True)
    for f in source_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, d / f.name)
    meta = {
        "name": title,
        "width": 320,
        "height": 240,
    }
    write_design(design_name, meta)
    return scan_design(design_name)
