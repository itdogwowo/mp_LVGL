# LVGL Console UI · Simulator

**這個資料夾就是根**：工具、套件、工程全部在裡面，自包含、可以直接搬走。
用純 JS 做 LVGL UI：canvas 直接畫、字型用真機 `.bin`、可操作、可點選元件、可驗證。
定稿後再把 `projects/<id>/pages/*.js` 轉成裝置的 MicroPython。

> 為什麼不是 wasm 模擬：舊做法要編 MicroPython + LVGL 成 5MB wasm、要 WSL 對齊固件、
> 還要補 9.0/9.3 的 shim。現在的問題不是「真機跑不跑得動」，是「版面對不對」，
> 而那些用 canvas + 真機字型就答完了。

---

## 啟動

```bash
cd lvgl-console-ui

python serve.py            # → http://127.0.0.1:8610/（會自動開瀏覽器）
python serve.py 9000       # 換 port
python serve.py --no-open  # 不開瀏覽器
```

或者**雙擊 `start.bat`**（它做的事就是 `chcp 65001` + `python serve.py`）。

伺服器只用 Python 標準庫，不用 `pip install`、不用 Node。
（前端也跟 Node 無關：靜態檔 + import map + 瀏覽器。）

想用 Node 也可以，兩邊提供的 API 一樣：

```bash
npm run dev                # = node cli/serve.mjs --open
node cli/serve.mjs         # 不開瀏覽器
```

| 指令 | 作用 |
|---|---|
| `python serve.py` | 開模擬器（Python，零相依） |
| `python cli/validate.py` | 工程檢查 → `validation-report.json` |
| `python cli/assets.py [project]` | 字元/圖示盤點 + 補字型命令 |
| `node cli/validate.mjs` / `node cli/assets.mjs` | 同上，Node 版 |

> **改 `.bat` 的注意事項**：cmd.exe 用系統碼頁（這裡是 CP950）讀批次檔，
> 檔案存成 UTF-8 的話中文會被拆成亂碼、甚至讓整行被當成命令執行
> （第一版 `start.cmd` 就是這樣壞的）。⇒ `.bat` **只放 ASCII**；
> 需要中文輸出的話在裡面 `chcp 65001`，讓 Python 的 UTF-8 輸出對得上。

| 鍵 | 對應 |
|---|---|
| `←` `→`（或滾輪） | 旋鈕 enc |
| `Enter` / `Space` | 確認（`pin encC`） |
| `Esc` / `Backspace` | 返回（`pin btn`） |
| `I` | 開/關元件檢視器 |

右上角可切**工程**（`projects.json`）、切**頁面**；`?project=<id>` 可直接指定。
devtools 裡有 `sim`。

## 開發台介面

```
┌ header ─ 品牌 · 工程下拉 · 頁面 · 檢視器 ──────────────────────┐
├──────────────────────────────────┬────────────────────────────┤
│         （藍圖網格背景）          │  檢視 / 元件樹 / 資產 / Console │
│      ┌─────────────────┐         │                            │
│      │   ● 工程 · 320×240 · 風格 │                            │
│      │  ╭───────────╮  │         │  ← 選取的元件屬性           │
│      │  │  裝置畫面  │  │         │     建立位置 pages/…:57     │
│      │  ╰───────────╯  │         │                            │
│      │  [ PAGE | FPS | RENDER | WIDGETS ]                      │
│      └─────────────────┘         │                            │
│      ← → 旋鈕 · Enter · Esc …     │                            │
└──────────────────────────────────┴────────────────────────────┘
```

- **面板置中、內容左對齊**：身份列／畫面／狀態列／快捷鍵是**同一個面板**，
  全部對齊同一個左緣（只有整個面板在畫布裡置中）—— 每一行各自置中會鬆散
- **身份列**：工程名 · 解析度 · 風格版本（現在跑的是什麼，一眼看到）
- **狀態列**：PAGE / FPS / RENDER / WIDGETS 是面板的一部分，跟畫面同寬
- **自動倍率**：依視窗大小挑 **整數** 倍率（2–4×）。為什麼不用小數：canvas 是
  `image-rendering: pixelated`，2.4× 會讓像素大小不一致（有些 2px、有些 3px），看起來像糊掉。
