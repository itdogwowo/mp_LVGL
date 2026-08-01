# fxgen.py — 動態效果 helper 生成
#
# 把設計稿的 CSS 動效（@keyframes / transition / :hover/:active/:focus）
# 翻譯成 LVGL 對應 helper,輸出:
#   lv_ui_fx.py   板上可用的動效函式
#   fx_notes.md   CSS → LVGL 對照說明（含不支援項目）
#
# 動效分類（依 animation 名稱）:
#   pulse 類    → pulse()      呼吸閃爍（livedot / tag dot）
#   淡入類      → fade_in()    載入淡入 + 位移（rise / fade-in / tile-in）
#   bar-grow    → bar_grow()   bar 數值成長
#   mon-draw 等 → 註記略過（SVG stroke 動畫,LVGL 無對應）
#   hover/active/focus → set_state_colors() 狀態換色
from __future__ import annotations

from pathlib import Path

from . import OUT_DIR

# animation 名 → (分類, helper 名稱)
_PULSE_NAMES = {"pulse", "live-ping", "mon-ping"}
_FADE_NAMES = {"rise", "fade-in", "set-in", "tile-in", "mon-fade"}
_GROW_NAMES = {"bar-grow"}
_SKIP_NAMES = {"mon-draw"}  # SVG stroke-dashoffset 描繪,LVGL 無對應
_SHIMMER_NAMES = {"ds-skeleton-shine"}  # skeleton 掃光,一般 UI 不需要

FX_HELPER = """# lv_ui_fx.py — 動態效果 helper（由 LVGL UI Asset Studio 產生）
#
# 對應設計稿 CSS 動效（用 lv_binding_micropython 的 anim API）:
#   pulse()    ← pulse / live-ping / mon-ping（呼吸閃爍:livedot、tag dot、狀態燈）
#   fade_in()  ← rise / fade-in / set-in / tile-in（載入淡入 + 位移）
#   bar_grow() ← bar-grow（數值/進度成長）
#   set_state_colors() ← :hover/:active/:focus（焦點/按壓換色,配合 set_focus 外框）
#
# 注意:此 binding 的 anim API 是 lv.anim_t()（沒有 lv.anim()）:
#   - set_time() 不存在 → 用 set_duration()（LVGL 9）
#   - 呼吸來回用 set_reverse_duration()（播放完反向播）
#   - 無限重複用 repeat_count = 0xFFFF（LV_ANIM_REPEAT_INFINITE）
# anim 不可用時自動降級為「直接設定最終值」,不影響功能。
import lvgl as lv

_ANIM_CLASS = getattr(lv, "anim_t", None)
_REPEAT_INF = 0xFFFF  # LV_ANIM_REPEAT_INFINITE


def _anim_start(a):
    try:
        a.init()
    except Exception:
        pass
    a.start()
    return a


def pulse(wid, period_ms=1500, min_opa=110, max_opa=255):
    \"\"\"呼吸閃爍:opa 在 min/max 間往返,永續播放。CSS 'pulse' 對應。\"\"\"
    if _ANIM_CLASS is None:
        wid.set_style_opa(max_opa, 0)
        return None
    half = max(80, period_ms // 2)
    a = _ANIM_CLASS()
    a.set_var(wid)
    a.set_values(max_opa, min_opa)
    a.set_duration(half)
    a.set_reverse_duration(half)
    a.set_repeat_count(_REPEAT_INF)
    a.set_custom_exec_cb(lambda _a, v: wid.set_style_opa(int(v), 0))
    return _anim_start(a)


def fade_in(wid, dy=6, time_ms=300, delay_ms=0):
    \"\"\"載入淡入 + 向上位移。CSS 'rise'/'fade-in' 對應。\"\"\"
    x, y = wid.get_x(), wid.get_y()
    if _ANIM_CLASS is None:
        wid.set_style_opa(255, 0)
        return None
    a = _ANIM_CLASS()
    a.set_var(wid)
    a.set_values(y + dy, y)
    a.set_duration(time_ms)
    a.set_delay(delay_ms)
    a.set_custom_exec_cb(lambda _a, v: wid.set_pos(x, int(v)))
    _anim_start(a)

    b = _ANIM_CLASS()
    b.set_var(wid)
    b.set_values(0, 255)
    b.set_duration(time_ms)
    b.set_delay(delay_ms)
    b.set_custom_exec_cb(lambda _a, v: wid.set_style_opa(int(v), 0))
    _anim_start(b)
    return (a, b)


def bar_grow(bar, from_val=0, to_val=None, time_ms=400):
    \"\"\"進度/數值成長動畫。CSS 'bar-grow' 對應。\"\"\"
    to_val = to_val if to_val is not None else bar.get_value()
    if _ANIM_CLASS is None:
        bar.set_value(to_val, 0)
        return None
    a = _ANIM_CLASS()
    a.set_var(bar)
    a.set_values(from_val, to_val)
    a.set_duration(time_ms)
    a.set_custom_exec_cb(lambda _a, v: bar.set_value(int(v), 0))
    return _anim_start(a)


def set_state_colors(wid, on, color_on, color_off, part=0):
    \"\"\"依狀態切換文字/元件顏色。CSS ':hover/:active/:focus' 換色對應。\"\"\"
    wid.set_style_text_color(
        lv.color_hex(color_on if on else color_off), part)
"""


