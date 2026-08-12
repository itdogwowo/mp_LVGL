# ---- entry: mp_lvgl(mp_LVGL 參考 UI:lvgl_shared mock + 複刻 lvgl_ui_app 迴圈) ----
#
# mp_LVGL 的頁面是平級模組(無 registry/app 框架);lvgl_ui_app.py 是 import 即
# 死迴圈的腳本,不能直接 import → 這裡 mock lvgl_shared(FrameBuffer/Inputs)+
# 複刻其主迴圈單幀契約(讀輸入 → on_enc/on_confirm/on_exit → update → 渲染)。

# mock lvgl_shared(真機版 import machine/lcd_bus,這裡對接平台)
class _FB:
    def __init__(self, *a, **k):
        pass

    def setup(self):
        pass

    def tick(self):
        _tick()

    def take(self):
        return []

    def show_rect(self, x1, y1, x2, y2, data):
        pass

    def show_all(self):
        pass

    def flush_done(self):
        pass


class _Inp:
    def __init__(self, *a, **k):
        pass

    def enc_delta(self):
        return consume_input("enc", idx=0) or 0

    def confirm_pressed(self):
        return consume_input("pin", key="encC") != 0

    def exit_pressed(self):
        return consume_input("pin", key="btn") != 0


_sys.modules["lvgl_shared"] = type("_ls", (), {
    "FrameBuffer": _FB, "Inputs": _Inp,
    "WIDTH": _W, "HEIGHT": _H,
})()

# 頁面模組(真碼;id = 模組名去掉 lvgl_page_ 前綴,對齊 lvgl_ui_app.PAGES)

# ---- LVGL 9.0 vs 9.3 相容:mp_LVGL 代碼用 9.3 的 anim API(如 set_reverse_duration) ----
# 包一層 try/except,AttributeError 時降級(動畫變直接設定;對齊 runtime 後自動 no-op)。
_fx = _safe_import("lv_ui_fx")
if _fx is not None:
    for _fn in ("pulse", "fade_in", "bar_grow", "set_state_colors"):
        _orig = getattr(_fx, _fn, None)
        if _orig is None:
            continue

        def _wrap(*a, _o=_orig, **k):
            try:
                return _o(*a, **k)
            except AttributeError:
                return None
        try:
            setattr(_fx, _fn, _wrap)
        except Exception:
            pass

import lvgl_ui_common as _uic

_uic.init_fonts()

_mods = {}
for _mn in $MODULES:
    _m = _safe_import(_mn)
    if _m is None:
        continue
    _pid = _mn.replace("lvgl_page_", "", 1)
    try:
        _m.build()
        _mods[_pid] = _m
    except Exception as _e:
        import sys as _s2
        try:
            _s2.print_exception(_e)
        except Exception:
            pass
        print("[simlab] build {} fail: {}".format(_pid, _e))

_cur = "launcher"
_lv.screen_load(_mods["launcher"].scr)

# 過場動畫常量(對齊 lvgl_ui_app;binding 差異防護)
_ANIM = getattr(_lv, "SCREEN_LOAD_ANIM", None)
_ANIM_OVER_LEFT = getattr(_ANIM, "OVER_LEFT", 1)
_ANIM_OVER_RIGHT = getattr(_ANIM, "OVER_RIGHT", 2)


def __go(name, back=False):
    global _cur
    if name == _cur or name not in _mods:
        return
    try:
        _mods[_cur].on_leave()
    except Exception:
        pass
    _scr = _mods[name].scr
    try:
        _lv.screen_load_anim(_scr, _ANIM_OVER_LEFT if back else _ANIM_OVER_RIGHT,
                             240, 0, False)
    except Exception:
        try:
            _lv.screen_load(_scr)
        except Exception:
            pass
    try:
        _mods[name].on_enter()
    except Exception:
        pass
    _cur = name
    print("[nav] ->", name)


_run = 0


def __step():
    """複刻 lvgl_ui_app 主迴圈單幀。"""
    global _run
    d = consume_input("enc", idx=0) or 0
    c = consume_input("pin", key="encC") != 0
    ex = consume_input("pin", key="btn") != 0
    m = _mods[_cur]

    if d != 0:
        try:
            m.on_enc(d)
        except Exception:
            pass
    if c:
        try:
            tgt = m.on_confirm()
        except Exception:
            tgt = None
        if tgt:
            __go(tgt)
    if ex and _cur != "launcher":
        try:
            consumed = m.on_exit()
        except Exception:
            consumed = False
        if not consumed:
            __go("launcher", back=True)

    try:
        m.update(_run)
    except Exception:
        pass
    _run += 1

    _tick()
    _echo_tick()


print("[simlab] mp_lvgl started (project=$PROJ)")
__step()
