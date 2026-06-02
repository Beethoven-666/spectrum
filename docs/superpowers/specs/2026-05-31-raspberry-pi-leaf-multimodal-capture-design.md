# Raspberry Pi 叶片多模态采集设备设计

**日期**: 2026-05-31
**状态**: 待用户书面 spec 复核
**目标硬件**: Raspberry Pi 5 4GB + Intel RealSense D455/D455f + H1 光谱仪 + 后续主 RGB 相机
**当前树莓派**: `croprix-spectrum.local`, Ubuntu 24.04.4 LTS ARM64

## 1. 背景

本仓库已有 H1 光谱仪的协议契约、Python/C++/Node.js SDK 和 Next.js 调试 UI。新目标是在树莓派上做一个叶片多模态采集设备，用于采集后续模型训练所需的数据。

v1 的重点不是实时推理，而是可靠地保存每条样本的原始数据和可追溯元数据。每条样本需要绑定 H1 光谱、D455 RGB、D455 深度、完整点云、ROI 点云、IMU/姿态、叶片距离、拍摄角度、质量标签、自动曝光过程和标定版本。主 RGB 相机通过分光镜与光谱仪硬件对齐，但当前线缆未到货，因此 v1 必须允许主 RGB 模块缺失。

当前远端设备只读探查结果：

- OS: Ubuntu 24.04.4 LTS, ARM64, kernel `6.8.0-1053-raspi`
- D455: USB 设备 `8086:0b5c Intel RealSense Depth Camera 455f`, 已挂在 5000M USB3 总线上
- H1: CH340 串口，稳定路径 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- 用户权限: 已在 `dialout`, `video`, `render`, `gpio`, `i2c` 等组
- 运行时缺口: 当前没有 `pyrealsense2`, RealSense CLI, Node.js, npm
- 存储约束: 根分区约 15GB，当前可用约 7GB，只适合少量测试样本

## 2. 目标与非目标

### 2.1 v1 目标

- 在树莓派上提供可用的 Web 采集控制台。
- 使用 D455 + H1 生成完整样本；主 RGB 缺失时仍能正常采集。
- 保存目录式样本包，并用 SQLite 建索引用于 Web 浏览和导出。
- 保存 D455 RGB、深度、完整点云、ROI 点云、IMU、H1 光谱和自动曝光过程。
- 计算并记录 ROI 距离、深度有效率、局部法线、拍摄角度、姿态稳定性和质量标签。
- 支持默认中心 ROI 和 Web UI 手动点选/框选 ROI。
- 支持无标定采集，并在存在 `calibration.json` 时启用更精确的 ROI 投影和几何计算。
- 提供样本列表、单条下载、批量导出、配置档保存和标定版本记录。

### 2.2 v1 非目标

- 不在树莓派上做实时模型推理或训练。
- 不把 ROS 2 放进第一版核心路径。
- 不做硬件触发同步，先使用软件时间戳。
- 不强制主动光源或环境光校正。
- 不做云端/NAS 实时同步。
- 不实现全局定位、RTK、SLAM 或机器人运动集成，只预留字段和接口。
- 不要求主 RGB 相机在 v1 初期可用。

## 3. 选定方案

采用 **Python 常驻采集服务 + Next.js Web UI**。

```text
Browser / phone / laptop
        |
        | HTTP + WebSocket/SSE
        v
Next.js Web UI
        |
        | localhost HTTP API
        v
Python acquisition service
        |
        +-- H1 spectrometer over /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
        +-- RealSense D455 over USB3 / pyrealsense2
        +-- Main RGB camera plugin, initially disabled
        +-- Local filesystem sample store
        +-- SQLite sample index
```

Python 服务是唯一硬件主控。它负责设备发现、RealSense stream、H1 自动曝光采集、ROI、点云、几何指标、metadata、SQLite、文件落盘和采集状态机。Next.js 不直接访问串口、RealSense 或视频设备，只负责 Web 操作层。

不选择 ROS 2 作为 v1 核心，是因为当前目标是采集闭环和数据可靠性；ROS 2 会增加部署和 Web 集成复杂度。后续机器人化时，可以在 Python 服务外增加 ROS 2 bridge。

不选择 Next.js 直接主控硬件，是因为 RealSense、点云、OpenCV、串口、自动曝光重试和长时间设备状态维护更适合常驻 Python 服务。

## 4. 仓库结构

新增 Python 采集服务目录，保留现有 H1 SDK 的职责边界。

```text
spectrum/
├── acquisition/
│   ├── pyproject.toml
│   └── spectrum_acq/
│       ├── api/
│       ├── calibration/
│       ├── capture/
│       ├── devices/
│       ├── geometry/
│       └── storage/
├── docs/
│   └── superpowers/specs/
├── sdk/python/
└── webui/
```

