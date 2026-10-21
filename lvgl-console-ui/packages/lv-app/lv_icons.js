// ui/lv_icons.js — 圖示名稱 → 字元（對應 ui/lvgl/src/lv_icons.py）
//
// 圖示是「字型」不是圖片：icons_16.bin 裡每個 lucide 名稱對應一個
// Material Symbols 的私有區碼點。用 label 畫 = 免費拿到顏色/縮放/基線對齊。
//
// load_icon_font() 在這裡不做（瀏覽器要 fetch，是非同步的），
// 由 ui_common.init_fonts() 統一載入；這個檔只留資料。

/** lucide 圖示名 → 字元（Material Symbols Rounded）。 */
export const ICONS = {
  activity: "\uF190",
  "alert-triangle": "\uF083",
  "battery-full": "\uE1A5",
  "chevron-down": "\uE313",
  "chevron-left": "\uE5CB",
  "chevron-right": "\uE5CC",
  clock: "\uEFD6",
  droplets: "\uE798",
  fan: "\uF168",
  flame: "\uEF55",
  gauge: "\uE9E4",
  info: "\uE88E",
  "layout-dashboard": "\uE871",
  lightbulb: "\uE90F",
  play: "\uE037",
  power: "\uF8C7",
  "refresh-cw": "\uE5D5",
  save: "\uE161",
  sensors: "\uE51E",
  settings: "\uE8B8",
  shield: "\uE9E0",
  "sliders-horizontal": "\uE429",
  square: "\uE3C6",
  sun: "\uE518",
  thermometer: "\uE1FF",
  "trending-up": "\uE8E5",
  wifi: "\uE63E",
  wind: "\uEFD8",
  zap: "\uEA0B",
};

export default { ICONS };
