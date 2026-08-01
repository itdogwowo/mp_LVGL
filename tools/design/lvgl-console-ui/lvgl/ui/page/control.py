# lvgl_page_control.py — page-control 設備控制（橫屏雙欄）
#
# 對應 lvgl-console-ui/pages/control.html（320×240 橫屏）：
#   左欄：4 繼電器 2×2 + 運行模式段選
#   右欄：目標溫度/風速滑桿 + 暫停/立即啟動
# 操作（純編碼器）：
#   A/B 旋轉 → 移動焦點；「編輯模式」中 → 調整滑桿值
#   C 確認   → 開關切換 / 模式切換 / 進入(離開)滑桿編輯 / 觸發按鈕
#   BTN42    → 編輯中先離開編輯，否則返回（由 app 處理）

import lvgl as lv
import time
from ui.registry import register
from ui.ui_common import (
    ZH, BG, SURFACE, TEXT, TEXT2, TEXT3,
    PRIMARY, SUCCESS, TRACK, F_NUM_M, F_NUM_S, C,
    mk_appbar, mk_card, mk_label, mk_btn, mk_slider, mk_switch,
    mk_icon, set_focus, fade_in,
)

_RELAYS = [("主電源", True, "power"), ("冷卻風扇", True, "fan"),
           ("加熱器", False, "flame"), ("輔助照明", False, "lightbulb")]
_MODES = ["自動", "手動", "節能"]

scr = None
_appbar_status = None
_sw = []
_seg = []
_seg_lb = []
_sl = []
_sl_lb = []
_btn_pause = _btn_start = None
_footer_lb = None

_focusables = []
_fi = 0
_editing = False
_mode = 1
_running = False
_t0 = 0
_last_status = ""

@register(id="control", title="設備控制", icon="sliders-horizontal", desc="繼電器與參數控制", order=3, accent=0xE67E22)
def build():
    global scr, _appbar_status, _btn_pause, _btn_start, _t0
    global _sl, _sl_lb, _footer_lb
    scr = lv.obj(None)
    scr.set_style_bg_color(C(BG), 0)
    _bar, _appbar_status = mk_appbar(scr, "設備控制", "就緒")

    # ── 左欄（x=12, w=148）：繼電器 2×2 ──
    pos = [(12, 44), (88, 44), (12, 98), (88, 98)]
    for i, ((name, on, ico), (x, y)) in enumerate(zip(_RELAYS, pos)):
        t = mk_card(scr, x, y, 72, 48)
        mk_label(t, name, 22, 4, TEXT, ZH)
        mk_icon(t, ico, 4, 4, TEXT2)
        fade_in(t, dy=5, time_ms=280, delay_ms=i * 70)
        s = mk_switch(t, 14, 26, on=on)
        _sw.append(s)
        _focusables.append((s, "sw", i))

    # 運行模式段選
    mk_label(scr, "運行模式", 12, 152, TEXT2, ZH)
    segbox = lv.obj(scr)
    segbox.set_size(148, 26)
    segbox.set_pos(12, 174)
    segbox.set_style_bg_color(C(TRACK), 0)
    segbox.set_style_radius(8, 0)
    segbox.set_style_border_width(0, 0)
    segbox.set_style_pad_all(0, 0)
    segbox.remove_flag(lv.obj.FLAG.SCROLLABLE)
    for i, m in enumerate(_MODES):
        seg = lv.obj(segbox)
        seg.set_size(47, 22)
        seg.set_pos(2 + i * 49, 2)
        seg.set_style_radius(6, 0)
        seg.set_style_border_width(0, 0)
        seg.set_style_pad_all(0, 0)
        seg.remove_flag(lv.obj.FLAG.SCROLLABLE)
        lb = mk_label(seg, m, 0, 3, TEXT2, ZH)
        lb.align(lv.ALIGN.TOP_MID, 0, 3)
        _seg.append(seg)
        _seg_lb.append(lb)
    _focusables.append((segbox, "seg", 0))
    _paint_mode()

    # ── 右欄（x=166, w=142）：參數卡 ──
    pc = mk_card(scr, 166, 44, 142, 92)
    mk_label(pc, "目標溫度", 8, 5, TEXT2, ZH)
    lb1 = lv.label(pc)
    lb1.align(lv.ALIGN.TOP_RIGHT, -8, 5)
    lb1.set_style_text_font(F_NUM_M, 0)
    lb1.set_style_text_color(C(PRIMARY), 0)
    s1 = mk_slider(pc, 8, 26, 126, 20, 90, 58)
    _focusables.append((s1, "slider", 0))

    mk_label(pc, "風速", 8, 50, TEXT2, ZH)
    lb2 = lv.label(pc)
    lb2.align(lv.ALIGN.TOP_RIGHT, -8, 50)
    lb2.set_style_text_font(F_NUM_M, 0)
    lb2.set_style_text_color(C(PRIMARY), 0)
    s2 = mk_slider(pc, 8, 71, 126, 0, 100, 65)
    _focusables.append((s2, "slider", 1))

    _sl = [s1, s2]
    _sl_lb = [lb1, lb2]
    _paint_sliders()

    # 動作按鈕
    _btn_pause = mk_btn(scr, "暫停", 166, 142, 66, 32, "secondary")
    _btn_start = mk_btn(scr, "立即啟動", 236, 142, 72, 32, "primary")
    _focusables.append((_btn_pause, "btn", 0))
    _focusables.append((_btn_start, "btn", 1))

    _footer_lb = mk_label(scr, "", 166, 182, TEXT3, ZH)

    _t0 = time.time()
    _paint_focus()
    return scr

