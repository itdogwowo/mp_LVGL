# SimLab — LVGL 設備模擬器(獨立工具,同一 web service 內)

SimLab 是掛在 Asset Studio(同一 `tools/ui_assets_server.py`,同 port 8600)上的
**獨立新工具**,URL 命名空間 `/simlab/*`,文件全在 `tools/simlab/`,與
design 庫/designlib/scanner 零共享邏輯。

核心差異(相對於 Asset Studio 內建模擬器):

| | Asset Studio 模擬器 | SimLab |
|---|---|---|
| 輸入 | 鍵盤 → 自製 input_bus | **中間緩存模擬器**:`bus.shared["_hw_inputs"]`(真 `consume_input` 語義 + 累加注入) |
| 頁面互動 | 部分頁面無響應(缺 PAGES["mod"] 註冊) | 複刻 `page/__init__.py` 註冊,真碼 `board._make_snapshot_inputs` 接線 |
| 性能 | 無 | `[perf]` 渲染儀表 + canvas diff 髒區 + 硬體成本模型 → 預估真機 FPS |
| 項目 | 固定 design 庫副本 | `projects.json` 註冊表,下拉快速切換(slave / mp_LVGL) |
| runtime | vendor 官方 v9.0 | `build_runtime.py` 一鍵換成**與固件同源**的自建 wasm |

## 項目儲存:本地複製件(自包含 + 匯入/匯出)

SimLab 的每個項目是**完全在本地的複製件**,不依賴真機路徑(可攜帶整個 tools/simlab):

```
tools/simlab/projects/{name}/
├── lvgl/     ← 真機 LVGL 代碼複製(page/ src/ + 根模組)
├── html/     ← HTML 設計稿複製
├── assets/   ← 字體/圖示 bin
└── design.json ← (framework 型才會有,頁面對照用)
```

- 模擬器一律跑**本地複製件**;改本地檔案真機不變、改真機檔案本地不變(完全隔離)
- `projects.json` = 索引:name/title/group/w/h/**source(來源路徑)**/entry 配置

### CLI(`tools/simlab/project_io.py`,對齊 Asset Studio 慣例)
```bash
python tools/simlab/project_io.py list
python tools/simlab/project_io.py import mp_Net-Core/slave/ui/lvgl --name slave \
    --title "mp_Net-Core slave (真機 UI)" --html mp_LVGL/tools/design/slave-ui/html
python tools/simlab/project_io.py import mp_LVGL --name mp_lvgl --title "mp_LVGL 參考 UI" \
    --html mp_LVGL/lvgl-console-ui/pages --bins-dir mp_Net-Core/slave/ui/lvgl/src
python tools/simlab/project_io.py export slave    # 本地複製件寫回真機來源
```

### GUI(🗂 項目管理)
- **🔍 掃描** → 顯示偵測到的頁面/結構(預覽)
- **📥 匯入** → 複製進 `projects/{name}/` + 加入清單 + 模擬器切換
- 每項目 **📤 匯出** → 寫回真機來源(source / source_html / bins 到 src/)

## 啟動

```bash
cd mp_LVGL
python tools/ui_assets_server.py      # 零參數,開瀏覽器 → /simlab/
```

工具切換:SimLab 頁面右上「Asset Studio ↗」;`/` 回 Asset Studio。

## 操作

- **連續步進**:模擬器開機後以 33ms(= LVGL 內部刷新節拍)自動步進,像真機主迴圈 —
  過場動畫 / fade_in / pulse 呼吸 / 頁面 update 都會真正播放;轉頁後畫面不再凍結。
  指令注入仍走中間緩存(累加),每次輸入立即步進一幀,其餘由定時器補幀。
- **◀ ▶** 編碼器(累加 delta,可 >±1)、**Enter** 確認(encC)、**Esc** 返回(btn)
- 按住不重複(鍵盤 `e.repeat` 抑制,對齊裝置去抖邊緣語義)
- **指令輸入框**:`enc 1` / `enc -1` / `pin encC` / `pin btn`(Enter 執行,腳本/除錯用)
- **● 錄製 / ▶ 播放**:操作腳本錄放,重播比對性能(兩次 FPS 曲線應一致)
- **↻ 重啟**:重新載入 iframe(換項目/改代碼後)

## REPL(模擬真機命令行)

- **輸入框**直接執行任意 Python 進模擬器,**轉錄式終端顯示**(像真機 `>>>` 提示):
  ```
  >>> print(123)
  123
  >>> print(bus.shared.get('_display_mode'))
  None
  >>> 
  ```
