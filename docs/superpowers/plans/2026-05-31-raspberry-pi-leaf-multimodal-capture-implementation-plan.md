# Raspberry Pi 叶片多模态采集设备实施计划

**日期**: 2026-05-31
**状态**: Ready for implementation
**对应设计**: `docs/superpowers/specs/2026-05-31-raspberry-pi-leaf-multimodal-capture-design.md`
**说明**: 本机未安装 `writing-plans` skill；此文档按已批准 spec 手工生成，作为实施入口。

## 1. 实施原则

- 先证明真实硬件链路，再扩展 UI 和导出能力。
- Python acquisition service 是唯一硬件主控；Next.js 只调用 Python API。
- 样本目录是权威数据源，SQLite 只做索引。
- 主 RGB 先实现空插件，不阻塞 D455 + H1 样本采集。
- v1 使用软件时间戳，不引入硬件触发或 ROS 2。
- 在当前 SD 卡测试阶段，默认低分辨率 D455 profile，并实现低空间保护。

## 2. 阶段 0: 树莓派依赖和硬件冒烟

目标是在 `croprix-spectrum.local` 上确认 RealSense、H1、Python、Node 环境都能满足后续开发。

### 任务

1. 建立树莓派环境记录脚本。
   - 记录 OS、kernel、CPU 架构、内存、磁盘、USB 拓扑、串口路径、用户组。
   - 输出保存到 `docs/hardware/croprix-spectrum-env.md` 或后续等价位置。
2. 安装或确认 Python 运行环境。
   - 使用 Python 3.12 venv。
   - 安装 `h1-sdk` editable 依赖路径，验证 `pyserial`。
3. 安装或确认 RealSense Python 运行时。
   - 优先验证 PyPI `pyrealsense2` 是否可在 CPython 3.12 aarch64 上安装和导入。
   - 如果 wheel 不可用，再走 librealsense source build 分支。
   - 不把 apt 包存在作为前提；当前 apt-cache 没有返回 RealSense 包。
4. 安装或确认 Node.js/npm。
   - 需要能运行现有 `webui` Next.js。
   - 版本选择以后续 Next.js 16 能正常 build/dev 为准。
5. 写两个最小硬件 smoke 脚本。
   - D455: enumerate devices, 打印 serial/firmware/depth scale/profile，读取一组 color/depth/IMU。
   - H1: 通过 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` 读取设备信息、波长范围并采集一帧。

### 验收

- `python -c "import pyrealsense2 as rs"` 成功。
- D455 在 USB3 上可读取 color/depth，IMU 可用性被明确记录。
- H1 通过稳定 by-id 串口返回设备信息和单帧光谱。
- Node/npm 能安装并启动 Next.js dev server。
- 依赖安装路径和失败分支写入文档或脚本注释。

## 3. 阶段 1: Python acquisition 包骨架

目标是建立可测试的后端工程边界，先用 mock 跑通 API 和状态机，再接真实硬件。

### 任务

1. 新增 `acquisition/pyproject.toml`。
   - 包名建议 `spectrum-acq`。
   - 初始依赖: `fastapi`, `uvicorn[standard]`, `pydantic`, `numpy`, `pillow`, `pyserial`, `h1-sdk` 本地路径依赖。
   - RealSense 依赖先作为可选 extra 或部署依赖，避免非树莓派开发机安装失败。
2. 建立目录:
   - `spectrum_acq/api`
   - `spectrum_acq/capture`
   - `spectrum_acq/devices`
   - `spectrum_acq/geometry`
   - `spectrum_acq/storage`
   - `spectrum_acq/calibration`
3. 定义核心接口。
   - `H1Spectrometer`
   - `RealSenseCamera`
   - `MainRgbProvider`
   - `SampleStore`
   - `CaptureCoordinator`
4. 提供 mock 设备实现。
   - mock H1 生成正常/过曝/欠曝光谱。
   - mock D455 生成小尺寸 color/depth/pointcloud。
   - `NullMainRgbProvider` 返回 `disabled` 或 `missing`。
5. 建立配置模型。
   - 数据目录、D455 profile、ROI 默认值、H1 曝光策略、质量阈值、低空间阈值。
   - 配置文件建议 `data/config/acquisition.json`。

### 验收

- `pytest` 能在没有硬件的本机通过核心单元测试。
- acquisition 服务能以 mock 模式启动。
- mock 模式下可生成符合 spec 的样本目录。

## 4. 阶段 2: 样本存储、metadata 和 SQLite

目标是先把数据契约做扎实，让后续设备数据只是在明确位置填充。

### 任务

1. 实现样本目录 writer。
   - 先写 `data/.tmp/<sample_id>.partial/`。
   - 所有文件完成后原子 rename 到 `data/samples/<sample_id>/`。
   - 失败样本保留在临时目录并写错误摘要。
2. 定义并测试 metadata schema。
   - `metadata.json`
   - `quality.json`
   - `h1/spectrum.json`
   - `h1/exposure_attempts.json`
   - `d455/imu.json`
   - `roi/roi.json`
   - `main_rgb/status.json`
3. 实现 SQLite index。
   - `samples` 表按 spec 字段建索引。
   - 提供从样本目录重建索引的函数和 CLI。
4. 实现导出。
   - 单样本 zip。
   - 按筛选条件批量 zip。
   - 导出前检查剩余空间。
5. 实现磁盘空间检查。
   - warning 阈值只提示。
   - stop 阈值默认阻止采集。

### 验收

- 样本目录离线拷走后，单靠 JSON 和文件清单能理解样本。
- SQLite 删除后可以从 `data/samples/` 重建。
- 低空间状态能被 API 返回，并能阻止新采集。

## 5. 阶段 3: D455 真实设备适配和几何计算

目标是使用 D455 生成 color/depth/IMU/pointcloud，并基于 ROI 计算距离和角度。

### 任务

1. 实现 RealSense 设备适配。
   - 设备枚举、serial、firmware、depth scale。
   - 默认低负载 profile。
   - profile 配置切换。
   - color/depth 对齐策略明确记录。
2. 实现 frame snapshot。
   - `d455/color.jpg`
   - `d455/depth.png`
   - `d455/depth.npy`
   - `d455/imu.json`
3. 实现点云保存。
   - 使用 RealSense pointcloud 或 depth intrinsics 转换。
   - 写 `pointcloud_full.ply`。
   - 根据 ROI 写 `pointcloud_roi.ply`。
   - v1 不引入 Open3D 作为必需依赖，平面拟合用 numpy SVD。
4. 实现 ROI。
   - 中心 ROI。
   - 手动矩形 ROI 数据模型。
   - ROI preview 图。
5. 实现几何指标。
   - ROI 中位距离。
   - 深度有效率。
   - ROI 局部平面法线。
   - 相机光轴与法线夹角。
   - 点不足或拟合失败时写 `unknown`。

### 验收

- 树莓派上采集一条 D455-only mock/H1-disabled 诊断样本可生成 color/depth/pointcloud。
- 完整点云和 ROI 点云可被标准 PLY 工具读取。
- ROI 无效时样本不崩溃，质量标签降级并写 warning。

## 6. 阶段 4: H1 自动曝光采集

目标是把现有 Python H1 SDK 作为设备适配层，加入自动曝光策略和采集过程记录。

### 任务

1. 集成 `sdk/python/h1_sdk`。
   - 默认串口路径为 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`。
   - 支持配置覆盖。