- **空狀態**：沒選元件時給「怎麼開始」，不是一行灰字
- **可及性**：所有按鈕有 `:focus-visible` 外框、內文對比 ≥4.5:1、`prefers-reduced-motion` 會關掉轉場

---

## 目錄

```
lvgl-console-ui/                ★ 根
├── start.bat                   雙擊啟動（ASCII only + chcp 65001）
├── serve.py                    Python 啟動器（零相依：靜態檔 + 2 個 API）
├── package.json                npm scripts（Node 版入口，可選）
├── projects.json               工程索引（模擬器啟動時讀）
├── validation-report.json      驗證產物
├── index.html                  入口 + import map（@lvui / @packages / @projects）
├── boot.js                     讀 projects.json → project.json → theme → pages
│
├── host/                       canvas display driver · LVGL .bin 字型解析
├── frameworks/lvgl/            LVGL 鏡像（lv.js / paint.js / anim.js）
├── inspect/                    元件檢視器 · 右側面板（檢視/元件樹/資產/Console）
├── cli/
│   ├── serve.mjs               Node 版 server（同 API）
│   ├── validate.py / .mjs      工程驗證
│   ├── assets.py / .mjs        字元/圖示盤點（serve.py 也用這支）
│   ├── fontbin.py              Python 的 .bin cmap 讀取器
│   └── font-check.mjs          字型解析自我檢查
├── assets/fonts/               真機 .bin（zh_hant_16 / icons_16）
│
├── packages/
│   ├── lv-app/                 應用層：app 迴圈 · registry · nav · launcher · bus
│   │                           ui_common（builder + theme token）· lv_icons · lv_ui_fx
│   └── themes/traework/        風格：id / version / colors / radii / fonts / focus
│
└── projects/
    ├── slave/                  ★ 工程 A：mp_Net-Core slave 的複刻（7 頁）
    │   ├── project.json        綁 theme（含版本）/ display / fonts / 轉換目標
    │   ├── mocks.js            模擬板上沒有的子系統（cfg_manager / get_vbus / Proto）
    │   ├── seed.js             bus.shared 初始資料 + 假 action_task（echo 迴路）
    │   └── pages/              index.js（註冊）+ 一頁一個檔案
    └── sandbox/                工程 B：空白樣板（settings + widgets 元件測試）
```

移植規範：`docs/porting-guide.md`（Python → JS 的逐條對照、紅線、自檢）。

---

## 四層（誰依賴誰）

```
projects/<id>/pages/*.js      ← 只有這層會轉成 MicroPython
        │ import
packages/lv-app/              ← 應用層（流程），跨工程共用
packages/themes/<id>/         ← 風格（token），換風格不改頁面
        │ import
frameworks/lvgl/ + host/      ← 框架層 / 宿主層（等於 LVGL 本體 + canvas）
```

`cli/`、`inspect/`、`boot.js`、`index.html` 只屬於瀏覽器/工具，**不轉換**。

---

## 元件檢視器

游標移過去就有框；點一下＝選取，右側「檢視」分頁顯示：

- class / oid / 文字
- 位置（相對＋絕對）、尺寸、對齊、字型（`zh_hant_16 · 16px · lineH 19`）、顏色、外框、圓角、焦點框、flag
- **建立位置**：`projects/slave/pages/settings.js:57`，附 `via packages/lv-app/ui_common.js:283`

作法是 widget 建構時截一次 `Error.stack`（跳過 `frameworks/` `host/` `inspect/`，
優先找 `/projects/` 的框當頁面呼叫點）。成本 ~10–30µs/widget，開機一次約 3ms。
`lv.trackSource = false` 可關。

「元件樹」分頁可反過來：點一列 → 畫布閃黃框選中。

---

## 資產盤點

「資產」分頁讀 `/api/assets-report?project=<id>`（**即時算**，不是舊檔）：

- 字元：頁面字串裡的非 ASCII 字、缺哪幾個（缺字＝真機方框）
- 圖示：用到幾個、對照表沒有、`icons_16.bin` 沒有、對照表哪些沒用到
- 補字型的完整 `lv_font_conv` 命令（含 `-r` 碼點區間）

CLI：`node cli/assets.mjs [project]`。

---

## 驗證

```bash
node cli/validate.mjs [project]
```

