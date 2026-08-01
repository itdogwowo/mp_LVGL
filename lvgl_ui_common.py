# lvgl_ui_common.py — lvgl-console-ui 共用 UI 層
#
# 把 lvgl-console-ui 設計稿（colors_and_type.css / components.css）
# 轉成 LVGL9 橫屏 320×240 可用的 palette / 字體 / 元件 builder。
#
# 注意（對應 DEV_NOTES 踩坑）：
#   - 字體用 getattr fallback（binding 沒編到的尺寸自動降級）
#   - 枚举常數能用整數就用整數（soft reboot 後常數可能不穩）
#   - 所有容器 pad_all(0) + 移除 SCROLLABLE（預設樣式會干擾佈局）

import lvgl as lv

# ====== 版面（橫屏 ST7789，MADCTL=0x60） ======
W = 320
H = 240

# ====== Palette（來自 colors_and_type.css） ======
BG       = 0xF5F5F5   # --bg-base-secondary
SURFACE  = 0xFFFFFF   # --bg-base-default
BORDER   = 0xE0E0E0   # --border-neutral-l1
TEXT     = 0x1F1F1F   # --text-default
TEXT2    = 0x5F5F5F   # --text-secondary
TEXT3    = 0x8F8F8F   # --text-tertiary
PRIMARY  = 0x1A73E8   # --bg-brand
SUCCESS  = 0x188038   # --status-success-default
WARNING  = 0xF9AB00   # --status-warning-default
DANGER   = 0xD93025   # --status-danger-default
TRACK    = 0xDADCE0   # --bg-overlay-l3
FOCUS_BG = 0xE8F0FE   # 焦點卡片底色（brand 淡色）
DANGER_BG = 0xFCE8E6  # danger-subtle 按鈕底色

# ====== 字體 ======
# 繁體中文 .bin 字體須在 lv.init() 之後才能載入，
# 因此用 init_fonts() 延遲載入（由 lvgl_ui_app 在 fb.setup() 後呼叫）。
ZH = None

def init_fonts():
    """在 lv.init() 完成後呼叫，載入繁體中文 .bin 字體。
    用 Python open() 讀檔 → binfont_create_from_buffer()，
    繞過 LVGL FS 驅動（lv_conf 未啟用 POSIX/STDIO/FATFS）。
    """
    global ZH
    if ZH:
        return
    # 方法：Python 讀檔 → buffer 載入
    try:
        with open("/zh_hant_16.bin", "rb") as fp:
            buf = fp.read()
        print("[font] read {} bytes".format(len(buf)))
        f = None
        if hasattr(lv, "binfont_create_from_buffer"):
            try:
                f = lv.binfont_create_from_buffer(bytearray(buf), len(buf))
            except TypeError:
                # binding 可能只需一個參數（自動推斷 size）
                try:
                    f = lv.binfont_create_from_buffer(bytearray(buf))
                except Exception as e2:
                    print("[font] from_buffer(1arg) fail:", e2)
            except Exception as e1:
                print("[font] from_buffer(2arg) fail:", e1)
        else:
            print("[font] binfont_create_from_buffer NOT in binding")
        if f:
            ZH = f
            print("[font] loaded from buffer OK")
            return
        print("[font] from_buffer returned None")
    except Exception as _e:
        print("[font] buffer load fail:", _e)
    # 最後 fallback：內建 CJK（通常未編入）
    ZH = getattr(lv, "font_simsun_16_cjk", None)
    print("[font] fallback:", ZH)

# 此 binding 沒有 lv.font_default()，用 montserrat_14（LVGL 主題預設字體）兜底
_BASE_FONT = None
for _n in ("font_montserrat_14", "font_montserrat_16", "font_montserrat_12",
           "font_montserrat_18", "font_montserrat_20"):
    _BASE_FONT = getattr(lv, _n, None)
    if _BASE_FONT:
        break

# ====== 圖示字體（lv_icons.py，由 tools/ 工具產生） ======
# 板上沒有 icons_16.bin 時全部降級為 None，不影響其他功能。
_icon_font = None

def _icon_font_ready():
    """回傳 icon 字體（首次使用才載入）。"""
    global _icon_font
    if _icon_font is None:
        try:
            from lv_icons import load_icon_font
            _icon_font = load_icon_font()
        except Exception as e:
            print("[icons] skip:", e)
            _icon_font = False
    return _icon_font or None