2. 实现 H1 设备状态。
   - device info。
   - wavelength range。
   - exposure mode/time/max exposure。
3. 实现自动曝光策略。
   - `conservative`: 最多 2-3 次重试，失败也保存。
   - `strict`: 非 normal 默认不保存，除非 force。
   - `multi_exposure`: 保存多档曝光。
4. 写 `spectrum.json` 和 `spectrum.csv`。
   - 保存 raw spectrum、actual spectrum、plant params、exposure status、selected attempt。
5. 写 `exposure_attempts.json`。
   - 每次尝试的曝光时间、状态、开始/结束时间戳、是否选中。

### 验收

- H1 真实设备可以完成单帧采集。
- 人工触发 over/under 或 mock over/under 时，会按策略重试并写完整过程。
- H1 失败不会留下被 SQLite 标记为成功的半样本。

## 7. 阶段 5: CaptureCoordinator 和 FastAPI

目标是把设备、存储、几何和质量控制组合成单个稳定采集 API。

### 任务

1. 实现 `CaptureCoordinator`。
   - 单飞锁，禁止并发采集。
   - 明确状态: `idle`, `previewing`, `capture_requested`, `capturing`, `writing`, `done`, `failed`。
   - 所有状态变化发布到事件流。
2. 实现质量评分。
   - `good | warn | bad`。
   - 输入: H1 曝光、距离、角度、深度有效率、IMU 稳定性、同步时间、磁盘空间、设备缺失。
3. 实现 FastAPI endpoints。
   - `GET /health`
   - `GET /devices`
   - `GET /preview/d455/status`
   - `GET /preview/d455/frame`
   - `GET /config`
   - `PUT /config`
   - `POST /capture`
   - `GET /capture/current`
   - `GET /samples`
   - `GET /samples/{sample_id}`
   - `GET /samples/{sample_id}/download`
   - `POST /samples/export`
   - `GET /calibration`
   - `PUT /calibration`
   - `GET /storage`
   - `WS/SSE /events`
4. 实现错误码。
   - device missing。
   - capture busy。
   - low disk。
   - H1 failure。
   - D455 failure。
   - write failure。
   - invalid ROI/config。

### 验收

- API 在 mock 模式下通过单元/集成测试。
- API 在树莓派真实 D455 + H1 下可以完成采集闭环。
- 事件流能驱动 UI 显示采集进度和失败原因。

## 8. 阶段 6: Next.js Web UI

目标是在现有 `webui` 中加入多模态采集控制台，同时尽量不破坏已有 H1 调试功能。

### 任务

1. 新增 Python acquisition API client。
   - `ACQUISITION_API_BASE_URL` 环境变量。
   - 浏览器请求优先经 Next.js route handler 代理，避免跨域和内网地址泄漏问题。
