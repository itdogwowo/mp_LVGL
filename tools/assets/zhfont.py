# zhfont.py — 中文字體生成
#
# 收集 workspace/design 設計稿的非 ASCII 字符 + 附加字符（GUI 輸入）+ 常用符號,
# 用 lv_font_conv 生成 zh_hant_16.bin（--no-compress,與 LVGL binfont 相容）。
from __future__ import annotations

import subprocess
from pathlib import Path

from . import OUT_DIR
from .icons import run_lv_font_conv, verify_bin_font
from .scanner import scan

# 動態字串常見符號（不一定要在設計稿中）
COMMON_SYMBOLS = "°℃·±×÷→←↑↓…─／　—"

DEFAULT_FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"


def collect_chars(design_dir: Path, extra_chars: str = "") -> str:
    chars = set(scan(design_dir)["chars"])
    chars |= set(extra_chars)
    chars |= set(COMMON_SYMBOLS)
    # 只留非 ASCII（ASCII 由 lv_font_conv 的 0x20-0x7F range 涵蓋）
    chars = {c for c in chars if ord(c) > 0x7F}
    return "".join(sorted(chars, key=ord))


def generate_zh(design_dir: Path, extra_chars: str = "",
                font_path: str = DEFAULT_FONT_PATH, log=None,
                out_root: Path | None = None) -> dict:
    """生成中文字體。out_root 預設 OUT_DIR,design 模式下傳該 design 的 lvgl/src。"""
    out_root = out_root or OUT_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    chars = collect_chars(design_dir, extra_chars)
    if not chars:
        raise RuntimeError("設計稿沒有非 ASCII 字符可生成。")
    codepoints = [ord(c) for c in chars]

    if not Path(font_path).exists():
        raise RuntimeError(f"字體檔不存在: {font_path}（可在 GUI 或 assets/zhfont.py 修改）")

    bin_path = out_root / "zh_hant_16.bin"
    run_lv_font_conv(Path(font_path), codepoints, bin_path, 16, log)

    missing = verify_bin_font(bin_path, codepoints)
    if missing:
        log and log(f"  ⚠ bin 驗證缺 {len(missing)} 個字符: "
                    f"{[chr(c) for c in missing[:20]]}")
    log and log(f"zh 完成: {len(chars)} 個字符, "
                f"{len(codepoints) - len(missing)} 個驗證通過")
    return {
        "char_count": len(chars),
        "missing": len(missing),
        "bin": str(bin_path.relative_to(out_root.parent)),
    }
