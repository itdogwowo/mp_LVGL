// ui/core/font.js — LVGL 二進位字型(.bin)載入 + 量測 + 繪製
//
// 為什麼要自己解 .bin，而不是用瀏覽器的系統字型？
// ────────────────────────────────────────────────────────────
// 這層 JS 的唯一目的是「先把 UI 在瀏覽器做到定稿，再逐頁轉成 MicroPython」。
// 轉換時最容易出錯的不是 API，是**版面**：同一個字串在裝置上是幾 px 寬，
// 決定 label 會不會爆框、list 會不會擠。系統字型的 advance 跟裝置的
// lv_font_conv 產物不一樣（Arial Unicode vs 瀏覽器 CJK 字型），量出來的寬度
// 差 1~2px，累積起來整列就偏了。
// ⇒ 直接讀裝置正在用的那顆 .bin，字形、字寬、baseline 全部跟真機同一份。
//
// 格式來源：lvgl/lv_font_conv `lib/font/table_*.js`（--format bin, version 1）
//   head(48B 固定) → cmap → loca → glyf → kern(本專案沒有)
//   本專案兩顆字型都是 --no-compress(=compression 0)、bpp 4。
//
// 注意：這個解析器**不支援壓縮**(compression 1/2/3)。真的遇到就明確報錯，
// 不要靜默畫出亂碼 —— 那比沒有字更難查。

const TAG_HEAD = 0x68656164; // 'head'
const TAG_CMAP = 0x636d6170; // 'cmap'

const SUB_FORMAT_0 = 0;
const SUB_FORMAT_SPARSE = 1;
const SUB_FORMAT_0_TINY = 2;
const SUB_FORMAT_SPARSE_TINY = 3;

function align4(n) {
  return (n + 3) & ~3;
}

/** 大端位元讀取器（lv_font_conv 用 bit-buffer，bigEndian）。 */
class BitReader {
  constructor(bytes, byteOffset) {
    this.b = bytes;
    this.pos = byteOffset * 8; // bit position
  }
  bits(n) {
    let v = 0;
    for (let i = 0; i < n; i++) {
      const bit = (this.b[this.pos >> 3] >> (7 - (this.pos & 7))) & 1;
      v = (v << 1) | bit;
      this.pos++;
    }
    return v;
  }
  /** n 位元二補數（有號）。 */
  sbits(n) {
    const v = this.bits(n);
    const sign = 1 << (n - 1);
    return v & sign ? v - (sign << 1) : v;
  }
}

/**
 * 一顆 LVGL .bin 字型。
 *
 * 對外只需要三件事：lineHeight / measure(text) / draw(ctx, ...)。
 * 其餘(cmap/loca/glyf)都收在私有欄位，模仿 LVGL 內部的三張表。
 */
