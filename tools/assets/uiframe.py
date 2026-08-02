# uiframe.py — 動態註冊式 UI 框架產生器
#
# 產生到 out/ui/ 的完整框架（輸出在工具工作區,測試後才部署板上）:
#   ui/registry.py      @register 註冊表（性能優先:集中 import,運行時零成本）
#   ui/app.py           主程式（go() 每次重建 screen + 刪舊屏 → 修 heap 累積 reboot）
#   ui/launcher.py      動態主頁面（讀 registry 產生卡片,不硬編碼）
#   ui/ui_common.py     共用層（從 mp_LVGL/lvgl_ui_common.py 遷移）
#   ui/page/xxx.py      各功能頁（從 lvgl_page_xxx.py 遷移 + @register）
#
# 架構（板上/模擬器共用）:
#   UI 層 = ui/page/* + ui/launcher（純 lv API,不碰硬體）
#   平台層 = ui/app 的 platform 物件（板上 FrameBuffer / 之後模擬器 stub）
from __future__ import annotations

import re
from pathlib import Path

from . import OUT_DIR

# 現有頁面檔（在 mp_LVGL 根目錄,工具宿主專案 = tools/.. 的上一層）
# 轉換規則:import lvgl_ui_common → ui.ui_common;build 前插 @register
_PAGE_SRC = [
    ("overview", "lvgl_page_overview.py"),
    ("monitor", "lvgl_page_monitor.py"),
    ("control", "lvgl_page_control.py"),
    ("settings", "lvgl_page_settings.py"),
]

# 從現有 launcher CARDS 抽 meta:(title, desc, accent, id, num, icon)
_CARDS_RE = re.compile(
    r'\(\s*"([^"]+)",\s*"([^"]+)",\s*(0x[0-9A-Fa-f]+),\s*"([a-z]+)",\s*"(\d+)",\s*"([a-z0-9-]+)"\s*\)'
)

REGISTRY_PY = '''# ui/registry.py — 動態註冊表（框架核心）
#
# 頁面「自己註冊」:在 build() 前加一行裝飾器即可,
#   ui/page/__init__.py 的集中 import 保證每頁都被載入註冊。
# 性能:註冊只在 import 時執行一次,運行時零成本(不掃描目錄)。
PAGES = {}


def register(id, title, icon="", desc="", order=0, accent=0x1A73E8, status=""):
    """頁面註冊裝飾器。裝飾 build(),meta 存進 PAGES。"""
    def deco(fn):
        PAGES[id] = {
            "id": id, "title": title, "icon": icon, "desc": desc,
            "order": order, "accent": accent, "status": status,
            "build": fn,
        }
        return fn
    return deco


def ordered():
    """依 order 排序的頁面 meta 清單(launcher 用)。"""
    return [PAGES[k] for k in sorted(PAGES, key=lambda k: PAGES[k]["order"])]


def get(page_id):
    return PAGES.get(page_id)
'''

