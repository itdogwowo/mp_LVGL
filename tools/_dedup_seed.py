# -*- coding: utf-8 -*-
"""移除 lvgl.html 中重複 12 份的 MEMFS seed 區塊，只保留最後一份（含 bin+shim）。"""
import pathlib
import re

p = pathlib.Path(__file__).parent / "workspace" / "cache" / "vendor" / "sim" / "lvgl.html"
s = p.read_text(encoding="utf-8")

mark = "// --- BEGIN LVGL UI STUDIO: seed MEMFS with /sim driver&lib .py ---"
endmark = "// --- END LVGL UI STUDIO ---"

idxs = [m.start() for m in re.finditer(re.escape(mark), s)]
ends = [m.start() for m in re.finditer(re.escape(endmark), s)]

print("seed blocks:", len(idxs))
print("END markers:", len(ends), "at lines", [s.count("\n", 0, e) + 1 for e in ends])
print("last seed block starts at line", s.count("\n", 0, idxs[-1]) + 1)
print("file lines:", s.count("\n") + 1)

# 第 12 份 seed block 起點（保留區起點）
start_keep = idxs[-1]
# 檔案結尾（保留到最後的 END 之後，含結尾）
end_keep = ends[-1] + len(endmark)

prefix = s[:idxs[0]]            # 第 1 份 BEGIN 之前的所有內容
suffix = s[end_keep:]           # 最後 END 之後的內容
keep = s[start_keep:end_keep]   # 最後一份 seed+bin+shim 區段

out = prefix + keep + suffix
out = re.sub(r"\n{3,}", "\n\n", out)  # 收斂多餘空行
p.write_text(out, encoding="utf-8")

print("---- after ----")
print("seed blocks:", len(re.findall(re.escape(mark), out)))
print("END markers:", len(re.findall(re.escape(endmark), out)))
print("file lines:", out.count("\n") + 1)
print("bytes:", len(s), "->", len(out))
