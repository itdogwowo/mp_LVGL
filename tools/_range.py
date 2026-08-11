from pathlib import Path

p = Path(__file__).parent / "assets" / "designlib.py"
lines = p.read_text(encoding="utf-8").splitlines()

# 把 L498~L916 整段（FRAMEWORK_CODE 的內容）刪除，重寫成外部檔案載入。
# 我們直接把 FRAMEWORK_CODE 整段取代成 placeholder。先備份：
#
# 先找出 FRAMEWORK_CODE 定義起點行號，與 3 引號結尾行號。
head_line = None
close_line = None
for i, line in enumerate(lines):
    if line.startswith('FRAMEWORK_CODE = """') and head_line is None:
        head_line = i
        # scan head: line content = 'FRAMEWORK_CODE = """xxx'？如果有 inline comment 要注意。
        # 這個開頭是「一行只有 FRAMEWORK_CODE = """」+ 內容跟在同一行。實際情況是：
        # FRAMEWORK_CODE = """# ui framework shim — WebAssembly ...
        # 所以第一個 triple quote 就是同一行的開啟。
        # 先判斷 triple quote 在同一行有沒有關閉
        if line.count('"""') >= 2:
            # 同一行關閉（不可能）
            close_line = i
            break
        continue
    if head_line is not None and '"""' in line and line.strip() == '"""':
        close_line = i
        break

print(f"head_line={head_line and head_line+1}, close_line={close_line and close_line+1}")
