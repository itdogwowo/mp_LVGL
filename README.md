# mp_LVGL

這個 repo 是多個獨立東西的集合。**LVGL UI 開發系統已經自包含在 [`lvgl-console-ui/`](lvgl-console-ui/)。**

```bash
cd lvgl-console-ui
python serve.py      # → http://127.0.0.1:8610/（自動開瀏覽器）
# 或直接雙擊 start.bat
```

| 路徑 | 是什麼 |
|---|---|
| **[`lvgl-console-ui/`](lvgl-console-ui/)** | LVGL Console UI · Simulator：模擬器 + 套件 + 工程（自包含，看它的 README） |
| `tools/simlab/` | 舊的 wasm 模擬器（MicroPython + LVGL 編成 wasm），已被上面取代 |
| `tools/design/` `tools/assets/` | 舊的 Asset Studio（HTML 設計稿 → 字型/圖示） |
| `ESP32-S3-Touch-LCD-2.8-Demo*` | 開發板官方 demo |
| `lvgl_*.py` `test_*.py` | 早期單體實驗（LVGL 顯示/觸控/字型） |
| `DEV_NOTES.md` | 真機踩坑筆記（LVGL 初始化、CST328、soft reboot…） |

裝置端（轉換目標）在另一個 repo：`mp_Net-Core/slave/ui/lvgl/`。
