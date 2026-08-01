# test_icons.py — 板上 icon 字體自測
#
# 用法:先跑過 import lvgl_ui_app（或任何建立 display 的流程）,再執行本檔。
#   預期輸出:
#     [icons] loaded N icons
#     ✓ icon 字體載入成功
#     然後螢幕左上角出現一個紅色圖示(thermometer)。
#   若顯示 ✗ → 照錯誤訊息處理:
#     FileNotFoundError: 板上根目錄缺少 icons_16.bin,請上傳
#     其他錯誤 → 把訊息貼回來
import lvgl as lv
from lv_icons import ICONS, load_icon_font

print("[test] ICONS 數量:", len(ICONS))
try:
    f = load_icon_font()
    print("[test] ✓ icon 字體載入成功:", f)
    scr = lv.screen_active()
    lb = lv.label(scr)
    lb.set_text(ICONS["thermometer"])
    lb.set_pos(8, 8)
    lb.set_style_text_font(f, 0)
    lb.set_style_text_color(lv.color_hex(0xE53935), 0)  # 紅色,明顯易見
    print("[test] ✓ 已畫出 thermometer 圖示(螢幕左上角紅色)")
except Exception as e:
    print("[test] ✗ icon 載入失敗:", repr(e))
    if "No such file" in str(e):
        print("[test]   → 板上根目錄缺少 /icons_16.bin,請先上傳")
