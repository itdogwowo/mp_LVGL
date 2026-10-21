"""cli/validate.py — 工程驗證（Python 版，跟 cli/validate.mjs 同一套檢查）

    cd lvgl-console-ui
    python cli/validate.py            # 全部專案
    python cli/validate.py slave      # 指定專案

檢查：projects.json / project.json 完整、theme 存在且版本相符、每個頁面有唯一
meta.id + build()、pages/index.js 有 import、字型可解析、沒有缺字、圖示名都在
對照表與 icons_16.bin 裡。

產物：validation-report.json（outcome / errors / warnings / hashes / checkedAt）。
有錯時 exit code = 1，可直接接 CI 或 bat。
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from cli.assets import build_report
    from cli.fontbin import codepoints as font_codepoints
else:
    from .assets import build_report
    from .fontbin import codepoints as font_codepoints

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "validation-report.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

errors = []
warnings = []
hashes = {}
projects = []


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def err(project, check, message):
    errors.append({"project": project, "check": check, "message": message})


def warn(project, check, message):
    warnings.append({"project": project, "check": check, "message": message})


def parse_page_meta(src):
    """只抽 meta 區塊（不執行模組，避免把瀏覽器相依帶進來）。

    ⚠️ 不要用 `export const meta = {...\\n};` 這種「一定要換行再收尾」的寫法：
       實際的 meta 常常是幾行、最後一個欄位跟 `};` 同一行（remote/pca9685 就是），
       這種寫法會把合法頁面判成「缺少 meta」。這裡允許一層巢狀大括號。
    """
    m = re.search(r"export const meta\s*=\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*;", src)
    if not m:
        return None
    block = m.group(0)

    def pick(pattern):
        mm = re.search(pattern, block)
        return mm.group(1) if mm else None

    return {
        "id": pick(r"""\bid:\s*["']([^"']+)["']"""),
        "title": pick(r"""\btitle:\s*["']([^"']+)["']"""),
        "icon": pick(r"""\bicon:\s*["']([^"']+)["']"""),
        "order": float(pick(r"\border:\s*(-?[\d.]+)") or 0),
        "dev": bool(re.search(r"\bdev:\s*true", block)),
    }


def check_project(entry):
    pid = entry["id"]
    base = os.path.join(ROOT, entry.get("path", "projects/" + pid))
    pj_path = os.path.join(base, "project.json")
    if not os.path.isfile(pj_path):
        err(pid, "project.json", "找不到 " + _rel(pj_path))
        return

    hashes[_rel(pj_path)] = _sha(pj_path)
    try:
        pj = json.loads(_read(pj_path))
    except Exception as e:
        err(pid, "project.json", "解析失敗：%s" % e)
        return

    display = pj.get("display") or {}
    if not display.get("w") or not display.get("h"):
        warn(pid, "project.json", "display.w/h 未設定，會用 320×240 預設")

    # theme 綁定
    theme = pj.get("theme") or {}
    theme_id = theme.get("id", "traework")
    theme_file = os.path.join(ROOT, "packages", "themes", theme_id, "index.js")
    if not os.path.isfile(theme_file):
        err(pid, "theme", "theme '%s' 不存在（%s）" % (theme_id, _rel(theme_file)))
    else:
        hashes[_rel(theme_file)] = _sha(theme_file)
        m = re.search(r"""export const version\s*=\s*["']([^"']+)["']""", _read(theme_file))
        theme_version = m.group(1) if m else None
        if theme.get("version") and theme_version and theme["version"] != theme_version:
            err(pid, "theme", "版本不合：project 綁 %s，theme 是 %s" % (theme["version"], theme_version))

    # 頁面
    pages_dir = os.path.join(base, pj.get("pages", "pages"))
    if not os.path.isdir(pages_dir):
        err(pid, "pages", "找不到頁面目錄 " + _rel(pages_dir))
        return

    files = sorted(f for f in os.listdir(pages_dir) if f.endswith(".js") and f != "index.js")
    index_path = os.path.join(pages_dir, "index.js")
    index_src = _read(index_path) if os.path.isfile(index_path) else ""
    if not index_src:
        err(pid, "pages", "pages/index.js 不存在（沒有它就不會註冊任何頁面）")

    metas = []
    seen = set()
    for f in files:
        path = os.path.join(pages_dir, f)
        hashes[_rel(path)] = _sha(path)
        # 共用模組（*_common.js / *_util.js）不是頁面：沒有 meta，也不該出現在 index.js
        if re.search(r"_(common|util)\.js$", f):
            if f in index_src:
                err(pid, "pages", "共用模組 %s 不該在 index.js 註冊" % f)
            continue
        src = _read(path)
        meta = parse_page_meta(src)
        if not meta or not meta.get("id"):
            err(pid, "page", "%s 缺少 export const meta { id }" % f)
            continue
        if meta["id"] in seen:
            err(pid, "page", "%s 的 id '%s' 重複" % (f, meta["id"]))
        seen.add(meta["id"])
        if not re.search(r"export function build\s*\(", src):
            err(pid, "page", "%s 缺少 export function build()" % f)
        if ('"./%s"' % f) not in index_src:
            err(pid, "pages", 'pages/index.js 沒有 import "./%s"' % f)
        metas.append(dict(meta, file=f))

    # 字型檔可解析
    for name in ("zh_hant_16.bin", "icons_16.bin"):
        fpath = os.path.join(ROOT, "assets", "fonts", name)
        if not os.path.isfile(fpath):
            err(pid, "font", "字型不存在 " + _rel(fpath))
            continue
        try:
            font_codepoints(fpath)
        except Exception as e:
            err(pid, "font", "%s 解析失敗：%s" % (name, e))

    # 資產盤點（缺字 / 圖示）
    try:
        rep = build_report(pid)
        for m in rep["chars"]["missing"]:
            err(pid, "glyph", "缺字 '%s' %s（%s）→ 真機方框" % (m["ch"], m["cp"], ", ".join(m["files"])))
        for n in rep["icons"]["unknown"]:
            err(pid, "icon", "圖示 '%s' 不在對照表" % n)
        for n in rep["icons"]["missing_in_bin"]:
            err(pid, "icon", "圖示 '%s' 不在 icons_16.bin" % n)
        if rep["icons"]["unused"]:
            warn(pid, "icon", "對照表有 %d 個圖示沒用到（不是錯誤）" % len(rep["icons"]["unused"]))
        projects.append(
            {
                "id": pid,
                "title": pj.get("title") or entry.get("title") or pid,
                "theme": "%s@%s" % (theme_id, theme.get("version", "?")),
                "pages": sorted(metas, key=lambda m: m["order"]),
                "chars": rep["chars"]["total"],
                "icons": len(rep["icons"]["used"]),
            }
        )
    except Exception as e:
        err(pid, "assets", "盤點失敗：%s" % e)


def main():
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    index_path = os.path.join(ROOT, "projects.json")
    if not os.path.isfile(index_path):
        err(None, "projects", "找不到根目錄的 projects.json")
    else:
        hashes["projects.json"] = _sha(index_path)
        try:
            index = json.loads(_read(index_path))
        except Exception as e:
            err(None, "projects", "projects.json 解析失敗：%s" % e)
            index = {"projects": []}
        items = index.get("projects", [])
        if not items:
            err(None, "projects", "projects.json 裡沒有任何專案")
        for entry in items:
            if wanted and entry.get("id") not in wanted:
                continue
            check_project(entry)

    report = {
        "schema": "validation-report/1",
        "generated_at": _now(),
        "outcome": "failed" if errors else "passed",
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "projects": projects,
        "hashes": hashes,
        "checkedAt": _now(),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[validate] %s - %d error(s) - %d warning(s)" % (report["outcome"].upper(), len(errors), len(warnings)))
    for e in errors:
        print("   x [%s] %s: %s" % (e["project"] or "-", e["check"], e["message"]))
    for w in warnings:
        print("   ! [%s] %s: %s" % (w["project"] or "-", w["check"], w["message"]))
    for p in projects:
        print("   . %s -> %d page(s), theme %s, %d chars, %d icons" % (p["id"], len(p["pages"]), p["theme"], p["chars"], p["icons"]))
    print("[validate] -> " + _rel(OUT))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