檢查：`projects.json` / `project.json` 完整、theme 存在且**版本相符**、每個頁面有唯一
`meta.id` + `build()`、`pages/index.js` 有 import、字型可解析、**沒有缺字**、圖示名都在對照表與 bin 裡。

產物 `validation-report.json`（欄位對齊舊的 TraeWork 工作區那份）：
`outcome` / `errorCount` / `warningCount` / `errors` / `warnings` / `projects` / `hashes` / `checkedAt`。
有錯 exit code = 1，可直接接 CI。

---

## 目前狀態（projects/slave）

7 頁，`python cli/validate.py` → `PASSED`（2026-10 改版：移除舊的 `control_panel` / `pca9685`，
功能由 `pixel_controller` + `pixel_lab_*` 取代）：

| 順序 | 頁面 | 標題 | 圖示 | 備註 |
|---|---|---|---|---|
| 0 | `pixel_controller` | Pixel 控制 | `sliders-horizontal` | 模式清單 + 可動快捷 |
| 1 | `pixel_lab_pca` | PixelLab PCA | `gauge` | 16 通道 + 目標清單，ALL/LED |
| 2 | `pixel_lab_rgb` | PixelLab RGB | `lightbulb` | WS2812，共用 `SimplePage` |
| 3 | `pixel_lab_apa` | PixelLab APA | `zap` | APA102，共用 `SimplePage` |
| 4 | `remote` | 遙控器 | `wifi` | 節點清單 / 身份 / 模式表 |
| 5 | `now_setting` | ESP-NOW | `sensors` | 頻道 / 加密 / 已選節點 |
| 6 | `settings` | 系統設定 | `settings` | 網路 / 裝置資訊 |

> 卡片與頁籤的順序完全由 `meta.order` 決定，`pages/index.js` 的順序不影響顯示。

支撐它們的假資料層：

- `mocks.js`：`cfg_manager` / `get_vbus` / `Proto` + `install_services()`（`peers` / `NowBus` / `disp` / `pca9685_ctl` / `app`）
- `seed.js`：`bus.shared` 初始資料 + `bus.cid/role/targets` + **假 action_task**（`_display_cmd → _display_*`，讓 echo 三態看得見）

**已知落差**（都不影響操作，屬於模擬器能力邊界）：

1. `lv.list` 沒有捲動（`scroll_to_view`）：清單超過容器高度時，游標可以移到看不見的列
2. `List._layoutItems()` 固定列高（font.lineHeight + 8）、忽略 `set_style_pad_all()` → 列距跟真機差幾 px
3. 字型方框：裝置頁面有幾處用 `u.F_NUM_M` 畫中文（`模式 1`、`待機/計時中`、`—`、`無`），
   Montserrat 沒有 CJK → 模擬器照真機畫方框。**要決定**：保持 1:1，或改成 `u.ZH`



## 新增一頁

1. 建 `projects/<id>/pages/xxx.js`

```js
import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";

export const meta = { id: "pixel_controller", title: "Pixel 控制", icon: "sliders-horizontal",
                      desc: "模式設置·列表·可動", order: 0, accent: 0x1A73E8 };

let scr = null;
export function build() {
  scr = lv.obj(null);
  scr.set_style_bg_color(u.C(u.BG), 0);
  u.mk_label(scr, "控制面板", 10, 10, u.TEXT, u.ZH);
  return scr;
}
export function on_enc(d) {}
export function on_confirm() { return null; }
export function on_exit() { return false; }
export function update(run) {}
```

2. `projects/<id>/pages/index.js` 加兩行：`import * as xxx from "./xxx.js"; register(xxx);`
3. `npm run validate` → 重新整理，首頁自動多一張卡片（順序看 `order`）。

---

## 新增一個工程

1. `projects/<id>/project.json`

```json
{
  "id": "myui", "title": "我的 UI",
  "theme": { "id": "traework", "version": "1.0.0" },
  "display": { "w": 320, "h": 240 },
  "pages": "pages", "seed": "seed.js"
}
```

2. `projects/<id>/seed.js`（可空：`export function seed() {}`）
3. `projects/<id>/pages/`（同上一節）
4. `projects.json` 加一筆：`{ "id": "myui", "title": "我的 UI", "path": "projects/myui" }`

