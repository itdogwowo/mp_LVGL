#!/usr/bin/env python3
# build_runtime.py — SimLab 一鍵 runtime 對齊工具
#
# 目的:把模擬器的 wasm runtime(官方 sim.lvgl.io v9.0)換成「與真機固件同源」的
# 自建版本(MicroPython 1.29 + LVGL 9.3,你的 fork),編完永久離線。
#
# 以 mp_Make-Tools 慣例為藍本:
#   - 版本 pin 從 ../mp_Make-Tools/git_config.json + config.json(detected)自動帶入
#   - ref 語義:branch = 追最新;commit SHA = 固定點
#   - 源碼優先重用本地 checkout,缺的才 clone;產物放本工具的 build/ 與 sim/
#
# 用法:
#   python tools/simlab/build_runtime.py status     # 各步驟狀態一覽
#   python tools/simlab/build_runtime.py build      # 準備 emsdk/源碼 + 編譯(需 Linux/WSL + 上網一次)
#   python tools/simlab/build_runtime.py swap       # 產物換進 sim/ + 備份 + 記錄
#   python tools/simlab/build_runtime.py verify     # banner/檔案驗證
#   python tools/simlab/build_runtime.py all        # build swap verify 一鍵
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE / "sim"
BUILD_DIR = HERE / "build"
CONFIG_FILE = HERE / "config.json"
RECIPE_FILE = HERE / "runtime_recipe.json"
GIT_ROOT = HERE.parent.parent.parent
MK_TOOLS = GIT_ROOT / "mp_Make-Tools"

_DEPS = ("firmware.wasm", "micropython.js")
# 官方 runtime 的 is_initialized 等行為被 lvgl.html 依賴;swap 只換這兩個檔,
# lvgl.html(iframe 頁)/driver/lib .py(MEMFS seed)由 simlab 自己維護。


