# ui/__init__.py — UI 區塊（slave new 專案內的一個區塊,像 tasks/lib）
#
# 純 LVGL UI 邏輯,不碰硬體;硬體透過注入的 platform 對接
#（板上 = ui.board 對 slave new bus;模擬器 = ui.sim_platform）。
