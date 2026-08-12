# lv_ui_fx.py — 動態效果 helper
#
# 對應設計稿 CSS 動效(用 lv_binding_micropython 的 anim API):
#   pulse()    ← pulse / live-ping / mon-ping（呼吸閃爍:livedot、tag dot、狀態燈）
#   fade_in()  ← rise / fade-in / set-in / tile-in（載入淡入 + 位移）
#   bar_grow() ← bar-grow（數值/進度成長）
#   anim_pos() ← 輪播/卡片位移（launcher carousel 滑動）
#   opa_to()   ← 透明度過渡（輪播卡片淡入淡出）
#   scale_to() ← transform 縮放過渡（輪播卡片 94%↔100%）
#   color_anim() ← 樣式顏色漸變（選中高亮 / 焦點邊框換色）
#   set_state_colors() ← :hover/:active/:focus（焦點/按壓換色,配合 set_focus 外框）
#
# 注意:此 binding 的 anim API 是 lv.anim_t()（沒有 lv.anim()）:
#   - set_time() 不存在 → 用 set_duration()（LVGL 9）
#   - 呼吸來回用 set_reverse_duration()（播放完反向播）
#   - 無限重複用 repeat_count = 0xFFFF（LV_ANIM_REPEAT_INFINITE）
#   - 曲線:LVGL 9 預設就是 ease-out;set_path_cb 若有則顯式指定,
#     對齊 HTML 的 --ease-lv-out(cubic-bezier(.25,.46,.45,.94))。
# anim 不可用時自動降級為「直接設定最終值」,不影響功能。
import lvgl as lv

_ANIM_CLASS = getattr(lv, "anim_t", None)
_REPEAT_INF = 0xFFFF  # LV_ANIM_REPEAT_INFINITE
_EASE = getattr(lv, "anim_path_ease_out", None)
# 世代守衛:(id(wid), slot) → 世代號。每次同 slot 新動畫 +1,舊動畫 exec cb
# 檢查世代不符就自行失效(即使 binding 沒有 anim_delete 也能避免重疊殘影)。
# slot 依屬性分開(x/y/opa/scale/color…),同 widget 不同屬性的動畫可並存。
_GEN = {}       # (id(wid), slot) → gen
_WID_SLOTS = {} # id(wid) → {slot,...},cancel 用


def _anim_start(a):
    """建立 anim 後 start()。"""
    a.start()
    return a


def _set_ease(a):
    """套用 ease-out 曲線(LVGL 9 預設已是 ease-out,顯式指定保險)。"""
    if _EASE is not None:
        try:
            a.set_path_cb(_EASE)
        except Exception:
            pass


def _new_anim(wid, slot, start_v, end_v, time_ms, delay_ms):
    """建立 anim + 世代記號。回傳 (anim, skey, gen)。
    注意:init() 必須在 setter 之前(會重置結構,呼叫在後會清掉設定)。"""
    key = id(wid)
    _WID_SLOTS.setdefault(key, set()).add(slot)
    skey = (key, slot)
    gen = _GEN.get(skey, 0) + 1
    _GEN[skey] = gen
    a = _ANIM_CLASS()
    try:
        a.init()
    except Exception:
        pass
    a.set_var(wid)
    a.set_values(start_v, end_v)
    a.set_duration(time_ms)
    a.set_delay(delay_ms)
    _set_ease(a)
    return a, skey, gen


def _guard(skey, gen):
    """exec cb 開頭呼叫:世代不符 → 舊動畫直接放棄。"""
    return _GEN.get(skey, -1) == gen


def cancel(wid=None):
    """取消動畫:指定 widget 上的(或全部)。binding 有 anim_delete/anim_del 就刪,
    沒有也無妨(世代守衛會讓舊動畫自行失效)。"""
    for fn_name in ("anim_delete", "anim_del"):
        fn = getattr(lv, fn_name, None)
        if fn is None:
            continue
        try:
            fn(wid, None)
            return
        except Exception:
            pass
        try:
            fn(wid)
            return
        except Exception:
            pass
    if wid is None:
        for fn_name in ("anim_delete_all", "anim_del_all"):
            try:
                fn2 = getattr(lv, fn_name, None)
                if fn2 is not None:
                    fn2()
                return
            except Exception:
                continue
    if wid is not None:
        for slot in _WID_SLOTS.get(id(wid), ()):
            sk = (id(wid), slot)
            _GEN[sk] = _GEN.get(sk, 0) + 1


def pulse(wid, period_ms=1500, min_opa=110, max_opa=255):
    """呼吸閃爍:opa 在 min/max 間往返,永續播放。CSS 'pulse' 對應。"""
    if _ANIM_CLASS is None:
        wid.set_style_opa(max_opa, 0)
        return None
    half = max(80, period_ms // 2)
    a = _ANIM_CLASS()
    a.set_var(wid)
    a.set_values(max_opa, min_opa)
    a.set_duration(half)
    a.set_reverse_duration(half)
    a.set_repeat_count(_REPEAT_INF)
    a.set_custom_exec_cb(lambda _a, v: wid.set_style_opa(int(v), 0))
    _set_ease(a)
    return _anim_start(a)


def fade_in(wid, dy=6, time_ms=300, delay_ms=0):
    """載入淡入 + 向上位移。CSS 'rise'/'fade-in' 對應。"""
    x, y = wid.get_x(), wid.get_y()
    if _ANIM_CLASS is None:
        wid.set_pos(x, y)
        wid.set_style_opa(255, 0)
        return None
    a, key, gen = _new_anim(wid, "fy", y + dy, y, time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and wid.set_pos(x, int(v)))
    _anim_start(a)

    b, key2, gen2 = _new_anim(wid, "opa", 0, 255, time_ms, delay_ms)
    b.set_custom_exec_cb(
        lambda _a, v, k=key2, g=gen2: _guard(k, g) and wid.set_style_opa(int(v), 0))
    _anim_start(b)
    return (a, b)


def bar_grow(bar, from_val=0, to_val=None, time_ms=400):
    """進度/數值成長動畫。CSS 'bar-grow' 對應。"""
    to_val = to_val if to_val is not None else bar.get_value()
    if _ANIM_CLASS is None:
        bar.set_value(to_val, 0)
        return None
    a, key, gen = _new_anim(bar, "value", from_val, to_val, time_ms, 0)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and bar.set_value(int(v), 0))
    return _anim_start(a)


