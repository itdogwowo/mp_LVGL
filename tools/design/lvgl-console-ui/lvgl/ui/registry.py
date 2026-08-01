# ui/registry.py — 動態註冊表（框架核心）
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