APP_PY = '''# ui/app.py — 動態註冊式 UI 主程式
#
# 生命週期(修掉「進出頁面幾次就 reboot」的 heap 累積):
#   go(name): on_leave 舊頁 → 全新 build 新頁 screen → screen_load →
#             刪除舊 screen(釋放全部子物件) → on_enter 新頁
# 每次進入都重建,不沿用舊實例 → 記憶體乾淨。
#
# 平台解耦:所有硬體透過 platform 物件注入,本檔不 import 任何硬體。
#   板上: ui/board.py 用 slave new bus 組 platform
#   模擬器: 直接 import app(平級) 或 ui.app(package) 皆可(見下方相容 import)
import lvgl as lv
try:
    import ui.registry as registry
    import ui.launcher as launcher
except ImportError:
    # 模擬器 wasm importer 不支援 package 目錄 → 平級 import
    import registry
    import launcher

platform = None      # {tick, take, show, enc_delta, confirm, exit}
cur = None
_last_scr = None
_run = 0


def init(plat):
    """注入 platform 物件 + 載入所有頁面(集中 import 已註冊)。"""
    global platform
    platform = plat
    # 頁面由外部註冊(板上 = ui/page/__init__;模擬器 = 啟動碼平級 import)
    # 這裡不強制 import,避免模擬器(無 package)與板上行為差異
    pass


def _page():
    """目前頁面模組(launcher 或註冊頁面),沒有就回 launcher。"""
    if cur == "launcher":
        return launcher
    meta = registry.get(cur)
    if meta is not None:
        return meta.get("mod")
    return launcher


def go(name, back=False):
    """切換頁面。每次重建 screen + 刪舊屏,避免 heap 累積。"""
    global cur, _last_scr
    if name == cur:
        return
    if name != "launcher" and name not in registry.PAGES:
        return

    # 1. 離開舊頁(清編輯狀態等)
    old = _page()
    if hasattr(old, "on_leave"):
        old.on_leave()

    # 2. 全新 build 新頁(不沿用舊實例)
    if name == "launcher":
        scr = launcher.build()
    else:
        scr = registry.get(name)["build"]()

    # 3. 載入
    try:
        lv.screen_load(scr)
    except Exception:
        pass

    # 4. 刪舊屏(新屏已活動,舊屏連子物件全部釋放 → 修 reboot)
    if _last_scr is not None:
        try:
            _last_scr.delete()
        except Exception:
            pass
    _last_scr = scr

    cur = name
    print("[nav] ->", name)
    new = _page()
    if hasattr(new, "on_enter"):
        new.on_enter()


def run():
    """主迴圈(啟動後不返回)。板上用。"""
    while True:
        step()
        _sleep(5)


def _sleep(ms):
    try:
        import time
        time.sleep_ms(ms)
    except Exception:
        pass


def step():
    """單幀處理(模擬器事件驅動用)。回傳 1 表示處理了一幀。"""
    global _run
    d = platform["enc_delta"]()
    c = platform["confirm"]()
    ex = platform["exit"]()
    m = _page()

    if d != 0 and hasattr(m, "on_enc"):
        m.on_enc(d)
    if c and hasattr(m, "on_confirm"):
        target = m.on_confirm()
        if target:
            go(target)
    if ex and cur != "launcher":
        go("launcher", back=True)

    if hasattr(m, "update"):
        m.update(_run)
    _run += 1

    platform["tick"]()
    for rect in platform["take"]():
        platform["show"](*rect)
    return 1
'''