export class BinFont {
  /**
   * @param {ArrayBuffer} buffer  .bin 檔內容
   * @param {string} name         除錯用名稱
   */
  constructor(buffer, name = "binfont") {
    this.name = name;
    const b = new Uint8Array(buffer);
    this.bytes = b;
    this.dv = new DataView(buffer);

    if (this.u32(0) !== align4(this.u32(0))) throw new Error(`${name}: head size 不是 4 對齊`);
    if (this._tagAt(4) !== TAG_HEAD) throw new Error(`${name}: 開頭不是 head table`);

    this.version = this.u32(8);
    this.tables = this.u16(12);
    this.size = this.u16(14);
    this.ascent = this.u16(16); // 注意：寫入時是 UInt16，讀回仍視為正值
    this.descent = this.i16(18);
    this.typoAscent = this.u16(20);
    this.typoDescent = this.i16(22);
    this.typoLineGap = this.u16(24);
    this.minY = this.i16(26);
    this.maxY = this.i16(28);
    this.defaultAdvance = this.u16(30);
    this.kerningScale = this.u16(32) / 16; // FP12.4
    this.indexToLocFormat = b[34]; // 0=u16(÷2?), 1=u32
    this.glyphIdFormat = b[35]; // 0=u8, 1=u16
    this.advanceWidthFormat = b[36]; // 0=int, 1=FP4
    this.bpp = b[37];
    this.xyBits = b[38];
    this.whBits = b[39];
    this.advanceWidthBits = b[40];
    this.compressionId = b[41];
    this.subpixelsMode = b[42];
    this.underlinePosition = this.i16(44);
    this.underlineThickness = this.u16(46);

    if (this.compressionId !== 0) {
      throw new Error(
        `${name}: 壓縮字型(compression=${this.compressionId})不支援；` +
          `請用 lv_font_conv --no-compress 重新產生`
      );
    }

    this.monospace = this.defaultAdvance > 0;

    // LVGL 的 line_height：ascent 到 descent 的整條行高。
    // 真機值：16px 中文字型 ascent=15 / descent=-4 ⇒ 19px（實測行距接近 20）。
    this.lineHeight = this.ascent - this.descent;

    this._codeToGlyph = new Map(); // codepoint → glyph id
    this._glyphs = []; // glyph id → {adv,ofsX,ofsY,w,h,pixels}
    this._atlas = new Map(); // `${gid}|${color}` → canvas
    /** 這顆字型缺少、但畫面真的用到的字（harness 會把它列出來） */
    this.missing = new Set();

    const cmapOff = this._findTable(TAG_CMAP, 48);
    this._readCmap(cmapOff);
    const locaOff = this._findTable(0x6c6f6361, cmapOff + align4(this.u32(cmapOff)));
    const glyfOff = this._findTable(0x676c7966, locaOff + align4(this.u32(locaOff)));
    this._readGlyphs(locaOff, glyfOff);
  }

  // ───────────── 基本讀取 ─────────────
  u8(o) {
    return this.bytes[o];
  }
  u16(o) {
    return this.dv.getUint16(o, true);
  }
  i16(o) {
    return this.dv.getInt16(o, true);
  }
  u32(o) {
    return this.dv.getUint32(o, true);
  }

  _tagAt(o) {
    return (this.bytes[o] << 24) | (this.bytes[o + 1] << 16) | (this.bytes[o + 2] << 8) | this.bytes[o + 3];
  }

  /** 從 start 起找下一個 table（格式：u32 size, 4B tag, payload）。 */
  _findTable(tag, start) {
    for (let o = start; o < this.bytes.length - 8; o += align4(this.u32(o))) {
      if (this._tagAt(o + 4) === tag) return o;
      if (this.u32(o) === 0) break;
    }
    throw new Error(`${this.name}: 找不到 table 0x${tag.toString(16)}`);
  }

  // ───────────── cmap ─────────────
  _readCmap(off) {
    const count = this.u32(off + 8);
    const subs = off + 12;
    for (let i = 0; i < count; i++) {
      const h = subs + i * 16;
      const dataOff = off + this.u32(h);
      const rangeStart = this.u32(h + 4);
      const rangeLen = this.u16(h + 8);
      const gidStart = this.u16(h + 10);
      const total = this.u16(h + 12);
      const type = this.u8(h + 14);

      if (type === SUB_FORMAT_0_TINY) {
        // 連續碼點，glyph id 從 gidStart 起連續遞增。無 data。
        for (let k = 0; k < rangeLen; k++) this._codeToGlyph.set(rangeStart + k, gidStart + k);
      } else if (type === SUB_FORMAT_0) {
        // 連續碼點 + 每點 1 byte 的 id delta。
        for (let k = 0; k < rangeLen; k++) {
          const delta = this.u8(dataOff + k);
          if (delta !== 0) this._codeToGlyph.set(rangeStart + k, gidStart + delta);
        }
      } else if (type === SUB_FORMAT_SPARSE_TINY) {
        // 離散碼點：只存 code delta，id 依 index 遞增。
        for (let k = 0; k < total; k++) {
          const code = rangeStart + this.u16(dataOff + k * 2);
          this._codeToGlyph.set(code, gidStart + k);
        }
      } else if (type === SUB_FORMAT_SPARSE) {
        // 離散碼點：code delta 與 id delta 各一段。
        const codesAt = dataOff;
        const idsAt = dataOff + total * 2;
        for (let k = 0; k < total; k++) {
          const code = rangeStart + this.u16(codesAt + k * 2);
          const id = gidStart + this.u16(idsAt + k * 2);
          this._codeToGlyph.set(code, id);
        }
      } else {
        throw new Error(`${this.name}: 未知 cmap subtable type ${type}`);
      }
    }
    this.glyphCount = Math.max(...this._codeToGlyph.values()) + 1;
  }

