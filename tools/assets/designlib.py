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
from pathlib import Path

from . import TOOLS_DIR

DESIGN_LIB = TOOLS_DIR / "design"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_DOMID_RE = re.compile(r'data-dom-id="([^"]+)"')
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


def lvgl_path(design_name: str) -> Path:
    """該 design 的 LVGL 輸出路徑:design/{name}/lvgl/（跟 design 走）。"""
    return DESIGN_LIB / design_name / "lvgl"


def lvgl_src_path(design_name: str) -> Path:
    """資源進 ui 內:板上只上傳 ui/ 一個資料夾即根目錄。
    → design/{name}/lvgl/ui/src/（原 lvgl/src → lvgl/ui/src）
    """
    return lvgl_path(design_name) / "ui" / "src"


def lvgl_status(design_name: str) -> dict:
    """回傳該 design 的 lvgl 產出狀態（框架/資源是否已生成）。"""
    lv = lvgl_path(design_name)
    ui = lv / "ui"
    src = ui / "src"  # 新路徑 lvgl/ui/src
    return {
        "exists": lv.exists(),
        "ui_files": sorted(p.name for p in ui.glob("*.py")) if ui.exists() else [],
        "src_files": sorted(p.name for p in src.iterdir()) if src.exists() else [],
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
FRAMEWORK_CODE = '''# ui 框架模式:在模擬器跑 design 的 ui/app（純 UI,不碰 machine）
# 模擬器 wasm importer 不支援 package 目錄 → 用 sys.path 指到 ui/ 各層平級 import。
import imp, usys as sys
sys.path.append('{origin}/dlib/{design}/lvgl/ui')
sys.path.append('{origin}/dlib/{design}/lvgl/ui/src')
sys.path.append('{origin}/dlib/{design}/lvgl/ui/page')

# SDL 顯示 + 平級 import(不 import ui package)
import display_driver
import lvgl as lv
import registry
import app
import launcher
import overview, monitor, control, settings  # noqa 平級頁面(註冊)

# 補 mod + 排序
registry.PAGES["overview"]["mod"] = overview
registry.PAGES["monitor"]["mod"] = monitor
registry.PAGES["control"]["mod"] = control
registry.PAGES["settings"]["mod"] = settings

# 模擬輸入:前端按鈕 → mp_js_do_str("import input_bus; input_bus.push('c')")
# 由於 mp_js_do_str 用獨立 globals,把 input_bus 注入 sys.modules 供前端 import。
import usys as sys
class _InputBus:
    pass
_input_bus = _InputBus()
_input_bus._buf = []


def _push(c):
    _input_bus._buf.append(c)


def _poll():
    b = _input_bus._buf[:]
    del _input_bus._buf[:]
    return b


_input_bus.push = _push
sys.modules["input_bus"] = _input_bus


def _enc_delta():
    # 只消費 l/r 字元,其餘(c/e)塞回,避免 confirm/exit 讀不到
    d = 0
    rest = []
    for c in _poll():
        if c == "l":
            d -= 1
        elif c == "r":
            d += 1
        else:
            rest.append(c)
    _input_bus._buf = rest + _input_bus._buf
    return d


def _confirm():
    b = _poll()
    found = "c" in b
    _input_bus._buf = [x for x in b if x != "c"] + _input_bus._buf
    return found


def _exit():
    b = _poll()
    found = "e" in b
    _input_bus._buf = [x for x in b if x != "e"] + _input_bus._buf
    return found


def _tick():
    lv.tick_inc(5)
    lv.task_handler()


def run():
    app.init({{
        "tick": _tick,
        "take": lambda: [],
        "show": lambda *a: None,
        "enc_delta": _enc_delta,
        "confirm": _confirm,
        "exit": _exit,
    }})
    app.go("launcher")
    # 前端按鈕每次點擊 → do_str("input_bus.push('c'); input_bus.step()")
    # step 綁定到 input_bus 供 do_str 呼叫(事件驅動步進,不需 timer)
    _input_bus.step = app.step
    _input_bus.go = app.go
    print("ui 框架啟動: 用前端按鈕 ◀▶=旋轉, 確認, 返回")


run()
'''


def write_design(name: str, meta: dict) -> None:
    import json

    d = DESIGN_LIB / name
    d.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in meta.items() if k != "dir"}
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
        # 沒 design.json 的資料夾也算（顯示未掃描）
        meta["has_meta"] = (d / "design.json").exists()
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
    """重新掃描 design 資料夾,更新 design.json 的頁面/互動。"""
    d = DESIGN_LIB / name
    meta = read_design(name) or {
        "name": name, "width": 320, "height": 240,
    }
    scanned = scan_html_files(d)
    meta["pages"] = scanned["pages"]
    meta["interactions"] = scanned["interactions"]
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