LAUNCHER_PY = '''# ui/launcher.py — 動態主頁面（讀 registry 產生卡片,不硬編碼）
import lvgl as lv
try:
    from ui.registry import ordered
    from ui import ui_common as u
except ImportError:
    # 模擬器平級模式
    from registry import ordered
    import ui_common as u

scr = None
cards = []
_focus = 0

CARD_W = 160
CARD_H = 140
CX = (u.W - CARD_W) // 2
STRIDE = 176
FOCUS_Y = 48
IDLE_Y = 56


def build():
    global scr, cards
    scr = lv.obj(None)
    scr.set_style_bg_color(u.C(u.BG), 0)

    title = u.mk_label(scr, "選擇功能", 0, 8, u.TEXT, u.ZH)
    title.align(lv.ALIGN.TOP_MID, 0, 8)
    sub = u.mk_label(scr, "旋鈕 切換 · 按下 確認 · GPIO42 返回", 0, 28, u.TEXT3, u.ZH)
    sub.align(lv.ALIGN.TOP_MID, 0, 28)

    metas = ordered()
    cards = []
    for i, meta in enumerate(metas):
        c = lv.obj(scr)
        c.set_size(CARD_W, CARD_H)
        c.set_style_bg_color(u.C(u.SURFACE), 0)
        c.set_style_radius(12, 0)
        c.set_style_border_color(u.C(u.BORDER), 0)
        c.set_style_border_width(1, 0)
        c.set_style_pad_all(0, 0)
        c.remove_flag(lv.obj.FLAG.SCROLLABLE)

        blk = lv.obj(c)
        blk.set_size(40, 40)
        blk.set_pos(14, 16)
        blk.set_style_bg_color(u.C(meta["accent"]), 0)
        blk.set_style_radius(8, 0)
        blk.set_style_border_width(0, 0)
        blk.set_style_pad_all(0, 0)
        blk.remove_flag(lv.obj.FLAG.SCROLLABLE)
        ic = u.mk_icon(blk, meta["icon"], 0, 0, 0xFFFFFF)
        if ic is not None:
            ic.align(lv.ALIGN.CENTER, 0, 0)
        num = u.mk_label(c, "{:02d}".format(meta["order"]), 0, 0, u.TEXT3, u.F_NUM_S)
        num.align(lv.ALIGN.TOP_RIGHT, -8, 8)

        u.mk_label(c, meta["title"], 14, 68, u.TEXT, u.ZH)
        u.mk_label(c, meta["desc"], 14, 92, u.TEXT3, u.ZH)
        cards.append(c)

    n = len(cards)
    x0 = (u.W - (n * 8 + (n - 1) * 6)) // 2
    for i in range(n):
        d = lv.obj(scr)
        d.set_size(8, 8)
        d.set_pos(x0 + i * 14, 200)
        d.set_style_radius(4, 0)
        d.set_style_bg_color(u.C(0xDADCE0), 0)
        d.set_style_border_width(0, 0)

    _layout()
    return scr


def _layout():
    n = len(cards)
    for i, c in enumerate(cards):
        rel = ((i - _focus + n + n // 2) % n) - n // 2
        x = CX + rel * STRIDE
        foc = rel == 0
        c.set_pos(x, FOCUS_Y if foc else IDLE_Y)
        c.set_style_opa(255 if foc else 160, 0)
        c.set_style_border_color(u.C(u.PRIMARY if foc else u.BORDER), 0)
        c.set_style_border_width(2 if foc else 1, 0)


def on_enc(d):
    global _focus
    n = len(cards)
    if n == 0:
        return
    _focus = (_focus + d) % n
    _layout()


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
    pass
'''

PAGE_INIT_PY = '''# ui/page/__init__.py — 集中 import 所有頁面（保證全部註冊）
#
# 新增頁面流程:
#   1. 建立 ui/page/xxx.py,在 build() 前加 @register(id="xxx", ...)
#   2. 在下面的 import 與「補 mod」清單各加一行
# 動態 launcher 會自動出現該頁面,不需改其他檔。
#
# 集中 import 是為了性能:MPY 無法可靠跑 os.listdir 動態載入,
# 且凍結/複製時要有明確 import 才保證每頁都註冊。
# 「補 mod」是把頁面模組引用存進註冊表,app 才能呼叫 on_enc/on_confirm 等。
from ui import registry
from ui.page import overview, monitor, control, settings

registry.PAGES["overview"]["mod"] = overview
registry.PAGES["monitor"]["mod"] = monitor
registry.PAGES["control"]["mod"] = control
registry.PAGES["settings"]["mod"] = settings
'''

# 模擬器平級模式:ui/page/ 無法作為 package import,
# 改由啟動碼把 ui/page 目錄加進 sys.path,再 import page 模組。
PAGE_INIT_PY_FLAT = '''# ui/page/__init__.py（模擬器平級模式替身 — 未使用,見啟動碼）
'''

