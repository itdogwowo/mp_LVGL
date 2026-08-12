# SimLab API 与小工具文档

这份文档整理 `SimLab` 本地服务的接口、项目结构、runtime 小工具与当前版本策略。

当前默认策略：

- **运行时基线：`LVGL 9.3`**
- **兼容对照：`LVGL 9.0`**

---

## 1. SimLab 是什么

`SimLab` 是挂在现有服务里的一个独立设备模拟器命名空间：

- 页面入口：`/simlab/`
- 本地 runtime：`/simlab/sim/*`
- 项目资源：`/simlab/proj/{name}/*`
- API：`/simlab/api/*`

核心目录：

- `tools/simlab/server.py`
- `tools/simlab/web/index.html`
- `tools/simlab/sim/`
- `tools/simlab/projects/`
- `tools/simlab/config.json`
- `tools/simlab/runtime_recipe.json`
- `tools/simlab/build_runtime.py`

---

## 2. API 一览

这些接口都由 `server.py` 提供。

### 页面与资源

- `/simlab/`
  - SimLab 单页应用入口

- `/simlab/sim/*`
  - 本地 wasm runtime、js、`lvgl.html`、驱动资源

- `/simlab/proj/{name}/*`
  - 项目本地复制件
  - 包括 `lvgl/`、`html/`、`assets/`

### 项目与代码

- `/simlab/api/projects`
  - `GET`: 取项目清单
  - `POST`: `save | scan | import | export`

- `/simlab/api/code?proj=...`
  - 取渲染后的 shim 代码

- `/simlab/api/files?proj=...`
  - 取项目内所有 LVGL `.py`
  - 返回 `{rel: content}`

- `/simlab/api/bins?proj=...`
  - 取字型/图示资源
  - 返回 `{vfs, url}`

- `/simlab/api/code_pairs?proj=...`
  - HTML ↔ LVGL 页面对应表

- `/simlab/api/tree?proj=...`
  - 项目代码树

### 配置与运行时

- `/simlab/api/config`
  - `GET`: 读取性能和本地配置
  - `POST`: 更新配置

- `/simlab/api/runtime`
  - 读取当前 runtime 状态
  - 用来确认是否已切到自建 `9.3` runtime

---

## 3. 项目结构

项目注册表在：

- `tools/simlab/projects.json`

当前已注册项目：

- `slave`
  - 真机 UI 项目
  - framework 结构
  - `modules`: `registry`, `ui_common`, `nav`, `launcher`, `app`

- `mp_lvgl`
  - 参考 UI 项目
  - `mp_lvgl` 结构
  - `lvgl_page_*` 页面模块

每个项目本地复制件放在：

- `tools/simlab/projects/{name}/`

内部一般包含：

- `lvgl/`
- `html/`
- `assets/`

---

## 4. Runtime 小工具

Runtime 管理脚本：

- `tools/simlab/build_runtime.py`

支持命令：

- `status`
  - 查看当前状态
  - 包括 `emsdk`、源码、build 产物、swap 状态

- `build`
  - 拉起编译流程
  - 需要 `Linux/WSL`
  - 第一次需要联网与 `emsdk`

- `swap`
  - 把 `build/wasm/` 产物换入 `sim/`
  - 自动备份旧 runtime

- `verify`
  - 校验当前 runtime 产物与 banner

- `all`
  - 一键执行 `build + swap + verify`

常用命令：

```bash
python tools/simlab/build_runtime.py status
python tools/simlab/build_runtime.py build
python tools/simlab/build_runtime.py swap
python tools/simlab/build_runtime.py verify
python tools/simlab/build_runtime.py all
```

---

## 5. 版本策略

当前项目默认：

- 运行时以 **`LVGL 9.3`** 为准
- 文档查询以 **`9.3`** 为主
- `9.0` 只作为兼容对照

### 推荐查找顺序

1. 先看 `9.3`
2. 再看最新 `open`
3. 如有兼容疑问再回 `9.0`

### 为什么保留 9.0

因为部分旧 example、旧命名、旧绑定行为，仍可能在历史代码里出现。

---

## 6. 当前最常用的两个文档入口

### LVGL 官方文档索引

- `tools/simlab/LVGL-open-doc-index.md`

用途：

- 查动画
- 查 scroll / snap
- 查 `tileview`
- 查 `screen load`
- 查 `style transform`
- 查 `9.3 / 9.0` 对照

### SimLab 本地文档

- 当前文件：`tools/simlab/SIMLAB-api-and-tools.md`

用途：

- 查本地 API
- 查 runtime 管理命令
- 查项目注册结构
- 查调试入口

---

## 7. 面向当前工作流的建议

如果你接下来要继续修 `launcher` / 页面动画 / runtime 行为，建议这样查：

1. 先看 `LVGL-open-doc-index.md`
2. 再看 `/simlab/api/runtime`
3. 需要确认项目结构时看 `projects.json`
4. 需要确认接口时看 `server.py`
5. 需要重建 runtime 时用 `build_runtime.py`

---

## 8. 当前结论

对这套项目，后续默认使用：

- **`LVGL 9.3` 作为实现基线**

只有在：

- API 名称不一致
- 某个 example 在 `9.3` 下行为不同
- 旧页面绑定依赖旧写法

这几种情况，才回头查：

- **`LVGL 9.0`**
