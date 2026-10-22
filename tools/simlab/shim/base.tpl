# SimLab base shim — 中間緩存模擬器 + 注入 + perf 儀表
# (由 simlab/server.py 依項目參數渲染;跑在 wasm MicroPython+LVGL 內)
#
# 核心:模擬 bus.shared 緩存層(不是實體按鈕):
#   lib.sys_bus    mock — bus.shared 是真 dict(None-safe)
#   lib.hw_manager mock — 真 consume_input 語義(enc 讀取即清 / pin_edge 讀取即清)
#   inject_enc/inject_edge — 模擬 HwSampleTask 累加寫入(不覆寫未消費 delta)
#   _echo_tick     — executor 0x1502 回音模擬(_display_cmd → _display_*)
#   _tick          — LVGL 渲染 + [perf] 儀表(render_us 印到 REPL)
import sys as _sys

_W = $W
_H = $H
_PROJ = "$PROJ"
_PROJ_URL = "$PROJ_URL"
_WSP = "/_wsp/" + _PROJ

try:
    import uos as _os
except Exception:
    try:
        import os as _os
    except Exception:
        _os = None


def _mkdirs(p):
    if not p or not _os:
        return
    parts = []
    for seg in p.split("/"):
        if not seg:
            continue
        parts.append(seg)
        d = "/" + "/".join(parts)
        try:
            _os.mkdir(d)
        except Exception:
            pass


# JS 已把項目 .py 預載到 /_wsp/{proj}(含 src/page)+ 寫 .preloaded
for _p in (_WSP, _WSP + "/src", _WSP + "/page", "/sim/lib", "/sim/driver/js"):
    _mkdirs(_p)
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


def _safe_import(name):
    try:
        return __import__(name, None, None, ["*"])
    except Exception as e:
        print("[simlab] import {} fail: {}".format(name, e))
        return None


# ---- 1) lib.sys_bus mock(bus.shared 是真 dict,None-safe) ----
class _BusAdapter:
    """記錄式 bus adapter:統計髒區(供日後 flush 級統計)。"""

    def __init__(self):
        self._win = None
        self._pending = b""
        self.stats = {"rects": 0, "bytes": 0}

    def write_cmd_data(self, cmd, data):
        pass

    def set_window(self, x1, y1, x2, y2):
        self._win = (x1, y1, x2, y2)

    def write_data_async(self, data):
        self._pending = bytes(data)

    def flush(self):
        if self._win:
            x1, y1, x2, y2 = self._win
            self.stats["rects"] += 1
            self.stats["bytes"] += (x2 - x1 + 1) * (y2 - y1 + 1) * 2


class _StubLcd:
    def __init__(self):
        self._bus = _BusAdapter()
        self.width = _W
        self.height = _H
        self.rotation = 0


class _Shared(dict):
    def __missing__(self, k):
        return None


class _WebBus:
    def __init__(self):
        self._services = {"lcd": _StubLcd()}
        self.shared = _Shared()
        self.slave_id = 1

    def get_service(self, n):
        return self._services.get(n)

    def register_service(self, n, s):
        self._services[n] = s

    def has_lcd(self):
        return "lcd" in self._services


_bus = _WebBus()
_sys.modules["lib"] = type("_lib", (), {})()
_sys.modules["lib.sys_bus"] = type("_sys_bus", (), {"bus": _bus})()


# ---- 2) lib.hw_manager mock:真 consume_input 語義(對齊 hw_manager.py:324-347) ----
def _hw_snap():
    snap = _bus.shared.get("_hw_inputs")
    if snap is None:
        snap = {"enc": [0], "pin": {}, "pin_edge": {}, "pin_stable": {},
                "_pin_state": {}, "_enc_last": []}
        _bus.shared["_hw_inputs"] = snap
    return snap


def sample_inputs():
    return _hw_snap()


def get_input(kind, key=None, idx=None):
    return 0


def consume_input(kind, key=None, idx=None):
    """對齊真碼:enc 累加 delta 讀取即清;pin 去抖按壓邊緣讀取即清(按住不重複)。"""
    snap = _bus.shared.get("_hw_inputs")
    if snap is None:
        return 0
    if kind == "enc":
        lst = snap.get("enc", [])
        if idx is not None and 0 <= idx < len(lst):
            v = lst[idx]
            lst[idx] = 0
            return v
        return 0
    if kind == "pin":
        edges = snap.get("pin_edge", {})
        v = edges.get(key, 0)
        if v:
            edges[key] = 0
        return v
    return get_input(kind, key=key, idx=idx)


# 注入 API(模擬 HwSampleTask:累加語義,絕不覆寫未消費 delta)
def inject_enc(delta):
    snap = _hw_snap()
    snap["enc"][0] = snap["enc"][0] + int(delta)


def inject_edge(label):
    snap = _hw_snap()
    snap["pin_edge"][label] = snap["pin_edge"].get(label, 0) + 1
    snap["pin"][label] = 0  # active-low 按下


def inject_release(label):
    snap = _hw_snap()
    snap["pin"][label] = 1


def inject_reset():
    _bus.shared["_hw_inputs"] = {"enc": [0], "pin": {}, "pin_edge": {},
                                 "pin_stable": {}, "_pin_state": {}, "_enc_last": []}