  // ───────────── loca + glyf ─────────────
  _readGlyphs(locaOff, glyfOff) {
    const count = this.u32(locaOff + 8); // 含保留 id 0
    const base = locaOff + 12;
    const offsets = new Array(count);
    for (let i = 0; i < count; i++) {
      // ⚠️ 兩種格式存的都是「原始 byte offset」，不是 OpenType 的 offset/2。
      //    lv_font_conv 的 table_loca 直接寫 getOffset()(byte)，LVGL 的 loader
      //    也照原值用；一開始照 OpenType 慣例乘 2，整個 glyf 就讀到錯位置，
      //    症狀是每個字都是 0x0 空白（icons 字型踩到）。
      offsets[i] =
        this.indexToLocFormat === 0 ? this.u16(base + i * 2) : this.u32(base + i * 4);
    }
    this.glyphCount = count;

    const nBitsAdv = this.monospace ? 0 : this.advanceWidthBits;
    for (let gid = 1; gid < count; gid++) {
      const at = glyfOff + offsets[gid];
      const r = new BitReader(this.bytes, at);
      let adv = this.monospace ? this.defaultAdvance : r.bits(nBitsAdv);
      const x = r.sbits(this.xyBits);
      const y = r.sbits(this.xyBits);
      const w = r.bits(this.whBits);
      const h = r.bits(this.whBits);

      // ofs_y：glyph 頂端到「行頂」的距離。
      //
      // .bin 裡的 y 是 **baseline 往上量的字形底邊**（不是 OpenType 的 bearing）：
      // 證據是 head.min_y / head.max_y 正好等於「所有 glyph 的 min(y) / max(y+h)」
      // （zh：-4 / 15 = descent / ascent），'A' 的 y=0 代表它貼齊 baseline。
      // 所以：頂端 = baseline + y + h ⇒ ofsY = ascent - y - h。
      // （一開始寫成 ascent - y，每個字都往下掉 12~15px，整頁文字會沉到框外。）
      const ofsY = this.ascent - y - h;

      let pixels = null;
      if (w > 0 && h > 0) {
        pixels = new Uint8Array(w * h);
        const maxv = (1 << this.bpp) - 1;
        for (let p = 0; p < w * h; p++) {
          const v = r.bits(this.bpp);
          pixels[p] = (v * 255) / maxv;
        }
      }
      this._glyphs[gid] = { gid, adv, ofsX: x, ofsY, w, h, pixels };
    }
  }

  // ───────────── 查詢 ─────────────
  glyphId(codePoint) {
    return this._codeToGlyph.get(codePoint) ?? 0;
  }

  hasChar(ch) {
    return this._codeToGlyph.has(ch.codePointAt(0));
  }

  glyph(codePoint) {
    const gid = this.glyphId(codePoint);
    return this._glyphs[gid] ?? null;
  }