def mk_icon(parent, name, x, y, color=TEXT2):
    """建立圖示 label（lucide 名）。icon 字體不可用時回傳 None。"""
    f = _icon_font_ready()
    if f is None:
        return None
    from lv_icons import ICONS
    if name not in ICONS:
        return None
    lb = lv.label(parent)
    lb.set_text(ICONS[name])
    lb.set_pos(x, y)
    lb.set_style_text_color(C(color), 0)
    lb.set_style_text_font(f, 0)
    return lb

# ====== 動效 helper（lv_ui_fx.py，由 tools/ 工具產生） ======
# 板上沒有 lv_ui_fx.py 時降級為 no-op。
try:
    from lv_ui_fx import pulse as _fx_pulse, fade_in as _fx_fade_in
except Exception:
    _fx_pulse = _fx_fade_in = None

def pulse(wid, period_ms=1500, min_opa=110, max_opa=255):
    if _fx_pulse:
        return _fx_pulse(wid, period_ms, min_opa, max_opa)
    return None

def fade_in(wid, dy=6, time_ms=300, delay_ms=0):
    if _fx_fade_in:
        return _fx_fade_in(wid, dy, time_ms, delay_ms)
    return None

def font(*names):
    """依序嘗試字體名，全部沒有就回 montserrat 基本字體。"""
    for n in names:
        f = getattr(lv, n, None)
        if f:
            return f
    return _BASE_FONT

# 數字/拉丁用 Montserrat（binding 有編到哪個尺寸就用哪個）
F_NUM_L = font("font_montserrat_22", "font_montserrat_20", "font_montserrat_18")
F_NUM_M = font("font_montserrat_16", "font_montserrat_14")
F_NUM_S = font("font_montserrat_12", "font_montserrat_10")

# ====== 基礎 builder ======

def C(hexval):
    return lv.color_hex(hexval)

def mk_label(parent, text, x, y, color=TEXT, f=None):
    lb = lv.label(parent)
    lb.set_text(text)
    lb.set_pos(x, y)
    lb.set_style_text_color(C(color), 0)
    if f:
        lb.set_style_text_font(f, 0)
    elif ZH:
        lb.set_style_text_font(ZH, 0)
    return lb

def mk_card(parent, x, y, w, h):
    c = lv.obj(parent)
    c.set_size(w, h)
    c.set_pos(x, y)
    c.set_style_bg_color(C(SURFACE), 0)
    c.set_style_radius(10, 0)
    c.set_style_border_color(C(BORDER), 0)
    c.set_style_border_width(1, 0)
    c.set_style_pad_all(0, 0)
    c.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return c

def mk_appbar(scr, title, right=""):
    """頂欄 36px：返回符號 + 標題 + 右側狀態。"""
    bar = lv.obj(scr)
    bar.set_size(W, 36)
    bar.set_pos(0, 0)
    bar.set_style_bg_color(C(SURFACE), 0)
    bar.set_style_radius(0, 0)
    bar.set_style_border_color(C(BORDER), 0)
    bar.set_style_border_width(1, 0)
    bar.set_style_pad_all(0, 0)
    bar.remove_flag(lv.obj.FLAG.SCROLLABLE)

    # 返回指示（BTN42）：優先 icon 字體,沒有就文字符號
    back = mk_icon(bar, "chevron-left", 8, 9, TEXT2)
    if back is None:
        mk_label(bar, "<", 10, 9, TEXT2, F_NUM_M)
    mk_label(bar, title, 28, 9, TEXT, ZH)
    r = None
    if right:
        r = mk_label(bar, right, 0, 0, TEXT3, F_NUM_S)
        r.align(lv.ALIGN.RIGHT_MID, -10, 0)
    return bar, r

def mk_btn(parent, text, x, y, w, h, kind="primary"):
    """kind: primary / secondary / danger-subtle"""
    b = lv.button(parent)
    b.set_size(w, h)
    b.set_pos(x, y)
    if kind == "primary":
        b.set_style_bg_color(C(PRIMARY), 0)
        b.set_style_border_width(0, 0)
        fg = 0xFFFFFF
    elif kind == "danger":
        b.set_style_bg_color(C(DANGER_BG), 0)
        b.set_style_border_width(0, 0)
        fg = DANGER
    else:  # secondary
        b.set_style_bg_color(C(SURFACE), 0)
        b.set_style_border_color(C(BORDER), 0)
        b.set_style_border_width(1, 0)
        fg = TEXT2
    b.set_style_radius(8, 0)
    lb = lv.label(b)
    lb.set_text(text)
    lb.align(lv.ALIGN.CENTER, 0, 0)
    lb.set_style_text_color(C(fg), 0)
    if ZH:
        lb.set_style_text_font(ZH, 0)
    return b

