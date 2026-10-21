# 移植規範：MicroPython LVGL → JS（1:1）

## 目標

把裝置的 `page/*.py` **原樣**搬到 `projects/slave/pages/*.js`。
**1:1** 的意思是：版面座標、顏色、字級、導覽順序、bus 讀寫、文字內容、更新節奏都要一樣。
**不要**重新設計、不要「順手改善」、不要改文案。唯一允許的差異是 JS 語法。

## 輸入 / 輸出

- 來源：`<mp_Net-Core 的位置>/slave/ui/lvgl/page/<name>.py`
- 目標：`lvgl-console-ui/projects/slave/pages/<name>.js`
- 參考檔（先讀）：`projects/sandbox/pages/settings.js`（已完成的 1:1 樣板）、
  `projects/sandbox/pages/widgets.js`（元件用法）

## 每個頁面檔的形狀

```js
// projects/slave/pages/<id>.js — <一句話說明>
//
// 對應 ui/lvgl/page/<name>.py

import lv from "@lvui/frameworks/lvgl/lv.js";
import * as u from "@packages/lv-app/ui_common.js";
import { Nav, ITEM_INFO, ITEM_SWITCH, ITEM_ENUM, ITEM_SLIDER, ITEM_BUTTON, ITEM_LIST } from "@packages/lv-app/nav.js";
import { bus } from "@packages/lv-app/bus.js";

export const meta = {
  id: "<與 @register 的 id 相同>",
  title: "<title>",
  icon: "<icon>",
  desc: "<desc>",
  order: <order>,
  accent: <0xRRGGBB>,
};

// 模組層變數（Python 的 global）
export let scr = null;

export function build() { /* ... */ return scr; }

export function on_enter() {}
export function on_leave() {}
export function on_enc(d) {}
export function on_confirm() { return null; }
export function on_exit() { return false; }
export function update(run) {}
```

## 語法對照

| Python | JS |
|---|---|
| `global a, b` | 模組層 `let a, b`（直接賦值，不用 global） |
| `scr = lv.obj(None)` | `scr = lv.obj(null)` |
| `lb.set_text("x")` | 一樣（方法名全部保留 snake_case） |
| `lambda: _f()` | `() => _f()` |
| `lambda v: _f(v)` | `(v) => _f(v)` |
| `a if c else b` | `c ? a : b` |
| `x or 0` / `x or {}` | `x \|\| 0` / `x \|\| dict()`（0 是有效值時用 `??`） |
| `"{}:{}".format(a,b)` | `` `${a}:${b}` `` |
| `"%02d" % n` / `"{:02d}"` | `String(n).padStart(2, "0")` |
| `len(x)` | `x.length`（dict 用 `.keys().length`） |
| `int(x)` | `Math.trunc(Number(x))`（旗標運算用 `\| 0`） |
| `str(x)` | `String(x)` |
| `abs/min/max/round` | `Math.abs/Math.min/Math.max/Math.round` |
| `for i, x in enumerate(l)` | `l.forEach((x, i) => {…})` |
| `for k, v in d.items()` | `for (const [k, v] of d.items())` |
| `for x in lst` | `for (const x of lst)` |
| `range(n)` | `Array.from({length:n}, (_, i) => i)` |
| `s[a:b]` | `s.slice(a, b)` |
| `d.get(k, default)` | 一樣（`bus.shared` / `dict()` 都有 `.get`） |
| `k in d` | `k in d`（Dict 有 Proxy `has`） |
| `d[k] = v` | `d[k] = v` |
| `None` / `True` / `False` | `null` / `true` / `false` |
| `try: … except Exception: pass` | `try { … } catch (e) { /* 跟裝置一樣：失敗就跳過 */ }` |
| `print(...)` | 一樣（`print` 已全域提供） |
| `time.ticks_ms()` | `Date.now()` |
| `divmod(a, b)` | `[Math.floor(a / b), a % b]` |

## bus / 服務

- `bus.shared` 是 Python dict 的替身：`.get(k, default)`、`[k]`、`k in d`、`d.set(k, v)`、`.items()` 都有。
- `bus.get_service(name)`：**這台沒有那顆硬體時回 `null`**（跟裝置上服務沒註冊一樣）。
  呼叫端本來就有 `if s is None: return` 這類守衛，照抄即可。
- `bus.slave_id`、`bus.has_lcd()` 都有。
- 裝置的 `from lib.sys.sys_bus import get_vbus` → `import { get_vbus } from "../mocks.js"`。
- 裝置的 `from lib.sys.ConfigManager import cfg_manager` → `import { cfg_manager } from "../mocks.js"`。
- 裝置的 `from lib.sys.proto import Proto` → `import { Proto } from "../mocks.js"`。
- 這些 mock 只需要讓頁面跑得起來：`cfg_manager` 提供 `get/set/save/now_state`，
  `get_vbus()` 回 `null`，`Proto` 提供頁面用到的那幾個靜態方法（沒有就 no-op）。

## 版面注意（模擬器與真機的差異）

- `u.mk_*` 的簽名跟裝置完全一樣（`mk_label/mk_card/mk_appbar/mk_btn/mk_slider/mk_arc/mk_switch/mk_list/mk_led`）。
- 樣式 method 名稱相同（`set_style_bg_color` 等），part 用 `lv.PART.MAIN/INDICATOR/KNOB`。
- `lv.ALIGN.*`、`lv.obj.FLAG.*`、`lv.STATE.CHECKED` 都在。
- 座標一律整數；`align()` 之後不要再 `set_pos`（跟 LVGL 一樣會被覆蓋）。

## 紅線

1. **不要改** `packages/`、`frameworks/`、`host/`、`inspect/`、`cli/`、`projects.json`、
   其他頁面、`seed.js`、`pages/index.js`。
2. 如果頁面需要 **LVGL API 我們的 lv.js 沒有**：不要自己改 lv.js。
   在檔案開頭註解寫 `// ⚠ 缺少 API: xxx（已用 yyy 代替）`，並在回報中列出。
3. 如果頁面需要 **bus.shared 的某個 key 才不會空白**：不要改 seed.js，回報 key + 建議的假資料形狀。
4. 註解要留：裝置註解的「為什麼」是這個專案最有價值的資產，翻成中文保留（可以精簡，
   但不要刪掉踩坑說明）。不要整段照抄英文。

## 自我檢查（交件前）

1. 語法：把檔案複製成 `%TEMP%\x.mjs` 跑 `node --check`，必須通過。
2. import 路徑只能用 `@lvui/`、`@packages/`、`../mocks.js`（不要用 `../../` 走到工具層）。
3. 檔案裡不能有 `def `、`lambda`、`None`、`True`、`False`、`.format(`（那是沒翻到的 Python）。
4. 每個 `build()` 都要 `return scr`。
5. `export const meta` 的 id 必須等於裝置 `@register(id=...)`。

## 回報格式

```
完成：projects/slave/pages/<id>.js（<行數> 行）
缺少 API：<清單或「無」>
需要的 seed key：<清單或「無」，附建議形狀>
無法 1:1 的地方：<清單或「無」>
```
