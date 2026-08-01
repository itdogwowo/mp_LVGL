# LVGL UI Asset Studio

`mp_LVGL` 的完全自包含 UI 資產工具：把設計稿（如 Trae 產出的 `lvgl-console-ui`）
變成 LVGL 板上可用的資產——**圖示字體、中文字體、動態效果 helper**。

工具不依賴任何專案路徑、不推算外部位置：設計稿由你上傳進工作區，
全部產物寫在自己的 `workspace/` 裡。

## 啟動

```bash
cd /Users/user/Documents/code/git/mp_LVGL
python3 tools/ui_assets_server.py
```

- 零參數啟動，自動開瀏覽器 `http://localhost:8600`
- 可選：`--port 9000` 指定端口、`--no-browser` 不開瀏覽器
- 純 Python 標準庫，無需 pip 安裝；`lv_font_conv` 需 Node（`npx`）

## 使用流程

1. **上傳設計稿**：把 `.html` / `.css` / `.design` 拖進「設計稿」區
2. **自動掃描**：工具列出
   - 圖示：`data-lucide` 清單 + 建議的 Material Symbols 對應（名稱可改，會記憶）
   - 中文：設計稿的非 ASCII 字符
   - 動效：`@keyframes` / `:hover` / `transition` 對照
3. **生成**：按各區塊的按鈕，或「生成全部」
   - 圖示 → `icons_16.bin` + `lv_icons.py`
   - 中文 → `zh_hant_16.bin`
   - 動效 → `lv_ui_fx.py` + `fx_notes.md`

## 產物（tools/workspace/out/）

| 檔案 | 用途 | 板上用法 |
|---|---|---|
| `icons_16.bin` | Material Symbols 圖示字體(16px) | 放根目錄 `/icons_16.bin` |
| `lv_icons.py` | 圖示 helper | `from lv_icons import mk_icon; mk_icon(parent, "thermometer", x, y)` |
| `zh_hant_16.bin` | 中文字體 | 放根目錄 `/zh_hant_16.bin` |
| `lv_ui_fx.py` | 動效 helper | `pulse(wid)`、`fade_in(wid)`、`bar_grow(bar)`、`set_state_colors(...)` |
| `fx_notes.md` | CSS 動效 → LVGL 對照表 | 開發參考 |

## 工作區結構

```
tools/
├── ui_assets_server.py    Web server + GUI
├── assets/                核心邏輯（scanner/icons/zhfont/fxgen）
├── web/index.html         單頁介面
└── workspace/             ★ 工具工作區（自動建立）
    ├── design/            設計稿（上傳）
    ├── cache/             Material Symbols 下載快取
    ├── out/               生成產物
    └── config.json        設定（映射表修改、附加字符）
```

## 註記

- 圖示來源：Material Symbols Rounded（Google 開放字體），lucide → Material
  對應表在 `assets/icons.py` 的 `LUCIDE_TO_MS`，也可在 GUI 逐筆調整。
- 中文字體來源：`/Library/Fonts/Arial Unicode.ttf`（macOS 內建）。
- `lv_font_conv` 用 `--no-compress`，與 LVGL 9 binfont 載入相容。
- 產物在板上使用時需先 `lv.init()` 再載入字體（與 `lvgl_ui_common.init_fonts()`
  相同流程）。
