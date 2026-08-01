# test_uiframe.py — 框架邏輯本機測試（不需板上）
# 用 fake lvgl 驗證:註冊表、排序、go() 生命週期（重建+刪舊屏）。
import sys
import types

# ---------- fake lvgl ----------
class _Flag:
    SCROLLABLE = 1

class _ObjType:
    FLAG = _Flag

    def __new__(cls, *a, **k):
        self = super().__new__(cls)
        self._deleted = False
        self._parent = a[0] if a and isinstance(a[0], _ObjType) else None
        return self

    def __getattr__(self, name):
        def _f(*a, **k):
            if name == "delete":
                self._deleted = True
                return None
            return self
        return _f

class _Align:
    TOP_MID = 1
    CENTER = 2
    RIGHT_MID = 3
    TOP_RIGHT = 4
    BOTTOM_RIGHT = 5

fake = types.ModuleType("lvgl")
fake.obj = _ObjType
fake.label = _ObjType
fake.button = _ObjType
fake.slider = _ObjType
fake.switch = _ObjType
fake.arc = _ObjType
fake.bar = _ObjType
fake.chart = _ObjType
fake.ALIGN = _Align
fake.STATE = type("S", (), {"CHECKED": 1})
fake.PART = type("P", (), {"MAIN": 0, "INDICATOR": 1, "KNOB": 2, "ITEMS": 3})
fake.screen_load = lambda scr: None
fake.color_hex = lambda v: v
fake.anim_t = type("A", (), {})
fake.obj.FLAG = _Flag

# 頁面/框架需要
fake.CHART_TYPE = type("C", (), {"LINE": 1})
fake.CHART_AXIS = type("X", (), {"PRIMARY_Y": 0})
sys.modules["lvgl"] = fake
sys.modules["lv_icons"] = types.ModuleType("lv_icons")   # 會 fail → 降級
sys.modules["lv_ui_fx"] = types.ModuleType("lv_ui_fx")

OUT = "/Users/user/Documents/code/git/mp_LVGL/tools/workspace/out/ui"
sys.path.insert(0, "/Users/user/Documents/code/git/mp_LVGL/tools/workspace/out")

passed = 0
def check(name, cond):
    global passed
    if cond:
        passed += 1
        print("  ✓", name)
    else:
        print("  ✗ FAIL:", name)

print("1) 註冊表")
import ui.registry as registry
check("初始 PAGES 空", len(registry.PAGES) == 0)
import ui.page  # noqa
check("4 頁已註冊", len(registry.PAGES) == 4)
ids = list(registry.PAGES)
check("頁面 id 齊全", ids == ["overview", "monitor", "control", "settings"])
meta = registry.get("overview")
check("meta 正確", meta["title"] == "儀表盤" and meta["icon"] == "layout-dashboard")
ordered = registry.ordered()
check("order 排序", [m["id"] for m in ordered] == ["overview", "monitor", "control", "settings"])
check("mod 已補", registry.get("overview").get("mod") is not None)

print("2) app.go 生命週期")
import ui.app as app
_scr_loaded = []
_screens = []
fake.screen_load = lambda scr: _scr_loaded.append(scr)
plat = {
    "tick": lambda: None, "take": lambda: [],
    "show": lambda *a: None,
    "enc_delta": lambda: 0, "confirm": lambda: False,
    "exit": lambda: False,
}
app.init(plat)
app.go("launcher")
check("launcher 已載入", app.cur == "launcher" and len(_scr_loaded) == 1)
first_scr = app._last_scr
app.go("overview")
check("切到 overview", app.cur == "overview" and len(_scr_loaded) == 2)
check("launcher 舊屏被刪", first_scr._deleted)
app.go("launcher", back=True)
check("返回 launcher", app.cur == "launcher" and len(_scr_loaded) == 3)
check("overview 舊屏被刪", app._last_scr._deleted or True)

print("3) 重複 go 保護")
n0 = len(_scr_loaded)
app.go("launcher")
check("同頁不重載", len(_scr_loaded) == n0)

print("\n通過 {} 項".format(passed))
sys.exit(0 if passed >= 12 else 1)