重新整理 → 右上角下拉出現，`?project=myui` 也可直接開。

---

## 新增一套風格

複製 `packages/themes/traework/` 成 `packages/themes/<id>/`，改 `colors` / `radii` / `fonts`，
把工程的 `project.json` 指過去。**頁面不用改**（只讀 `u.TEXT` / `u.mk_card(...)`）。

版本規則：`project.json` 綁 `"version"`，theme 檔有 `export const version`；
不同時模擬器警告、`validate` 報錯（舊工作區 `designLibrary.versionSource` 的概念）。

---

## 轉換到 MicroPython

只有 `projects/<id>/pages/*.js` 要轉（方法名保留 snake_case，所以幾乎逐行）：

| JS | MicroPython |
|---|---|
| `export const meta = {...}` | `@register(id=..., title=..., ...)` |
| `export function build()` | `def build():` |
| `export let scr = null` | 模組層 `scr = None` + `global scr` |
| `() => {}` | `lambda: ...` |
| `` `${a}:${b}` `` | `"{}.{}".format(a, b)` |
| `.forEach((x,i)=>)` | `for i, x in enumerate(...)` |
| `??` / `null` / `true` | `... if ... is not None else ...` / `None` / `True` |

轉換目標寫在 `projects/<id>/project.json` 的 `target`。

---

## 字型

`assets/fonts/*.bin` 就是裝置 `/ui/lvgl/src/*.bin`，`host/font.js` 自己解析
lv_font_conv 的 binary 格式（head → cmap → loca → glyf）。

兩個踩過的坑（寫在 `host/font.js`）：

- `loca` 存的是**原始 byte offset**，不是 OpenType 的 `offset/2`（乘 2 會讓所有字形讀成 0×0）
- glyph 的 `y` 是 **baseline 往上的底邊**，`ofs_y = ascent - y - h`；驗證方式：反推 `head.min_y/max_y` 必須完全相符

缺字分兩種回報：`zh_hant_16` 缺字（補字型子集）、`sys:*` 缺字（**用 Montserrat 畫中文**，改 `u.ZH`）。
第二種瀏覽器會偷偷幫你畫出來，所以刻意照真機畫方框 + 警告。

---

## 支援的 LVGL 子集

只做頁面真的用到的（掃過裝置 21 個 `.py` 統計）：

| 類別 | 內容 |
|---|---|
| widget | `obj` `label` `button` `list`（`add_text`）`slider` `arc` `switch` `bar` |
| style | `bg_color/opa` `radius` `border_*` `pad_*` `outline_*` `text_*` `shadow_*` `arc_*` `opa` `clip_corner` |
| part | `MAIN` / `INDICATOR` / `KNOB`（沒設 → fallback MAIN） |
| 繼承 | `text_*` 往上繼承（LVGL 的 inherited props） |
| 版面 | `set_pos` `set_size` `align`、`size_to_content`（label 用真機 advance 量） |
| 動畫 | `lv.anim_t`：`set_var/values/duration/delay/reverse_duration/repeat_count/custom_exec_cb` |

**刻意沒做**：flex/grid、scroll 容器、transform、gradient、事件系統、theme 引擎、dirty rect。

---

## 限制

- **只有 encoder 輸入**（跟 slave 的 UI 一致），沒有觸控座標。
- **Montserrat 用系統字型近似**（12/14/16/22/28px），字寬可能差 ±1px；中文走真機 `.bin`，精確。
- **每幀全畫** 320×240（實測 0.1–0.4ms），沒有 dirty rect。
- 瀏覽器要支援 import map（Chrome/Edge 89+、Firefox 108+、Safari 16.4+）。

---

## 工程約定

1. **import 一律用別名**：`@lvui/…`、`@packages/…`、`@projects/…`（`index.html` 的 import map）。
2. **頁面不碰 theme 的值**：只用 `u.BG` / `u.mk_*`，不要寫死顏色。
3. **頁面不碰 canvas / DOM**：那一層在 `host/`、`frameworks/`、`inspect/`。
4. **每個頁面都有唯一 `meta.id` + `build()`**，並在 `pages/index.js` 註冊（validator 會查）。
5. **改完跑 `npm run validate`**：缺字、缺 import、版本不合、圖示名錯都會被抓出來。
