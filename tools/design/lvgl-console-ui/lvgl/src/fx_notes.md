# CSS 動效 → LVGL 對照表（由 LVGL UI Asset Studio 產生）

設計稿裡的動態效果大多可以在 LVGL 用 `lv.anim` + style state 重現。
以下為掃描工作區設計稿後的對照結果。

## @keyframes 動畫

| CSS 動畫 | 效果 | LVGL 對應 |
|---|---|---|
| `bar-grow` | 進度成長 | bar_grow() |
| `ds-skeleton-shine` | skeleton 掃光(一般不需) | — 略過 |
| `fade-in` | 載入淡入+位移 | fade_in() |
| `live-ping` | 呼吸閃爍 | pulse() |
| `mon-draw` | SVG stroke 描繪,LVGL 無對應 | — 略過 |
| `mon-fade` | 載入淡入+位移 | fade_in() |
| `mon-ping` | 呼吸閃爍 | pulse() |
| `pulse` | 呼吸閃爍 | pulse() |
| `rise` | 載入淡入+位移 | fade_in() |
| `set-in` | 載入淡入+位移 | fade_in() |
| `tile-in` | 載入淡入+位移 | fade_in() |

## :hover / :active / :focus

| 選擇器 | 狀態 | LVGL 對應 | 出現於 |
|---|---|---|---|
| `.alarm-card` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | overview.html |
| `.alarm-more` | `active` | active(按下),可用 press 事件 | overview.html |
| `.alarm-more` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | overview.html, overview.html |
| `.alarm-row` | `active` | active(按下),可用 press 事件 | overview.html |
| `.alarm-row` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | overview.html |
| `.app-card` | `focus` | focus(焦點),配合 set_focus 外框 | launcher.html |
| `.app-card.is-active` | `active` | active(按下),可用 press 事件 | launcher.html |
| `.app-card.is-active` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | launcher.html, launcher.html |
| `.appbar__back` | `active` | active(按下),可用 press 事件 | control.html, overview.html |
| `.appbar__back` | `focus` | focus(焦點),配合 set_focus 外框 | control.html, overview.html |
| `.appbar__back` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | control.html, monitor.html |
| `.carousel__arrow` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | launcher.html |
| `.carousel__viewport` | `active` | active(按下),可用 press 事件 | launcher.html |
| `.dot` | `focus` | focus(焦點),配合 set_focus 外框 | launcher.html |
| `.ds-btn--brand` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--brand` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--danger` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--danger` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--danger-subtle` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--danger-subtle` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--link` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--primary` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--primary` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--secondary` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--secondary` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--tertiary` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--tertiary` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-btn--warning` | `active` | active(按下),可用 press 事件 | components.css, control.html |
| `.ds-btn--warning` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-dialog__close` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-input` | `focus` | focus(焦點),配合 set_focus 外框 | components.css, components.css |
| `.ds-menu__item` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-notif__close` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-pagination__item` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-select` | `focus` | focus(焦點),配合 set_focus 外框 | components.css, control.html |
| `.ds-slider` | `active` | active(按下),可用 press 事件 | control.html |
| `.ds-slider` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | control.html |
| `.ds-tab` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `.ds-textarea` | `focus` | focus(焦點),配合 set_focus 外框 | components.css, control.html |
| `.kpi-tile` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | overview.html |
| `.mon-ch__row` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | monitor.html |
| `.mon-pill` | `focus` | focus(焦點),配合 set_focus 外框 | monitor.html |
| `.mon-pill` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | monitor.html |
| `.mon-refresh` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | monitor.html |
| `.relay-tile` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | control.html |
| `.seg__item` | `active` | active(按下),可用 press 事件 | control.html |
| `.seg__item` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | control.html |
| `.seg__item.is-active` | `active` | active(按下),可用 press 事件 | control.html |
| `.seg__item.is-active` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | control.html |
| `.tag-field` | `focus` | focus(焦點),配合 set_focus 外框 | components.css, control.html |
| `.tag-remove` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `a` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |
| `button` | `hover` | hover(滑鼠/焦點),嵌入式可用 add_state(CHECKED/FOCUSED) | components.css, control.html |

## transition（過渡）

LVGL 沒有 CSS transition 的「自動插值」;換樣式通常直接跳變。
需要平滑時改用對應的 lv.anim。

設計稿過渡的屬性: `background .12s、background .12s ease、background .15s、background .15s ease、border-color .15s、border-color .15s ease、color .15s、color .15s ease、left .15s、none !important`

## 不支援 / 略過

| 項目 | 原因 |
|---|---|
| mon-draw / mon-fade | SVG stroke 描繪動畫,LVGL 無 SVG 路徑動畫 |
| box-shadow / color-mix | LVGL shadow 可用但效果有限;color-mix 漸層不支援 |
| carousel__track 滑動 | 用 set_pos() + 自訂動畫即可,或維持直接切換 |
| skeleton 掃光 | 一般嵌入式 UI 不需要 |

---
產生時間: 2026-08-02 02:17
