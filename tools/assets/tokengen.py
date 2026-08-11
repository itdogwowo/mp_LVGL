# tokengen.py — 設計 token 三份同步產生器
#
# tokens.json（真相來源，人工編輯） → design-tokens.css（web 用）+ design-tokens.py（lvgl 用）
#
# 規範化結構下，tokens.json 放 design/{name}/assets/tokens/，是顏色/字體大小/間距等
# 設計常數的唯一編輯處。產出兩份生成物：
#   design-tokens.css  → 給 html/ 的 *.html <link> 引用（:root { --xxx: yyy }）
#   design-tokens.py   → 給 lvgl/ui/ 的 ui_common.py import（PRIMARY = 0x... 常數）
# 生成物加「DO NOT EDIT」註解，禁止人工改（改了會被下次產生覆蓋）。
#
# 也提供 init_tokens_json() 從 HTML 的 :root 抽初始 tokens.json（給新 design 用）。
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import scanner


# ============ tokens.json 結構 ============
# {
#   "_meta": { "version": 1, "note": "真相來源，設計師編輯此檔" },
#   "colors": {
#     "primary":   { "value": "#1A73E8", "py": "PRIMARY",  "comment": "主色" },
#     "bg":        { "value": "#F5F5F5", "py": "BG",       "comment": "背景" },
#     ...
#   },
#   "fonts": {
#     "body-md-size": { "value": "12px", "py": "BODY_MD_FONT_SIZE", "comment": "內文 12px" },
#     ...
#   },
#   "spacers": { ... },
#   "radii":   { ... }
# }
#
# 每個 token 三欄：
#   value   原始值（CSS 字串：#1A73E8 / 12px / 16px）
#   py      Python 常數名（如 PRIMARY）；空字串 = 不產進 .py
#   comment 註解（可選）


# ============ 顏色字串 → LVGL 0xRRGGBB ============

def _color_to_hex(value: str) -> int | None:
    """把 CSS 顏色字串轉成 LVGL 用的 0xRRGGBB 整數。

    支援：#RGB、#RRGGBB、rgb(r,g,b)；rgba 取 RGB 部分（丟 alpha）。
    無法解析回 None。
    """
    v = value.strip()
    m = re.match(r"^#([0-9A-Fa-f]{3})$", v)
    if m:
        h = m.group(1)
        return int(h[0] * 2 + h[1] * 2 + h[2] * 2, 16)
    m = re.match(r"^#([0-9A-Fa-f]{6})$", v)
    if m:
        return int(m.group(1), 16)
    m = re.match(r"^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", v)
    if m:
        return (int(m.group(1)) << 16) | (int(m.group(2)) << 8) | int(m.group(3))
    return None


def _px_to_int(value: str) -> int | None:
    """把 '12px' / '12' 轉成 int 12；失敗回 None。"""
    v = value.strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*px?$", v)
    if m:
        return int(float(m.group(1)))
    return None


# ============ 產 design-tokens.css ============

def _token_to_css_var(group: str, name: str, tok: dict) -> str:
    """tokens.json 一筆 → CSS 變數宣告 '--group-name: value;'。"""
    value = tok.get("value", "")
    comment = tok.get("comment", "")
    # CSS 變數名：--{group}-{name}（例如 colors.primary → --color-primary）
    css_name = f"--{group.rstrip('s')}-{name}".replace("_", "-")
    line = f"  {css_name}: {value};"
    if comment:
        line += f"  /* {comment} */"
    return line


def render_css(tokens: dict) -> str:
    """產 design-tokens.css 內容（:root { ... }）。"""
    lines = [
        "/* design-tokens.css — 由 tokengen.py 自動產生，請勿人工編輯。",
        "   真相來源：tokens.json。修改 tokens.json 後重跑 generate_tokens。 */",
        ":root {",
    ]
    skip_keys = ("_meta",)
    for group, items in tokens.items():
        if group in skip_keys or not isinstance(items, dict):
            continue
        lines.append(f"  /* {group} */")
        for name, tok in items.items():
            if isinstance(tok, dict) and "value" in tok:
                lines.append(_token_to_css_var(group, name, tok))
    lines.append("}")
    return "\n".join(lines) + "\n"


# ============ 產 design-tokens.py ============

