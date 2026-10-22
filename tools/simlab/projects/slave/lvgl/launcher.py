# ui/lvgl/launcher.py — 動態首頁(讀 registry 產生卡片)
#
# 橫屏 320×240 佈局:卡片橫向輪播(旋鈕左右選,按下確認)。
# 對齊 mp_LVGL/ui/lvgl_ui_launcher.py 的輪播風格。
import lvgl as lv
from ui.lvgl.registry import ordered
from ui.lvgl import ui_common as u

_ANIM = getattr(lv, "anim_t", None)
_EASE = getattr(lv, "anim_path_ease_out", None)

scr = None
cards = []
dots = []
card_ids = []
card_desc_lbs = []
card_stat_lbs = []
_focus = 0
_mounted = False
_last_card_txt = {}

CARD_W = 156
CARD_H = 134
CX = 0
STRIDE = 176
FOCUS_Y = 50
IDLE_Y = 58

CTRL_MODE_LABELS = ["模式 1", "模式 2", "模式 3", "模式 4", "模式 5"]
PCA_MODE_LABELS = ["逐腳呼吸", "全腳呼吸"]


def _slide_to(wid, x, y, time_ms=260, delay_ms=0):
    """單一 exec callback 同時更新 x/y,避免內容與邊框分離。"""
    sx, sy = wid.get_x(), wid.get_y()
    if _ANIM is None or (sx == x and sy == y):
        wid.set_pos(x, y)
        return None
    a = _ANIM()
    try:
        a.init()
    except Exception:
        pass
    a.set_var(wid)
    a.set_values(0, 1000)
    a.set_duration(time_ms)
    a.set_delay(delay_ms)
    if _EASE is not None:
        try:
            a.set_path_cb(_EASE)
        except Exception:
            pass

    def _exec(_a, v, _w=wid, _sx=sx, _sy=sy, _tx=x, _ty=y):
        k = v / 1000.0
        _w.set_pos(int(_sx + (_tx - _sx) * k), int(_sy + (_ty - _sy) * k))

    a.set_custom_exec_cb(_exec)
    a.start()
    return a


