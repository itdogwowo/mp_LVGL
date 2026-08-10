"""本機端驗證：render_framework_code 合法 Python 語法。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from assets import designlib


def main():
    origin = "http://localhost:8600"
    design_name = "lvgl-console-ui"
    meta = designlib.read_design(design_name) or {}
    W = int(meta.get("width", 320))
    H = int(meta.get("height", 240))
    lv, ui = designlib._ui_candidates(design_name)
    if ui is not None:
        d_path = ui.relative_to(designlib.DESIGN_LIB).as_posix()
    else:
        d_path = design_name + "/lvgl/ui"
    try:
        lvgl_rel = lv.relative_to(designlib.DESIGN_LIB).as_posix()
    except Exception:
        lvgl_rel = design_name
    code = designlib.render_framework_code(
        origin=origin, design=design_name,
        width=W, height=H,
        dlib_ui=f"{origin}/dlib/{d_path}",
        dlib_src=f"{origin}/dlib/{d_path}/src",
        dlib_page=f"{origin}/dlib/{d_path}/page",
        dlib_lvgl_root=f"{origin}/dlib/{lvgl_rel}",
    )
    try:
        compile(code, "<framework>", "exec")
        print("[OK] Python syntax valid. bytes=", len(code), "lines=", code.count("\n"))
    except SyntaxError as e:
        print(f"[FAIL] {e.msg} line {e.lineno}")
        lines = code.splitlines()
        for lno in range(max(0, e.lineno - 5), min(len(lines), e.lineno + 5)):
            print(f"  {lno+1:4}: {lines[lno]}")
        return 1
    # Dump first 70 lines for review
    print("--- HEAD 70 lines ---")
    for i, line in enumerate(code.splitlines()[:70]):
        print(f"{i+1:3} | {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
