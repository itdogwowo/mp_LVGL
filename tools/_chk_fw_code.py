from pathlib import Path

p = Path(__file__).parent / "assets" / "designlib.py"
txt = p.read_text(encoding="utf-8")

# 找出 FRAMEWORK_CODE = """ 開頭
idx_head = txt.find('FRAMEWORK_CODE = """')
if idx_head < 0:
    raise SystemExit("FRAMEWORK_CODE head not found")
head_end = txt.find("\n", idx_head) + 1  # 第一個 triple-quote 行結束

# 找出其後下一個行首 """\n（關閉）
idx_close = txt.find('\n"""', head_end)
if idx_close < 0:
    raise SystemExit("FRAMEWORK_CODE close not found")
close_end = idx_close + 4  # 吃掉 \n"""
extracted = txt[head_end:idx_close]
print(f"head line end offset={head_end}, close_offset={idx_close} length={len(extracted)}")

# 1) 當設計庫模塊看能不能 import
import sys
sys.path.insert(0, str(Path(__file__).parent))
try:
    from assets import designlib
    print("import designlib OK")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    lines = txt.splitlines()
    bad = lines[e.lineno - 1]
    print(f"L{e.lineno}: {bad}")
    raise SystemExit(1)

# 2) 渲染出 framework 碼再 compile
code = designlib.render_framework_code(
    origin="http://localhost:8600",
    design="lvgl-console-ui",
    width=320,
    height=240,
    dlib_ui="http://localhost:8600/dlib/lvgl-console-ui/lvgl/ui",
    dlib_src="http://localhost:8600/dlib/lvgl-console-ui/lvgl/ui/src",
    dlib_page="http://localhost:8600/dlib/lvgl-console-ui/lvgl/ui/page",
    dlib_lvgl_root="http://localhost:8600/dlib/lvgl-console-ui",
)
try:
    compile(code, "<framework-rendered>", "exec")
    print(f"compile rendered OK, {len(code)} bytes, {code.count(chr(10))} lines")
except SyntaxError as e:
    print(f"rendered SyntaxError: {e}")
    lines = code.splitlines()
    a = max(0, e.lineno - 5)
    b = min(len(lines), e.lineno + 5)
    for lno in range(a, b):
        marker = " >>" if lno == e.lineno - 1 else "   "
        print(f"{marker} {lno+1:4}: {lines[lno]}")
    raise SystemExit(1)

# dump head
print("==== RENDERED HEAD (first 40 lines) ====")
lines = code.splitlines()
for i, line in enumerate(lines[:40]):
    print(f"  L{i+1:3}| {line}")