# ====== 繪製 ======

def _paint_mode():
    for i, seg in enumerate(_seg):
        act = i == _mode
        seg.set_style_bg_color(C(PRIMARY if act else SURFACE), 0)
        _seg_lb[i].set_style_text_color(C(0xFFFFFF if act else TEXT2), 0)

def _paint_sliders():
    _sl_lb[0].set_text("{}°C".format(_sl[0].get_value()))
    _sl_lb[1].set_text("{}%".format(_sl[1].get_value()))

def _paint_focus():
    for i, (w, _kind, _idx) in enumerate(_focusables):
        set_focus(w, i == _fi, editing=(_editing and i == _fi))

def _set_status(txt):
    global _last_status
    if txt != _last_status:
        _last_status = txt
        _appbar_status.set_text(txt)

# ====== 頁面接口 ======

def on_enter():
    _set_status("運行中" if _running else "就緒")

def on_leave():
    global _editing
    _editing = False

def on_enc(d):
    global _fi, _editing
    if _editing:
        kind = _focusables[_fi][1]
        if kind == "slider":
            s = _focusables[_fi][0]
            s.set_value(max(s.get_min_value(), min(s.get_max_value(),
                          s.get_value() + d)), 0)
            _paint_sliders()
        return
    _fi = (_fi + (1 if d > 0 else -1)) % len(_focusables)
    _paint_focus()

def on_confirm():
    global _mode, _editing, _running, _t0
    w, kind, idx = _focusables[_fi]

    if kind == "sw":
        if w.get_state():
            w.clear_state(lv.STATE.CHECKED)
        else:
            w.add_state(lv.STATE.CHECKED)
        print("[control] relay {} -> {}".format(
            _RELAYS[idx][0], "ON" if w.get_state() else "OFF"))

    elif kind == "seg":
        _mode = (_mode + 1) % len(_MODES)
        _paint_mode()
        print("[control] mode -> {}".format(_MODES[_mode]))

    elif kind == "slider":
        _editing = not _editing
        _paint_focus()
        print("[control] slider edit = {}".format(_editing))

    elif kind == "btn":
        if idx == 0:
            _running = False
            _set_status("已暫停")
            _footer_lb.set_text("已暫停")
            print("[control] pause")
        else:
            _running = True
            _t0 = time.time()
            _set_status("運行中")
            _footer_lb.set_text("")
            print("[control] start")
    return None

def on_exit():
    global _editing
    if _editing:
        _editing = False
        _paint_focus()
        return True
    return False

def update(run):
    if run % 40 != 0:
        return
    if _running:
        sec = int(time.time() - _t0)
        _set_status("運行中 {:02d}:{:02d}".format(sec // 60, sec % 60))
