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
