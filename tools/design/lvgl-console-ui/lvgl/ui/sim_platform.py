# ui/sim_platform.py — 模擬器平台（在瀏覽器模擬器跑真框架用,不碰 machine）
#
# 在 sim.lvgl.io 的 MicroPython 環境,SDL display_driver 已提供顯示,
# 本平台只提供「輸入模擬」給 ui/app:
#   輸入字元從前端按鈕送進 stdin（process_char）,
#   這裡讀 stdin 當作編碼器/按鈕事件。
#
# 使用（模擬器代碼區「ui 框架」模式）:
#   import ui.sim_platform as sp
#   sp.run(app)   # 注入 + 啟動主迴圈
import sys


class _SimPlatform:
    """模擬平台:SDL 顯示(display_driver 已建),輸入讀 stdin 字元。"""

    def __init__(self):
        self._enc = 0
        self._buf = b""

    def _poll(self):
        # 從 stdin 收字元(前端按鈕透過 process_char 送來)
        try:
            import select
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                self._buf += sys.stdin.read(1).encode()
        except Exception:
            pass
        return self._buf

    # ---- app 介面 ----
    def tick(self):
        lv.task_handler() if "lv" in globals() else None

    def take(self):
        return []

    def show(self, *a):
        pass

    def enc_delta(self):
        b = self._poll()
        d = 0
        while b:
            c = b[0:1]
            b = b[1:]
            if c in (b"l", b"L"):   # ← 左
                d -= 1
            elif c in (b"r", b"R"):  # → 右
                d += 1
        return d

    def confirm(self):
        return self._poll() == b"c"  # 確認

    def exit(self):
        return self._poll() == b"e"  # 返回


def run(app):
    """在模擬器跑真框架:注入模擬平台 + 啟動。"""
    sp = _SimPlatform()
    app.init({
        "tick": sp.tick,
        "take": sp.take,
        "show": sp.show,
        "enc_delta": sp.enc_delta,
        "confirm": sp.confirm,
        "exit": sp.exit,
    })
    app.run()
