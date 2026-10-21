"""cli/assets.py — 字元 / 圖示盤點（Python 版，給 serve.py 的 /api/assets-report）

跟 cli/assets.mjs 是同一套規則，輸出同一個 JSON 形狀：
  字元：只掃 pages/*.js 的**字串字面量**（註解不算）
  圖示：mk_icon(x,"name") / icon: "name" / 任何剛好是對照表 key 的字串
  icons_16.bin 的覆蓋：用 cli/fontbin.py 讀 cmap

Node 版留給有 node 的人跑 CLI；這支讓「只有 Python」也能開模擬器。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):  # 直接 `python cli/assets.py` 也能跑
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from cli.fontbin import codepoints as font_codepoints
else:
    from .fontbin import codepoints as font_codepoints

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_ZH = os.path.join(ROOT, "assets", "fonts", "zh_hant_16.bin")
FONT_ICON = os.path.join(ROOT, "assets", "fonts", "icons_16.bin")
ICONS_JS = os.path.join(ROOT, "packages", "lv-app", "lv_icons.js")
PROJECTS_JSON = os.path.join(ROOT, "projects.json")

COMMON_SYMBOLS = "°℃·±×÷→←↑↓…─／　—"

_LITERAL = re.compile(r"""(["'`])(?:\\.|(?!\1)[^\\\n])*\1""")
_MK_ICON = re.compile(r"""mk_icon\(\s*[^,]+,\s*["']([a-z0-9-]+)["']""")
_META_ICON = re.compile(r"""\bicon:\s*["']([a-z0-9-]+)["']""")
_STRING = re.compile(r"""(["'])([a-z0-9-]+)\1""")
_ICONS_ENTRY = re.compile(r'(?:"([a-z0-9-]+)"|([a-z0-9-]+))\s*:\s*"\\u([0-9A-Fa-f]{4})"')


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _project(project_id=None):
    data = json.loads(_read(PROJECTS_JSON))
    items = data.get("projects", [])
    if not items:
        raise ValueError("projects.json 裡沒有任何專案")
    if project_id:
        for p in items:
            if p.get("id") == project_id:
                return p
        raise ValueError("找不到專案：" + project_id)
    for p in items:
        if p.get("default"):
            return p
    return items[0]


def _icons_map():
    """圖示名 → 碼點（從 lv_icons.js 的 ICONS 物件抽出來）。"""
    out = {}
    for m in _ICONS_ENTRY.finditer(_read(ICONS_JS)):
        name = m.group(1) or m.group(2)
        out[name] = int(m.group(3), 16)
    return out


def _literals(src):
    return "\n".join(m.group(0) for m in _LITERAL.finditer(src))


def _to_ranges(cps):
    cps = sorted(set(cps))
    if not cps:
        return "0x20-0x7F"
    parts = []
    start = prev = cps[0]
    for cp in cps[1:] + [None]:
        if cp is not None and cp == prev + 1:
            prev = cp
            continue
        parts.append("0x%X" % start if start == prev else "0x%X-0x%X" % (start, prev))
        if cp is None:
            break
        start = prev = cp
    return "0x20-0x7F," + ",".join(parts)


def build_report(project_id=None):
    proj = _project(project_id)
    pid = proj["id"]
    pages_dir = os.path.join(ROOT, proj.get("path", "projects/" + pid), "pages")
    files = sorted(
        os.path.join(pages_dir, f)
        for f in os.listdir(pages_dir)
        if f.endswith(".js") and f != "index.js"
    )

    zh = font_codepoints(FONT_ZH)
    icon_bin = font_codepoints(FONT_ICON)
    icons = _icons_map()

    char_files = {}   # ch -> set(files)
    icon_files = {}   # name -> set(files)
    for path in files:
        src = _read(path)
        base = os.path.basename(path)
        for ch in _literals(src):
            if ord(ch) < 0x80:
                continue
            char_files.setdefault(ch, set()).add(base)

        names = set(_MK_ICON.findall(src)) | set(_META_ICON.findall(src))
        for s in _STRING.findall(src):
            if s[1] in icons:
                names.add(s[1])
        for n in names:
            icon_files.setdefault(n, set()).add(base)

    char_list = sorted(char_files, key=ord)
    missing = [
        {
            "ch": ch,
            "cp": "U+%04X" % ord(ch),
            "files": sorted(char_files[ch]),
        }
        for ch in char_list
        if ord(ch) not in zh
    ]

    used_icons = sorted(icon_files)
    unknown = [n for n in used_icons if n not in icons]
    missing_in_bin = [n for n in used_icons if n in icons and icons[n] not in icon_bin]
    unused = sorted(n for n in icons if n not in icon_files)

    all_cps = [ord(c) for c in char_list] + [ord(c) for c in COMMON_SYMBOLS]
    command = (
        "npx lv_font_conv --font <你的字型.ttf> --size 16 --format bin --bpp 4 "
        "-r " + _to_ranges(all_cps) + " --no-compress -o zh_hant_16.bin"
    )

    return {
        "project": {"id": pid, "title": proj.get("title", pid)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": ["projects/%s/pages/%s" % (pid, os.path.basename(f)) for f in files],
        "chars": {
            "total": len(char_list),
            "all": "".join(char_list),
            "missing": missing,
        },
        "icons": {
            "used": used_icons,
            "unknown": unknown,
            "missing_in_bin": missing_in_bin,
            "unused": unused,
            "total_in_map": len(icons),
        },
        "command": command,
    }


if __name__ == "__main__":
    import sys

    rid = sys.argv[1] if len(sys.argv) > 1 else None
    r = build_report(rid)
    print(json.dumps(r, ensure_ascii=False, indent=2))
