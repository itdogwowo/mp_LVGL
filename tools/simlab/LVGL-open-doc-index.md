# LVGL Open Docs 检索清单

这份清单用于快速查找 `LVGL` 官方文档里和当前项目最相关的能力，重点服务于：

- `launcher` 轮播 / 卡片切换
- 页面切换动画
- `scroll + snap` 类似 carousel 的实现
- `style transform / scale / translate / opacity`
- `examples` 快速找参考

## 官方入口

- 最新 Open Docs 根入口: [https://lvgl.io/docs/open](https://lvgl.io/docs/open)
- 最新 Examples 总入口: [https://lvgl.io/docs/open/examples](https://lvgl.io/docs/open/examples)
- 最新 API 总入口: [https://lvgl.io/docs/open/api](https://lvgl.io/docs/open/api)

## v9.0 对照入口

- v9.0 文档根入口: [https://lvgl.io/docs/open/9.0/](https://lvgl.io/docs/open/9.0/)
- v9.0 Examples 总页: [https://lvgl.io/docs/open/9.0/examples.html](https://lvgl.io/docs/open/9.0/examples.html)
- v9.0 API 总入口: [https://lvgl.io/docs/open/9.0/API/index.html](https://lvgl.io/docs/open/9.0/API/index.html)

## 1. 动画系统

用于卡片滑动、缩放、淡入淡出、页面级过渡、时间轴编排。

- 动画总指南: [https://lvgl.io/docs/open/main-modules/animation](https://lvgl.io/docs/open/main-modules/animation)
- 动画示例: [https://lvgl.io/docs/open/examples/anim](https://lvgl.io/docs/open/examples/anim)
- 当前 `lv_anim.h`: [https://lvgl.io/docs/open/api/public/core/lv_anim_h](https://lvgl.io/docs/open/api/public/core/lv_anim_h)
- 当前 `lv_anim_timeline.h`: [https://lvgl.io/docs/open/api/public/core/lv_anim_timeline_h](https://lvgl.io/docs/open/api/public/core/lv_anim_timeline_h)
- v9.0 `lv_anim.h`: [https://lvgl.io/docs/open/9.0/API/misc/lv_anim.html](https://lvgl.io/docs/open/9.0/API/misc/lv_anim.html)
- v9.0 `lv_anim_timeline.h`: [https://lvgl.io/docs/open/9.0/API/misc/lv_anim_timeline.html](https://lvgl.io/docs/open/9.0/API/misc/lv_anim_timeline.html)

### 常用关键字

- `lv_anim_t`
- `lv_anim_set_exec_cb`
- `lv_anim_set_values`
- `lv_anim_set_duration`
- `lv_anim_set_path_cb`
- `lv_anim_start`
- `timeline`

## 2. 布局系统

用于横向卡片排列、主页宫格、左右区块、顶部控制区等。

- Layout 总览: [https://lvgl.io/docs/open/common-widget-features/layouts](https://lvgl.io/docs/open/common-widget-features/layouts)
- Flex: [https://lvgl.io/docs/open/common-widget-features/layouts/flex](https://lvgl.io/docs/open/common-widget-features/layouts/flex)
- Grid: [https://lvgl.io/docs/open/common-widget-features/layouts/grid](https://lvgl.io/docs/open/common-widget-features/layouts/grid)

### 常用关键字

- `LV_LAYOUT_FLEX`
- `lv_obj_set_flex_flow`
- `lv_obj_set_flex_align`
- `lv_obj_set_grid_dsc_array`
- `lv_obj_set_grid_cell`

## 3. 样式 / 变换 / 视觉强调

用于中心卡放大、侧卡缩小、边缘淡化、位移、旋转、焦点强调。

- Styles 总入口: [https://lvgl.io/docs/open/common-widget-features/styles](https://lvgl.io/docs/open/common-widget-features/styles)
- Style Properties: [https://lvgl.io/docs/open/common-widget-features/styles/style-properties](https://lvgl.io/docs/open/common-widget-features/styles/style-properties)

### 重点属性

- `translate_x`
- `translate_y`
- `transform_scale_x`
- `transform_scale_y`
- `transform_rotation`
- `transform_pivot_x`
- `transform_pivot_y`
- `bg_opa`
- `image_opa`

## 4. Scroll / Snap / Carousel 相关

LVGL 没有一个直接叫 carousel 的标准控件，最接近的官方实现路径在这里。

- Scrolling 通用特性: [https://lvgl.io/docs/open/common-widget-features/scrolling](https://lvgl.io/docs/open/common-widget-features/scrolling)
- Scroll 示例总页: [https://lvgl.io/docs/open/examples/scroll](https://lvgl.io/docs/open/examples/scroll)

### 最有用的 examples

- Scroll snapping: [https://lvgl.io/docs/open/examples/scroll#scroll-snapping](https://lvgl.io/docs/open/examples/scroll#scroll-snapping)
- Scroll one at a time: [https://lvgl.io/docs/open/examples/scroll#scroll-one-at-a-time](https://lvgl.io/docs/open/examples/scroll#scroll-one-at-a-time)
- Translate children while scrolling: [https://lvgl.io/docs/open/examples/scroll#translate-children-while-scrolling](https://lvgl.io/docs/open/examples/scroll#translate-children-while-scrolling)
- Endless circular scrolling: [https://lvgl.io/docs/open/examples/scroll#endless-circular-scrolling](https://lvgl.io/docs/open/examples/scroll#endless-circular-scrolling)
- Reacting to scroll events: [https://lvgl.io/docs/open/examples/scroll#reacting-to-scroll-events](https://lvgl.io/docs/open/examples/scroll#reacting-to-scroll-events)

## 5. 页面切换 / Screen Navigation

用于首页进入二级页、左右滑动切屏、淡入淡出切页。

- Screens 指南: [https://lvgl.io/docs/open/common-widget-features/screens](https://lvgl.io/docs/open/common-widget-features/screens)
- Display API: [https://lvgl.io/docs/open/api/public/display/lv_display_h](https://lvgl.io/docs/open/api/public/display/lv_display_h)

### 常用关键字

- `lv_screen_load`
- `lv_screen_load_anim`
- `lv_screen_active`

## 6. 候选组件

如果不手写 carousel，可以先看这些官方组件是否更接近需求。

- Widgets 总页: [https://lvgl.io/docs/open/widgets](https://lvgl.io/docs/open/widgets)
- Tile View: [https://lvgl.io/docs/open/widgets/tileview](https://lvgl.io/docs/open/widgets/tileview)
- Tab View: [https://lvgl.io/docs/open/widgets/tabview](https://lvgl.io/docs/open/widgets/tabview)
- Menu: [https://lvgl.io/docs/open/widgets/menu](https://lvgl.io/docs/open/widgets/menu)
- Image: [https://lvgl.io/docs/open/widgets/image](https://lvgl.io/docs/open/widgets/image)
- Image Button: [https://lvgl.io/docs/open/widgets/imagebutton](https://lvgl.io/docs/open/widgets/imagebutton)
- Label: [https://lvgl.io/docs/open/widgets/label](https://lvgl.io/docs/open/widgets/label)

## 7. 当前项目最适合的查找顺序

如果目标是修现在这个 `launcher` 的动画手感，建议按这个顺序找：

1. `scroll examples`
2. `scroll snapping`
3. `translate children while scrolling`
4. `animation`
5. `style-properties`
6. `lv_anim.h`
7. `lv_screen_load_anim`

## 8. 版本注意

- `open` 是最新维护文档，结构更清楚，但不一定完全等于冻结版 `v9.0`
- 真正写 API 名称时，建议回 `open/9.0/API` 再核对一次
- `timeline`、某些 widget 条目、以及部分命名，在新文档和 `v9.0` 里可能略有差异

## 9. 当前问题对应建议

如果要把现在的 `launcher` 做得更像 HTML 轮播，优先参考：

- `scroll one at a time`
- `scroll snapping`
- `translate children while scrolling`
- `animation timeline`

如果要做“整页进入下一屏”的效果，而不是只做卡片轮播，优先参考：

- `lv_screen_load_anim`
- `tileview`