def _load_recipe() -> dict:
    if RECIPE_FILE.exists():
        try:
            return json.loads(RECIPE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _mp_make_tools_pins() -> dict:
    """從 mp_Make-Tools 讀真機 pin:git_config.json(ref)+ config.json(detected.head)。"""
    pins: dict[str, dict] = {}
    gc = MK_TOOLS / "git_config.json"
    if gc.exists():
        try:
            cfg = json.loads(gc.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        for name in ("micropython", "lv_binding"):
            spec = cfg.get(name)
            if isinstance(spec, dict):
                pins[name] = {"ref": spec.get("ref")}
    det = MK_TOOLS / "config.json"
    if det.exists():
        try:
            dcfg = json.loads(det.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dcfg = {}
        for name in ("micropython", "lv_binding"):
            dd = (dcfg.get("detected") or {}).get(name)
            if isinstance(dd, dict) and dd.get("head"):
                pins.setdefault(name, {})["detected"] = dd.get("head")
                pins[name]["describe"] = dd.get("describe")
    return pins


def _resolve_refs() -> dict:
    """recipe 覆寫優先;否則用 mp_Make-Tools pin(固定 SHA 優先於 branch)。"""
    recipe = _load_recipe()
    pins = _mp_make_tools_pins()
    out: dict[str, str] = {}
    for name in ("micropython", "lv_binding"):
        r = (recipe.get("sources") or {}).get(name, {}).get("ref")
        if not r and name in pins:
            r = pins[name].get("detected") or pins[name].get("ref")
        out[name] = r or "?"
    return out


def _sh(desc: str) -> bool:
    return shutil.which(desc) is not None


def _banner_of(p: Path) -> str | None:
    try:
        data = p.read_bytes()
        m = re.search(rb"MicroPython (?:v)?[^\x00\" ]+", data)
        return m.group(0).decode("utf-8", errors="replace") if m else None
    except OSError:
        return None


def _write_runtime_info(banner: str | None, built_from: dict) -> None:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    cfg["runtime"] = {
        "built_from": built_from,
        "banner": banner,
        "swapped_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "local": True,
    }
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _abs(p) -> Path | None:
    if not p:
        return None
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else (HERE / q).resolve()


def _src_dir(spec: dict) -> Path:
    """源碼目錄:recipe 的 dir 相對 git root(如 "micropython" → git_root/micropython)。"""
    p = spec.get("dir")
    if not p:
        return GIT_ROOT
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else (GIT_ROOT / q).resolve()


def _git_head(d: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(d), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


# ================= status =================

def cmd_status() -> None:
    refs = _resolve_refs()
    pins = _mp_make_tools_pins()
    recipe = _load_recipe()
    print("== SimLab runtime 狀態 ==")
    print("mp_Make-Tools pin(真機):")
    for name in ("micropython", "lv_binding"):
        p = pins.get(name, {})
        print("  {:<14} ref={:<10} detected={}".format(
            name, p.get("ref", "?"), (p.get("describe") or p.get("detected") or "?")))
    print("sim runtime 目標 refs:")
    for name, r in refs.items():
        print("  {:<14} {}".format(name, r))

    print("\nemsdk(Emscripten):")
    em = recipe.get("emsdk") or {}
    emdir = _abs(em.get("dir"))
    emcc = emdir / "upstream/emscripten/emcc" if emdir else None
    if emcc is not None and emcc.exists():
        print("  ✓ 已安裝 @ {}".format(emdir))
    elif _sh("emcc"):
        print("  ✓ 系統 emcc 可用")
    else:
        print("  ✗ 未安裝(需 Linux/WSL 一次 `emsdk install`;Windows 也可借遠端)")

    print("\n源碼(優先本地 checkout):")
    for name in ("micropython", "lv_binding"):
        spec = (recipe.get("sources") or {}).get(name) or {}
        d = _src_dir(spec)
        if d.exists():
            head = _git_head(d)
            print("  ✓ {:<14} {} @ {}".format(name, d, head or "?"))
        else:
            print("  ✗ {:<14} {} (缺,build 時 clone)".format(name, d))

    print("\n建置產物:")
    wasm = BUILD_DIR / "firmware.wasm"
    if wasm.exists():
        b = _banner_of(wasm)
        print("  ✓ build/firmware.wasm ({} bytes){}{}".format(
            wasm.stat().st_size, " · " + b if b else "", ""))
    else:
        print("  ✗ 無 build/firmware.wasm(先跑 build)")

    print("\nswap 狀態(simlab/sim/):")
    cur = SIM_DIR / "firmware.wasm"
    if cur.exists():
        b = _banner_of(cur)
        print("  ✓ sim/firmware.wasm ({} bytes){}{}".format(
            cur.stat().st_size, " · " + b if b else "", ""))
    else:
        print("  ✗ sim/firmware.wasm 缺失!")
    rt = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("runtime", {}) if CONFIG_FILE.exists() else {}
    if rt.get("swapped_at"):
        print("  上次 swap: {}  built_from={}".format(rt.get("swapped_at"), rt.get("built_from")))
    else:
        print("  未 swap(目前是官方 v9.0 runtime)")

    if _sh("wsl.exe") or os.path.exists("/proc/version"):
        print("\n建置主機:{}".format("WSL 可用" if _sh("wsl.exe") else "本機 Linux"))
    else:
        print("\n建置主機:✗ 無 WSL/Linux — build 需 Linux;swap/verify 可離線執行")


# ================= build =================

def _write_build_script(refs: dict, recipe: dict) -> Path:
    """產出 Linux/WSL 用的一鍵建置腳本(斷點續跑:缺步驟才做)。"""
    mp_dir = _src_dir((recipe.get("sources") or {}).get("micropython", {}))
    lv_dir = _src_dir((recipe.get("sources") or {}).get("lv_binding", {}))
    em = recipe.get("emsdk") or {}
    emdir = _abs(em.get("dir")) or (HERE / ".cache" / "emsdk")
    emsdk_url = em.get("url", "https://github.com/emscripten-core/emsdk.git")
    emver = em.get("version", "3.1.64")
    jobs = os.environ.get("SIMLAB_JOBS", "")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    s = BUILD_DIR / "wasm_build.sh"
    s.write_text("""#!/usr/bin/env bash
# 由 build_runtime.py 產生 — SimLab wasm runtime 一鍵建置(斷點續跑)
set -e
JOBS=${JOBS:-%JOBS%}
REF_MP=%MP_REF%
REF_LV=%LV_REF%

# 1) Emscripten(一次)
if [ ! -x %EMDIR%/upstream/emscripten/emcc ]; then
  echo "[1/4] install emsdk %EMVER% ..."
  git clone --depth=1 %EMSDK_URL% %EMDIR%
  (cd %EMDIR% && ./emsdk install %EMVER% && ./emsdk activate %EMVER%)
fi
source %EMDIR%/emsdk_env.sh >/dev/null 2>&1

# 2) 源碼:micropython(需要 ports/webassembly)
if [ ! -d %MP_DIR%/.git ]; then
  echo "[2/4] clone micropython @ $REF_MP ..."
  git clone --depth=1 https://github.com/itdogwowo/micropython.git %MP_DIR%
fi
if [ "$REF_MP" != "?" ]; then
  (cd %MP_DIR% && git fetch --depth=1 origin $REF_MP 2>/dev/null || true && git checkout -q $REF_MP 2>/dev/null || true)
fi

# 3) lv_binding(含 lvgl submodule = 真機同源 LVGL)
if [ ! -d %LV_DIR%/.git ]; then
  echo "[3/4] clone lv_binding @ $REF_LV ..."
  git clone --recursive https://github.com/itdogwowo/lv_binding_micropython.git %LV_DIR%
fi
if [ "$REF_LV" != "?" ]; then
  (cd %LV_DIR% && git fetch --depth=1 origin $REF_LV 2>/dev/null || true && git checkout -q $REF_LV 2>/dev/null || true)
fi
(cd %LV_DIR% && git submodule update --init --recursive)

# 4) 編譯 ports/webassembly(掛 lv_binding 的 USER_C_MODULES)
echo "[4/4] make -C %MP_DIR%/ports/webassembly ..."
make -j${JOBS:-4} -C %MP_DIR%/ports/webassembly \\
  USER_C_MODULES=%LV_DIR%/micropython.cmake

# 產物集中
mkdir -p %OUT%
cp -f %MP_DIR%/ports/webassembly/build-standard/micropython.wasm %OUT%/firmware.wasm
cp -f %MP_DIR%/ports/webassembly/build-standard/micropython.mjs %OUT%/micropython.js
# 相容舊名(官方 sim 用 micropython.js + firmware.wasm)
if [ ! -f %OUT%/micropython.js ]; then
  cp -f %MP_DIR%/ports/webassembly/build-standard/micropython.mjs %OUT%/micropython.js
fi
echo "done -> %OUT%"
""".replace("%MP_REF%", refs.get("micropython", "?") or "?")
         .replace("%LV_REF%", refs.get("lv_binding", "?") or "?")
         .replace("%EMDIR%", str(emdir).replace("\\", "/"))
         .replace("%EMSDK_URL%", emsdk_url)
         .replace("%EMVER%", emver)
         .replace("%MP_DIR%", str(mp_dir).replace("\\", "/"))
         .replace("%LV_DIR%", str(lv_dir).replace("\\", "/"))
         .replace("%OUT%", str((BUILD_DIR / "wasm").resolve()).replace("\\", "/"))
         .replace("%JOBS%", jobs or "4"))
    s.chmod(0o755)
    return s


def cmd_build(args) -> None:
    refs = _resolve_refs()
    recipe = _load_recipe()
    script = _write_build_script(refs, recipe)
    print("建置腳本: {}".format(script))

    if not (os.path.exists("/proc/version") or _sh("wsl.exe")):
        print("✗ 本機無 Linux 環境。方式:")
        print("  1) WSL2:`wsl.exe bash -lc \"bash {}\"`(需上網一次裝 emsdk)")
        print("  2) 遠端 Linux:把 tools/simlab 整包拷過去,在內執行 `python3 build_runtime.py build`")
        print("  完成後把 build/wasm/ 的產物拿回來,再跑 `python3 build_runtime.py swap`")
        return 1

    if _sh("wsl.exe") and not os.path.exists("/proc/version"):
        wsl = "wsl.exe"
        target = str(script).replace("\\", "/")
        # 轉 /mnt/c/... 路徑
        mnt = "/mnt/" + target[0].lower() + target[2:]
        cmd = [wsl, "bash", "-lc", "cd {} && bash wasm_build.sh".format(mnt)]
        print("在 WSL 執行:", " ".join(cmd))
        if not args.dry_run:
            return subprocess.call(cmd)
        return 0
    print("本機 Linux 執行:", script)
    if not args.dry_run:
        return subprocess.call(["bash", str(script)])
    return 0


# ================= swap =================

def cmd_swap(args) -> None:
    src = BUILD_DIR / "wasm" / "firmware.wasm"
    if not src.exists():
        print("✗ 沒有 build/wasm/firmware.wasm(先跑 build)")
        return 1
    refs = _resolve_refs()
    # 備份現有 runtime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = SIM_DIR / (".bak-" + ts)
    bak.mkdir(exist_ok=True)
    for f in _DEPS:
        p = SIM_DIR / f
        if p.exists():
            shutil.copy2(p, bak / f)
    # 換檔
    for f in _DEPS:
        s = BUILD_DIR / "wasm" / (f.replace(".js", ".mjs") if f == "micropython.js" and not (BUILD_DIR / "wasm" / f).exists() else f)
        if not s.exists():
            print("✗ 產物缺:{}".format(s))
            return 1
        shutil.copy2(s, SIM_DIR / f)
    banner = _banner_of(SIM_DIR / "firmware.wasm")
    _write_runtime_info(banner, refs)
    print("✓ swap 完成 → simlab/sim/(備份在 {})".format(bak))
    if banner:
        print("  banner: {}".format(banner))
    else:
        print("  ⚠ 新 wasm 找不到 MicroPython banner(檢查產物)")
    # lvgl.html 無需改(SimLab 直接維護它);driver/lib .py 無需動(MEMFS seed 自帶)


# ================= verify =================

def cmd_verify() -> None:
    ok = True
    for f in _DEPS + ("lvgl.html",):
        p = SIM_DIR / f
        if not p.exists():
            print("✗ sim/{} 缺失".format(f))
            ok = False
        else:
            print("✓ sim/{} ({} bytes)".format(f, p.stat().st_size))
    b = _banner_of(SIM_DIR / "firmware.wasm")
    if b:
        print("✓ banner: {}".format(b))
    rt = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("runtime", {}) if CONFIG_FILE.exists() else {}
    if rt.get("swapped_at"):
        print("✓ 上次 swap: {} built_from={}".format(rt.get("swapped_at"), rt.get("built_from")))
    print("離線可用:{}".format("✓ 是" if ok else "✗ 否"))
    return 0 if ok else 1


# ================= main =================

def main(argv=None) -> int:
    if sys.version_info < (3, 10):
        print("需要 Python >= 3.10", file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser(description="SimLab runtime 一鍵對齊工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="各步驟狀態一覽")
    p_build = sub.add_parser("build", help="準備 emsdk/源碼 + 編譯(需 Linux/WSL + 上網一次)")
    p_build.add_argument("--dry-run", action="store_true", help="只印指令不執行")
    sub.add_parser("swap", help="產物換進 sim/(備份 + 記錄)")
    sub.add_parser("verify", help="檔案/banner 驗證")
    sub.add_parser("all", help="build swap verify 一鍵")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        return cmd_status() or 0
    if args.cmd == "build":
        return cmd_build(args) or 0
    if args.cmd == "swap":
        return cmd_swap(args) or 0
    if args.cmd == "verify":
        return cmd_verify() or 0
    if args.cmd == "all":
        r1 = cmd_build(args)
        if r1:
            return r1
        r2 = cmd_swap(args)
        if r2:
            return r2
        return cmd_verify()
    return 1


if __name__ == "__main__":
    sys.exit(main())
