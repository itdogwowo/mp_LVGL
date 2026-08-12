# ---- entry: framework(mp_Net-Core slave 型:registry/app/launcher/nav + page/) ----
#
# 用真碼:board._make_snapshot_inputs(純緩存讀取,零硬體)+ app.py 全流程;
# 只補 page/__init__.py 的 PAGES["mod"] 註冊(wasm importer 無法載入點號 package)。

# 虛擬 package:ui.lvgl → 根模組;ui.lvgl.page → page 模組(平級名稱)
class _V:
    __name__ = ""
    __path__ = []
    __package__ = ""

    def __init__(self, name, aliases=None, prefixes=None):
        self.__name__ = name
        self.__path__ = ["<shim:/{}>".format(name)]
        self.__package__ = name
        self._aliases = aliases or {}
        self._prefixes = prefixes or []
        self._cache = {}

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        if attr in self._cache:
            return self._cache[attr]
        real = self._aliases.get(attr)
        if isinstance(real, str):
            try:
                real = __import__(real, None, None, ["*"])
            except Exception:
                real = None
        if real is None:
            for prefix in list(self._prefixes) + [""]:
                cand = (prefix + "." + attr) if prefix else attr
                try:
                    real = __import__(cand, None, None, ["*"])
                    break
                except Exception:
                    real = None
        if real is None:
            raise AttributeError("no attr '{}' in pkg {}".format(attr, self.__name__))
        self._cache[attr] = real
        return real


def _install(dotted, leaf=None):
    parts = dotted.split(".")
    parent = None
    built = []
    for i, seg in enumerate(parts):
        built.append(seg)
        full = ".".join(built)
        is_leaf = (i == len(parts) - 1)
        if is_leaf and isinstance(leaf, _V):
            pkg = leaf
        elif is_leaf and isinstance(leaf, dict):
            pkg = _V(full, aliases=leaf)
        elif is_leaf and isinstance(leaf, (list, tuple)):
            pkg = _V(full, prefixes=list(leaf))
        else:
            if full in _sys.modules and not isinstance(_sys.modules.get(full), _V):
                parent = _sys.modules[full]
                continue
            pkg = _V(full)
        _sys.modules[full] = pkg
        if isinstance(parent, _V):
            parent._cache[seg] = pkg
        parent = pkg
    return parent


_MODULES = $MODULES
_install("ui", ["", "src", "page", "lvgl"])
_install("ui.lvgl", ["", "src", "page"])
_install("ui.lvgl.page", _MODULES)

# 依序載入根模組(registry → ui_common → nav → launcher → app)並預裝到 ui.lvgl.*
for _mn in _MODULES:
    _m = _safe_import(_mn)
    if _m is not None:
        try:
            _sys.modules["ui.lvgl." + _mn] = _m
        except Exception:
            pass

# 頁面:載入(觸發 @register)+ 補 PAGES["mod"](複刻 page/__init__.py 語義)
_reg_mod = _safe_import("registry")
for _pn in $PAGE_MODULES:
    _m = _safe_import(_pn)
    if _m is not None:
        try:
            _sys.modules["ui.lvgl.page." + _pn] = _m
        except Exception:
            pass
        if _reg_mod is not None and _pn in getattr(_reg_mod, "PAGES", {}):
            _reg_mod.PAGES[_pn]["mod"] = _m

# ---- 輸入:真碼 board._make_snapshot_inputs(消費 lib.hw_manager 快照) ----
import board as _board

_enc, _conf, _ex = _board._make_snapshot_inputs(consume_input)

# ---- app 啟動(對齊 board._setup 的順序,但用我們的 platform) ----
import app as _app
import ui_common as _uic


class _Plat:
    W = _W
    H = _H


_uic.init(_Plat)
_uic.init_fonts()
_app.build_all()
_app.init({
    "tick": _tick,
    "take": _take,
    "show": _show,
    "enc_delta": _enc,
    "confirm": _conf,
    "exit": _ex,
})
_app.go("launcher")

_step_n = 0


def __step():
    """單幀:真碼 app.step() + echo 模擬。前端的 sim-input 注入後呼叫。"""
    global _step_n
    _app.step()
    _echo_tick()
    _step_n += 1


def __go(name):
    _app.go(name)


print("[simlab] framework started (project=$PROJ)")
__step()