  /** 量測寬度（LVGL label 的 size_to_content 用的就是這個）。 */
  measure(text) {
    let w = 0;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      const g = this._glyphs[this.glyphId(cp)];
      if (g) w += g.adv;
      else if (cp === 9) w += this.size * 2; // tab 近似
      else {
        // 缺字：LVGL 開著 LV_USE_FONT_PLACEHOLDER（預設開）時會畫一個方框，
        // 寬度是 line_height/2 + 2。照著做，版面才不會跟真機差一段。
        this.missing.add(cp);
        w += this._placeholder().adv;
      }
    }
    return w;
  }

  /** LVGL 的缺字替代方塊尺寸。 */
  _placeholder() {
    const box = Math.max(4, Math.floor(this.lineHeight / 2));
    return { box, adv: box + 2 };
  }

  /** 某個字元的 advance（除錯用）。 */
  advanceOf(ch) {
    const g = this._glyphs[this.glyphId(ch.codePointAt(0))];
    return g ? g.adv : 0;
  }

  /** 取得「指定顏色」的字形小畫布（延遲建立 + 快取）。 */
  _glyphCanvas(g, colorCss) {
    const key = g.gid + "|" + colorCss;
    let cv = this._atlas.get(key);
    if (cv) return cv;
    if (typeof document === "undefined") return null; // node 測試環境

    cv = document.createElement("canvas");
    cv.width = g.w;
    cv.height = g.h;
    const c = cv.getContext("2d");
    const img = c.createImageData(g.w, g.h);
    const [r, gg, bb] = parseCssColor(colorCss);
    for (let i = 0; i < g.pixels.length; i++) {
      const a = g.pixels[i];
      img.data[i * 4 + 0] = r;
      img.data[i * 4 + 1] = gg;
      img.data[i * 4 + 2] = bb;
      img.data[i * 4 + 3] = a;
    }
    c.putImageData(img, 0, 0);
    this._atlas.set(key, cv);
    return cv;
  }

  /**
   * 繪製一行文字。
   * @param {CanvasRenderingContext2D} ctx
   * @param {string} text
   * @param {number} x       文字框左上角
   * @param {number} y       文字框左上角（行頂）
   * @param {string} colorCss
   * @param {number} opa     0..255
   * @param {number} letterSpace 額外字距 px（LVGL text_letter_space）
   */
  draw(ctx, text, x, y, colorCss, opa = 255, letterSpace = 0) {
    if (opa <= 0) return;
    const prevAlpha = ctx.globalAlpha;
    if (opa < 255) ctx.globalAlpha = prevAlpha * (opa / 255);

    let penX = 0;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      const g = this._glyphs[this.glyphId(cp)];
      if (!g) {
        // 缺字 → 畫方框（跟 LVGL 的 LV_USE_FONT_PLACEHOLDER 行為一致）
        if (cp !== 9 && cp !== 10) {
          this.missing.add(cp);
          const ph = this._placeholder();
          ctx.strokeStyle = colorCss;
          ctx.lineWidth = 1;
          ctx.strokeRect((x + penX + 0.5) | 0, (y + 3.5) | 0, ph.box, ph.box);
          penX += ph.adv;
        }
        continue;
      }
      if (g.pixels) {
        const cv = this._glyphCanvas(g, colorCss);
        if (cv) ctx.drawImage(cv, (x + penX + g.ofsX) | 0, (y + g.ofsY) | 0);
      }
      penX += g.adv + letterSpace;
    }
    ctx.globalAlpha = prevAlpha;
  }
}

