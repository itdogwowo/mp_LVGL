# ui/board.py — 板上平台實作（lvgl_ui_app 的替代入口）
#
# 用法（soft reboot 後）:
#   import ui.board
#   ui.board.run()
import lvgl as lv
from lvgl_shared import FrameBuffer, Inputs
from ui import app


def run():
    """初始化硬體 + 注入 platform + 啟動主迴圈。"""
    fb = FrameBuffer(320, 240, 0x60)
    fb.setup()

    from lvgl_ui_common import init_fonts
    init_fonts()

    inp = Inputs()

    app.init({
        "tick": fb.tick,
        "take": fb.take,
        "show": fb.show_rect,
        "enc_delta": inp.enc_delta,
        "confirm": inp.confirm_pressed,
        "exit": inp.exit_pressed,
    })
    app.run()
