# assets — LVGL UI Asset Studio 核心邏輯模組
#
# 模組:
#   scanner  掃描工作區設計稿（lucide 圖示 / 非 ASCII 字符 / 動態效果）
#   icons    Material Symbols 下載、lucide→MS 映射、lv_font_conv、bin cmap 驗證
#   zhfont   中文字體生成（--no-compress）
#   fxgen    動效 helper + CSS→LVGL 對照文件
#
# 工具完全自包含:所有輸入在 workspace/design、快取在 workspace/cache、
# 產物在 workspace/out,不讀取任何工具目錄以外的路徑。
from __future__ import annotations

from pathlib import Path

# tools/assets/__init__.py 的上一層上一層 = mp_LVGL/tools
TOOLS_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = TOOLS_DIR / "web"
WORKSPACE = TOOLS_DIR / "workspace"
DESIGN_DIR = WORKSPACE / "design"
CACHE_DIR = WORKSPACE / "cache"
OUT_DIR = WORKSPACE / "out"
CONFIG_FILE = WORKSPACE / "config.json"

DEFAULT_PORT = 8600


def ensure_workspace() -> None:
    """首次啟動自動建立工作區目錄。"""
    for d in (WORKSPACE, DESIGN_DIR, CACHE_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config({})


def load_config() -> dict:
    import json

    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_config(cfg: dict) -> None:
    import json

    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
