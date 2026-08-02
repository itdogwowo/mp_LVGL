# lvgl_page_monitor.py — page-monitor 數據監控（橫屏雙欄）
#
# 對應 lvgl-console-ui/pages/monitor.html（320×240 橫屏）：
#   左欄：主讀數卡 + 趨勢圖卡 + 閾值進度
#   右欄：通道狀態卡（4 列，編碼器切焦點，確認選取）
# 操作：
#   編碼器 A/B → 切換通道列焦點
#   C 確認     → 選取該通道（讀數/趨勢/閾值隨之切換）

import lvgl as lv
import math
import random
try:
    from ui.registry import register
    from ui.ui_common import (

    ZH, BG, SURFACE, TEXT, TEXT2, TEXT3,
    PRIMARY, SUCCESS, WARNING, FOCUS_BG,
    F_NUM_L, F_NUM_M, F_NUM_S, C,
    mk_appbar, mk_card, mk_label, mk_bar, mk_chart,
    pulse, fade_in,

    )
except ImportError:
    from registry import register
    from ui_common import (

    ZH, BG, SURFACE, TEXT, TEXT2, TEXT3,
    PRIMARY, SUCCESS, WARNING, FOCUS_BG,
    F_NUM_L, F_NUM_M, F_NUM_S, C,
    mk_appbar, mk_card, mk_label, mk_bar, mk_chart,
    pulse, fade_in,

    )


# 通道：[名稱, id, 基準值, 單位, 閾值, 狀態]
CH = [
    ["溫度", "T-01", 62.4, "°C", 70.0, "偏高"],
    ["濕度", "H-02", 41.2, "%",        100.0, "正常"],
    ["風速", "F-03", 3.6,  "m/s",      10.0,  "正常"],
    ["電壓", "V-04", 23.9, "V",        30.0,  "正常"],
]
_TREND = ["溫度趨勢", "濕度趨勢", "風速趨勢", "電壓趨勢"]

scr = None
_rows = []
_row_vals = []
_read_ch_lb = _read_val_lb = _read_delta_lb = None
_trend_lb = _trend_val_lb = None
_chart = _ser = None
_th_lb = _th_bar = _th_pct_lb = None
_sel = 0
_focus = 0
_vals = [c[2] for c in CH]
_hist = []
_last_txt = {}

def _fmt(i):
    return "{:.1f}{}".format(_vals[i], CH[i][3])

@register(id="monitor", title="數據監控", icon="activity", desc="傳感器實時數據", order=2, accent=0x2ECC71)
def build():
    global scr, _read_ch_lb, _read_val_lb, _read_delta_lb
    global _trend_lb, _trend_val_lb, _chart, _ser
    global _th_lb, _th_bar, _th_pct_lb
    scr = lv.obj(None)
    scr.set_style_bg_color(C(BG), 0)
    _bar, _live = mk_appbar(scr, "數據監控", "LIVE")
    if _live:
        pulse(_live, 1800, 90, 255)

    # ── 左欄（x=12, w=148） ──

    # 主讀數卡
    rc = mk_card(scr, 12, 44, 148, 62)
    fade_in(rc, dy=6, time_ms=280, delay_ms=0)
    _read_ch_lb = mk_label(rc, "T-01 · 溫度", 8, 6, TEXT2, ZH)
    _read_val_lb = lv.label(rc)
    _read_val_lb.set_pos(8, 28)
    _read_val_lb.set_style_text_font(F_NUM_L, 0)
    _read_val_lb.set_style_text_color(C(TEXT), 0)
    _read_delta_lb = lv.label(rc)
    _read_delta_lb.align(lv.ALIGN.BOTTOM_RIGHT, -8, -6)
    _read_delta_lb.set_style_text_font(F_NUM_S, 0)
    _read_delta_lb.set_style_text_color(C(WARNING), 0)

    # 趨勢圖卡
    tc = mk_card(scr, 12, 112, 148, 82)
    _trend_lb = mk_label(tc, "溫度趨勢", 6, 4, TEXT2, ZH)
    _trend_val_lb = lv.label(tc)
    _trend_val_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4)
    _trend_val_lb.set_style_text_font(F_NUM_M, 0)
    _trend_val_lb.set_style_text_color(C(PRIMARY), 0)
    _chart, _ser = mk_chart(tc, 6, 24, 136, 52, PRIMARY, points=24, ymax=100)

    # 閾值進度（絕對座標）
    _th_lb = mk_label(scr, "閾值", 12, 200, TEXT3, ZH)
    _th_bar = mk_bar(scr, 12, 220, 110, 8, 89, PRIMARY)
    _th_pct_lb = lv.label(scr)
    _th_pct_lb.set_pos(128, 216)
    _th_pct_lb.set_style_text_font(F_NUM_S, 0)
    _th_pct_lb.set_style_text_color(C(TEXT2), 0)

    # ── 右欄（x=166, w=142）：通道狀態卡 ──
    cc = mk_card(scr, 166, 44, 142, 162)
    mk_label(cc, "通道狀態", 8, 4, TEXT2, ZH)
    cnt = lv.label(cc)
    cnt.align(lv.ALIGN.TOP_RIGHT, -8, 6)
    cnt.set_style_text_font(F_NUM_S, 0)
    cnt.set_style_text_color(C(TEXT3), 0)
    cnt.set_text("4")

    for i, (name, cid, _v, _u, _th, tag) in enumerate(CH):
        row = lv.obj(cc)
        row.set_size(130, 24)
        row.set_pos(6, 26 + i * 27)
        row.set_style_radius(6, 0)
        row.set_style_bg_color(C(FOCUS_BG if i == 0 else SURFACE), 0)
        row.set_style_border_width(0, 0)
        row.set_style_pad_all(0, 0)
        row.remove_flag(lv.obj.FLAG.SCROLLABLE)

        mk_label(row, name, 4, 3, TEXT, ZH)
        mk_label(row, cid, 40, 5, TEXT3, F_NUM_S)
        fade_in(row, dy=4, time_ms=260, delay_ms=80 + i * 50)

        vlb = lv.label(row)
        vlb.align(lv.ALIGN.RIGHT_MID, -4, 0)
        vlb.set_style_text_font(F_NUM_S, 0)
        vlb.set_style_text_color(C(TEXT), 0)
        _row_vals.append(vlb)

        _rows.append(row)

    _seed_hist()
    _apply_selection()
    return scr