PAGE_BOARD_PY = '''# ui/board.py — 板上對接層（slave new bus 系統）
#
# ui/ 是 slave new 專案裡的一個 UI 區塊（像 tasks/lib）。
# 硬體全部透過 slave new 的 bus 系統取得,本檔不自建任何硬體:
#   顯示   bus.get_service("lcd")   （ST7789 + SpiBusAdapter,set_window/write_data_async）
#   編碼器 bus.shared["_enc_delta"] （control_panel 累加寫入）
#   按鈕   bus.shared["_vbtn1_event"]（VBTN 虛擬按鈕事件）
#
# 用法（slave new 環境,soft reboot 後）:
#   import ui.board
#   ui.board.run()
import sys
import lvgl as lv
from lib.sys_bus import bus
from ui import app

# 資源在 ui/src,加進 import 路徑（ui_common 的 from lv_icons/lv_ui_fx 由此找到）
_SRC = "/ui/src"
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_W = 320
_H = 240
_LINES = 40
_BPP = 2


class _Platform:
    """slave new bus 版平台:app 吃 {tick,take,show,enc_delta,confirm,exit}。"""

    def __init__(self):
        self.lcd = bus.get_service("lcd")
        if self.lcd is None:
            raise RuntimeError("lcd not on bus — 先跑 boot.py")
        self._bus = getattr(self.lcd, "_bus", None)
        self._dirty = []
        self._last_enc = 0

        # LVGL 初始化
        if lv.is_initialized():
            lv.deinit()
        lv.init()
        self._disp = lv.display_create(_W, _H)
        self._disp.set_color_format(18)  # RGB565
        buf = bytearray(_W * _LINES * _BPP)
        self._disp.set_buffers(buf, None, len(buf), 0)  # PARTIAL
        self._disp.set_flush_cb(self._flush_cb)

    # ---- LVGL flush:存髒區,由主迴圈 show ----
    def _flush_cb(self, disp_drv, area, color_p):
        w = area.x2 - area.x1 + 1
        h = area.y2 - area.y1 + 1
        data = color_p.__dereference__(w * h * _BPP)
        lv.draw_sw_rgb565_swap(data, w * h)
        self._dirty.append((area.x1, area.y1, area.x2, area.y2, bytes(data)))
        disp_drv.flush_ready()

    # ---- platform 介面 ----
    def tick(self):
        import time
        time.sleep_us(5000)
        lv.tick_inc(5)
        lv.task_handler()
        lv.refr_now(self._disp)

    def take(self):
        rects = self._dirty
        self._dirty = []
        return rects

    def show(self, x1, y1, x2, y2, data):
        self.lcd.set_window(x1, y1, x2, y2)
        self._bus.write_data_async(data)
        self._bus.flush()

    def enc_delta(self):
        v = int(bus.shared.get("_enc_delta", 0) or 0)
        d = v - self._last_enc
        self._last_enc = v
        return d

    def confirm(self):
        return bool(bus.shared.get("_vbtn1_event", 0) or 0)

    def exit(self):
        return False


def run():
    """建立 slave new 平台 + 啟動 UI 主迴圈。"""
    plat = _Platform()

    # 載入字體資源 + 註冊頁面（ui/src 已加進 sys.path）
    import ui_common
    ui_common.init_fonts()
    try:
        import ui.page  # noqa: F401  板上:集中註冊所有頁面
    except ImportError:
        pass

    app.init({
        "tick": plat.tick,
        "take": plat.take,
        "show": plat.show,
        "enc_delta": plat.enc_delta,
        "confirm": plat.confirm,
        "exit": plat.exit,
    })
    app.go("launcher")
    app.run()
'''

UI_INIT_PY = '''# ui/__init__.py — UI 區塊（slave new 專案內的一個區塊,像 tasks/lib）
#
# 純 LVGL UI 邏輯,不碰硬體;硬體透過注入的 platform 對接
#（板上 = ui.board 對 slave new bus;模擬器 = ui.sim_platform）。
'''

