# scanner.py — 掃描工作區設計稿
#
# 從 workspace/design 下的 .html/.css 抽出:
#   - lucide 圖示（data-lucide="..."）
#   - 非 ASCII 字符（中文字體字集用）
#   - 動態效果（@keyframes / transition / :hover/:active/:focus）
# 純文字掃描,不解析 DOM,對 Trae 輸出的 HTML 已足夠。
from __future__ import annotations

import re
from pathlib import Path

from . import DESIGN_DIR

_LUCIDE_RE = re.compile(r'data-lucide="([a-z0-9-]+)"', re.IGNORECASE)
_KEYFRAMES_RE = re.compile(r"@keyframes\s+([A-Za-z0-9_-]+)")
_ANIM_NAME_RE = re.compile(r"animation(?:\-name)?\s*:\s*([^;{}]+)")
_TRANSITION_RE = re.compile(r"transition\s*:\s*([^;}]+)")
_INTERACT_RE = re.compile(
    r"([.#A-Za-z][\w.\\\-]*)\s*:(hover|active|focus|focus-visible|focus-within)\b[^{]*\{"
)
_NONASCII_RE = re.compile(r"[^\x00-\x7F]")
# :root { --var: value; } 區塊解析（給 token 系統初始化用）
_ROOT_BLOCK_RE = re.compile(r":root\s*\{([^}]*)\}", re.S)
_CSS_VAR_RE = re.compile(r"--([\w-]+)\s*:\s*([^;{}]+)")

SUPPORTED_EXT = (".html", ".css", ".design", ".json")


def design_files(design_dir: Path | None = None) -> list[Path]:
    d = design_dir or DESIGN_DIR
    if not d.exists():
        return []
    return sorted(
        p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXT
    )


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan(design_dir: Path | None = None) -> dict:
    """掃描設計稿,回傳結構化結果:
    {
      icons: [name, ...],
      chars: 排序後的非 ASCII 字符字串,
      char_count: int,
      fx: {
        animations: [{name, files, used_by}],
        transitions: [{file, props}],
        hover: [{file, selector, state}],
      }
    }
    """
    icons: set[str] = set()
    chars: set[str] = set()
    animations: dict[str, dict] = {}
    transitions: list[dict] = []
    hover: list[dict] = []

    for f in design_files(design_dir):
        text = _read_text(f)
        if not text:
            continue
        icons |= set(_LUCIDE_RE.findall(text))
        chars |= set(_NONASCII_RE.findall(text))
        for m in _KEYFRAMES_RE.finditer(text):
            animations.setdefault(m.group(1), {"name": m.group(1), "files": []})
            animations[m.group(1)]["files"].append(f.name)
        for m in _ANIM_NAME_RE.finditer(text):
            for tok in re.split(r"[, ]+", m.group(1).strip()):
                if tok in animations:
                    animations[tok].setdefault("used_by", [])
                    animations[tok]["used_by"].append(f.name)
        for m in _TRANSITION_RE.finditer(text):
            transitions.append({"file": f.name, "props": m.group(1).strip()})
        for m in _INTERACT_RE.finditer(text):
            hover.append(
                {
                    "file": f.name,
                    "selector": m.group(1).strip(),
                    "state": m.group(2),
                }
            )

    return {
        "icons": sorted(icons),
        "chars": "".join(sorted(chars, key=ord)),
        "char_count": len(chars),
        "fx": {
            "animations": sorted(animations.values(), key=lambda a: a["name"]),
            "transitions": transitions[:200],
            "hover": hover[:200],
        },
    }


# ============ Token 抽取（給 tokengen 初始化 tokens.json 用） ============

def _parse_value(raw: str, raw_vars: dict[str, str],
                 _seen: set[str] | None = None) -> str:
    """把 CSS 變數值解析成最終值（遞迴解 var(--xxx) 引用）。

    例如 var(--bg-brand) → #4B3FE3（若 --bg-brand 定義為 #4B3FE3）。
    無法解析（循環/未定義）就回原值。
    """
    v = raw.strip()
    if _seen is None:
        _seen = set()
    # 處理 var(--xxx[, fallback])
    m = re.match(r"^var\(\s*(--[\w-]+)(?:\s*,\s*([^)]+))?\)$", v)
    if m:
        ref = m.group(1)[2:]  # 去 --
        if ref in _seen:  # 循環引用
            return m.group(2).strip() if m.group(2) else v
        _seen.add(ref)
        resolved = raw_vars.get(ref)
        if resolved is None:
            return m.group(2).strip() if m.group(2) else v
        return _parse_value(resolved, raw_vars, _seen)
    return v


def extract_tokens_from_css(css_text: str) -> dict:
    """從 CSS 文字抽 :root{} 的設計 token，分群回傳。

    回傳結構（與 tokengen.generate_tokens 的 tokens.json 格式對齊）：
      {
        "raw": {"--bg-brand": "#4B3FE3", "--color-surface": "var(--bg-base-secondary)", ...},
        "resolved": {"--bg-brand": "#4B3FE3", "--color-surface": "#F5F5F5", ...},
        "groups": {"colors": {...}, "fonts": {...}, "spacers": {...}, "radii": {...}}
      }
    raw = 原始值（保留 var() 引用）；resolved = 解析到最終值。
    groups 依前綴分群：bg/color/text/icon/border/accent/brand/status → colors，
      font/body/heading/code → fonts，spacer → spacers，radius → radii。
    """
    raw_vars: dict[str, str] = {}
    for block_m in _ROOT_BLOCK_RE.finditer(css_text):
        for vm in _CSS_VAR_RE.finditer(block_m.group(1)):
            name = vm.group(1)   # 不含 -- 前綴
            raw_vars[name] = vm.group(2).strip()

    # resolved：逐項解析 var() 引用
    resolved: dict[str, str] = {}
    for name, raw in raw_vars.items():
        resolved[name] = _parse_value(raw, raw_vars)

    # 分群（依名稱前綴）
    groups: dict[str, dict[str, str]] = {
        "colors": {}, "fonts": {}, "spacers": {}, "radii": {}, "icons": {},
        "other": {},
    }
    color_prefixes = ("bg", "color", "text", "icon", "border", "accent",
                      "brand", "status", "viz", "code-text", "code-doc",
                      "code-link", "code-number", "code-action",
                      "code-instruction", "code-function", "code-constant",
                      "code-parameter", "code-attribute", "code-tag")
    for name, val in resolved.items():
        key = name.lower()
        if key.startswith(color_prefixes) or re.match(
                r"(bg|color|text|icon|border|accent|brand|status|viz)-", key):
            groups["colors"]["--" + name] = val
        elif key.startswith(("font", "body", "heading", "code-", "code_")):
            groups["fonts"]["--" + name] = val
        elif key.startswith("spacer"):
            groups["spacers"]["--" + name] = val
        elif key.startswith("radius"):
            groups["radii"]["--" + name] = val
        elif key.startswith("icon-size"):
            groups["icons"]["--" + name] = val
        else:
            groups["other"]["--" + name] = val

    # 去空群
    groups = {k: v for k, v in groups.items() if v}
    return {"raw": raw_vars, "resolved": resolved, "groups": groups}
