# icons.py — 圖示資產生成
#
# 流程:
#   1. 下載 Material Symbols Rounded 字體 + codepoints 對照表（快取,重跑不重載）
#   2. lucide 圖示名 → Material Symbols 名（內建映射,可在 GUI 調整）
#   3. lv_font_conv 抽出碼點 → icons_16.bin（--no-compress）
#   4. bin cmap 驗證（format0_tiny / sparse_tiny 格式）
#   5. 產生板上 helper: lv_icons.py
#
# 網路來源（皆為公開免費資源）:
#   ttf:  marella/material-symbols (static rounded)  → fallback google variable
#   cp:   google/material-design-icons codepoints
from __future__ import annotations

import re
import subprocess
import urllib.request
from pathlib import Path

from . import CACHE_DIR, OUT_DIR
from .scanner import scan

# ---------- 來源 URL ----------
_VAR = "%5BFILL%2CGRAD%2Copsz%2Cwght%5D"  # [FILL,GRAD,opsz,wght] URL 編碼
MS_TTF_URLS = [
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    f"variablefont/MaterialSymbolsRounded{_VAR}.ttf",
    "https://github.com/google/material-design-icons/raw/master/"
    f"variablefont/MaterialSymbolsRounded{_VAR}.ttf",
]
MS_CP_URL = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    f"variablefont/MaterialSymbolsRounded{_VAR}.codepoints"
)

TTF_NAME = "material_symbols_rounded.ttf"
CP_NAME = "material_symbols_rounded.codepoints"

# ---------- lucide 圖示 → Material Symbols 名稱 ----------
# GUI 可覆寫（存 config.json 的 icons 欄位）。
LUCIDE_TO_MS = {
    "activity": "monitoring",
    "alert-triangle": "warning",
    "battery-full": "battery_full",
    "chevron-down": "keyboard_arrow_down",
    "chevron-left": "chevron_left",
    "chevron-right": "chevron_right",
    "clock": "schedule",
    "droplets": "water_drop",
    "fan": "mode_fan",
    "flame": "local_fire_department",
    "gauge": "speed",
    "info": "info",
    "layout-dashboard": "dashboard",
    "lightbulb": "lightbulb",
    "play": "play_arrow",
    "power": "power_settings_new",
    "refresh-cw": "refresh",
    "save": "save",
    "sensors": "sensors",
    "settings": "settings",
    "shield": "shield",
    "sliders-horizontal": "tune",
    "square": "crop_square",
    "sun": "light_mode",
    "thermometer": "device_thermostat",
    "trending-up": "trending_up",
    "wifi": "wifi",
    "wind": "air",
    "zap": "bolt",
}

_CP_RE = re.compile(r"^([a-z0-9_]+)\s+([0-9a-fA-F]+)$")


def _log(log, msg: str) -> None:
    if log:
        log(msg)
    else:
        print(msg)


def _download(url: str, dest: Path, log) -> bool:
    """下載到 dest,回傳成功與否。"""
    try:
        _log(log, f"下載 {url}")
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
        return True
    except Exception as e:
        _log(log, f"  ✗ 失敗: {e}")
        if dest.exists():
            dest.unlink()
        return False


def _is_ttf(path: Path) -> bool:
    """TTF/OTF magic: 0x00010000 或 'OTTO' 或 'true'。"""
    try:
        head = path.read_bytes()[:4]
        return head in (b"\x00\x01\x00\x00", b"OTTO", b"true")
    except OSError:
        return False