模块职责：

- `sdk/python`: 只负责 H1 光谱仪协议和设备 API，不引入 D455、点云或样本存储概念。
- `acquisition/spectrum_acq/devices`: H1、D455、主 RGB 的设备适配层。
- `acquisition/spectrum_acq/capture`: 采集状态机、软件时间戳、H1 自动曝光策略。
- `acquisition/spectrum_acq/geometry`: ROI、深度有效率、点云裁剪、平面拟合、距离和角度计算。
- `acquisition/spectrum_acq/storage`: 目录式样本包、SQLite 索引、导出压缩包。
- `acquisition/spectrum_acq/calibration`: 标定文件、标定版本、坐标系关系。
- `acquisition/spectrum_acq/api`: FastAPI HTTP/WebSocket/SSE 接口。
- `webui`: Next.js 采集控制台，调用 Python 服务 API。

## 5. 采集流程

v1 使用软件时间戳，不做硬件触发。采集前 UI 提示用户稳定设备，采集服务记录每个关键步骤的 monotonic time 和 wall-clock time。

```text
idle
 -> previewing
 -> capture_requested
 -> read_current_d455_frames
 -> h1_auto_exposure_capture
 -> compute_roi_geometry
 -> write_sample_files
 -> index_sample
 -> done / failed
```

关键步骤：

1. Web UI 发起采集请求，携带当前 ROI、配置档和自动曝光模式。
2. Python 服务锁定一次采集状态，避免并发写同一设备。
3. 读取当前 D455 color/depth/IMU 状态，并保存采集时间戳。
4. 执行 H1 自动曝光采集。
5. 根据 ROI 和标定状态生成 ROI 深度统计、完整点云、ROI 点云、局部法线和拍摄角度。
6. 计算质量标签。
7. 先写入临时样本目录，所有文件成功后原子重命名为正式样本目录。
8. 写入或更新 SQLite 索引。
9. 通过 SSE/WebSocket 向 UI 推送采集完成或失败原因。

## 6. H1 自动曝光

H1 默认使用保守自动曝光策略。**优先使用设备自带的自动曝光**（开发者文档 CMD
`0x0A=Auto`，配合 `0x13` 设置最大曝光封顶），再用软件做少量校正：

- 先设最大曝光封顶（`0x13`），第 1 帧用设备原生自动曝光，由固件挑曝光时间。
- 只调整 H1 曝光，不联动 D455 或主 RGB。
- 每次采集后读取 `exposureStatus`。
- 若原生自动曝光的首帧不是 `normal`（或设备不支持自动），切到手动模式校正：
  按配置倍率缩短/拉长曝光；一旦同时出现过 `under` 和 `over`（夹住目标），改用两端
  几何二分，避免来回震荡。
- 总采集次数受 `max_attempts` 限制（默认 4 = 1 次原生自动 + 至多 3 次手动校正）。
- 如果最终仍过曝或欠曝，仍保存样本，但质量标记为 `warn` 或 `bad`。
- 采集会在结束后**恢复操作员在曝光面板里设置的曝光模式**（采集内部固定走手动校正，
  不会把设备静默留在手动）。

Web UI 提供三个模式：

- `conservative`: 默认模式，有限重试，失败也保存（保存选中帧）。
- `strict`: 没有正常曝光则不保存，除非用户强制覆盖。
- `multi_exposure`: 先按上面的策略找到中心曝光，再围绕它采集一组几何阶梯曝光
  （`multi_exposure_steps` 档，默认 5：中心 ×{0.25, 0.5, 1, 2, 4}），**保存每一档的完整
  光谱**，供离线研究选择。

每次尝试都写入 `h1/exposure_attempts.json`，最终选中帧写入 `h1/spectrum.json` 和
`h1/spectrum.csv`。`multi_exposure` 模式额外写 `h1/exposures.json`（各档摘要）和
`h1/exposures/attempt_NN.csv`（各档光谱）。

## 7. D455 配置

D455 profile 使用配置档管理。

默认低负载档：

- depth: `640x480 @ 15/30fps`
- D455 RGB: `640x480 @ 15/30fps`

实验档可提高深度/RGB 分辨率，但在当前 SD 卡测试阶段不建议长期使用高分辨率完整点云。

每条样本必须记录：

- D455 serial number 和 firmware version
- color/depth 分辨率和 FPS
- depth scale
- color/depth intrinsics
- color-depth extrinsics
- IMU 可用性和采样摘要

## 8. 主 RGB 插件

