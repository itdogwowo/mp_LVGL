#!/usr/bin/env python3
"""產生繁體中文 .bin 字體（lv_font_conv 1.5.3 + LVGL 9 binfont loader）

做法：
  1. 自動掃描本專案所有 .py 源碼，收集所有非 ASCII 字符
     （頁面字串字面量 + 註解都會掃到；多收無害，漏收才會變方塊）
  2. 額外補充動態字串可能用到的符號（° ℃ · ± → ← 等）
  3. 用「碼點 range」傳給 lv_font_conv（避免 CLI 直接傳中文字的編碼問題）
  4. --no-compress：與官方 binfont 範例一致，不依賴 RLE 解壓路徑

注意：LVGL binfont bin 格式的 cmap 有兩類 subtable：
  - format0_tiny (type 2)：連續區段，無 data（glyph = glyph_id_start + rcp）
  - sparse_tiny  (type 3)：離散字符，data 存「code - range_start」相對值
  兩者共享 data_offset 是正常設計，勿當成重複。
"""
import subprocess, sys, re

FONT = "/Library/Fonts/Arial Unicode.ttf"
OUT = "zh_hant_16.bin"

# ── 1. 掃描源碼收集字符 ──
SRC_FILES = [
    "lvgl_ui_common.py", "lvgl_ui_app.py", "lvgl_ui_launcher.py",
    "lvgl_page_launcher.py", "lvgl_page_overview.py",
    "lvgl_page_monitor.py", "lvgl_page_control.py", "lvgl_page_settings.py",
    "gen_font.py",
]
chars = set()
for fn in SRC_FILES:
    with open(fn, "r", encoding="utf-8") as f:
        chars |= {c for c in f.read() if ord(c) > 0x7F}

# ── 2. 補充動態字串符號 ──
# ° 溫度單位；· 分隔點；± 公差；→/← 方向；↑/↓ 趨勢；℃ ℃ 溫度；… 省略
chars |= set("°℃·±×÷→←↑↓─…／　")

codepoints = sorted(ord(c) for c in chars)
print("Unique non-ASCII chars: {}".format(len(codepoints)))

# ── 3. 組 -r range 參數（ASCII + 全部 CJK/符號）──
r = "0x20-0x7F," + ",".join("0x%04X" % cp for cp in codepoints)

# ── 4. 執行轉換 ──
cmd = [
    "npx", "lv_font_conv",
    "--font", FONT,
    "--size", "16",
    "--format", "bin",
    "--bpp", "4",
    "-r", r,
    "--no-compress",
    "-o", OUT,
]
print("\nRunning:", " ".join(cmd[:8]), "...")
r2 = subprocess.run(cmd, capture_output=True, text=True)
print(r2.stdout)
if r2.returncode != 0:
    print("STDERR:", r2.stderr, file=sys.stderr)
    sys.exit(1)

import os
print("Done → {} ({} bytes)".format(OUT, os.path.getsize(OUT)))
