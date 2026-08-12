#!/usr/bin/env python3
# project_io.py — SimLab 項目匯入/匯出(本地複製件)
#
# SimLab 的項目是「完全在本地」的複製件(tools/simlab/projects/{name}/):
#   匯入 = 從真機路徑複製一份進來(lvgl/ + html/ + assets/)
#   匯出 = 本地複製件寫回真機來源(source / source_html / bins)
#
# 用法(在 mp_LVGL/tools 下):
#   python simlab/project_io.py list
#   python simlab/project_io.py import <真機路徑> [--name N] [--title T] [--group G]
#                                          [--html DIR] [--bins-dir DIR] [--w 320] [--h 240]
#   python simlab/project_io.py export <name>
#
# 例:
#   python simlab/project_io.py import mp_Net-Core/slave/ui/lvgl --name slave \
#       --title "mp_Net-Core slave (真機 UI)" --html mp_LVGL/tools/design/slave-ui/html
#   python simlab/project_io.py import mp_LVGL --name mp_lvgl --title "mp_LVGL 參考 UI" \
#       --html mp_LVGL/lvgl-console-ui/pages --bins-dir mp_Net-Core/slave/ui/lvgl/src
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import (  # noqa: E402
    _load_projects,
    _project,
    _save_projects,
    _scan_source,
    export_project,
    import_project,
)


def cmd_list() -> None:
    projects = _load_projects()
    if not projects:
        print("(沒有項目)")
        return
    for p in projects:
        entry = p.get("entry") or {}
        print("- {:<12} [{}]  {}x{}  kind={}  source={}".format(
            p.get("name"), p.get("group") or "-", p.get("w", 320), p.get("h", 240),
            entry.get("kind", "?"), p.get("source", "?")))
        if p.get("source_html"):
            print("    html: {}".format(p["source_html"]))
        bins = entry.get("bins") or {}
        if bins:
            print("    bins: {}".format(", ".join("{}←{}".format(k, v) for k, v in bins.items())))


def cmd_import(args) -> int:
    try:
        suggest = _scan_source(args.path)
    except ValueError as e:
        print("✗ 掃描失敗: {}".format(e), file=sys.stderr)
        return 1
    entry = suggest.get("entry") or {}
    html_dir = args.html or suggest.get("html_dir", "")
    try:
        meta = import_project(
            name=args.name or suggest["name"],
            title=args.title or suggest["title"],
            group=args.group or "",
            path=args.path,
            html_dir=html_dir,
            entry=entry,
            w=args.w,
            h=args.h,
            bins_src=args.bins_dir or "",
        )
    except ValueError as e:
        print("✗ 匯入失敗: {}".format(e), file=sys.stderr)
        return 1
    projects = _load_projects()
    projects = [p for p in projects if p.get("name") != meta["name"]]
    projects.append(meta)
    _save_projects(projects)
    d = Path(__file__).resolve().parent / "projects" / meta["name"]
    n_lvgl = sum(1 for _ in (d / "lvgl").rglob("*.py")) if (d / "lvgl").is_dir() else 0
    n_html = sum(1 for _ in (d / "html").rglob("*")) if (d / "html").is_dir() else 0
    n_assets = sum(1 for _ in (d / "assets").rglob("*")) if (d / "assets").is_dir() else 0
    print("✓ 匯入完成 → {}".format(d))
    print("  lvgl {} 檔 · html {} 檔 · assets {} 檔 · 頁面: {}".format(
        n_lvgl, n_html, n_assets, ", ".join(suggest.get("pages", []))))
    print("  模擬器改跑本地複製件;改完用 `export {}` 寫回真機".format(meta["name"]))
    return 0


def cmd_export(args) -> int:
    proj = _project(args.name)
    if proj is None:
        print("✗ 沒有這個項目: {}".format(args.name), file=sys.stderr)
        return 1
    try:
        r = export_project(proj)
    except ValueError as e:
        print("✗ 匯出失敗: {}".format(e), file=sys.stderr)
        return 1
    written = r.get("written", [])
    print("✓ 匯出完成 → {} ({} 檔)".format(proj.get("source"), len(written)))
    for f in written[:30]:
        print("  " + f)
    if len(written) > 30:
        print("  ...共 {} 檔".format(len(written)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SimLab 項目匯入/匯出(本地複製件)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出項目")
    p_in = sub.add_parser("import", help="從真機路徑匯入(複製成本地複製件)")
    p_in.add_argument("path", help="真機路徑(相對 git root)")
    p_in.add_argument("--name", help="項目 name(預設取路徑末段)")
    p_in.add_argument("--title", help="顯示名稱")
    p_in.add_argument("--group", help="分類")
    p_in.add_argument("--html", help="HTML 設計稿目錄(相對 git root)")
    p_in.add_argument("--bins-dir", help="字體借用來源目錄(相對 git root)")
    p_in.add_argument("--w", type=int, default=320)
    p_in.add_argument("--h", type=int, default=240)
    p_out = sub.add_parser("export", help="匯出本地複製件回真機")
    p_out.add_argument("name", help="項目 name")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        return cmd_list() or 0
    if args.cmd == "import":
        return cmd_import(args)
    if args.cmd == "export":
        return cmd_export(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
