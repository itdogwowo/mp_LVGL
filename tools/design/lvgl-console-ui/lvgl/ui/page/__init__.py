# ui/page/__init__.py — 集中 import 所有頁面（保證全部註冊）
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