def _seed_hist():
    global _hist
    base = _vals[_sel]
    _hist = []
    for i in range(24):
        v = base + base * 0.04 * math.sin(i / 3.0 + _sel)
        _hist.append(v)
    for v in _hist:
        _chart.set_next_value(_ser, _to_pct(v))

def _to_pct(v):
    th = CH[_sel][4]
    p = int(v / th * 100)
    return max(0, min(100, p))

def _apply_selection():
    name, cid, _v, _u, th, _tag = CH[_sel]
    _read_ch_lb.set_text("{} · {}".format(cid, name))
    _trend_lb.set_text(_TREND[_sel])
    _th_lb.set_text("閾值 {:.0f}{}".format(th, CH[_sel][3]))
    _last_txt.clear()
    _seed_hist()
    _refresh_readout()
    _paint_focus()

def _refresh_readout():
    vtxt = _fmt(_sel)
    if _last_txt.get("val") != vtxt:
        _last_txt["val"] = vtxt
        _read_val_lb.set_text(vtxt)
        _trend_val_lb.set_text(vtxt)
    d = _hist[-1] - _hist[0]
    dtxt = "{}{:.1f}{}".format("+" if d >= 0 else "", d, CH[_sel][3])
    if _last_txt.get("delta") != dtxt:
        _last_txt["delta"] = dtxt
        _read_delta_lb.set_text(dtxt)
        _read_delta_lb.set_style_text_color(
            C(WARNING if abs(d) > CH[_sel][2] * 0.02 else SUCCESS), 0)
    pct = _to_pct(_vals[_sel])
    if _last_txt.get("pct") != pct:
        _last_txt["pct"] = pct
        _th_bar.set_value(pct, 0)
        _th_pct_lb.set_text("{}%".format(pct))

def _paint_focus():
    for i, row in enumerate(_rows):
        row.set_style_bg_color(C(FOCUS_BG if i == _focus else SURFACE), 0)

# ====== 頁面接口 ======

def on_enter():
    _refresh_readout()

def on_leave():
    pass

def on_enc(d):
    global _focus
    _focus = (_focus + d) % len(CH)
    _paint_focus()

def on_confirm():
    global _sel
    if _focus != _sel:
        _sel = _focus
        _apply_selection()
        print("[monitor] select {}".format(CH[_sel][1]))
    return None

def on_exit():
    return False

def update(run):
    if run % 20 != 0:
        return
    for i in range(len(CH)):
        base = CH[i][2]
        _vals[i] = base + base * 0.03 * math.sin(run / 890.0 + i * 1.7) \
                   + random.randint(-10, 10) * base * 0.001
        vtxt = _fmt(i)
        if _last_txt.get("row{}".format(i)) != vtxt:
            _last_txt["row{}".format(i)] = vtxt
            _row_vals[i].set_text(vtxt)

    _hist.append(_vals[_sel])
    if len(_hist) > 24:
        _hist.pop(0)
    _chart.set_next_value(_ser, _to_pct(_vals[_sel]))
    _refresh_readout()
