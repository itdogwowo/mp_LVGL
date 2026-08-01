# lvgl_shared.py — 緩衝分離架構 + slave new TFT 驅動 + 編碼器/按鈕
# LVGL 只負責渲染到緩衝,flush_cb 只存 (area, data)
# 「show」完全由用戶控制:你決定何時、怎麼送到 TFT 驅動
#
# 顯示硬體：改用 slave new 的 TFT 驅動（bus service "lcd"，ST7789 + SpiBusAdapter）
#   → boot.py 已 init，此處直接取用，不再自己 st7789_init
# 輸入硬體：
#   Inputs 類 — 可調編碼器(A=18/B=8) + 確認鍵(編碼器 C=17) + 退出鍵(外接 BTN=42)
#
# 核心 API:
#   fb = FrameBuffer()
#   fb.setup()          → 從 bus 拿 lcd + 初始化 LVGL
#   fb.tick()           → lv.task_handler(),LVGL 渲染髒區到內部 list
#   rects = fb.take()   → 取出 [(x1,y1,x2,y2, data_mv), ...]
#   fb.show_rect(...)   → 用 TFT 驅動送一塊髒區
#   inp = Inputs()      → 編碼器 + 雙按鈕

from micropython import const
import lcd_bus
import lvgl as lv
from machine import Pin, PWM, I2C, Encoder
import time

# ============== 腳位定義 ==============
# 對應 slave new 板子（boot.py/config.json）接線：
#   SPI: sck=21, data=[14]；TFT: cs=11, dc=12, rst=13, bl=10
class Pins:
    HOST       = const(1)
    MOSI       = const(14)   # slave new: data_pins=[14]（單線）
    CLK        = const(21)   # slave new: sck=21
    DC         = const(12)   # slave new: tft_dc
    CS         = const(11)   # slave new: tft_cs
    RST        = const(13)   # slave new: tft_rst
    BL         = const(10)   # slave new: tft_bl
    SPI_FREQ   = const(80_000_000)

    # 輸入腳位（操作階段用；本版僅記錄）
    ENC_A      = const(18)   # 可調編碼器 A
    ENC_B      = const(8)    # 可調編碼器 B
    ENC_C      = const(17)   # 可調編碼器 按鍵
    BTN        = const(42)   # 按鈕

    # 觸控（slave new 板無 touch；demo3 觸控版用，保留原值）
    TOUCH_SDA  = const(1)
    TOUCH_SCL  = const(3)
    TOUCH_INT  = const(4)
    TOUCH_RST  = const(2)

# ============== 顯示參數 ==============
WIDTH       = const(240)
HEIGHT      = const(320)
_CF_RGB565  = const(18)   # lv.COLOR_FORMAT.RGB565
BPP         = const(2)
LINES       = const(40)   # PARTIAL draw buffer 行數


# ============== ST7789 硬體初始化 ==============
def st7789_init(bus, dc, cs, rst, bl):
    rst.value(0); time.sleep_ms(50)
    rst.value(1); time.sleep_ms(50)

    def _cmd(reg, data=None):
        cs.value(0)
        dc.value(0); bus.write(bytearray([reg])); bus.wait_all()
        if data:
            dc.value(1); bus.write(data); bus.wait_all()
        cs.value(1)

    _cmd(0x01); time.sleep_ms(150)
    _cmd(0x11); time.sleep_ms(120)
    _cmd(0x3A, b'\x55')
    _cmd(0x36, b'\x00')
    _cmd(0xB2, b'\x0C\x0C\x00\x33\x33')
    _cmd(0xB7, b'\x35')
    _cmd(0xBB, b'\x19')
    _cmd(0xC0, b'\x2C')
    _cmd(0xC2, b'\x01')
    _cmd(0xC3, b'\x12')
    _cmd(0xC4, b'\x20')
    _cmd(0xC6, b'\x0F')
    _cmd(0x21)
    _cmd(0xD0, b'\xA4\xA1')
    _cmd(0x29); time.sleep_ms(20)

    for d in (16384, 32768, 49152, 65535):
        bl.duty_u16(d); time.sleep_ms(50)


