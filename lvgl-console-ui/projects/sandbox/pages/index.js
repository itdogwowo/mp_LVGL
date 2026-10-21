// pages/index.js — 集中註冊所有頁面（對應 ui/lvgl/page/__init__.py）
//
// 新增頁面流程：
//   1. 建 pages/xxx.js，export const meta = {...} + export function build()
//   2. 下面加一行 import 與 register(...)
//   launcher 會自動出現該頁卡片（order 決定順序）。
//
// 容錯：單頁 import/build 失敗不拖垮其他頁（registry 那層會 catch build）。

import { register } from "@packages/lv-app/registry.js";

import * as settings from "./settings.js";
import * as widgets from "./widgets.js";

register(settings);
register(widgets);

export { settings, widgets };
