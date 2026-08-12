# lvgl_page_settings.py — page-settings 系統設定（橫屏雙欄）
#
# 對應 lvgl-console-ui/pages/settings.html（320×240 橫屏）：
#   左欄：一般（名稱/語言）+ 顯示（亮度滑桿）
#   右欄：系統（3 開關）+ 重設/儲存 + dirty 狀態
# 操作（純編碼器）：
#   A/B 旋轉 → 移動焦點；「編輯模式」中 → 調整亮度
#   C 確認   → 語言切換 / 開關切換 / 進入(離開)亮度編輯 / 重設 / 儲存
#   BTN42    → 編輯中先離開編輯，否則返回（由 app 處理）

import lvgl as lv
from lvgl_ui_common import (
    ZH, BG, SURFACE, BORDER, TEXT, TEXT2, TEXT3,
    PRIMARY, SUCCESS, WARNING, F_NUM_M, C,
    mk_appbar, mk_card, mk_label, mk_btn, mk_slider, mk_switch,
    mk_icon, set_focus, fade_in,
)

_LANGS = ["中文", "English", "日本"]
_SW_DEF = [True, True, False]
_SW_NAMES = ["自動更新", "錯誤上報", "通知音效"]
_SW_ICONS = ["refresh-cw", "alert-triangle", "shield"]

scr = None
_lang_box = _lang_lb = None
_bright = _bright_lb = None
_sw = []
_btn_reset = _btn_save = None
_status_lb = None

_focusables = []
_fi = 0
_editing = False
_lang = 0
_dirty = False

def build():
    global scr, _lang_box, _lang_lb, _bright, _bright_lb
    global _btn_reset, _btn_save, _status_lb
    scr = lv.obj(None)
    scr.set_style_bg_color(C(BG), 0)
    mk_appbar(scr, "系統設置", "v2.4.1")

    # ── 左欄（x=12, w=148） ──

    # 一般
    c1 = mk_card(scr, 12, 44, 148, 62)
    mk_label(c1, "設備名稱", 8, 6, TEXT2, ZH)
    mk_label(c1, "機組 A-01", 80, 6, TEXT, ZH)
    mk_label(c1, "語言", 8, 34, TEXT2, ZH)
    _lang_box = lv.obj(c1)
    _lang_box.set_size(64, 22)
    _lang_box.set_pos(76, 32)
    _lang_box.set_style_bg_color(C(BG), 0)
    _lang_box.set_style_radius(6, 0)
    _lang_box.set_style_border_color(C(BORDER), 0)
    _lang_box.set_style_border_width(1, 0)
    _lang_box.set_style_pad_all(0, 0)
    _lang_box.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _lang_lb = mk_label(_lang_box, _LANGS[0] + " >", 6, 2, TEXT, ZH)
    _focusables.append((_lang_box, "lang", 0))

    # 顯示：亮度滑桿
    c2 = mk_card(scr, 12, 112, 148, 56)
    mk_label(c2, "屏幕亮度", 8, 5, TEXT2, ZH)
    _bright_lb = lv.label(c2)
    _bright_lb.align(lv.ALIGN.TOP_RIGHT, -8, 5)
    _bright_lb.set_style_text_font(F_NUM_M, 0)
    _bright_lb.set_style_text_color(C(PRIMARY), 0)
    _bright = mk_slider(c2, 8, 34, 132, 0, 100, 80)
    _focusables.append((_bright, "slider", 0))
    _bright_lb.set_text("80%")

    # ── 右欄（x=166, w=142） ──

    # 系統：3 開關
    c3 = mk_card(scr, 166, 44, 142, 98)
    for i, ((name, on), ico) in enumerate(zip(zip(_SW_NAMES, _SW_DEF), _SW_ICONS)):
        mk_label(c3, name, 26, 8 + i * 30, TEXT, ZH)
        mk_icon(c3, ico, 7, 10 + i * 30, TEXT2)
        s = mk_switch(c3, 90, 6 + i * 30, on=on)
        _sw.append(s)
        _focusables.append((s, "sw", i))

    # 動作按鈕
    _btn_reset = mk_btn(scr, "重設", 166, 150, 66, 34, "danger")
    _btn_save = mk_btn(scr, "保存設置", 236, 150, 72, 34, "primary")
    _focusables.append((_btn_reset, "btn", 0))
    _focusables.append((_btn_save, "btn", 1))

    _status_lb = mk_label(scr, "", 166, 192, TEXT3, ZH)

    fade_in(c1, dy=5, time_ms=280, delay_ms=40)
    fade_in(c2, dy=5, time_ms=280, delay_ms=120)
    fade_in(c3, dy=5, time_ms=280, delay_ms=200)

    _paint_focus()
    return scr

# ====== 繪製 ======

def _paint_focus():
    for i, (w, _kind, _idx) in enumerate(_focusables):
        set_focus(w, i == _fi, editing=(_editing and i == _fi))

def _set_status(txt, color):
    _status_lb.set_text(txt)
    _status_lb.set_style_text_color(C(color), 0)

def _mark_dirty():
    global _dirty
    _dirty = True
    _set_status("未保存更改", WARNING)

def _restore_defaults():
    global _lang
    _lang = 0
    _lang_lb.set_text(_LANGS[0] + " >")
    _bright.set_value(80, 0)
    _bright_lb.set_text("80%")
    for s, on in zip(_sw, _SW_DEF):
        if on:
            s.add_state(lv.STATE.CHECKED)
        else:
            s.clear_state(lv.STATE.CHECKED)

# ====== 頁面接口 ======

def on_enter():
    pass

def on_leave():
    global _editing
    _editing = False

def on_enc(d):
    global _fi
    if _editing:
        v = max(0, min(100, _bright.get_value() + d))
        _bright.set_value(v, 0)
        _bright_lb.set_text("{}%".format(v))
        return
    _fi = (_fi + (1 if d > 0 else -1)) % len(_focusables)
    _paint_focus()

def on_confirm():
    global _lang, _editing, _dirty
    _w, kind, idx = _focusables[_fi]

    if kind == "lang":
        _lang = (_lang + 1) % len(_LANGS)
        _lang_lb.set_text(_LANGS[_lang] + " >")
        _mark_dirty()
        print("[settings] lang -> {}".format(_LANGS[_lang]))

    elif kind == "slider":
        _editing = not _editing
        if _editing:
            _mark_dirty()
        _paint_focus()

    elif kind == "sw":
        s = _sw[idx]
        if s.get_state():
            s.clear_state(lv.STATE.CHECKED)
        else:
            s.add_state(lv.STATE.CHECKED)
        _mark_dirty()
        print("[settings] {} -> {}".format(
            _SW_NAMES[idx], "ON" if s.get_state() else "OFF"))

    elif kind == "btn":
        if idx == 0:
            _restore_defaults()
            _dirty = True
            _set_status("已恢復默認", TEXT2)
            print("[settings] reset")
        else:
            _dirty = False
            _set_status("設置已保存", SUCCESS)
            print("[settings] saved")
    return None

def on_exit():
    global _editing
    if _editing:
        _editing = False
        _paint_focus()
        return True
    return False

def update(run):
    pass