def ensure_resources(log=None) -> tuple[Path, dict[str, int]]:
    """確保 ttf + codepoints 已快取,回傳 (ttf_path, {name: codepoint})。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ttf = CACHE_DIR / TTF_NAME
    cp_file = CACHE_DIR / CP_NAME

    if not (ttf.exists() and _is_ttf(ttf)):
        for url in MS_TTF_URLS:
            if _download(url, ttf, log) and _is_ttf(ttf):
                break
        if not _is_ttf(ttf):
            raise RuntimeError("Material Symbols 字體下載失敗(所有來源)。請檢查網路後重試。")

    if not cp_file.exists():
        if not _download(MS_CP_URL, cp_file, log):
            raise RuntimeError("Material Symbols codepoints 下載失敗。")

    cps: dict[str, int] = {}
    for line in cp_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CP_RE.match(line.strip())
        if m:
            cps[m.group(1)] = int(m.group(2), 16)
    _log(log, f"資源就緒: {ttf.name} ({ttf.stat().st_size//1024} KB), "
             f"codepoints {len(cps)} 個")
    return ttf, cps


def _range_arg(codepoints: list[int]) -> str:
    return "0x20-0x7F," + ",".join("0x%04X" % cp for cp in sorted(codepoints))


def run_lv_font_conv(font_path: Path, codepoints: list[int],
                     out_path: Path, size: int, log=None) -> None:
    """呼叫 npx lv_font_conv 生成 bin 字體。"""
    cmd = [
        "npx", "lv_font_conv",
        "--font", str(font_path),
        "--size", str(size),
        "--format", "bin",
        "--bpp", "4",
        "-r", _range_arg(codepoints),
        "--no-compress",
        "-o", str(out_path),
    ]
    _log(log, "執行 " + " ".join(cmd[:8]) + " …")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout:
        _log(log, r.stdout.strip())
    if r.returncode != 0:
        raise RuntimeError("lv_font_conv 失敗:\n" + (r.stderr or r.stdout))
    _log(log, f"→ {out_path.name} ({out_path.stat().st_size} bytes)")


# ---------- bin cmap 驗證（對齊 LVGL lv_binfont_loader） ----------
def _parse_cmap(bin_path: Path) -> list[dict]:
    """解析 binfont 的 cmap 區段（format0_tiny type2 / sparse_tiny type3）。"""
    data = bin_path.read_bytes()
    hlen = int.from_bytes(data[0:4], "little")
    if data[4:8] != b"head":
        raise ValueError("不是有效的 binfont 檔")
    cmap_start = hlen
    n_sub = int.from_bytes(data[cmap_start + 8 : cmap_start + 12], "little")
    subs = []
    for i in range(n_sub):
        o = cmap_start + 12 + i * 16
        subs.append(
            {
                "data_offset": int.from_bytes(data[o : o + 4], "little"),
                "range_start": int.from_bytes(data[o + 4 : o + 8], "little"),
                "range_length": int.from_bytes(data[o + 8 : o + 10], "little"),
                "glyph_id_start": int.from_bytes(data[o + 10 : o + 12], "little"),
                "entries": int.from_bytes(data[o + 12 : o + 14], "little"),
                "fmt": data[o + 14],
            }
        )
    for s in subs:
        s["list"] = []
        if s["fmt"] in (0, 2):  # format0: 無 data 或連續
            continue
        d0 = cmap_start + s["data_offset"]
        for k in range(s["entries"]):
            off = d0 + k * 2
            s["list"].append(int.from_bytes(data[off : off + 2], "little"))
    return subs


def verify_bin_font(bin_path: Path, codepoints: list[int]) -> list[int]:
    """驗證所有碼點都可在 bin 字形表中找到,回傳缺失碼點。"""
    subs = _parse_cmap(bin_path)
    missing = []
    for cp in codepoints:
        found = False
        for s in subs:
            if cp < s["range_start"] or cp >= s["range_start"] + s["range_length"]:
                continue
            if s["fmt"] in (0, 2):
                found = True
                break
            if (cp - s["range_start"]) in s["list"]:
                found = True
                break
        if not found:
            missing.append(cp)
    return missing


# ---------- 生成 ----------
def generate_icons(mapping: dict[str, str], log=None,
                   out_root: Path | None = None) -> dict:
    """依 mapping（lucide名→MS名）生成 icons_16.bin + lv_icons.py。

    out_root: 輸出目錄（預設 OUT_DIR）。design 模式下傳該 design 的 lvgl/src。
    """
    out_root = out_root or OUT_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    ttf, cps = ensure_resources(log)

    lucide_names = sorted(mapping)
    ms_names = []
    for n in lucide_names:
        ms = mapping[n]
        if ms not in cps:
            _log(log, f"  ⚠ {n} → '{ms}' 不在 Material Symbols 中,請在 GUI 調整")
            continue
        ms_names.append((n, ms))

    if not ms_names:
        raise RuntimeError("沒有可生成的圖示(檢查映射)。")

    codepoints = [cps[ms] for _n, ms in ms_names]
    bin_path = out_root / "icons_16.bin"
    run_lv_font_conv(ttf, codepoints, bin_path, 16, log)

    missing = verify_bin_font(bin_path, codepoints)
    if missing:
        _log(log, f"  ⚠ bin 驗證缺 {len(missing)} 個碼點: "
                  f"{[hex(c) for c in missing]}")

    _write_lv_icons(out_root / "lv_icons.py", ms_names, cps, log)
    _log(log, f"icons 完成: {len(ms_names)} 個圖示 "
              f"({len([c for c in codepoints if c not in missing])} 個碼點驗證通過)")
    return {
        "count": len(ms_names),
        "missing_codepoints": len(missing),
        "bin": str(bin_path.relative_to(out_root.parent)),
    }


_ICON_HELPER_TEMPLATE = """# lv_icons.py — 圖示 helper（由 LVGL UI Asset Studio 產生）
#
# 使用:
#   from lv_icons import ICONS, load_icon_font, mk_icon
#   ic = mk_icon(parent, "thermometer", x, y, color=0x1F1F1F)
#
# 板上需有 /icons_16.bin（與本檔同層放置）。
import lvgl as lv

_ICON = None
_FONT_FILE = "/icons_16.bin"

# lucide 圖示名 → 字符（Material Symbols Rounded）
ICONS = {{
{icons_dict}
}}


def load_icon_font():
    \"\"\"載入 icon 字體（lf binfont,需在 lv.init() 之後呼叫）。\"\"\"
    global _ICON
    if _ICON is not None:
        return _ICON
    with open(_FONT_FILE, "rb") as fp:
        buf = fp.read()
    if hasattr(lv, "binfont_create_from_buffer"):
        try:
            _ICON = lv.binfont_create_from_buffer(bytearray(buf), len(buf))
        except TypeError:
            _ICON = lv.binfont_create_from_buffer(bytearray(buf))
    if _ICON is None:
        raise RuntimeError("icons_16.bin 載入失敗")
    print("[icons] loaded", len(ICONS), "icons")
    return _ICON


def mk_icon(parent, name, x, y, color=0x1F1F1F):
    \"\"\"建立一個圖示 label。name 為 ICONS 的鍵名。\"\"\"
    if name not in ICONS:
        raise KeyError("unknown icon: " + str(name))
    lb = lv.label(parent)
    lb.set_text(ICONS[name])
    lb.set_pos(x, y)
    lb.set_style_text_color(lv.color_hex(color), 0)
    lb.set_style_text_font(load_icon_font(), 0)
    return lb
"""


def _write_lv_icons(out_path: Path, ms_names: list[tuple[str, str]],
                    cps: dict[str, int], log) -> None:
    lines = [
        '    "{}": "\\u{:04X}",'.format(name, cps[ms])
        for name, ms in ms_names
    ]
    content = _ICON_HELPER_TEMPLATE.format(icons_dict="\n".join(lines))
    out_path.write_text(content, encoding="utf-8")
    _log(log, f"→ {out_path.name}")
