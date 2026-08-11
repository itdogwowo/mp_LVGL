from pathlib import Path
import re

p = Path(__file__).parent / "assets" / "designlib.py"
txt = p.read_text(encoding="utf-8")

# 設計庫的 467 行是 simcode（真實 def）；設計庫的 def _mkdirs 等 8 個函数，位置都在 500 多行的 FRAMEWORK_CODE 字串內容裡（不是設計庫的真實函數）。
# 把 FRAMEWORK_CODE 從 'FRAMEWORK_CODE = """' 開頭到下一個只含 '"""' 的行之間的整段抽出；若這段抽取出來的內容裡有 "def _mkdirs" 當成 Python 語句（頂級縮排），會造成設計庫本身 import 時 syntax error。
#
# 解決方案：把所有 FRAMEWORK_CODE 裡的 `def _XXX(` 開頭（且前面只有 0 或多個空白 + `def`）全部在第一個字前面加空白（讓它們在設計庫解析時仍是字符串內容；但字符串裡保留內容不影響運行）— 不對，字符串內任何內容都 OK。問題是我們真實把字符串結束引號放錯了位置，導致設計庫以為 `def _mkdirs` 是真實的 designlib 函式宣告！
#
# 驗證：找出所有關鍵字 def 在 L500..L920 的位置，用行號印出，觀察哪些在字符串外部。
lines = txt.splitlines()
for i in range(497, 930):
    line = lines[i]
    m = re.match(r'^(\s*)def\s+\w+\s*\(', line)
    if m:
        indent = m.group(1)
        print(f"L{i+1:4d} indent={len(indent):2d} | {line[:100]}")