2. 仪表盘。
   - D455 RGB/depth 预览。
   - H1 状态。
   - 主 RGB 状态。
   - 磁盘空间。
   - 当前质量预览。
3. 采集页。
   - ROI 设置。
   - 自动曝光模式。
   - 采集按钮。
   - 采集进度。
   - 最近样本摘要。
4. 样本页。
   - 样本列表。
   - 质量状态、缩略图、距离、角度、曝光状态。
   - 单条下载。
   - 批量导出。
5. 设置页。
   - D455 profile。
   - ROI 默认值。
   - H1 自动曝光参数。
   - 质量阈值。
   - 数据目录和低空间阈值。
6. 标定页。
   - 当前标定版本。
   - 导入/保存 `calibration.json`。
   - 无标定状态说明。

### 验收

- Next.js build 通过。
- Web UI 能连接 Python mock 服务并完成采集闭环。
- Web UI 能连接树莓派真实服务并生成可下载样本。
- 主 RGB missing 不阻止采集，UI 明确显示状态。

## 9. 阶段 7: 部署脚本和运行手册

目标是让树莓派开发模式可重复，后续 systemd 服务化有清晰入口。

### 任务

1. 新增开发脚本。
   - Python venv 创建和依赖安装。
   - Node/npm 安装说明或版本检查。
   - acquisition 服务启动。
   - webui dev server 启动。
2. 新增硬件检查命令。
   - USB topology。
   - serial by-id。
   - D455 smoke。
   - H1 smoke。
3. 写运行手册。
   - 如何 SSH 到设备。
   - 如何启动服务。
   - 如何访问 Web UI。
   - 如何清理样本和导出数据。
   - 当前 SD 卡存储限制。
4. 预留 systemd 文件模板。
   - 不在第一轮强制启用。
   - 记录 env file、working directory、restart policy。

### 验收

- 新机器或清空 venv 后，按手册可以复现开发模式启动。
- 常见失败能在手册中找到检查命令。

## 10. 阶段 8: 端到端验收

目标是证明 v1 达到已批准 spec 的采集闭环。

### 验收用例

1. 设备状态。
   - Web UI 显示 D455 online。
   - Web UI 显示 H1 online。
   - Web UI 显示 main RGB missing/disabled。
   - Web UI 显示剩余空间。
2. 单次采集。
   - 点击采集。
   - 生成正式样本目录。
   - SQLite 可查询该样本。
   - Web UI 样本列表出现新样本。
3. 样本内容。
   - `metadata.json` 存在。
   - `quality.json` 存在。
   - `h1/spectrum.json` 和 `h1/spectrum.csv` 存在。
   - `h1/exposure_attempts.json` 存在。
   - `d455/color.jpg`, `depth.png`, `depth.npy`, `imu.json`, `pointcloud_full.ply`, `pointcloud_roi.ply` 存在。
   - `main_rgb/status.json` 明确 missing/disabled。
4. 质量控制。
   - H1 曝光状态影响质量标签。
   - ROI 点不足或深度无效会写 warning。
   - 低空间阈值可触发 warning/stop。
5. 下载导出。
   - 单样本 zip 可下载。
   - 批量导出可生成 zip。
6. 标定。
   - 无标定时 metadata 写 `uncalibrated`。
   - 导入标定后新样本记录标定版本。

## 11. 风险和处理

- RealSense Python 依赖在 Ubuntu 24.04 ARM64 上可能变化。
  - 先验证 PyPI wheel；失败再 source build。
  - 不把 RealSense 作为普通开发机必装依赖，避免拖慢本机测试。
- SD 卡空间不足。
  - 默认低分辨率。
  - 实现低空间阻止。
  - 正式采集前迁移 USB SSD。
- D455 IMU 或 frame profile 不稳定。
  - 启动时记录实际支持 profile。
  - 样本 metadata 保存真实 profile，不写假设值。
- H1 自动曝光策略可能需要现场调参。
  - 默认 conservative。
  - 所有尝试完整保存，便于复盘。
- 点云生成可能占用内存。
  - v1 不引入 Open3D 必需依赖。
  - 使用 numpy 和 PLY streaming writer。
- UI 与 Python 服务状态不一致。
  - Python 是状态源。
  - UI 通过 `/capture/current` 和事件流恢复状态。

## 12. 建议提交节奏

1. `acquisition: scaffold python service and mock capture`
2. `acquisition: add sample storage and sqlite index`
3. `acquisition: add realsense adapter and geometry outputs`
4. `acquisition: add h1 auto exposure capture`
5. `acquisition: expose fastapi capture api`
6. `webui: add acquisition api client and dashboard`
7. `webui: add capture and sample browser pages`
8. `docs: add pi setup and hardware smoke runbook`
9. `test: add end-to-end mock capture checks`

每个提交都应能通过对应层级测试；真实硬件 smoke 可以在阶段性提交后执行，不要求每个小提交都跑完整硬件采集。

## 13. 参考

- RealSense SDK releases: https://github.com/realsenseai/librealsense/releases
- pyrealsense2 PyPI files: https://pypi.org/project/pyrealsense2/
