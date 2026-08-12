# simlab — SimLab:同一 web service 內的獨立 LVGL 設備模擬器
#
# 與 Asset Studio(designlib/scanner/design 庫)零共享邏輯:
#   - 文件路徑全部在 tools/simlab/(sim runtime / shim / web / projects / config)
#   - URL 命名空間全部在 /simlab/*(與既有 /sim/*、/dlib/*、/api/* 不衝突)
#   - ui_assets_server.py 只加一行路由委派,其餘不動
#
# 掛載方式(ui_assets_server.py do_GET/do_POST):
#   if url.path == "/simlab" or url.path.startswith("/simlab/"):
#       from simlab import handle_get
#       return handle_get(self, url)
from __future__ import annotations

from .server import handle_get, handle_post

__all__ = ["handle_get", "handle_post"]