def _token_to_py_const(tok: dict, value_coerce) -> str | None:
    """tokens.json 一筆 → Python 常數宣告 'NAME = value'。

    value_coerce: 把 CSS value 字串轉成 Python 字面值的函數（如 _color_to_hex）。
    無 py 欄（空字串）或值無法轉 → 回 None（略過）。
    """
    py_name = tok.get("py", "")
    if not py_name:
        return None
    value = tok.get("value", "")
    coerced = value_coerce(value)
    if coerced is None:
        return None
    # 顏色用 0xRRGGBB hex 字面值（易讀），數字直接用
    if isinstance(coerced, int) and value.strip().startswith("#"):
        return f"{py_name} = 0x{coerced:06X}"
    return f"{py_name} = {coerced!r}" if isinstance(coerced, str) else f"{py_name} = {coerced}"


def render_py(tokens: dict) -> str:
    """產 design-tokens.py 內容（Python 常數）。

    顏色 → 0xRRGGBB 整數；字體大小/間距/圓角 → int；其他（字體家族等）→ 原始字串。
    """
    lines = [
        "# design-tokens.py — 由 tokengen.py 自動產生，請勿人工編輯。",
        "# 真相來源：tokens.json。修改 tokens.json 後重跑 generate_tokens。",
        "# ui_common.py 可 from design_tokens import PRIMARY, BG, ...",
        "",
    ]
    # 顏色群：轉 0xRRGGBB
    colors = tokens.get("colors", {})
    if colors:
        lines.append("# ====== Palette ======")
        for name, tok in colors.items():
            if not isinstance(tok, dict):
                continue
            line = _token_to_py_const(tok, _color_to_hex)
            if line:
                if tok.get("comment"):
                    lines.append(f"# {tok['comment']}")
                lines.append(line)
        lines.append("")

    # 字體大小群：轉 int（px）
    fonts = tokens.get("fonts", {})
    if fonts:
        lines.append("# ====== Font sizes (px) ======")
        for name, tok in fonts.items():
            if not isinstance(tok, dict):
                continue
            line = _token_to_py_const(tok, _px_to_int)
            if line:
                if tok.get("comment"):
                    lines.append(f"# {tok['comment']}")
                lines.append(line)
        lines.append("")

    # spacers / radii：轉 int
    for group in ("spacers", "radii"):
        items = tokens.get(group, {})
        if not items:
            continue
        lines.append(f"# ====== {group} (px) ======")
        for name, tok in items.items():
            if not isinstance(tok, dict):
                continue
            line = _token_to_py_const(tok, _px_to_int)
            if line:
                lines.append(line)
        lines.append("")

    return "\n".join(lines) + "\n"


# ============ 主要 API ============