_sys.modules["lib.hw_manager"] = type("_hm", (), {
    "sample_inputs": sample_inputs,
    "consume_input": consume_input,
    "get_input": get_input,
    "HW": None,
})()


# ---- 3) seed + echo 模擬(executor 0x1502 回音) ----
_bus.shared.setdefault("System", {"name": "SimLab", "version": "sim"})
_bus.shared.setdefault("Network", {"wifi": {}})
_bus.shared.setdefault("_pca_devices", [])
_bus.shared.setdefault("pca9685", {})

_pending_cmd = None
_echo_cnt = 0


def _echo_tick():
    """每幀呼叫:watch _display_cmd → 2 幀後寫 echo;display_time 節流遞增。"""
    global _pending_cmd, _echo_cnt
    cmd = _bus.shared.get("_display_cmd")
    if cmd is not None:
        _pending_cmd = cmd
        _bus.shared["_display_cmd"] = None  # consume(對齊 ControlPanelTask 語義)
        print("[echo] cmd:", cmd)
    if _pending_cmd is not None and _echo_cnt % 2 == 0:
        if "mode" in _pending_cmd:
            _bus.shared["_display_mode"] = _pending_cmd["mode"]
        if "brightness" in _pending_cmd:
            _bus.shared["_display_brightness"] = _pending_cmd["brightness"]
        print("[echo] wrote mode={} brightness={}".format(
            _bus.shared.get("_display_mode"), _bus.shared.get("_display_brightness")))
        _pending_cmd = None
    _echo_cnt += 1
    if _echo_cnt % $ECHO_DIV == 0:
        t = int(_bus.shared.get("_display_time", 0) or 0)
        _bus.shared["_display_time"] = t + 1


# ---- 4) LVGL display(SDL 畫到 canvas)+ perf 儀表 ----
import time as _time
import lvgl as _lv

# REPL 友好別名:模擬器內直接打 bus.shared / lv.xxx / inject_* / __step()
bus = _bus
lv = _lv

# LVGL 9.0 vs 9.3 相容:js port 的 time 模組無 time()(device MP 有)→ 補上
if not hasattr(_time, "time"):
    try:
        _time.time = lambda: _time.ticks_ms() // 1000
    except Exception:
        pass
if not hasattr(_time, "time"):
    # setattr 被拒(builtin 模組)→ 包裝模組替換 sys.modules["time"]
    try:
        _wt = type("_wt", (), {})
        for _k in dir(_time):
            if not _k.startswith("__"):
                try:
                    setattr(_wt, _k, getattr(_time, _k))
                except Exception:
                    pass
        _wt.time = lambda: _time.ticks_ms() // 1000
        _sys.modules["time"] = _wt
    except Exception:
        pass
print("[simlab] time.time available:", hasattr(_time, "time") or "time" in dir(_sys.modules.get("time", None) or ()))

if not _lv.is_initialized():
    _lv.init()
_disp = None
try:
    _disp = _lv.display_create(_W, _H)
    _buf = bytearray(_W * 40 * 2)
    _disp.set_buffers(_buf, None, len(_buf), 0)

    # SimLab 9.3:SDL2.js WebGL 渲染在瀏覽器與 asyncify 衝突 → JS 橋渲染:
    # flush_cb 把 RGB565 像素送 simlab_canvas.putPixels → iframe canvas → 鏡像直播
    try:
        import simlab_canvas
    except Exception:
        simlab_canvas = None

    def _fb(drv, area, cp):
        try:
            w = area.x2 - area.x1 + 1
            h = area.y2 - area.y1 + 1
            size = w * h * 2
            data = cp.__dereference__(size)
            if simlab_canvas is not None:
                simlab_canvas.putPixels(area.x1, area.y1, w, h, data)
            drv.flush_ready()
        except Exception:
            try:
                drv.flush_ready()
            except Exception:
                pass

    _disp.set_flush_cb(_fb)
    print("[simlab] display: canvas {}x{} (js bridge)".format(_W, _H))
except Exception as _e:
    print("[simlab] canvas display fail:", _e)

_tick_last = _time.ticks_ms()
_perf_n = 0
_perf_last = _time.ticks_ms()


def _tick():
    """一幀:LVGL tick(量測真實間隔)+ task_handler + 強制渲染;量渲染成本。"""
    global _tick_last, _perf_n, _perf_last
    now = _time.ticks_ms()
    diff = _time.ticks_diff(now, _tick_last)
    _tick_last = now
    if diff > 0:
        _lv.tick_inc(diff)
    _tu = getattr(_time, "ticks_us", None)
    _t0 = _tu() if _tu else 0
    _lv.task_handler()
    if _disp is not None:
        try:
            _lv.refr_now(_disp)
        except Exception:
            pass
    _t1 = _tu() if _tu else 0
    _perf_n += 1
    # 連續步進(30Hz)時限流輸出(≥150ms 才印),避免 REPL 被 [perf] 淹沒
    if _tu and _time.ticks_diff(_time.ticks_ms(), _perf_last) >= 150:
        _perf_last = _time.ticks_ms()
        print("[perf] r={} n={}".format(_t1 - _t0, _perf_n))


def _take():
    return []


def _show(*a):
    pass
