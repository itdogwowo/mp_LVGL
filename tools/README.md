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

## 導入/導出外部專案（project_io.py）

把外部專案的 LVGL UI 資料夾（如 `mp_Net-Core/slave/ui/lvgl`）導入成
design 庫裡的一個 design，之後直接改 `design/{name}/` 下的檔案
（不需在網頁上 edit），改完再導出回專案：

```bash
# 導入:ui/lvgl → design/slave-ui/lvgl/ui/（自動掃 page/*.py 的 @register 寫進 design.json）
python3 tools/project_io.py import ../mp_Net-Core/slave/ui/lvgl --name slave-ui

# 改完後導出:
#   zip 內容 = lvgl/...,解壓到專案的 ui/ 下即部署
python3 tools/project_io.py export slave-ui                     # → design/slave-ui/lvgl/slave-ui.zip
python3 tools/project_io.py export slave-ui --to ../mp_Net-Core/slave/ui/lvgl  # 直接合併複製

# 列出 design 庫（含導入來源）
python3 tools/project_io.py list
```

導入的 design 沒有 html 設計稿（code-only）：網頁的「重新掃描」會改從
`lvgl/ui/page/*.py` 的 `@register` 更新頁面清單，不會清空。

## 工作區結構

```
tools/
├── ui_assets_server.py    Web server + GUI
├── project_io.py          外部專案導入/導出 CLI（見上節）
├── assets/                核心邏輯（scanner/icons/zhfont/fxgen）
├── web/index.html         單頁介面
├── design/                ★ design 庫:每個 design 一個資料夾
│   └── {name}/            設計稿 html（或導入的 code-only design）
│       ├── design.json    meta（掃描自動產生/更新）
│       └── lvgl/ui/       LVGL 產物（導出來源）
└── workspace/             工具工作區（自動建立）
    ├── design/            舊版設計稿（自動遷移進 design 庫）
    ├── cache/             Material Symbols 下載快取
    ├── out/               生成產物（無 design 時的輸出）
    └── config.json        設定（映射表修改、附加字符）
```

## 註記

- 圖示來源：Material Symbols Rounded（Google 開放字體），lucide → Material
  對應表在 `assets/icons.py` 的 `LUCIDE_TO_MS`，也可在 GUI 逐筆調整。
- 中文字體來源：`/Library/Fonts/Arial Unicode.ttf`（macOS 內建）。
- `lv_font_conv` 用 `--no-compress`，與 LVGL 9 binfont 載入相容。
- 產物在板上使用時需先 `lv.init()` 再載入字體（與 `lvgl_ui_common.init_fonts()`
  相同流程）。
