# ui/app.py — 動態註冊式 UI 主程式
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