def classify(name: str) -> tuple[str, str]:
    if name in _PULSE_NAMES:
        return "呼吸閃爍", "pulse()"
    if name in _FADE_NAMES:
        return "載入淡入+位移", "fade_in()"
    if name in _GROW_NAMES:
        return "進度成長", "bar_grow()"
    if name in _SHIMMER_NAMES:
        return "skeleton 掃光(一般不需)", "— 略過"
    if name in _SKIP_NAMES:
        return "SVG stroke 描繪,LVGL 無對應", "— 略過"
    return "未分類", "手動對應"


def _state_label(state: str) -> str:
    return {
        "hover": "hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED)",
        "active": "active(按下),可用 press 事件",
        "focus": "focus(焦點),配合 set_focus 外框",
        "focus-visible": "focus(焦點)",
        "focus-within": "focus(焦點)",
    }.get(state, state)


def generate_fx(scan_result: dict, log=None,
                out_root: Path | None = None) -> dict:
    """生成動效 helper。out_root 預設 OUT_DIR,design 模式下傳該 design 的 lvgl/src。"""
    out_root = out_root or OUT_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    notes = [
        "# CSS 動效 → LVGL 對照表（由 LVGL UI Asset Studio 產生）",
        "",
        "設計稿裡的動態效果大多可以在 LVGL 用 `lv.anim` + style state 重現。",
        "以下為掃描工作區設計稿後的對照結果。",
        "",
    ]

    # 1) 動畫
    anims = scan_result.get("fx", {}).get("animations", [])
    notes += ["## @keyframes 動畫", "", "| CSS 動畫 | 效果 | LVGL 對應 |", "|---|---|---|"]
    for a in anims:
        kind, helper = classify(a["name"])
        notes.append(f"| `{a['name']}` | {kind} | {helper} |")
    notes += [""]

    # 2) hover/active/focus
    hovers = scan_result.get("fx", {}).get("hover", [])
    seen = {}
    for h in hovers:
        key = (h["selector"], h["state"])
        seen.setdefault(key, []).append(h["file"])
    notes += ["## :hover / :active / :focus", "", "| 選擇器 | 狀態 | LVGL 對應 | 出現於 |", "|---|---|---|---|"]
    for (sel, state), files in sorted(seen.items()):
        notes.append(
            f"| `{sel}` | `{state}` | {_state_label(state)} | {', '.join(files[:2])} |"
        )
    notes += [""]

    # 3) transitions
    trs = scan_result.get("fx", {}).get("transitions", [])
    if trs:
        props = sorted({t["props"].split(",")[0].strip() for t in trs})
        notes += [
            "## transition（過渡）",
            "",
            "LVGL 沒有 CSS transition 的「自動插值」;換樣式通常直接跳變。",
            "需要平滑時改用對應的 lv.anim。",
            "",
            f"設計稿過渡的屬性: `{'、'.join(props[:10])}`",
            "",
        ]

    notes += [
        "## 不支援 / 略過",
        "",
        "| 項目 | 原因 |",
        "|---|---|",
        "| mon-draw / mon-fade | SVG stroke 描繪動畫,LVGL 無 SVG 路徑動畫 |",
        "| box-shadow / color-mix | LVGL shadow 可用但效果有限;color-mix 漸層不支援 |",
        "| carousel__track 滑動 | 用 set_pos() + 自訂動畫即可,或維持直接切換 |",
        "| skeleton 掃光 | 一般嵌入式 UI 不需要 |",
        "",
        "---",
        f"產生時間: {__import__('time').strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    (out_root / "fx_notes.md").write_text("\n".join(notes), encoding="utf-8")
    (out_root / "lv_ui_fx.py").write_text(FX_HELPER, encoding="utf-8")
    log and log("fx 完成: lv_ui_fx.py + fx_notes.md")

    return {
        "animations": len(anims),
        "hover_states": len(seen),
        "transitions": len(trs),
    }