def generate_tokens(design_dir: Path, log=None, out_root: Path | None = None) -> dict:
    """從 design 的 assets/tokens/tokens.json 產 css + py。

    design_dir: design 根目錄（含 assets/tokens/tokens.json）
    out_root:   產出根目錄；預設 = design_dir/assets/tokens/
                css 寫 out_root/design-tokens.css
                py  寫 out_root/design-tokens.py（呼叫端會複本到 lvgl/ui/src/）

    回傳 {ok, css_path, py_path, counts: {colors, fonts, ...}}。
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    tokens_path = design_dir / "assets" / "tokens" / "tokens.json"
    if not tokens_path.exists():
        _log("✗ tokens.json 不存在，無法產 token（先呼叫 init_tokens_json）")
        return {"ok": False, "error": "tokens.json missing"}

    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    out_root = out_root or (design_dir / "assets" / "tokens")
    out_root.mkdir(parents=True, exist_ok=True)

    css_text = render_css(tokens)
    py_text = render_py(tokens)

    css_path = out_root / "design-tokens.css"
    py_path = out_root / "design-tokens.py"
    css_path.write_text(css_text, encoding="utf-8")
    py_path.write_text(py_text, encoding="utf-8")

    counts = {k: len(v) for k, v in tokens.items()
              if isinstance(v, dict) and k != "_meta"}
    _log(f"✓ tokens: css={css_path.name}, py={py_path.name}, "
         f"counts={counts}")
    return {"ok": True, "css_path": str(css_path),
            "py_path": str(py_path), "counts": counts}


def init_tokens_json(design_dir: Path, html_files: list[Path] | None = None,
                     log=None) -> dict:
    """從 HTML 的 :root 抽初始 tokens.json（給新 design 種子用）。

    design_dir: design 根目錄（會在 assets/tokens/tokens.json 寫出）
    html_files: 要掃的 HTML 檔清單；預設掃 design_dir/html/ 下所有 .html
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    if html_files is None:
        html_dir = design_dir / "html"
        html_files = sorted(html_dir.rglob("*.html")) if html_dir.is_dir() else []

    if not html_files:
        _log("✗ 無 HTML 可抽 token")
        return {"ok": False, "error": "no html"}

    # 合併所有 HTML 的 :root
    all_raw: dict[str, str] = {}
    for f in html_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        result = scanner.extract_tokens_from_css(text)
        all_raw.update(result["raw"])

    # 轉成 tokens.json 結構（先只種顏色 + 字體大小，其他按需擴充）
    resolved = scanner.extract_tokens_from_css(
        ":root{" + "".join(f"--{k}:{v};" for k, v in all_raw.items()) + "}"
    )["resolved"]
    groups = scanner.extract_tokens_from_css(
        ":root{" + "".join(f"--{k}:{v};" for k, v in all_raw.items()) + "}"
    )["groups"]

    tokens: dict[str, Any] = {
        "_meta": {"version": 1, "note": "真相來源，設計師編輯此檔"},
    }

    # 顏色：只挑有 hex/rgb 值的（跳過純 var() 引用、字體家族）
    color_map = {
        # canonical name in tokens.json : (css var name stem, py name, comment)
        "primary":    ("bg-brand",            "PRIMARY",    "主色"),
        "surface":    ("bg-base-secondary",   "SURFACE",    "卡片表面"),
        "bg":         ("bg-base-secondary",   "BG",         "頁面背景"),
        "bg-base":    ("bg-base-default",     "BG_BASE",    "基礎背景"),
        "border":     ("border-default",      "BORDER",     "邊框"),
        "text":       ("text-default",        "TEXT",       "主文字"),
        "text-2":     ("text-secondary",      "TEXT2",      "次文字"),
        "text-3":     ("text-tertiary",       "TEXT3",      "弱文字"),
        "success":    ("bg-success",          "SUCCESS",    "成功"),
        "warning":    ("bg-warning",          "WARNING",    "警告"),
        "danger":     ("bg-danger",           "DANGER",     "危險"),
        "track":      ("bg-base-tertiary",    "TRACK",      "軌道"),
    }
    colors_out: dict[str, dict] = {}
    for cname, (stem, py, comment) in color_map.items():
        val = resolved.get(stem)
        if val and (val.startswith("#") or val.startswith("rgb")):
            colors_out[cname] = {"value": val, "py": py, "comment": comment}
    if colors_out:
        tokens["colors"] = colors_out

    # 字體大小：body-{xs,sm,md,base,lg}-font-size + heading-*（挑常用的）
    font_size_stems = [
        ("body-xs",   "BODY_XS_FONT_SIZE",   "內文 XS"),
        ("body-sm",   "BODY_SM_FONT_SIZE",   "內文 SM"),
        ("body-md",   "BODY_MD_FONT_SIZE",   "內文 MD"),
        ("body-base", "BODY_BASE_FONT_SIZE", "內文 BASE"),
        ("body-lg",   "BODY_LG_FONT_SIZE",   "內文 LG"),
    ]
    fonts_out: dict[str, dict] = {}
    for stem, py, comment in font_size_stems:
        val = resolved.get(f"{stem}-font-size")
        if val:
            fonts_out[stem] = {"value": val, "py": py, "comment": comment}
    if fonts_out:
        tokens["fonts"] = fonts_out

    # 間距（挑常用的）
    spacer_stems = [4, 8, 12, 16, 20, 24, 32]
    spacers_out: dict[str, dict] = {}
    for n in spacer_stems:
        val = resolved.get(f"spacer-{n}")
        if val:
            spacers_out[str(n)] = {"value": val, "py": f"SPACER_{n}", "comment": f"間距 {n}"}
    if spacers_out:
        tokens["spacers"] = spacers_out

    # 圓角
    radius_stems = [4, 8, 12, 16]
    radii_out: dict[str, dict] = {}
    for n in radius_stems:
        val = resolved.get(f"radius-{n}")
        if val:
            radii_out[str(n)] = {"value": val, "py": f"RADIUS_{n}", "comment": f"圓角 {n}"}
    if radii_out:
        tokens["radii"] = radii_out

    # 寫出
    out_path = design_dir / "assets" / "tokens" / "tokens.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"✓ init tokens.json: {out_path.relative_to(design_dir)} "
         f"(colors={len(colors_out)}, fonts={len(fonts_out)}, "
         f"spacers={len(spacers_out)}, radii={len(radii_out)})")
    return {"ok": True, "tokens_path": str(out_path),
            "counts": {k: len(v) for k, v in tokens.items() if k != "_meta"}}