主 RGB 相机通过分光镜与 H1 光谱仪硬件对齐，是未来模型训练的主图来源。当前线缆未到货，因此 v1 使用插件接口预留。

接口能力：

- `status()`: `ready | disabled | missing | error`
- `capture()`: 返回图片文件、曝光参数、intrinsics、采集时间戳
- `metadata()`: 返回相机型号、序列号、驱动、配置档

初期使用 `NullMainRgbProvider`，每条样本仍创建 `main_rgb/status.json`，写入 `disabled` 或 `missing`。以后接入真实相机时，不改变样本目录结构，只填充实际图片和元数据。

## 9. ROI、标定与几何

v1 支持两种 ROI：

- 默认中心 ROI: 适合手持对准，配置为画面中心的固定比例区域。
- 手动 ROI: Web UI 中点选或框选叶片区域。

自动叶片分割不进入 v1，只预留接口。

标定分两层：

- 无外参标定: 仍允许采集，几何数据标记为 `uncalibrated`。距离和角度基于 D455 自身 ROI 或中心区域估算。
- 有 `calibration.json`: 使用标定版本将主 RGB/光谱 ROI 映射到 D455 坐标系，裁剪 ROI 点云并计算更可信的几何指标。

几何输出：

- ROI 中位距离
- ROI 深度有效率
- ROI 点云文件
- ROI 局部平面法线
- 相机光轴与叶片法线夹角
- 设备姿态摘要，例如 roll/pitch/yaw 或 IMU 原始摘要
- 姿态稳定性，例如采集窗口内 roll/pitch 变化

如果 ROI 点不足、深度无效或平面拟合失败，样本仍保存，几何字段标记为 `unknown`，质量标签降级。

## 10. 样本目录与数据格式

每次采集生成一个目录式样本包。目录是权威数据源，SQLite 只是索引。

```text
data/samples/
└── 20260531T142530.124Z_8f3a2c/
    ├── metadata.json
    ├── h1/
    │   ├── spectrum.json
    │   ├── spectrum.csv
    │   ├── exposure_attempts.json
    │   ├── exposures.json          # 仅 multi_exposure：各档曝光摘要
    │   └── exposures/              # 仅 multi_exposure：各档完整光谱
    │       └── attempt_NN.csv
    ├── d455/
    │   ├── color.jpg
    │   ├── depth.png
    │   ├── depth.npy
    │   ├── imu.json
    │   ├── pointcloud_full.ply
    │   └── pointcloud_roi.ply
    ├── main_rgb/
    │   └── status.json
    ├── roi/
    │   ├── roi.json
    │   └── preview.jpg
    └── quality.json
```

`metadata.json` 记录：

- `schema_version`
- sample id
- start/end wall-clock time
- start/end monotonic time
- software version and git commit when available
- device inventory
- active config profile
- calibration version and calibration file hash when available
- D455 profile and intrinsics
- H1 device info and wavelength range
- main RGB status
- synchronization timing summary
- file manifest with checksums when enabled

`quality.json` 记录：

- `status`: `good | warn | bad`
- distance metrics
- angle metrics
- depth valid ratio
- H1 exposure result
- IMU stability
- sync timing
- disk space status
- missing optional devices
- error and warning list

## 11. SQLite 索引

SQLite 用于 Web 查询，不作为唯一数据源。样本目录和 `metadata.json` 必须足够自描述，离线拷走后仍能使用。

建议表：

- `samples`
  - `id`
  - `created_at`
  - `path`
  - `schema_version`
  - `quality_status`
  - `distance_mm`
  - `angle_deg`
  - `h1_exposure_status`
  - `d455_serial`
  - `h1_serial`
  - `main_rgb_status`
  - `calibration_version`
  - `config_profile`
  - `size_bytes`
  - `warnings_json`
- `exports`
  - `id`
  - `created_at`
  - `filter_json`
  - `archive_path`
  - `status`

索引可从样本目录重建。Web UI 应提供重建索引的维护入口或命令行脚本。

## 12. API

Python 采集服务使用 FastAPI。Next.js 只调用这些 API，不直接访问硬件。

```text
GET  /health
GET  /devices
GET  /preview/d455/status
GET  /preview/d455/frame
GET  /config
PUT  /config
POST /capture
GET  /capture/current
GET  /samples
GET  /samples/{sample_id}
GET  /samples/{sample_id}/download
POST /samples/export
GET  /calibration
PUT  /calibration
GET  /storage
WS/SSE /events
```

事件流内容：

- device connected/disconnected
- preview profile and frame status
- disk space status
- capture progress
- H1 exposure attempt status
- quality metric preview
- sample indexed/exported
- warnings and errors

## 13. Web UI

