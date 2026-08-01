# mp_LVGL 開發筆記
# ESP32-S3 + ST7789 + CST328 + LVGL + mp_lcd_bus 緩衝分離架構
# 最後更新: 2026-07-30

---

## 1. 架構總覽

```
┌─────────────────────────────────────────────────────────┐
│  你的主迴圈(完全控制 show 時機)                          │
│                                                         │
│  while True:                                            │
│      pos = touch.read()          ← I2C 讀觸控           │
│      indev.read()                ← 手動觸發 LVGL indev  │
│      fb.tick()                   ← LVGL 渲染到緩衝       │
│      rects = fb.take()           ← 取出 [(x1,y1,x2,y2,data)] │
│      for ... in rects:                                  │
│          fb.show_rect(...)       ← 你決定怎麼送 SPI      │
└─────────────────────────────────────────────────────────┘

核心原則:
  - LVGL 只負責渲染,flush_cb 只存緩衝+座標,不碰硬體
  - 你控制 show 的時機、方式、驅動
  - I2C 在主迴圈讀(不在 read_cb 裡),避免跟 SPI 衝突
```

---

## 2. 硬體配置(ESP32-S3-Touch-LCD-2.8)

| 功能 | GPIO | 備註 |
|------|------|------|
| SPI MOSI | 45 | lcd_bus data=(45,) |
| SPI CLK | 40 | |
| LCD DC | 41 | 命令/資料切換 |
| LCD CS | 42 | |
| LCD RST | 39 | |
| LCD BL | 5 | PWM 背光 |
| Touch SDA | 1 | I2C(0) |
| Touch SCL | 3 | I2C(0) |
| Touch INT | 4 | ⚠️ 不適合當閘門(見踩坑 #7) |
| Touch RST | 2 | |
| SPI Host | 1 | |
| SPI Freq | 80MHz | |

顯示: ST7789, 240×320, RGB565
觸控: CST328, I2C 地址 0x1A

---

## 3. 關鍵 API 用法

### 3.1 LVGL 初始化(必須硬編碼常數)

```python
# ⚠️ soft reboot 後 LVGL 常數不穩定,必須用整數
_CF_RGB565 = 18          # lv.COLOR_FORMAT.RGB565
_PARTIAL   = 0           # lv.DISPLAY_RENDER_MODE.PARTIAL
_PRESSED   = 1           # lv.INDEV_STATE.PRESSED
_RELEASED  = 0           # lv.INDEV_STATE.RELEASED

# ⚠️ soft reboot 後 LVGL C 層殘留,必須先 deinit
if lv.is_initialized():
    lv.deinit()
lv.init()

disp = lv.display_create(240, 320)
disp.set_color_format(18)  # RGB565

# ⚠️ 用 bytearray(MicroPython heap),不用 lv.draw_buf_create
#    draw_buf_create 在 soft reboot 後會 MemoryError(殘留指標)
buf = bytearray(240 * 40 * 2)  # 40 行 PARTIAL buffer
disp.set_buffers(buf, None, len(buf), 0)  # 0=PARTIAL
```

### 3.2 tick 計時(不能用 time_ns + ticks_diff)

```python
# ❌ 錯誤:time.ticks_diff() 是給 ticks_ms/ticks_us 用的,對 time_ns 得到垃圾值
t0 = time.time_ns()
time.sleep_us(5000)
t1 = time.time_ns()
elapsed = time.ticks_diff(t1, t0)  # ← 垃圾值!

# ✅ 正確:直接用已知的 sleep 時間
time.sleep_us(5000)
lv.tick_inc(5)  # sleep_us // 1000 = 5ms
lv.task_handler()
lv.refr_now(disp)  # 強制渲染(不等 33ms 內部節拍)
```

### 3.3 indev 觸控輸入

```python
# read_cb 只讀緩衝值,不做 I2C(I2C 在主迴圈做)
def _read_cb(drv, data):
    data.point.x = _touch_x[0]
    data.point.y = _touch_y[0]
    data.state = 1 if _touch_pressed[0] else 0

indev = lv.indev_create()
indev.set_type(lv.INDEV_TYPE.POINTER)
indev.set_display(disp)
indev.enable(True)
indev.set_read_cb(_read_cb)

# ⚠️ 主迴圈每輪手動呼叫 indev.read()
#    不等 LVGL 內部 30ms 節拍,確保座標連續(滑桿拖動需要)
while True:
    # ... 更新 _touch_x/_touch_y/_touch_pressed ...
    indev.read()       # ← 每輪都讀
    fb.tick()          # ← task_handler + refr_now
```

### 3.4 flush_cb(緩衝分離核心)

```python
def _flush_cb(disp_drv, area, color_p):
    w = area.x2 - area.x1 + 1
    h = area.y2 - area.y1 + 1
    size = w * h * 2  # RGB565 = 2 bytes/pixel

    data = color_p.__dereference__(size)
    lv.draw_sw_rgb565_swap(data, w * h)  # ESP32 小端 → ST7789 大端

    # 存起來(必須 bytes() 拷貝,因為 LVGL 會覆蓋 draw buffer)
    self._dirty.append((area.x1, area.y1, area.x2, area.y2, bytes(data)))

    # 立即 flush_ready(PARTIAL 單緩衝:LVGL 等這個才渲染下一條)
    disp_drv.flush_ready()
```

### 3.5 show_rect(DMA fire-and-forget)

```python
def show_rect(self, x1, y1, x2, y2, data):
    cs.value(0)

    # CASET + RASET + RAMWR(命令用 polling)
    dc.value(0); bus.write(bytearray([0x2A])); bus.wait_all()
    dc.value(1); bus.write(bytes([(x1>>8)&0xFF, x1&0xFF, (x2>>8)&0xFF, x2&0xFF])); bus.wait_all()
    dc.value(0); bus.write(bytearray([0x2B])); bus.wait_all()
    dc.value(1); bus.write(bytes([(y1>>8)&0xFF, y1&0xFF, (y2>>8)&0xFF, y2&0xFF])); bus.wait_all()
    dc.value(0); bus.write(bytearray([0x2C])); bus.wait_all()
    dc.value(1)

    # ★ DMA fire-and-forget:收集 tid,最後才 wait(對齊 test_jpeg_full 風格)
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
```

### 3.6 CST328 觸控(polling,不用 INT 閘門)

```python
def read(self):
    """每次都讀 I2C。INT pin 不適合當閘門(按著不動時 INT 會拉高)。"""
    try:
        self.i2c.readfrom_mem_into(0x1A, 0x00, self.first_buf)
    except OSError:
        return None

    count = self.first_buf[5] & 0x0F
    if count == 0:
        return None

    x = (self.first_buf[1] << 4) | (self.first_buf[3] & 0x0F)
    y = (self.first_buf[2] << 4) | (self.first_buf[3] >> 4)
    return (x, y)
```

---

## 4. 踩坑記錄(血淚教訓)

| # | 問題 | 根因 | 解法 |
|---|------|------|------|
| 1 | `MemoryError: allocating 1GB` | soft reboot 後 `lv.draw_buf_create` 用到殘留指標 | 改用 `bytearray()` + `set_buffers()` |
| 2 | `MemoryError` on soft reboot | LVGL C 層殘留 | `if lv.is_initialized(): lv.deinit()` |
| 3 | LVGL 常數不穩定 | soft reboot 後 `lv.COLOR_FORMAT.RGB565` 等值可能錯 | 硬編碼整數(18, 0, 1, 0) |
| 4 | `refr_now()` 後畫面不更新 | `time.ticks_diff()` 對 `time_ns()` 得到垃圾值 → `tick_inc` 累積錯誤 → LVGL 計時器不觸發 | 直接 `lv.tick_inc(sleep_us // 1000)` |
| 5 | read_cb 從不被呼叫 | LVGL indev 預設 30ms 才讀一次,`task_handler` 內部按自己節拍 | 主迴圈每輪手動 `indev.read()` |
| 6 | 滑桿拖不動 | CST328 的 count 短暫閃 0 → LVGL 看到 PRESSED→RELEASED 交替 → 取消拖動 | 釋放延遲:連續 N 次無觸控才報 RELEASED |
| 7 | INT pin 閘門不穩 | CST328 按著不動時 INT 會拉高(無新事件) → 跳過 I2C → 漏讀 | 不用 INT 閘門,每次都讀 I2C |
| 8 | 座標凍結 | `read_cb` 裡讀 I2C 跟主迴圈 SPI 衝突(同一輪讀兩次 I2C) | I2C 只在主迴圈讀一次,read_cb 只讀緩衝值 |
| 9 | 圓點/標籤每輪閃爍 | `set_pos()`/`set_text()` 每輪呼叫即使值沒變 → LVGL 標記髒區 → 每輪重繪 | 只在值真的變了才呼叫 |
| 10 | `lv.RADIUS.CIRCLE` 不存在 | binding 版本差異 | 用數字:半徑 = 寬/2 |
| 11 | `set_read_period` 不存在 | binding 版本沒暴露此 API | 用 `indev.read()` 手動觸發 |
| 12 | 觸控座標跟顯示不對 | 之前用 `align(CENTER)` 放 widget,虛擬手指 y 沒對到 | 用明確 `set_pos()` 放 widget |

---

## 5. 效能分析

### 目前瓶頸(手指移動時 ~4-10 FPS)

```
每輪(~5ms sleep + 處理):
  I2C 讀觸控         ~1-2ms   ← 無法再快(I2C 400kHz 限制)
  LVGL 渲染髒區      ~2-3ms   ← 正常
  bytes(data) 拷貝   ~1-2ms/塊 ← 必要(單緩衝 PARTIAL)
  SPI 傳送           ~3-5ms/塊 ← 已是 DMA 80MHz
```

### 已做的優化
- [x] 只在值變了才 `set_pos`/`set_text`(靜止時不產生髒區)
- [x] DMA fire-and-forget(收集 tid 最後 wait)
- [x] `refr_now()` 強制渲染(不等 33ms 內部節拍)
- [x] `indev.read()` 每輪手動觸發(不等 30ms)

### 待做的優化(下次繼續)
- [ ] **雙緩衝 PARTIAL**:兩塊 draw buffer,LVGL 渲染 buf_B 時同時 DMA 送 buf_A(重疊)
- [ ] **heap_caps DMA buffer**:用 `heap_caps.malloc(size, CAP_DMA)` 確保 DMA 可用記憶體
- [ ] **減少 bytes() 拷貝**:雙緩衝模式下可直接傳 memoryview(不需拷貝)
- [ ] **合併髒區**:相鄰的髒區合併成一次 SPI 傳送(減少 CASET/RASET 次數)
- [ ] **跳過無變化幀**:如果 `fb.take()` 回傳空 list,跳過 show(已隱含在邏輯中)

---

## 6. 檔案結構

```
mp_LVGL/
├── lvgl_shared.py          ← 核心:FrameBuffer + CST328 + ST7789 init
├── lvgl_demo1_display.py   ← 最小顯示測試(彩色方塊)
├── lvgl_demo2_widgets.py   ← widget 互動(按鈕/滑桿/arc/switch)
├── lvgl_demo3_touch.py     ← 觸控 + 圓點跟手 + 滑桿拖動 + FPS
├── lvgl_demo4_siminput.py  ← 模擬輸入(不依賴觸控硬體,驗證 indev)
├── test_jpeg_full.py       ← 參考:JPEG 管線 DMA fire-and-forget 模式
├── gen_font.py             ← 中文字體產生(CLI,自動掃描源碼字符)
├── tools/                  ← LVGL UI Asset Studio(Web GUI,自包含)
│   ├── ui_assets_server.py ←   零參數啟動,開瀏覽器操作
│   ├── assets/             ←   核心邏輯(scanner/icons/zhfont/fxgen)
│   ├── web/                ←   單頁介面
│   └── workspace/          ←   工作區:design上傳/cache下載/out產物
└── DEV_NOTES.md            ← 本文件
```

`tools/` 的產生流程:設計稿上傳 → 掃描 → 生成 icons_16.bin /
zh_hant_16.bin / lv_ui_fx.py / fx_notes.md(全在 tools/workspace/out)。

---

## 7. ST7789 初始化序列(已驗證)

```python
(0x01, None, 150ms)   # SWRESET
(0x11, None, 120ms)   # SLPOUT
(0x3A, b'\x55')       # COLMOD 16bpp RGB565
(0x36, b'\x00')       # MADCTL: RGB, 不旋轉
(0xB2, b'\x0C\x0C\x00\x33\x33')  # Porch
(0xB7, b'\x35')       # Gate
(0xBB, b'\x19')       # VCOM
(0xC0, b'\x2C')       # LCM
(0xC2, b'\x01')
(0xC3, b'\x12')
(0xC4, b'\x20')
(0xC6, b'\x0F')
(0x21, None)          # INVON(ST7789 需要)
(0xD0, b'\xA4\xA1')  # Power
(0x29, None, 20ms)    # DISPON
```

---

## 8. CST328 觸控要點

- I2C 地址: 0x1A
- 讀取: `readfrom_mem_into(0x1A, 0x00, buf6)`
- 資料格式(6 bytes):
  - `buf[0]`: 事件碼(低4位) + 觸控ID(高4位)
  - `buf[1]`: X 高8位
  - `buf[2]`: Y 高8位
  - `buf[3]`: 低4位=X低4位, 高4位=Y低4位
  - `buf[4]`: 壓力
  - `buf[5]`: 觸控點數(低4位)
- 座標解析:
  ```python
  x = (buf[1] << 4) | (buf[3] & 0x0F)
  y = (buf[2] << 4) | (buf[3] >> 4)
  ```
- ⚠️ 按著不動時 event 會從 0x06 變成 0x00,但 count 仍然是 1
  → 用 `count > 0` 判斷手指在不在,不要用 event 碼
- ⚠️ INT pin 不適合當「有沒有觸控」的閘門
- ⚠️ 釋放延遲:連續 5-8 次 count==0 才報 RELEASED(防閃爍)

---

## 9. 下次開發起點

1. **先跑 demo3 確認環境沒問題**:
   ```python
   import lvgl_demo3_touch
   ```
   預期:圓點跟手、滑桿可拖、FPS 顯示

2. **效能優化(雙緩衝)**:
   - 改 `lvgl_shared.py` 的 `set_buffers` 給兩塊 buffer
   - flush_cb 交替存到 buf_A/buf_B
   - show 時 DMA 送 buf_A,同時 LVGL 渲染 buf_B
   - 參考 `test_jpeg_full.py` 的 `PipelinePlayer` 模式

3. **多屏/多 bus 支援**:
   - `FrameBuffer` 加 `bus_id` 參數
   - 多個 `FrameBuffer` 實例各自獨立

4. **動畫/JPEG 整合**:
   - 你的 `mp_jpeg` decoder 解碼到 framebuffer
   - 跟 LVGL 的 draw buffer 共用或分開
   - 參考 `test_jpeg_full.py` 的 `DeepBufferPipeline`

---

## 10. 依賴版本

- MicroPython: 需含 `lvgl` module(lv_binding_micropython 編譯)
- lcd_bus: 你的 `mp_lcd_bus`(SPIBus, write/wait/wait_all)
- LVGL binding 注意:
  - 沒有 `lv.RADIUS.CIRCLE`(用數字)
  - 沒有 `indev.set_read_period`(用 `indev.read()`)
  - `lv.draw_buf_create` soft reboot 後不穩定(用 bytearray)
  - `lv.DISPLAY_RENDER_MODE.PARTIAL` = 0(硬編碼)
