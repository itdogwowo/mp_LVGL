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
# 平台解耦:所有硬體透過 platform 物件注入,本檔不 import lvgl_shared。
#   板上: ui/board.py 用 FrameBuffer+Inputs 組 platform 再 app.init/run
import lvgl as lv
import ui.registry as registry
import ui.launcher as launcher

platform = None      # {tick, take, show, enc_delta, confirm, exit}
cur = None
_last_scr = None
_run = 0


def init(plat):
    """注入 platform 物件 + 載入所有頁面(集中 import 已註冊)。"""
    global platform
    platform = plat
    import ui.page  # noqa: F401  集中 import 觸發全部 @register + 補 mod


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
    """主迴圈(啟動後不返回)。"""
    global _run
    go("launcher")
    while True:
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
'''

LAUNCHER_PY = '''# ui/launcher.py — 動態主頁面（讀 registry 產生卡片,不硬編碼）
import lvgl as lv
from ui import ui_common as u
from ui.registry import ordered

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

PAGE_BOARD_PY = '''# ui/board.py — 板上平台實作（lvgl_ui_app 的替代入口）
#
# 用法（soft reboot 後）:
#   import ui.board
#   ui.board.run()
import lvgl as lv
from lvgl_shared import FrameBuffer, Inputs
from ui import app


def run():
    """初始化硬體 + 注入 platform + 啟動主迴圈。"""
    fb = FrameBuffer(320, 240, 0x60)
    fb.setup()

    from lvgl_ui_common import init_fonts
    init_fonts()

    inp = Inputs()

    app.init({
        "tick": fb.tick,
        "take": fb.take,
        "show": fb.show_rect,
        "enc_delta": inp.enc_delta,
        "confirm": inp.confirm_pressed,
        "exit": inp.exit_pressed,
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
    """頁面轉換:import 改 ui.ui_common + build 前插 @register。"""
    src = src.replace(
        "from lvgl_ui_common import",
        "from ui.registry import register\nfrom ui.ui_common import",
    )
    deco = (
        '@register(id="{}", title="{}", icon="{}", desc="{}", '
        "order={}, accent=0x{:04X})"
    ).format(meta["id"], meta["title"], meta["icon"], meta["desc"],
             meta["order"], meta["accent"])
    src = src.replace("def build():", deco + "\ndef build():", 1)
    return src


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
    w("registry.py", REGISTRY_PY)
    w("app.py", APP_PY)
    w("launcher.py", LAUNCHER_PY)
    w("page/__init__.py", PAGE_INIT_PY)
    w("board.py", PAGE_BOARD_PY)

    # ui_common:從現有 lvgl_ui_common.py 遷移
    common_src = (project_root / "lvgl_ui_common.py").read_text(encoding="utf-8")
    w("ui_common.py", common_src)

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

    log and log("框架產生完成: {} 個頁面 + 5 個框架檔 → {}".format(
        count, ui_dir))
    return {
        "pages": count,
        "dir": str(ui_dir),
        "files": [p.name for p in ui_dir.rglob("*.py")],
    }
