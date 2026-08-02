# ui/board.py — 板上對接層（slave new bus 系統）
#
# ui/ 是 slave new 專案裡的一個 UI 區塊（像 tasks/lib）。
# 硬體全部透過 slave new 的 bus 系統取得,本檔不自建任何硬體:
#   顯示   bus.get_service("lcd")   （ST7789 + SpiBusAdapter,set_window/write_data_async）
#   編碼器 bus.shared["_enc_delta"] （control_panel 累加寫入）
#   按鈕   bus.shared["_vbtn1_event"]（VBTN 虛擬按鈕事件）
#
# 用法（slave new 環境,soft reboot 後）:
#   import ui.board
#   ui.board.run()
import sys
import lvgl as lv
from lib.sys_bus import bus
from ui import app

# 資源在 ui/src,加進 import 路徑（ui_common 的 from lv_icons/lv_ui_fx 由此找到）
_SRC = "/ui/src"
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_W = 320
_H = 240
_LINES = 40
_BPP = 2


class _Platform:
    """slave new bus 版平台:app 吃 {tick,take,show,enc_delta,confirm,exit}。"""

    def __init__(self):
        self.lcd = bus.get_service("lcd")
        if self.lcd is None:
            raise RuntimeError("lcd not on bus — 先跑 boot.py")
        self._bus = getattr(self.lcd, "_bus", None)
        self._dirty = []
        self._last_enc = 0

        # LVGL 初始化
        if lv.is_initialized():
            lv.deinit()
        lv.init()
        self._disp = lv.display_create(_W, _H)
        self._disp.set_color_format(18)  # RGB565
        buf = bytearray(_W * _LINES * _BPP)
        self._disp.set_buffers(buf, None, len(buf), 0)  # PARTIAL
        self._disp.set_flush_cb(self._flush_cb)

    # ---- LVGL flush:存髒區,由主迴圈 show ----
    def _flush_cb(self, disp_drv, area, color_p):
        w = area.x2 - area.x1 + 1
        h = area.y2 - area.y1 + 1
        data = color_p.__dereference__(w * h * _BPP)
        lv.draw_sw_rgb565_swap(data, w * h)
        self._dirty.append((area.x1, area.y1, area.x2, area.y2, bytes(data)))
        disp_drv.flush_ready()

    # ---- platform 介面 ----
    def tick(self):
        import time
        time.sleep_us(5000)
        lv.tick_inc(5)
        lv.task_handler()
        lv.refr_now(self._disp)

    def take(self):
        rects = self._dirty
        self._dirty = []
        return rects

    def show(self, x1, y1, x2, y2, data):
        self.lcd.set_window(x1, y1, x2, y2)
        self._bus.write_data_async(data)
        self._bus.flush()

    def enc_delta(self):
        v = int(bus.shared.get("_enc_delta", 0) or 0)
        d = v - self._last_enc
        self._last_enc = v
        return d

    def confirm(self):
        return bool(bus.shared.get("_vbtn1_event", 0) or 0)

    def exit(self):
        return False


def run():
    """建立 slave new 平台 + 啟動 UI 主迴圈。"""
    plat = _Platform()

    # 載入字體資源 + 註冊頁面（ui/src 已加進 sys.path）
    import ui_common
    ui_common.init_fonts()
    try:
        import ui.page  # noqa: F401  板上:集中註冊所有頁面
    except ImportError:
        pass

    app.init({
        "tick": plat.tick,
        "take": plat.take,
        "show": plat.show,
        "enc_delta": plat.enc_delta,
        "confirm": plat.confirm,
        "exit": plat.exit,
    })
    app.go("launcher")
    app.run()