- **⏸ 暫停**:連續步進與操作都只注入中間緩存**不步進**(像真機 Ctrl-C 停住),REPL 任意下指令;
  **單步**執行一幀 `__step()`;**▶ 繼續**恢復
- 別名:`bus`(bus.shared 緩存)、`lv`(lvgl)、`inject_enc/inject_edge/inject_release/inject_reset`

## 分頁

| 區 | 內容 |
|---|---|
| 顯示對比(並排) | **左:LVGL 模擬畫布 · 右:HTML 稿**(各 320×240 固定,直接對比);HTML 稿內 `[data-dom-id]` 按鈕點擊 → **跳轉對應 LVGL 頁面**(橋接 script 由 server 注入,`card-` 前綴自動剝除);下拉選頁同步跳轉 |
| REPL / 輸出 | 模擬器輸出 + REPL 輸入 + 暫停/單步(轉錄式 `>>>` 終端) |
| 代碼 | **摺疊式檔案樹 + 樸素 textarea**(對齊 Asset Studio 的 ed 樣式):`🐍 LVGL 程式碼`(含 page//src/ 子目錄)、`🖼 網頁設計稿`、`📦 共用資源` 分組可摺疊;點檔 → 等寬 textarea 檢視;`__shim__.py` 固定置頂 |

## 項目管理(🗂 按鈕)

- 列表 + **✎ 載入編輯**(名稱/title/group 分類/path/尺寸/入口 kind/modules/page_dir/src_dir/exclude/html_dir)
- **🔍 從真機路徑掃描**:輸入 `mp_Net-Core/slave/ui/lvgl` 這類路徑 → 自動偵測
  framework/mp_lvgl 結構 + 頁面 + 字體 + html 稿 → 填入表單 → 💾 新增/更新(存 projects.json)
- 每項目獨立配置:CPU_SCALE 等 perf 參數存到 `config.json` 的 `projects.{name}.perf`;
  上次選的項目自動恢復(`last_project`)

## 已驗證(2026-08-12)

- [x] slave:字體/圖示/4 screen 載入、編碼器輪播、進出頁(control_panel/pca9685/settings)、
      **echo 迴路**:頁面寫 `_display_cmd` → 2 幀後寫回 `_display_mode/_brightness`(REPL 見 `[echo]`)
- [x] mp_lvgl:5 頁全 build(launcher/overview/monitor/control/settings)+ 導航
- [x] **畫面鏡像**:iframe 內讀像素 → postMessage raw RGBA → 父頁 putImageData(`[frame] 畫面出現`)
- [x] 項目切換(slave ↔ mp_lvgl,下拉即換,重啟即反映真機代碼)
- [x] 性能面板:FPS 預估、髒區 px、渲染 µs、每幀分解、腳本重播後統計再現、開機幀計入暖機
- [x] REPL:`>>> print(123)` / `123` / `>>>` 轉錄式終端;`bus.shared` 查詢、`inject_enc` 執行;
      暫停只注入不步進、單步執行一幀
- [x] **顯示對比並排**:LVGL 畫布 + HTML 稿各 320×240;下拉選頁同步跳轉(`[nav] -> control_panel` 實測)
- [x] **代碼雙欄**:HTML ↔ LVGL .py 頁面對照(server 自動配對,slave 3 對、mp_lvgl 5 對)
- [x] 項目管理:列表/掃描(從路徑抽出 3 頁)/表單;每項目獨立 perf + last_project 恢復
- [x] 校準:真機 FPS → 反推 CPU_SCALE → 存配置(每項目獨立,離線保留)
- [x] 看門狗:心跳 ping 3s/次,閒置不誤判;當機 8s 自動重啟

### LVGL 9.0 vs 9.3 相容(對齊 runtime 前暫時)

模擬器 runtime 是官方 9.0;真機代碼用 9.3 API。shim 內建兩層補丁
(對齊 runtime 後自動變 no-op):
- `time.time()` → polyfill(js port 無;device MP 有)
- `lv_ui_fx` 的 anim API(如 `set_reverse_duration`)→ try/except 降級(動畫退化成直接設定)

若還有缺 API,在 `shim/` 補丁區加對應的守衛即可。

## 項目切換

`tools/simlab/projects.json`:

```json
{ "name": "slave", "title": "...", "path": "mp_Net-Core/slave/ui/lvgl",
  "w": 320, "h": 240,
  "entry": { "kind": "framework", "page_dir": "page", "src_dir": "src",
             "modules": ["registry","ui_common","nav","launcher","app"],
             "bins": {"ui/lvgl/src/zh_hant_16.bin": "ui/lvgl/src/zh_hant_16.bin", "..."} } }
```

- `path` 相對 git root;`bins` 的 `vfs: 相對路徑` 可跨倉(如借 slave 的字體)
- `kind: framework` — slave 型(registry/app/launcher/nav + page/)
- `kind: mp_lvgl` — mp_LVGL 參考 UI(平級頁面模組 + `lvgl_shared` mock)
- 新增項目:加一筆 + 重開頁面即可;真機改 `ui/lvgl` 任一檔 → **↻ 重啟即反映**(live source)

## 中間緩存模擬(核心)

```
前端鍵盤/按鈕/腳本 ──sim-input──▶ iframe ──mp_js_do_str──▶ inject_enc / inject_edge
                                                                │ (累加寫入,不覆寫未消費 delta)
        bus.shared["_hw_inputs"] {enc:[..], pin_edge:{encC,btn}}
                                                                ▲
  board._make_snapshot_inputs(真碼) ── consume_input(讀取即清) ─┘
        app.step()(真碼) → 頁面 → bus.shared["_display_cmd"]
                                    │  _echo_tick(2 幀後寫 _display_* 回音)
                                    ▼
   control_panel 頁 pending/echo 三態正常運作
```

## 性能面板(真機預估)

- 渲染成本:`_tick` 內 `time.ticks_us` 量 `task_handler` → `[perf] r=<us>`(REPL 通道)
- 髒區像素:iframe 內 canvas diff(跨源限制)→ `sim-perf` postMessage
- 每幀模型:`t_frame = 渲染(sim×CPU_SCALE) + 拷貝(bytes×常數) + SPI(頻寬+塊開銷) + gap(5ms)`
  → 分解條形 + 預估真機 FPS(滾動平均 120 幀)
- 校準:真機跑同場景量 FPS → 填「真機FPS」→ 反推 CPU_SCALE → 存配置(離線保留,`config.json`)

## 一鍵 runtime 對齊固件

```bash
python tools/simlab/build_runtime.py status   # 各步驟狀態
python tools/simlab/build_runtime.py build    # emsdk + 源碼 + 編譯(需 Linux/WSL + 上網一次)
python tools/simlab/build_runtime.py swap     # 產物換進 sim/ + 備份
python tools/simlab/build_runtime.py all      # 一鍵
```

- **版本 pin 自動帶入**:讀 `mp_Make-Tools/git_config.json`(micropython=c4fa8cb)+
  `config.json` detected(lv_binding=ac5d06c)→ 與真機固件同源編譯
- 源碼優先重用本地 `../micropython`、`../lv_binding_micropython` checkout
- Windows 自動走 WSL(`wsl.exe bash wasm_build.sh`);無 WSL 印遠端指引
- swap 前自動備份到 `sim/.bak-<時間>`;`verify` 檢查 banner(MicroPython v1.29...)

⚠ 第一次 build 是「對齊調校」:若 wasm 版 binding 與官方 JS port 有 glue 差異
(如缺 `jswindow` 模組),在 `runtime_recipe.json` 對應欄位補 patch 即可,之後一鍵復用。

## 檔案結構

```
tools/simlab/
├── __init__.py          ← handle_get/handle_post(掛載接口)
├── server.py            ← /simlab/* 路由(projects/config/runtime/code/files/bins)
├── projects.json        ← 項目註冊表(slave / mp_LVGL)
├── config.json          ← perf 常數 + runtime 記錄
├── runtime_recipe.json  ← 建置 recipe(emsdk/源碼 ref 覆寫)
├── build_runtime.py     ← status/build/swap/verify/all
├── sim/                 ← 本地 runtime(wasm/js/lvgl.html/driver/lib,獨立擁有)
├── shim/                ← base.tpl(緩存模擬器+perf)+ framework.tpl + mp_lvgl.tpl
└── web/index.html       ← SimLab 單頁 UI
```

## 文件入口

- `LVGL` 官方文檔索引:
  - `tools/simlab/LVGL-open-doc-index.md`
  - 目前以 `9.3` 為主，`9.0` 為兼容對照

- `SimLab` 本地 API / runtime / 小工具文檔:
  - `tools/simlab/SIMLAB-api-and-tools.md`