def anim_pos(wid, x, y, time_ms=280, delay_ms=0):
    """平滑位移到 (x, y)。CSS 輪播 track/card 滑動對應。"""
    sx, sy = wid.get_x(), wid.get_y()
    if _ANIM_CLASS is None:
        wid.set_pos(x, y)
        return None
    a, key, gen = _new_anim(wid, "px", sx, x, time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and wid.set_pos(int(v), wid.get_y()))
    _anim_start(a)

    b, key2, gen2 = _new_anim(wid, "py", sy, y, time_ms, delay_ms)
    b.set_custom_exec_cb(
        lambda _a, v, k=key2, g=gen2: _guard(k, g) and wid.set_pos(wid.get_x(), int(v)))
    _anim_start(b)
    return (a, b)


def opa_to(wid, opa, time_ms=280, delay_ms=0, from_opa=None):
    """透明度過渡。from_opa=None 時從目前值開始(進場用 from_opa=0)。"""
    if _ANIM_CLASS is None:
        wid.set_style_opa(opa, 0)
        return None
    if from_opa is None:
        try:
            from_opa = wid.get_style_opa(0)
        except Exception:
            from_opa = 255
    a, key, gen = _new_anim(wid, "opa", from_opa, opa, time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and wid.set_style_opa(int(v), 0))
    return _anim_start(a)


def scale_to(wid, pct, time_ms=280, delay_ms=0):
    """transform_scale 過渡(pct: 100 = 100%;LVGL 內部 256 = 100%)。
    pivot 需由呼叫端先設(set_style_transform_pivot_x/y)。
    binding 沒有 scale API 時自動略過(不影響功能)。"""
    setter = getattr(wid, "set_style_transform_scale", None)
    if setter is None or _ANIM_CLASS is None:
        if setter is not None:
            setter(int(pct * 2.56), 0)
        return None
    try:
        cur = wid.get_style_transform_scale(0)
    except Exception:
        cur = 256
    a, key, gen = _new_anim(wid, "scale", cur, int(pct * 2.56), time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and setter(int(v), 0))
    return _anim_start(a)


def num_style_to(wid, setter, target, time_ms=180, delay_ms=0, cur=None,
                 slot="num"):
    """通用單值樣式動畫。setter 收 int(例如 lambda v: wid.set_style_outline_width(v, 0))。
    cur=None 時試讀 getter(呼叫端可用 kwarg cur 指定已知起點)。"""
    if _ANIM_CLASS is None:
        setter(target)
        return None
    if cur is None:
        cur = target   # 讀不到就從終點開始(等於直接設定)
    a, key, gen = _new_anim(wid, slot, cur, target, time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and setter(int(v)))
    return _anim_start(a)


def border_width_to(wid, width, time_ms=260, delay_ms=0):
    """邊框寬度過渡(例如輪播卡片 1↔2px)。"""
    if _ANIM_CLASS is None:
        wid.set_style_border_width(width, 0)
        return None
    try:
        cur = wid.get_style_border_width(0)
    except Exception:
        cur = 0
    a, key, gen = _new_anim(wid, "bw", cur, width, time_ms, delay_ms)
    a.set_custom_exec_cb(
        lambda _a, v, k=key, g=gen: _guard(k, g) and wid.set_style_border_width(int(v), 0))
    return _anim_start(a)


def color_anim(wid, setter, from_hex, to_hex, time_ms=260, delay_ms=0):
    """樣式顏色漸變。setter 收 lv color(例如 lambda c: wid.set_style_bg_color(c, 0))。
    from_hex/to_hex: 0xRRGGBB。CSS 選中/焦點換色對應。"""
    if _ANIM_CLASS is None:
        setter(lv.color_hex(to_hex))
        return None
    fr = [(from_hex >> 16) & 0xFF, (from_hex >> 8) & 0xFF, from_hex & 0xFF]
    tr = [(to_hex >> 16) & 0xFF, (to_hex >> 8) & 0xFF, to_hex & 0xFF]
    a, key, gen = _new_anim(wid, "color", 0, 1000, time_ms, delay_ms)

    def cb(_a, v):
        if not _guard(key, gen):
            return
        k = v / 1000.0
        try:
            setter(lv.color_make(int(fr[0] + (tr[0] - fr[0]) * k),
                                 int(fr[1] + (tr[1] - fr[1]) * k),
                                 int(fr[2] + (tr[2] - fr[2]) * k)))
        except Exception:
            pass
    a.set_custom_exec_cb(cb)
    return _anim_start(a)


def set_state_colors(wid, on, color_on, color_off, part=0):
    """依狀態切換文字/元件顏色。CSS ':hover/:active/:focus' 換色對應。
    on=True → color_on(例如焦點 PRIMARY),False → color_off。"""
    wid.set_style_text_color(
        lv.color_hex(color_on if on else color_off), part)
