# lvgl_page_overview.py — page-overview 儀表盤（橫屏雙欄）
#
# 對應 lvgl-console-ui/pages/overview.html（320×240 橫屏）：
#   左欄：CPU/內存 arc 量表 + 隊列深度 sparkline
#   右欄：2×2 統計卡 + 狀態列 + 更新時間
# 純展示頁（無焦點操作），數據由 update() 模擬。

import lvgl as lv
import math
import random
try:
    from ui.registry import register
    from ui.ui_common import (

    ZH, BG, TEXT, TEXT2, TEXT3, PRIMARY, SUCCESS, DANGER,
    F_NUM_M, F_NUM_S, C,
    mk_appbar, mk_card, mk_label, mk_arc, mk_chart,
    pulse, fade_in,

    )
except ImportError:
    from registry import register
    from ui_common import (

    ZH, BG, TEXT, TEXT2, TEXT3, PRIMARY, SUCCESS, DANGER,
    F_NUM_M, F_NUM_S, C,
    mk_appbar, mk_card, mk_label, mk_arc, mk_chart,
    pulse, fade_in,

    )


scr = None
_cpu_arc = _mem_arc = None
_cpu_lb = _mem_lb = None
_q_chart = _q_ser = _q_lb = None
_time_lb = None
_stat_lbs = {}
_last = {}

@register(id="overview", title="儀表盤", icon="layout-dashboard", desc="系統運行狀態總覽", order=1, accent=0x4A90D9)
def build():
    global scr, _cpu_arc, _mem_arc, _cpu_lb, _mem_lb
    global _q_chart, _q_ser, _q_lb, _time_lb
    scr = lv.obj(None)
    scr.set_style_bg_color(C(BG), 0)
    _bar, _live = mk_appbar(scr, "儀表盤", "LIVE")
    if _live:
        pulse(_live, 1800, 90, 255)

    _cards = []

    # ── 左欄（x=12, w=148） ──

    # CPU 卡
    cc = mk_card(scr, 12, 44, 148, 56)
    _cards.append(cc)
    _cpu_arc = mk_arc(cc, 6, 4, 48, PRIMARY)
    _cpu_lb = lv.label(_cpu_arc)
    _cpu_lb.align(lv.ALIGN.CENTER, 0, 0)
    _cpu_lb.set_style_text_font(F_NUM_S, 0)
    _cpu_lb.set_style_text_color(C(TEXT), 0)
    mk_label(cc, "CPU 使用率", 62, 18, TEXT2, ZH)

    # 內存卡
    mc = mk_card(scr, 12, 106, 148, 56)
    _cards.append(mc)
    _mem_arc = mk_arc(mc, 6, 4, 48, SUCCESS)
    _mem_lb = lv.label(_mem_arc)
    _mem_lb.align(lv.ALIGN.CENTER, 0, 0)
    _mem_lb.set_style_text_font(F_NUM_S, 0)
    _mem_lb.set_style_text_color(C(TEXT), 0)
    mk_label(mc, "內存使用", 62, 18, TEXT2, ZH)

    # 隊列深度 sparkline
    qc = mk_card(scr, 12, 168, 148, 60)
    _cards.append(qc)
    mk_label(qc, "隊列深度", 6, 4, TEXT2, ZH)
    _q_lb = lv.label(qc)
    _q_lb.align(lv.ALIGN.TOP_RIGHT, -6, 4)
    _q_lb.set_style_text_font(F_NUM_M, 0)
    _q_lb.set_style_text_color(C(PRIMARY), 0)
    _q_chart, _q_ser = mk_chart(qc, 6, 24, 136, 30, SUCCESS, points=24, ymax=60)
    for i in range(24):
        _q_chart.set_next_value(_q_ser, 15 + int(8 * math.sin(i / 3.0)))

    # ── 右欄（x=166, w=142）：2×2 統計 ──
    stats = [
        ("tasks",   "任務總數", 128, TEXT,    166, 44),
        ("running", "運行中",     3, SUCCESS, 236, 44),
        ("ready",   "就緒",      12, TEXT,    166, 102),
        ("errors",  "錯誤",       0, DANGER,  236, 102),
    ]
    for key, name, val, color, x, y in stats:
        c = mk_card(scr, x, y, 68, 52)
        _cards.append(c)
        mk_label(c, name, 8, 6, TEXT2, ZH)
        lb = lv.label(c)
        lb.set_pos(8, 28)
        lb.set_style_text_font(F_NUM_M, 0)
        lb.set_style_text_color(C(color), 0)
        lb.set_text("{}".format(val))
        _stat_lbs[key] = lb
        _last[key] = val

    # 狀態列
    sc = mk_card(scr, 166, 160, 142, 28)
    dot = lv.obj(sc)
    dot.set_size(8, 8)
    dot.set_pos(10, 10)
    dot.set_style_radius(4, 0)
    dot.set_style_bg_color(C(SUCCESS), 0)
    dot.set_style_border_width(0, 0)
    pulse(dot, 1800, 90, 255)          # 狀態燈呼吸
    mk_label(sc, "系統正常", 24, 5, SUCCESS, ZH)

    # 更新時間
    _time_lb = mk_label(scr, "", 166, 196, TEXT3, F_NUM_S)

    # 載入動效：卡片淡入+位移（錯開 60ms）
    for i, c in enumerate(_cards):
        fade_in(c, dy=6, time_ms=280, delay_ms=i * 60)

    # 初始值
    _cpu_arc.set_value(45)
    _mem_arc.set_value(62)
    _cpu_lb.set_text("45%")
    _mem_lb.set_text("62%")
    _q_lb.set_text("18")
    _last.update({"cpu": 45, "mem": 62, "q": 18})
    return scr

def _set_stat(key, val):
    if _last.get(key) != val:
        _last[key] = val
        _stat_lbs[key].set_text("{}".format(val))

# ====== 頁面接口 ======

def on_enter():
    pass

def on_leave():
    pass

def on_enc(d):
    pass

def on_confirm():
    return None

def on_exit():
    return False

def update(run):
    if run % 20 != 0:
        return
    cpu = int(45 + 14 * math.sin(run / 970.0) + random.randint(-3, 3))
    cpu = max(2, min(98, cpu))
    mem = int(62 + 5 * math.sin(run / 2110.0) + random.randint(-1, 1))
    mem = max(2, min(98, mem))
    if cpu != _last.get("cpu"):
        _last["cpu"] = cpu
        _cpu_arc.set_value(cpu)
        _cpu_lb.set_text("{}%".format(cpu))
    if mem != _last.get("mem"):
        _last["mem"] = mem
        _mem_arc.set_value(mem)
        _mem_lb.set_text("{}%".format(mem))

    q = int(18 + 10 * math.sin(run / 430.0) + random.randint(-4, 4))
    q = max(0, min(60, q))
    _q_chart.set_next_value(_q_ser, q)
    if q != _last.get("q"):
        _last["q"] = q
        _q_lb.set_text("{}".format(q))

    if run % 200 == 0:
        _set_stat("running", max(0, min(8, 3 + random.randint(-1, 1))))
        _set_stat("ready", max(0, 12 + random.randint(-2, 2)))
        sec = run // 200
        _time_lb.set_text("更新 {:02d}:{:02d}".format(sec // 60, sec % 60))
