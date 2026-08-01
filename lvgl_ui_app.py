# lvgl_ui_app.py — LVGL 控制台主程式（lvgl-console-ui 完整 5 頁）
#
# 架構：
#   lvgl_ui_common      共用 palette / 字體 / 元件 builder
#   lvgl_page_launcher  功能選擇（hub）
#   lvgl_page_overview  儀表盤
#   lvgl_page_monitor   數據監控
#   lvgl_page_control   設備控制
#   lvgl_page_settings  系統設定
#
# 導航（對應 lvgl-console-ui.design 的 interactions）：
#   launcher 卡片 → 功能頁（C 確認進入，右滑入動畫）
#   功能頁 BTN42  → 返回 launcher（左滑入動畫）
#
# 輸入（Inputs 驅動，對應 lvgl_ui_launcher.py）：
#   編碼器 A/B → 旋轉（焦點 / 編輯中為調值）
#   編碼器 C(GPIO17) → 確認
#   外接按鈕 42 → 返回 / 退出
#
# 用法（soft reboot 後）：
#   import lvgl_ui_app

import lvgl as lv
from lvgl_shared import FrameBuffer, Inputs
from lvgl_ui_common import init_fonts

import lvgl_page_launcher as pg_launcher
import lvgl_page_overview as pg_overview
import lvgl_page_monitor as pg_monitor
import lvgl_page_control as pg_control
import lvgl_page_settings as pg_settings

# ====== 初始化 ======
fb = FrameBuffer(320, 240, 0x60)   # 橫屏：ST7789 MADCTL MV|MX
fb.setup()
init_fonts()                        # lv.init() 後才能載入 .bin 字體
inp = Inputs()

# ====== 頁面註冊 ======
PAGES = [
    ("launcher", pg_launcher),
    ("overview", pg_overview),
    ("monitor", pg_monitor),
    ("control", pg_control),
    ("settings", pg_settings),
]
mods = {}
for _name, _m in PAGES:
    _m.build()
    mods[_name] = _m

cur = "launcher"
lv.screen_load(pg_launcher.scr)

# 過場動畫常量（binding 差異防護：拿不到就用整數，再不行就無動畫）
_ANIM = getattr(lv, "SCREEN_LOAD_ANIM", None)
_ANIM_OVER_LEFT = getattr(_ANIM, "OVER_LEFT", 1)    # 返回：新頁從左滑入
_ANIM_OVER_RIGHT = getattr(_ANIM, "OVER_RIGHT", 2)  # 進入：新頁從右滑入

def go(name, back=False):
    """切換頁面（帶過場動畫，失敗時降級為直接切換）。"""
    global cur
    if name == cur or name not in mods:
        return
    mods[cur].on_leave()
    scr = mods[name].scr
    try:
        lv.screen_load_anim(scr, _ANIM_OVER_LEFT if back else _ANIM_OVER_RIGHT,
                            240, 0, False)
    except Exception:
        lv.screen_load(scr)
    mods[name].on_enter()
    print("[nav] {} -> {}".format(cur, name))
    cur = name

print("UI app ready — encoder: focus / C: confirm / BTN42: back")

# ====== 主迴圈 ======
_run = 0
while True:
    d = inp.enc_delta()
    c = inp.confirm_pressed()
    ex = inp.exit_pressed()
    m = mods[cur]

    if d != 0:
        m.on_enc(d)

    if c:
        target = m.on_confirm()
        if target:
            go(target)

    if ex:
        if cur != "launcher" and m.on_exit():
            pass                      # 頁面消耗了（例如離開編輯模式）
        elif cur != "launcher":
            go("launcher", back=True)
        else:
            print("[exit]")

    _run += 1
    m.update(_run)

    # ── 渲染 ──
    fb.tick()
    for x1, y1, x2, y2, data in fb.take():
        fb.show_rect(x1, y1, x2, y2, data)