# ============== 核心:FrameBuffer(緩衝分離) ==============
class FrameBuffer:
    """LVGL 渲染 → 存緩衝+座標 → 你來 show。

    預設直向 240×320（MADCTL=0x00）；橫屏控制台 UI 用
    FrameBuffer(320, 240, 0x60)（ST7789 橫屏：MV|MX；上下倒轉改 0xA0）。

    用法:
        fb = FrameBuffer()
        fb.setup()

        while True:
            fb.tick()                    # LVGL 渲染
            rects = fb.take()            # 取出 [(x1,y1,x2,y2,data), ...]
            for x1,y1,x2,y2,data in rects:
                my_show(x1,y1,x2,y2,data)  # 你自己送 lcd_bus
            fb.flush_done()              # 告訴 LVGL 可再渲染
    """

    def __init__(self, w=WIDTH, h=HEIGHT, madctl=0x00):
        self._w = w
        self._h = h
        self._madctl = madctl
        self._dirty = []       # [(x1, y1, x2, y2, bytes), ...]
        self._disp = None
        self._buf = None
        self._last = 0
        # 硬體 pin(供用戶 show 時用)
        self.bus = None
        self.dc = None
        self.cs = None

    def setup(self):
        """初始化硬體 + LVGL。flush_cb 只存緩衝,不碰 SPI 像素傳送。

        顯示硬體改用 slave new TFT 驅動（bus service "lcd"）：
        boot.py 已建好 ST7789 + SpiBusAdapter，這裡直接取用。
        """
        # --- 從 bus 拿 TFT 驅動（slave new boot 已 init） ---
        from lib.sys_bus import bus
        self.lcd = bus.get_service("lcd")
        if self.lcd is None:
            raise RuntimeError("lcd not on bus — run slave new boot.py first")
        self.bus = getattr(self.lcd, "_bus", None)
        if self.bus is None:
            raise RuntimeError("lcd service missing _bus (adapter)")
        self.dc = getattr(self.bus, "_dc", None)
        self.cs = getattr(self.bus, "_cs", None)
        self.width = self._w
        self.height = self._h

        # --- 橫屏：重設 MADCTL（boot 預設 0x00 直向） ---
        if self._madctl != 0x00:
            self._send_madctl(self._madctl)

        # --- LVGL ---
        # soft reboot 後 LVGL C 層殘留,先清再建
        if lv.is_initialized():
            lv.deinit()
        lv.init()
        self._disp = lv.display_create(self._w, self._h)
        self._disp.set_color_format(_CF_RGB565)

        # 用 MicroPython heap(soft reboot 後乾淨),不用 lv.draw_buf_create
        buf = bytearray(self._w * LINES * BPP)
        # PARTIAL=0, DIRECT=1, FULL=2 (硬編碼,避免 soft reboot 後常數不穩定)
        self._disp.set_buffers(buf, None, len(buf), 0)

        # ★ flush_cb:只存緩衝+座標,不送 SPI ★
        self._disp.set_flush_cb(self._flush_cb)

        print("FrameBuffer ready: {}x{} madctl=0x{:02X} PARTIAL lines={}".format(
            self._w, self._h, self._madctl, LINES))

    def _send_madctl(self, val):
        """重設 ST7789 MADCTL（0x36）以切換橫/直向。"""
        self.bus.write_cmd_data(0x36, bytes([val]))

    def _flush_cb(self, disp_drv, area, color_p):
        """LVGL 渲染完一塊 → 拷貝到 bytes + 立即 flush_ready。
           PARTIAL 單緩衝模式:必須拷貝,因為 LVGL 會立刻覆蓋 draw buffer 渲染下一條。"""
        w = area.x2 - area.x1 + 1
        h = area.y2 - area.y1 + 1
        size = w * h * BPP

        data = color_p.__dereference__(size)

        # byte swap(ESP32 小端 → ST7789 大端)— in-place
        lv.draw_sw_rgb565_swap(data, w * h)

        # 拷貝(必要:LVGL 會覆蓋 draw buffer)
        self._dirty.append((area.x1, area.y1, area.x2, area.y2, bytes(data)))

        # 立即釋放,讓 LVGL 渲染下一條
        disp_drv.flush_ready()

    def tick(self, sleep_us=5000):
        """LVGL tick + task_handler + 強制刷新。"""
        time.sleep_us(sleep_us)
        lv.tick_inc(sleep_us // 1000)   # 直接用 sleep 時間,不量測
        lv.task_handler()
        lv.refr_now(self._disp)         # 強制立刻渲染

    def read_indev(self, indev_obj):
        """手動觸發 indev 讀取(每輪呼叫,不等 LVGL 的 30ms 節拍)。"""
        indev_obj.read()

    def take(self):
        """取出所有髒區。回傳 [(x1,y1,x2,y2, data_mv), ...]。
           呼叫後清空,下次 take() 回傳新的。"""
        rects = self._dirty
        self._dirty = []
        return rects

    def flush_done(self):
        """保留接口。目前 flush_cb 已即時 flush_ready,此方法為 no-op。"""
        pass

    # --- 便捷方法:幫你 show(透過 slave new TFT 驅動) ---
    def show_rect(self, x1, y1, x2, y2, data):
        """把一塊髒區送到 ST7789（用 slave new TFT 驅動：set_window + write_data_async）。
        大 buffer 由 C 層 async 分 chunk，最後 flush 等完成。"""
        lcd = self.lcd
        lcd.set_window(x1, y1, x2, y2)
        self.bus.write_data_async(data)
        self.bus.flush()

    def show_all(self):
        """便捷:tick + take + show 全部髒區。一行搞定。"""
        self.tick()
        for x1, y1, x2, y2, data in self.take():
            self.show_rect(x1, y1, x2, y2, data)


# ============== CST328 觸控(polling,對齊你 is_ok_3.5) ==============
_CST328_ADDR = const(0x1A)

class CST328:
    def __init__(self, sda, scl, rst, int_pin, freq=400_000):
        self.i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self.address = _CST328_ADDR
        self._rst = Pin(rst, Pin.OUT)
        self._int = Pin(int_pin, Pin.IN, Pin.PULL_UP)  # INT: 低=有觸控
        self.first_buf = bytearray(6)
        self._last_pos = None  # 快取上次座標

        self._rst.value(0); time.sleep_ms(20)
        self._rst.value(1); time.sleep_ms(100)

        for _ in range(3):
            try:
                self.i2c.writeto_mem(self.address, 0xEE, b'\x01')
            except OSError:
                pass
            time.sleep_ms(20)

        try:
            cid = self.i2c.readfrom_mem(self.address, 0xA7, 1)
            print(f"CST328 Chip ID: 0x{cid[0]:02X}")
        except OSError:
            pass

        for _ in range(5):
            try:
                self.i2c.readfrom_mem(self.address, 0x00, 72)
            except OSError:
                pass
            time.sleep_ms(10)

    def read(self):
        """回傳 (x, y) 或 None。每次都讀 I2C(polling 模式)。
           INT pin 不適合當閘門(按著不動時 INT 會拉高),直接讀最可靠。"""
        try:
            self.i2c.readfrom_mem_into(self.address, 0x00, self.first_buf)
        except OSError:
            return None

        count = self.first_buf[5] & 0x0F
        if count == 0:
            return None

        x = (self.first_buf[1] << 4) | (self.first_buf[3] & 0x0F)
        y = (self.first_buf[2] << 4) | (self.first_buf[3] >> 4)

        tx = x if x < WIDTH else WIDTH - 1
        ty = y if y < HEIGHT else HEIGHT - 1
        return (tx, ty)


# ============== 輸入：可調編碼器 + 雙按鈕 ==============
#   編碼器   A=18  B=8  C(按鍵)=17 → 確認
#   外接按鈕 42 → 退出
class Inputs:
    """可調編碼器 + 兩個按鈕（確認=編碼器 C、退出=外接 BTN）。

    用法:
        inp = Inputs()
        d = inp.enc_delta()        # 編碼器轉動量(+N/-N)
        if inp.confirm_pressed():  # 編碼器按鍵(確認)
        if inp.exit_pressed():     # 外接按鈕(退出)
    """

    def __init__(self, enc_a=Pins.ENC_A, enc_b=Pins.ENC_B,
                 enc_c=Pins.ENC_C, btn=Pins.BTN):
        self._enc = Encoder(0, Pin(enc_a, Pin.IN, Pin.PULL_UP),
                            Pin(enc_b, Pin.IN, Pin.PULL_UP))
        self._enc_last = self._enc.value()
        self._confirm = Pin(enc_c, Pin.IN, Pin.PULL_UP)
        self._exit = Pin(btn, Pin.IN, Pin.PULL_UP)
        # 按鈕去抖狀態（low=按下）
        self._c_last = self._confirm.value()
        self._e_last = self._exit.value()

    def enc_delta(self):
        """回傳自上次呼叫以來的轉動量（順時針+,逆時針-）。"""
        v = self._enc.value()
        d = v - self._enc_last
        self._enc_last = v
        return d

    def confirm_pressed(self):
        """確認鍵（編碼器 C）是否被按下（一次邊緣）。"""
        v = self._confirm.value()
        edge = (self._c_last == 1 and v == 0)
        self._c_last = v
        return edge

    def exit_pressed(self):
        """退出鍵（外接 BTN）是否被按下（一次邊緣）。"""
        v = self._exit.value()
        edge = (self._e_last == 1 and v == 0)
        self._e_last = v
        return edge
