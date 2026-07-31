# lvgl_shared.py — 緩衝分離架構
# LVGL 只負責渲染到緩衝,flush_cb 只存 (area, data)
# 「show」完全由用戶控制:你決定何時、怎麼送到 lcd_bus
#
# 核心 API:
#   fb = FrameBuffer()
#   fb.setup()          → 初始化 LVGL + ST7789(硬體 init 還是要做)
#   fb.tick()           → lv.task_handler(),LVGL 渲染髒區到內部 list
#   rects = fb.take()   → 取出 [(x1,y1,x2,y2, data_mv), ...]
#   fb.flush_done()     → 告訴 LVGL 緩衝可再用(你在 show 完後呼叫)

from micropython import const
import lcd_bus
import lvgl as lv
from machine import Pin, PWM, I2C
import time

# ============== 腳位定義 ==============
class Pins:
    HOST       = const(1)
    MOSI       = const(45)
    CLK        = const(40)
    DC         = const(41)
    CS         = const(42)
    RST        = const(39)
    BL         = const(5)
    SPI_FREQ   = const(80_000_000)
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

    def __init__(self):
        self._dirty = []       # [(x1, y1, x2, y2, bytes), ...]
        self._disp = None
        # 硬體 pin(供用戶 show 時用)
        self.bus = None
        self.dc = None
        self.cs = None

    def setup(self):
        """初始化硬體 + LVGL。flush_cb 只存緩衝,不碰 SPI 像素傳送。"""
        # --- 硬體 pin ---
        self.dc = Pin(Pins.DC, Pin.OUT, value=0)
        self.cs = Pin(Pins.CS, Pin.OUT, value=1)
        rst = Pin(Pins.RST, Pin.OUT, value=1)
        bl  = PWM(Pin(Pins.BL), freq=5000, duty_u16=0)

        self.bus = lcd_bus.SPIBus(
            data=(Pins.MOSI,), clk=Pins.CLK,
            freq=Pins.SPI_FREQ, host=Pins.HOST
        )

        # ST7789 硬體 init(命令序列,不是像素)
        st7789_init(self.bus, self.dc, self.cs, rst, bl)

        # --- LVGL ---
        # soft reboot 後 LVGL C 層殘留,先清再建
        if lv.is_initialized():
            lv.deinit()
        lv.init()
        self._disp = lv.display_create(WIDTH, HEIGHT)
        self._disp.set_color_format(_CF_RGB565)

        # 用 MicroPython heap(soft reboot 後乾淨),不用 lv.draw_buf_create
        buf = bytearray(WIDTH * LINES * BPP)
        # PARTIAL=0, DIRECT=1, FULL=2 (硬編碼,避免 soft reboot 後常數不穩定)
        self._disp.set_buffers(buf, None, len(buf), 0)

        # ★ flush_cb:只存緩衝+座標,不送 SPI ★
        self._disp.set_flush_cb(self._flush_cb)

        print(f"FrameBuffer ready: {WIDTH}x{HEIGHT} PARTIAL lines={LINES}")

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

    # --- 便捷方法:幫你 show(DMA fire-and-forget,對齊你 test_jpeg_full 風格) ---
    def show_rect(self, x1, y1, x2, y2, data):
        """把一塊髒區送到 ST7789。DMA fire-and-forget,最後 wait。"""
        cs = self.cs
        dc = self.dc
        bus = self.bus

        cs.value(0)

        # CASET + RASET + RAMWR(命令用 polling,快速)
        dc.value(0); bus.write(bytearray([0x2A])); bus.wait_all()
        dc.value(1)
        bus.write(bytes([(x1>>8)&0xFF, x1&0xFF, (x2>>8)&0xFF, x2&0xFF]))
        bus.wait_all()

        dc.value(0); bus.write(bytearray([0x2B])); bus.wait_all()
        dc.value(1)
        bus.write(bytes([(y1>>8)&0xFF, y1&0xFF, (y2>>8)&0xFF, y2&0xFF]))
        bus.wait_all()

        dc.value(0); bus.write(bytearray([0x2C])); bus.wait_all()
        dc.value(1)

        # ★ DMA fire-and-forget:收集 tid,最後才 wait ★
        tids = []
        off = 0
        total = len(data)
        while off < total:
            n = min(32768, total - off)
            tid = bus.write(data[off:off+n])
            if tid is not None:
                tids.append(tid)
            off += n
        for tid in tids:
            bus.wait(tid)

        cs.value(1)

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
