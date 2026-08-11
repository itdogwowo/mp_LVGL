#!/usr/bin/env python3
# project_io.py — 外部專案 ↔ design 庫 導入/導出
#
# 把外部專案的 LVGL UI 資料夾（如 mp_Net-Core/slave/ui/lvgl）導入成
# tools/design/{name}/ 的一個 design（產物位置 = design/{name}/lvgl/ui/），
# AI 直接改 design 庫裡的檔案後再導出回專案。
#
# 用法（在 mp_LVGL 根目錄或任何目錄皆可）:
#   python tools/project_io.py import <專案的 ui/lvgl 目錄> [--name NAME]
#   python tools/project_io.py export <name> [--zip PATH] [--to DIR] [--no-zip]
#   python tools/project_io.py list
#
# 導入:整個目錄複製進 design/{name}/lvgl/ui/ + 掃 page/*.py 的 @register
#       寫進 design.json（GUI 的「重新掃描」對導入的 design 同樣有效）。
# 導出:--zip 打包成 zip（內容 = lvgl/ 資料夾,解壓到專案的 ui/ 下即部署）;
#       --to DIR 直接合併複製到目標目錄。兩者可同时使用。
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from assets import designlib  # noqa: E402


def _fail(msg: str) -> None:
    print("✗ " + msg, file=sys.stderr)
    raise SystemExit(1)


# ============ import ============

def cmd_import(src: Path, name: str) -> None:
    if not src.exists() or not src.is_dir():
        _fail(f"來源不存在或不是目錄: {src}")
    for req in ("app.py", "registry.py"):
        if not (src / req).exists():
            _fail(f"來源缺少 {req}（不像 LVGL UI 資料夾）: {src}")
    if not (src / "page").is_dir():
        _fail(f"來源缺少 page/ 目錄: {src}")

    # 解析螢幕尺寸（lvgl_init.py 的 _W/_H,找不到就用預設）
    w, h = 320, 240
    init_py = src / "lvgl_init.py"
    if init_py.exists():
        import re

        txt = init_py.read_text(encoding="utf-8", errors="replace")
        mw = re.search(r"^_W\s*=\s*(\d+)", txt, re.M)
        mh = re.search(r"^_H\s*=\s*(\d+)", txt, re.M)
        if mw:
            w = int(mw.group(1))
        if mh:
            h = int(mh.group(1))

    # 建 design（已存在則沿用 meta;name 會被 create_design 清洗成安全字串）
    meta = designlib.create_design(name, title=name, width=w, height=h)
    name = Path(meta["dir"]).name   # 清洗後的真名
    d = designlib.DESIGN_LIB / name
    ui_dst = designlib.lvgl_path(name) / "ui"

    # 複製整個 ui 資料夾（先清舊的,確保與來源一致）
    if ui_dst.exists():
        shutil.rmtree(ui_dst)
    ui_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, ui_dst)

    # 更新 meta:來源路徑 + 完整掃描（scan_design 會合併 HTML/LVGL 雙欄位）
    meta = designlib.read_design(name) or {}
    meta["source"] = str(src.resolve())
    designlib.write_design(name, meta)
    meta = designlib.scan_design(name)   # 重建 pages/nav/layout（含 lvgl_file 欄位）

    n_files = sum(1 for _ in ui_dst.rglob("*") if _.is_file())
    pages = [p for p in meta["pages"] if p.get("tag") != "launcher"]
    print(f"✓ 導入完成: {src} → design/{name}/lvgl/ui/")
    print(f"  {n_files} 個檔案, {len(pages)} 個頁面:")
    for p in pages:
        wf = "✓" if p.get("web_file") else " "
        lf = "✓" if p.get("lvgl_file") else " "
        print(f"    [{wf}{lf}] {p['id']}: {p.get('title', '')} ({p.get('lvgl_file', '')})")
    print("  之後直接改 design 庫裡的檔案即可;tools 網頁「重新掃描」會更新頁面清單。")


# ============ export ============

def cmd_export(name: str, zip_path: Path | None, to_dir: Path | None,
               no_zip: bool) -> None:
    meta = designlib.read_design(name)
    if not meta:
        _fail(f"design 不存在: {name}")
    lvgl_dir = designlib.lvgl_path(name)
    ui_dir = lvgl_dir / "ui"
    if not ui_dir.exists():
        _fail(f"design/{name} 沒有 lvgl/ui/（先導入或生成）")

    did_something = False

    if not no_zip:
        if zip_path is None:
            zip_path = lvgl_dir / f"{name}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        # zip 內路徑 = lvgl/... → 解壓到專案的 ui/ 下即是 ui/lvgl/...
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(ui_dir.rglob("*")):
                if p.is_file():
                    arc = "lvgl/" + p.relative_to(ui_dir).as_posix()
                    zf.write(p, arc)
        n = sum(1 for _ in zipfile.ZipFile(zip_path).infolist())
        print(f"✓ 導出 zip: {zip_path} ({zip_path.stat().st_size:,} bytes, {n} 檔)")
        print("  解壓到專案的 ui/ 資料夾即完成部署（內容為 lvgl/...）。")
        did_something = True

    if to_dir is not None:
        to_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ui_dir, to_dir, dirs_exist_ok=True)
        print(f"✓ 導出目錄: {ui_dir} → {to_dir}")
        did_something = True

    if not did_something:
        _fail("沒有導出動作（--no-zip 時需指定 --to）")


# ============ list ============

def cmd_list() -> None:
    designs = designlib.list_designs()
    if not designs:
        print("（design 庫為空）")
        return
    for meta in designs:
        name = Path(meta["dir"]).name
        lv = designlib.lvgl_status(name)
        src = meta.get("source", "")
        tag = "導入" if src else ("html" if meta.get("pages") else "空")
        print(f"- {name}  [{tag}]  {meta.get('width')}×{meta.get('height')}"
              f"  pages={len(meta.get('pages', []))}")
        if src:
            print(f"    source: {src}")
        if lv["ui_files"]:
            print(f"    ui: {', '.join(lv['ui_files'])}")
        if lv["src_files"]:
            print(f"    src: {', '.join(lv['src_files'])}")


# ============ main ============

def main() -> None:
    ap = argparse.ArgumentParser(
        description="外部專案 ↔ design 庫 導入/導出（LVGL UI Asset Studio）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("import", help="導入專案的 ui/lvgl 目錄成 design")
    p_in.add_argument("source", help="來源目錄（如 .../slave/ui/lvgl）")
    p_in.add_argument("--name", default="slave-ui",
                      help="design 名稱（預設 slave-ui）")

    p_out = sub.add_parser("export", help="導出 design 的 lvgl/ui")
    p_out.add_argument("name", help="design 名稱")
    p_out.add_argument("--zip", dest="zip_path", default=None,
                       help="zip 輸出路徑（預設 design/{name}/lvgl/{name}.zip）")
    p_out.add_argument("--to", dest="to_dir", default=None,
                       help="直接合併複製到目標目錄（如 .../slave/ui/lvgl）")
    p_out.add_argument("--no-zip", action="store_true", help="不產 zip")

    sub.add_parser("list", help="列出 design 庫")

    args = ap.parse_args()
    if args.cmd == "import":
        cmd_import(Path(args.source), args.name)
    elif args.cmd == "export":
        cmd_export(args.name,
                   Path(args.zip_path) if args.zip_path else None,
                   Path(args.to_dir) if args.to_dir else None,
                   args.no_zip)
    elif args.cmd == "list":
        cmd_list()


if __name__ == "__main__":
    main()