def mk_slider(parent, x, y, w, lo, hi, val, color=PRIMARY):
    s = lv.slider(parent)
    s.set_size(w, 8)
    s.set_pos(x, y)
    s.set_range(lo, hi)
    s.set_value(val, 0)   # 0 = ANIM_OFF
    s.set_style_bg_color(C(TRACK), lv.PART.MAIN)
    s.set_style_radius(4, lv.PART.MAIN)
    s.set_style_bg_color(C(color), lv.PART.INDICATOR)
    s.set_style_radius(4, lv.PART.INDICATOR)
    s.set_style_bg_color(C(color), lv.PART.KNOB)
    s.set_style_radius(8, lv.PART.KNOB)
    s.set_style_pad_all(4, lv.PART.KNOB)
    return s

def mk_switch(parent, x, y, on=False, color=PRIMARY):
    s = lv.switch(parent)
    s.set_size(44, 24)
    s.set_pos(x, y)
    s.set_style_bg_color(C(TRACK), lv.PART.MAIN)
    s.set_style_radius(12, lv.PART.MAIN)
    s.set_style_bg_color(C(color), lv.PART.INDICATOR)
    s.set_style_radius(12, lv.PART.INDICATOR)
    s.set_style_bg_color(C(SURFACE), lv.PART.KNOB)
    s.set_style_radius(10, lv.PART.KNOB)
    s.set_style_shadow_width(0, lv.PART.KNOB)
    if on:
        s.add_state(lv.STATE.CHECKED)
    return s

def mk_arc(parent, x, y, size, color):
    """環形量表（不可調整，knob 隱藏）。"""
    a = lv.arc(parent)
    a.set_size(size, size)
    a.set_pos(x, y)
    a.set_range(0, 100)
    a.set_style_arc_width(8, lv.PART.MAIN)
    a.set_style_arc_color(C(TRACK), lv.PART.MAIN)
    a.set_style_arc_width(8, lv.PART.INDICATOR)
    a.set_style_arc_color(C(color), lv.PART.INDICATOR)
    # 隱藏 knob（不設透明會畫出一個圓點）
    a.set_style_arc_opa(0, lv.PART.KNOB)
    a.set_style_bg_opa(0, lv.PART.KNOB)
    a.set_style_outline_width(0, lv.PART.KNOB)
    return a

def mk_bar(parent, x, y, w, h, val, color=PRIMARY):
    b = lv.bar(parent)
    b.set_size(w, h)
    b.set_pos(x, y)
    b.set_range(0, 100)
    b.set_value(val, 0)
    b.set_style_bg_color(C(TRACK), lv.PART.MAIN)
    b.set_style_radius(4, lv.PART.MAIN)
    b.set_style_bg_color(C(color), lv.PART.INDICATOR)
    b.set_style_radius(4, lv.PART.INDICATOR)
    return b

# chart 常量（binding 差異防護）
_CHART_TYPE_LINE = getattr(getattr(lv, "CHART_TYPE", None), "LINE", 1)
_CHART_AXIS_Y = getattr(getattr(lv, "CHART_AXIS", None), "PRIMARY_Y", 0)

def mk_chart(parent, x, y, w, h, color, points=24, ymax=100):
    """迷你趨勢圖（LINE，無座標軸文字）。"""
    ch = lv.chart(parent)
    ch.set_size(w, h)
    ch.set_pos(x, y)
    ch.set_type(_CHART_TYPE_LINE)
    ch.set_point_count(points)
    # LVGL 9.3：set_range 改名為 set_axis_range(axis, min, max)
    ch.set_axis_range(_CHART_AXIS_Y, 0, ymax)
    ch.set_div_line_count(3, 0)
    ch.set_style_bg_opa(0, 0)
    ch.set_style_border_width(0, 0)
    ch.set_style_pad_all(2, 0)
    ch.set_style_line_width(2, lv.PART.ITEMS)
    ch.set_style_line_color(C(color), lv.PART.ITEMS)
    # LVGL 9.3：set_style_size 改為 (width, height, selector)；設 0 不畫資料點
    ch.set_style_size(0, 0, lv.PART.INDICATOR)
    ser = ch.add_series(C(color), _CHART_AXIS_Y)
    return ch, ser

# ====== 焦點視覺 ======

def set_focus(wid, on, editing=False):
    """外框焦點環：藍=導覽中、琥珀=編輯中。"""
    if on:
        wid.set_style_outline_color(C(WARNING if editing else PRIMARY), 0)
        wid.set_style_outline_width(2, 0)
        wid.set_style_outline_pad(3, 0)
    else:
        wid.set_style_outline_width(0, 0)