SIM_PLATFORM_PY = '''# ui/sim_platform.py — 模擬器平台（在瀏覽器模擬器跑真框架用,不碰 machine）
#
# 在 sim.lvgl.io 的 MicroPython 環境,SDL display_driver 已提供顯示,
# 本平台只提供「輸入模擬」給 ui/app:
#   輸入字元從前端按鈕送進 stdin（process_char）,
#   這裡讀 stdin 當作編碼器/按鈕事件。
#
# 使用（模擬器代碼區「ui 框架」模式）:
#   import ui.sim_platform as sp
#   sp.run(app)   # 注入 + 啟動主迴圈
import sys


class _SimPlatform:
    """模擬平台:SDL 顯示(display_driver 已建),輸入讀 stdin 字元。"""

    def __init__(self):
        self._enc = 0
        self._buf = b""

    def _poll(self):
        # 從 stdin 收字元(前端按鈕透過 process_char 送來)
        try:
            import select
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                self._buf += sys.stdin.read(1).encode()
        except Exception:
            pass
        return self._buf

    # ---- app 介面 ----
    def tick(self):
        lv.task_handler() if "lv" in globals() else None

    def take(self):
        return []

    def show(self, *a):
        pass

    def enc_delta(self):
        b = self._poll()
        d = 0
        while b:
            c = b[0:1]
            b = b[1:]
            if c in (b"l", b"L"):   # ← 左
                d -= 1
            elif c in (b"r", b"R"):  # → 右
                d += 1
        return d

    def confirm(self):
        return self._poll() == b"c"  # 確認

    def exit(self):
        return self._poll() == b"e"  # 返回


def run(app):
    """在模擬器跑真框架:注入模擬平台 + 啟動。"""
    sp = _SimPlatform()
    app.init({
        "tick": sp.tick,
        "take": sp.take,
        "show": sp.show,
        "enc_delta": sp.enc_delta,
        "confirm": sp.confirm,
        "exit": sp.exit,
    })
    app.run()
'''


def _extract_cards(project_root: Path) -> dict:
    """從現有 lvgl_page_launcher.py 的 CARDS 抽頁面 meta。"""
    src = (project_root / "lvgl_page_launcher.py").read_text(encoding="utf-8")
    meta = {}
    for m in _CARDS_RE.finditer(src):
        title, desc, accent, pid, num, icon = m.groups()
        meta[pid] = {
            "id": pid, "title": title, "desc": desc,
            "accent": int(accent, 16), "order": int(num), "icon": icon,
        }
    return meta


def _transform_page(src: str, meta: dict) -> str:
    """頁面轉換:import 雙模式相容 + build 前插 @register。

    板上(package)走 ui.xxx;模擬器(平級)fallback 到根層模組。
    """
    src = _wrap_page_import(src)
    deco = (
        '@register(id="{}", title="{}", icon="{}", desc="{}", '
        "order={}, accent=0x{:04X})"
    ).format(meta["id"], meta["title"], meta["icon"], meta["desc"],
             meta["order"], meta["accent"])
    src = src.replace("def build():", deco + "\ndef build():", 1)
    return src


def _wrap_page_import(src: str) -> str:
    """把頁面頂部的 import 區塊包成 try/except 雙模式。

    原始:
        from lvgl_ui_common import (
            ZH, BG, ...
        )
    包成:
        try:
            from ui.registry import register
            from ui.ui_common import (
                ZH, BG, ...
            )
        except ImportError:
            from registry import register
            from ui_common import (
                ZH, BG, ...
            )
    """
    marker = "from lvgl_ui_common import ("
    i = src.find(marker)
    if i < 0:
        # 無括號形式(少見):直接兩行替換 + try 包兩行
        src = src.replace(
            "from lvgl_ui_common import",
            "try:\n    from ui.registry import register\n    from ui.ui_common import")
        # 把接續的 except 補上(整段是獨立 import,後接空行)
        src = src.replace(
            "\n\ndef ", "\nexcept ImportError:\n    from registry import register\n    from ui_common import\n\ndef ", 1)
        return src

    open_i = i + len(marker)
    j = src.find(")\n", open_i)
    if j < 0:
        return src
    body = src[open_i:j]          # "    ZH, BG, ..."（含縮排）
    head = src[:i]                # 頁面開頭
    tail = src[j + 1:]            # ")" 之後
    new_block = (
        "try:\n"
        "    from ui.registry import register\n"
        "    from ui.ui_common import (\n"
        + body +
        "\n    )\n"
        "except ImportError:\n"
        "    from registry import register\n"
        "    from ui_common import (\n"
        + body +
        "\n    )\n"
    )
    return head + new_block + tail