def build():
    global scr, cards, dots, card_ids, card_desc_lbs, card_stat_lbs, _focus, CX, _mounted, _last_card_txt
    _focus = 0
    _mounted = False
    _last_card_txt = {}
    CX = (u.W - CARD_W) // 2
    scr = lv.obj(None)
    scr.set_style_bg_color(u.C(u.BG), 0)
    title = u.mk_label(scr, "選擇功能", 0, 8, u.TEXT, u.ZH)
    title.align(lv.ALIGN.TOP_MID, 0, 10)
    sub = u.mk_label(scr, "旋鈕切換 · 按下確認", 0, 28, u.TEXT3, u.ZH)
    sub.align(lv.ALIGN.TOP_MID, 0, 30)

    metas = ordered()
    cards = []
    card_ids = []
    card_desc_lbs = []
    card_stat_lbs = []
    for meta in metas:
        c = lv.obj(scr)
        c.set_size(CARD_W, CARD_H)
        c.set_style_bg_color(u.C(u.SURFACE), 0)
        c.set_style_radius(12, 0)
        c.set_style_border_color(u.C(u.BORDER), 0)
        c.set_style_border_width(1, 0)
        c.set_style_shadow_width(0, 0)
        c.set_style_pad_all(0, 0)
        # 縮放 pivot 置中(聚焦 100% / 非聚焦 94%,HTML 卡片同款)
        c.set_style_transform_pivot_x(CARD_W // 2, 0)
        c.set_style_transform_pivot_y(CARD_H // 2, 0)
        c.remove_flag(lv.obj.FLAG.SCROLLABLE)

        blk = lv.obj(c)
        blk.set_size(40, 40)
        blk.set_pos(14, 16)
        blk.set_style_bg_color(u.C(u.PRIMARY_BG), 0)
        blk.set_style_radius(10, 0)
        blk.set_style_border_color(u.C(u.BORDER), 0)
        blk.set_style_border_width(0, 0)
        blk.set_style_pad_all(0, 0)
        blk.remove_flag(lv.obj.FLAG.SCROLLABLE)
        ic = u.mk_icon(blk, meta["icon"], 0, 0, meta["accent"])
        if ic is not None:
            ic.align(lv.ALIGN.CENTER, 0, 0)
        num = u.mk_label(c, "{:02d}".format(meta["order"]), 0, 0, u.TEXT3, u.F_NUM_S)
        num.align(lv.ALIGN.TOP_RIGHT, -8, 8)

        ttl = u.mk_label(c, meta["title"], 14, 68, u.TEXT, u.ZH)
        ttl.set_style_text_color(u.C(u.TEXT), 0)
        desc = u.mk_label(c, meta["desc"], 14, 92, u.TEXT3, u.ZH)
        desc.set_width(CARD_W - 28)
        try:
            desc.set_style_text_line_space(2, 0)
        except Exception:
            pass
        stat = u.mk_label(c, "同步中", 14, 114, u.TEXT2, u.F_NUM_S)
        stat.set_width(CARD_W - 28)
        try:
            stat.set_style_text_line_space(1, 0)
        except Exception:
            pass
        cards.append(c)
        card_ids.append(meta["id"])
        card_desc_lbs.append(desc)
        card_stat_lbs.append(stat)

    # 分頁指示點
    n = len(cards)
    x0 = (u.W - (n * 8 + (n - 1) * 6)) // 2
    dots = []
    for i in range(n):
        d = lv.obj(scr)
        d.set_size(7, 7)
        d.set_pos(x0 + i * 14, u.H - 40)
        d.set_style_radius(4, 0)
        d.set_style_bg_color(u.C(0xDADCE0), 0)
        d.set_style_border_width(0, 0)
        dots.append(d)

    _layout(False)
    _refresh_cards()
    _mounted = True
    return scr


def _safe_time(t):
    try:
        t = int(t)
    except Exception:
        t = 0
    t = max(0, min(255, t))
    return "{:02d}:{:02d}".format(*divmod(t, 60))


def _summary_for(page_id):
    from lib.sys_bus import bus
    if page_id == "control_panel":
        mode_raw = int(bus.shared.get("_display_mode", 0)) & 0x3F
        mode_txt = CTRL_MODE_LABELS[mode_raw % len(CTRL_MODE_LABELS)]
        bright = int(bus.shared.get("_display_brightness", 0))
        bright = max(0, min(36, bright))
        running = bool((bus.shared.get("control_panel") or {}).get("is_running", 0))
        time_txt = _safe_time(bus.shared.get("_display_time", 0))
        return (
            "模式 {} · 亮度 {}".format(mode_txt[-1], bright),
            "{} {}".format("計時中" if running else "待機", time_txt),
        )
    if page_id == "pca9685":
        st = bus.shared.get("pca9685") or {}
        devs = list(bus.shared.get("_pca_devices", []) or [])
        target = int(st.get("target", -1))
        target_txt = "廣播" if target == -1 else "0x{:02X}".format(target)
        active = 0
        for i in range(16):
            try:
                if int(st.get("ch{}".format(i), 0)) > 0:
                    active += 1
            except Exception:
                pass
        mode = int(st.get("mode", 0))
        mode_txt = PCA_MODE_LABELS[mode % len(PCA_MODE_LABELS)]
        return (
            "{} 台裝置 · {} ch".format(len(devs), active),
            "{} · {}".format(mode_txt, target_txt),
        )
    if page_id == "settings":
        syscfg = bus.shared.get("System", {}) or {}
        wifi = (bus.shared.get("Network", {}) or {}).get("wifi", {}) or {}
        ssid = str(wifi.get("ssid", "") or "未連線")
        host = str(syscfg.get("hostname", "") or "—")
        enabled = bool(int(wifi.get("enable", 0) or 0))
        return (
            "{} · {}".format("Wi‑Fi 開" if enabled else "Wi‑Fi 關", ssid),
            "主機 {}".format(host),
        )
    return ("", "")


def _refresh_cards():
    for i, page_id in enumerate(card_ids):
        if i >= len(card_desc_lbs) or i >= len(card_stat_lbs):
            continue
        try:
            desc, stat = _summary_for(page_id)
        except Exception:
            desc, stat = ("", "")
        if _last_card_txt.get((page_id, "desc")) != desc:
            _last_card_txt[(page_id, "desc")] = desc
            if desc:
                card_desc_lbs[i].set_text(desc)
        if _last_card_txt.get((page_id, "stat")) != stat:
            _last_card_txt[(page_id, "stat")] = stat
            if stat:
                card_stat_lbs[i].set_text(stat)


def _layout(animated=True):
    """輪播佈局:位置/透明度/縮放/邊框 300ms ease-out 過渡,
    依與焦點的距離階梯延遲(30ms/步,對齊 HTML 卡片逐張滑入)。"""
    n = len(cards)
    for i, c in enumerate(cards):
        rel = ((i - _focus + n + n // 2) % n) - n // 2
        x = CX + rel * STRIDE
        foc = rel == 0
        delay = min(60, abs(rel) * 30)
        y = FOCUS_Y if foc else IDLE_Y
        border = u.PRIMARY if foc else u.BORDER
        if animated:
            u.cancel(c)
            _slide_to(c, x, y, 240, delay)
            u.opa_to(c, 255 if foc else 172, 260, delay)
            u.scale_to(c, 100 if foc else 96, 260, delay)
            u.border_width_to(c, 2 if foc else 1, 260, delay)
            u.color_anim(c, lambda col, _c=c: _c.set_style_border_color(col, 0),
                         u.PRIMARY if foc else u.BORDER,
                         u.BORDER if foc else u.PRIMARY,
                         260, delay)
        else:
            c.set_pos(x, y)
            c.set_style_opa(255 if foc else 172, 0)
            c.set_style_border_width(2 if foc else 1, 0)
            c.set_style_border_color(u.C(border), 0)
            scale_setter = getattr(c, "set_style_transform_scale", None)
            if scale_setter is not None:
                scale_setter(int((100 if foc else 96) * 2.56), 0)
        if foc:
            c.move_foreground()
    for di, d in enumerate(dots):
        if animated:
            u.cancel(d)
            u.color_anim(d, lambda col, _d=d: _d.set_style_bg_color(col, 0),
                         0xDADCE0 if di == _focus else u.PRIMARY,
                         u.PRIMARY if di == _focus else 0xDADCE0,
                         260, 0)
        else:
            d.set_style_bg_color(u.C(u.PRIMARY if di == _focus else 0xDADCE0), 0)


def on_enc(d):
    global _focus
    n = len(cards)
    if n == 0:
        return
    _focus = (_focus + d) % n
    _layout(_mounted)


def on_confirm():
    metas = ordered()
    if not metas:
        return None
    target = metas[_focus]["id"]
    print("[launcher] enter", target)
    return target


def on_exit():
    return False


def update(run):
    if run % 10 != 0:
        return
    try:
        _refresh_cards()
    except Exception:
        pass
