// packages/themes/traework/index.js — 設計庫「TraeWork Light」
//
// 對應舊工作區的 colors_and_type.css + components.css：
// 那時是「一份 CSS 被所有頁面引用」；這裡是**一個可以被專案綁定的 theme 套件**。
//
// 為什麼要獨立成資料夾：
//   你之後會有很多風格（不同品牌、深色版、不同密度）。風格之間只差
//   token 與少量尺度，不該讓頁面或工具知道「現在是哪一種」——
//   專案在 project.json 綁 `"theme": { "id": "traework", "version": "1.0.0" }`，
//   模擬器啟動時載入、套用；頁面永遠只寫 `u.TEXT` / `u.mk_card(...)`。
//
// 版本號的用途：project.json 綁的版本跟 theme 宣告的不同時，模擬器會警告
// （舊工作區的 designLibrary.versionSource 就是同一個概念）。

export const id = "traework";
export const version = "1.0.0";
export const title = "TraeWork Light";

/** 顏色：全部是 0xRRGGBB（跟 lv.color_hex 同一個表示法）。 */
export const colors = {
  bg: 0xf5f5f5,
  surface: 0xffffff,
  border: 0xe0e0e0,
  text: 0x1f1f1f,
  text2: 0x5f5f5f,
  text3: 0x8f8f8f,
  primary: 0x1a73e8,
  success: 0x188038,
  warning: 0xf9ab00,
  danger: 0xd93025,
  track: 0xdadce0,
  focus_bg: 0xe8f0fe,
  danger_bg: 0xfce8e6,
};

/** 圓角/尺度：頁面透過 ui_common 的 mk_* 使用，不在頁面裡寫死數字。 */
export const radii = {
  card: 10,
  button: 8,
  list: 3,
};

/** 字級（Montserrat 系列；中文固定走真機 .bin）。 */
export const fonts = {
  numL: 22,
  numM: 16,
  numS: 12,
  numXL: 28,
};

/** 焦點框（nav 的選中視覺）。 */
export const focus = {
  width: 3,
  pad: 3,
};

export default { id, version, title, colors, radii, fonts, focus };