在现有 `webui` 基础上扩展为采集控制台。

页面：

- 仪表盘: D455 RGB/depth 预览、H1 状态、剩余空间、当前 profile、质量状态。
- 采集页: ROI 设置、采集按钮、自动曝光模式、采集进度、最近样本。
- 样本页: 样本列表、质量状态、缩略图、metadata 摘要、单条下载、批量导出。
- 设置页: D455 profile、ROI 默认值、H1 自动曝光参数、质量阈值、数据目录。
- 标定页: 当前标定版本、导入/保存 `calibration.json`、标定状态说明。

UI 默认不硬拦截采集，而是显示推荐范围和 `good/warn/bad`。硬拦截作为设置项。

## 14. 存储策略

v1 初期允许写当前 SD 卡，但这只用于少量测试。完整点云和 ROI 点云会快速消耗空间。

默认行为：

- Web UI 显示数据目录总空间和剩余空间。
- 低于 warning 阈值时显示明显警告。
- 低于 stop 阈值时阻止采集，除非开发配置显式允许覆盖。
- 批量导出前估算压缩包大小和剩余空间。
- 文件写入失败时样本标记为 failed，临时目录保留用于诊断或清理。

正式批量采集阶段应迁移到 USB SSD，并把 `data/` 放到 SSD 挂载点。

## 15. 部署

v1 先使用开发模式脚本，验通后再 systemd 服务化。

开发模式：

1. SSH 到 `croprix-spectrum.local`。
2. 安装 RealSense SDK、`pyrealsense2`、Node.js、npm、Python venv。
3. 验证 D455 枚举、D455 frame 读取、H1 串口采集。
4. 启动 Python acquisition 服务。
5. 启动 Next.js Web UI。
6. 在同一局域网用浏览器访问树莓派 Web UI。

服务化阶段：

- Python acquisition service 用 systemd 管理。
- Next.js Web UI 用 systemd 管理。
- 设置明确的 working directory、env file、restart policy、日志路径。

不使用 Docker Compose 作为 v1 默认部署方式，避免 RealSense USB/video/render 透传和 ARM64 依赖增加调试成本。

## 16. 错误处理

设备缺失：

- H1 缺失: UI 标红，禁止完整采集，只允许 D455 预览。
- D455 缺失: UI 标红，禁止完整采集，只允许 H1 设备检查。
- 主 RGB 缺失: 允许采集，写 `main_rgb/status.json`。

采集失败：

- 采集状态机必须有明确 `failed` 状态和错误码。
- 已写临时文件保留在临时目录，避免混入正式样本列表。
- SQLite 只索引成功完成的样本，失败样本另有诊断入口或日志。

几何失败：

- 不阻止保存。
- 几何字段写 `unknown`。
- 质量标签降级，并在 warnings 中记录原因。

标定缺失：

- 不阻止保存。
- `metadata.json` 标记 `calibration.status = "uncalibrated"`。

低空间：

- warning 阈值只提示。
- stop 阈值默认阻止采集。

## 17. 测试与验收

硬件连通性：

- D455 在 USB3 总线上枚举。
- Python 能读取 D455 color/depth/IMU。
- H1 能通过 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` 读取设备信息并采集单帧。

采集闭环：

- Web UI 能显示 D455 预览和 H1 状态。
- 点击一次采集生成完整样本目录。
- 样本包含 H1 光谱、D455 RGB、深度、完整点云、ROI 点云、IMU、ROI、质量和 metadata。
- SQLite 能列出该样本。
- Web UI 能查看样本摘要并下载单条样本。
- 批量导出能生成压缩包。

质量控制：

- 自动曝光尝试写入 `exposure_attempts.json`。
- 过曝/欠曝会影响 `quality.status`。
- 深度无效或点云不足会写 warning。
- 低空间状态能在 UI 中显示，并在 stop 阈值下阻止采集。

主 RGB 插件：

- 未接入时样本仍成功保存。
- `main_rgb/status.json` 明确写入 missing/disabled。

标定：

- 无标定时样本标记 `uncalibrated`。
- 导入 `calibration.json` 后，新样本记录标定版本。

## 18. 后续扩展

- 主 RGB 相机真实接入，保存主 RGB 图片、曝光和 intrinsics。
- USB SSD 数据盘和批量采集配置。
- 标定板流程自动化，包括棋盘格或 AprilTag。
- burst 选帧或硬件触发同步。
- 主动光源、白板/暗场校准和环境光记录。
- ROS 2 bridge，用于机器人/移动平台。
- 全局位置字段，包括行列号、GPS/RTK、SLAM pose 或机器人 TF。
- 离线标注和实验记录关联。