function parseCssColor(css) {
  // 只接受 #rrggbb（本層顏色一律由 lv.color_hex 產生）
  const v = parseInt(css.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

/**
 * 系統字型（給 Montserrat 系列用）。
 *
 * 裝置上的 F_NUM_L/M/S/XL 是 LVGL 內建的 montserrat 12/14/16/22/28。
 * 我們沒有那幾顆 .bin，所以用同 px 的瀏覽器字型近似。
 *
 * ★ 但有一個地方**不能**用瀏覽器的能力去補：**中文**。
 *   瀏覽器會很樂意用系統字型把「模式 1」畫出來，可是真機的 montserrat 沒有 CJK，
 *   那一行在面板上是方框。這個差異會讓「用錯字型」的 bug 在模擬器裡完全看不到
 *   —— 而 DEV_NOTES 記錄過，這正是真機實際踩到的坑（一整排方格）。
 *   ⇒ 這裡照 LVGL 的行為：CJK 一律畫 placeholder 方框 + 記進 missing。
 */
export class SystemFont {
  constructor(px, family = "Montserrat, 'Segoe UI', system-ui, sans-serif", weight = 400) {
    this.px = px;
    this.family = family;
    this.weight = weight;
    this.name = `sys:${px}px`;
    this.ascent = Math.round(px * 0.75);
    this.descent = -(px - this.ascent);
    this.lineHeight = Math.round(px * 1.2);
    this._ctx = null;
    this._cache = new Map();
    this._missing = new Set();
    /** 這顆字型缺少、但畫面真的用到的字 */
    this.missing = this._missing;
  }

  /**
   * 這顆字型能不能畫這個字元？
   * LVGL 內建 montserrat 的覆蓋範圍 ≈ ASCII + 少量符號；CJK 一定沒有。
   */
  static canRender(cp) {
    if (cp >= 0x20 && cp <= 0x7e) return true;
    // 這幾個是 lv_font_conv 預設會帶進 montserrat 的符號
    return [0xb0, 0xb1, 0xd7, 0xf7, 0x2022, 0x2026, 0x2190, 0x2191, 0x2192, 0x2193].includes(cp);
  }

  _measurer() {
    if (!this._ctx) {
      const cv = document.createElement("canvas");
      this._ctx = cv.getContext("2d");
      this._ctx.font = `${this.weight} ${this.px}px ${this.family}`;
    }
    return this._ctx;
  }

  get cssFont() {
    return `${this.weight} ${this.px}px ${this.family}`;
  }

  _charWidth(ch) {
    let w = this._cache.get(ch);
    if (w === undefined) {
      w = this._measurer().measureText(ch).width;
      this._cache.set(ch, w);
    }
    return w;
  }

  _placeholder() {
    const box = Math.max(4, Math.floor(this.lineHeight / 2));
    return { box, adv: box + 2 };
  }

  measure(text) {
    if (!text) return 0;
    let w = 0;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (SystemFont.canRender(cp)) w += this._charWidth(ch);
      else {
        this._missing.add(cp);
        w += this._placeholder().adv;
      }
    }
    return Math.round(w);
  }

  draw(ctx, text, x, y, colorCss, opa = 255, letterSpace = 0) {
    if (!text || opa <= 0) return;
    const prevAlpha = ctx.globalAlpha;
    const prevFont = ctx.font;
    const prevFill = ctx.fillStyle;
    const prevBaseline = ctx.textBaseline;
    if (opa < 255) ctx.globalAlpha = prevAlpha * (opa / 255);
    ctx.font = this.cssFont;
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = colorCss;

    let penX = x;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (SystemFont.canRender(cp)) {
        ctx.fillText(ch, penX, y + this.ascent);
        penX += this._charWidth(ch) + letterSpace;
      } else {
        this._missing.add(cp);
        const ph = this._placeholder();
        ctx.strokeStyle = colorCss;
        ctx.lineWidth = 1;
        ctx.strokeRect((penX + 0.5) | 0, (y + 3.5) | 0, ph.box, ph.box);
        penX += ph.adv;
      }
    }

    ctx.globalAlpha = prevAlpha;
    ctx.font = prevFont;
    ctx.fillStyle = prevFill;
    ctx.textBaseline = prevBaseline;
  }
}

/** fetch + parse。回傳 BinFont。 */
export async function loadBinFont(url, name) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`字型載入失敗 ${url}: HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  return new BinFont(buf, name || url.split("/").pop());
}