def generate(project_root: Path, out_root: Path, log=None) -> dict:
    """產生完整框架到 out_root/ui/。project_root = mp_LVGL。"""
    out_root.mkdir(parents=True, exist_ok=True)
    ui_dir = out_root / "ui"
    page_dir = ui_dir / "page"
    page_dir.mkdir(parents=True, exist_ok=True)

    def w(rel: str, content: str) -> None:
        p = ui_dir / rel
        p.write_text(content, encoding="utf-8")
        log and log("→ ui/{}".format(rel))

    # 固定框架檔
    w("__init__.py", UI_INIT_PY)
    w("registry.py", REGISTRY_PY)
    w("app.py", APP_PY)
    w("launcher.py", LAUNCHER_PY)
    w("page/__init__.py", PAGE_INIT_PY)
    w("board.py", PAGE_BOARD_PY)
    w("sim_platform.py", SIM_PLATFORM_PY)

    # ui_common:從現有 lvgl_ui_common.py 遷移（資源由 sys.path 提供,不需改 import）
    common_src = (project_root / "lvgl_ui_common.py").read_text(encoding="utf-8")
    w("ui_common.py", common_src)

    # 資源（src/）:從 workspace/out 或舊 lvgl/src 拷貝已生成資產
    _copy_assets(ui_dir, log)

    # 頁面:遷移 + @register
    cards = _extract_cards(project_root)
    count = 0
    for pid, src_name in _PAGE_SRC:
        p = project_root / src_name
        if not p.exists():
            log and log("⚠ 缺少 {}（跳過）".format(src_name))
            continue
        meta = cards.get(pid, {
            "id": pid, "title": pid, "icon": "", "desc": "",
            "accent": 0x1A73E8, "order": 99,
        })
        src = p.read_text(encoding="utf-8")
        w("page/{}.py".format(pid), _transform_page(src, meta))
        count += 1

    log and log("框架產生完成: {} 個頁面 + 框架檔 → {}".format(
        count, ui_dir))
    return {
        "pages": count,
        "dir": str(ui_dir),
        "files": [p.name for p in ui_dir.rglob("*.py")],
    }


def _rewrite_src_imports(common_src: str) -> str:
    """把 ui_common 對 lv_icons/lv_ui_fx 的 import 改到 ui/src（fallback 根目錄）。"""
    common_src = common_src.replace(
        "from lv_icons import load_icon_font",
        "try:\n    from ui.src.lv_icons import load_icon_font\nexcept Exception:\n    from lv_icons import load_icon_font")
    common_src = common_src.replace(
        "from lv_icons import ICONS",
        "try:\n    from ui.src.lv_icons import ICONS\nexcept Exception:\n    from lv_icons import ICONS")
    common_src = common_src.replace(
        "from lv_ui_fx import pulse as _fx_pulse, fade_in as _fx_fade_in",
        "try:\n    from ui.src.lv_ui_fx import pulse as _fx_pulse, fade_in as _fx_fade_in\nexcept Exception:\n    from lv_ui_fx import pulse as _fx_pulse, fade_in as _fx_fade_in")
    return common_src


def _copy_assets(ui_dir: Path, log=None) -> None:
    """把已生成的資源拷貝到 ui/src/（icons/zh/fx）。"""
    src_dir = ui_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    # 來源:先找 design 產出的 src,再 fallback workspace/out
    from . import OUT_DIR
    candidates = [
        OUT_DIR,                       # 預設產出
        ui_dir.parent / "src",         # 舊 lvgl/src
    ]
    copied = []
    for fname in ("icons_16.bin", "lv_icons.py", "zh_hant_16.bin",
                  "lv_ui_fx.py", "fx_notes.md"):
        for cand in candidates:
            p = cand / fname
            if p.exists():
                (src_dir / fname).write_bytes(p.read_bytes())
                copied.append(fname)
                break
    if copied:
        log and log("→ ui/src: " + ", ".join(copied))
    # lv_icons 的字體路徑指到板上 ui/src;並確認 src 可被 ui_common import
    lv_icons = src_dir / "lv_icons.py"
    if lv_icons.exists():
        t = lv_icons.read_text(encoding="utf-8")
        t = t.replace('_FONT_FILE = "/icons_16.bin"',
                      '_FONT_FILE = "/ui/src/icons_16.bin"')
        lv_icons.write_text(t, encoding="utf-8")
    # src 需為 package（ui_common 的 from lv_icons 由 sys.path 提供,不需 __init__）
