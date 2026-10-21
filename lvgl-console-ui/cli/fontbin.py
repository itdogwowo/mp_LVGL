"""cli/fontbin.py — 最小 LVGL binfont 讀取器（只抽 cmap：哪些碼點有字）

為什麼不重寫整個格式：Python 這邊只需要「這個字有沒有」，
不需要 advance / 點陣（那些是 serve.py 不負責的）。所以只解 cmap。

格式（lv_font_conv --format bin v1）：
  head(48B) → cmap → loca → glyf
  cmap: u32 size | 'cmap' | u32 count | count × 16B subheader | data
    subheader: u32 dataOffset, u32 rangeStart, u16 rangeLen,
               u16 gidStart, u16 total, u8 type
    type 0 = format0（每碼點 1 byte delta，0 = 未映射）
    type 1 = sparse（codes[] + ids[]）
    type 2 = format0_tiny（連續，無 data）
    type 3 = sparse_tiny（只有 codes[]）
"""

import struct

_HEAD_SIZE = 48


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _find_table(buf, tag, start=_HEAD_SIZE):
    o = start
    n = len(buf)
    while o + 8 <= n:
        size = _u32(buf, o)
        if size == 0:
            break
        if buf[o + 4:o + 8] == tag:
            return o
        o += (size + 3) & ~3
    return -1


def codepoints(path):
    """回傳這顆字型有的 Unicode 碼點集合。"""
    with open(path, "rb") as f:
        buf = f.read()

    off = _find_table(buf, b"cmap")
    if off < 0:
        raise ValueError("不是 LVGL binfont（找不到 cmap）：" + path)

    count = _u32(buf, off + 8)
    cps = set()
    for i in range(count):
        h = off + 12 + i * 16
        data_off = off + _u32(buf, h)
        range_start = _u32(buf, h + 4)
        range_len = _u16(buf, h + 8)
        total = _u16(buf, h + 12)
        typ = buf[h + 14]

        if typ == 2:  # format 0 tiny：連續碼點全部有
            cps.update(range(range_start, range_start + range_len))
        elif typ == 3:  # sparse tiny：data 是 code delta 陣列
            for k in range(total):
                cps.add(range_start + _u16(buf, data_off + k * 2))
        elif typ == 0:  # format 0：delta 0 = 空插槽
            for k in range(range_len):
                if buf[data_off + k]:
                    cps.add(range_start + k)
        elif typ == 1:  # sparse：code delta 陣列（前半）
            for k in range(total):
                cps.add(range_start + _u16(buf, data_off + k * 2))
    return cps
