# Spectrum 采集台 (`h1-webui`)

基于 Next.js 16 (App Router) + shadcn/ui 的树莓派 H1 + D455 多模态采集 Web UI。
默认入口连接 Python acquisition service，展示树莓派上的真实硬件状态。
本机 H1 调试页仍复用本仓库的 [`@h1/sdk`](../sdk/nodejs/) 进行协议通信。

## 模式

- **树莓派真实采集（默认）**：`/acquisition` 通过 `ACQUISITION_API_BASE_URL` 访问 acquisition service，读取真实 H1/D455 状态。
- **本机 H1 串口调试**：进入 `/debug`、`/stream`、`/capture` 等本机调试页后，通过环境变量 `H1_PORT=/dev/cu.usbserial-XXXX` 自动连接，或在顶部"连接"侧栏中选择"串口"页签。
- **Mock 模式（显式）**：只有设置 `H1_MOCK=1` 或在顶部连接侧栏中手动选择 Mock 时，才使用内置 `MockSerialPort`。

## 环境变量

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `ACQUISITION_API_BASE_URL` | acquisition service 地址 | `http://127.0.0.1:8000` |
| `H1_MOCK` | 设为 `1` 时强制本机调试页 Mock | 未设置时不 mock |
| `H1_PORT` | 本机调试页真实串口路径 | 未设置时保持未连接 |

## 开发

仓库根目录提供 workspace 脚本：

```bash
# 1) 安装并构建 SDK（webui 引用 dist/）
npm install
npm run build:sdk

# 2) 启动 dev server（默认访问 acquisition service）
npm run dev:webui
# 本机 SDK mock 调试需要显式开启：
# H1_MOCK=1 npm run dev -w h1-webui

# 3) 构建
npm run build:webui
```

启动后访问 <http://localhost:3000>。

## 路由

| 页面 | 说明 |
| --- | --- |
| `/` | 重定向到 `/acquisition` |
| `/acquisition` | 树莓派 H1 + D455 多模态采集 |
| `/debug` | 本机 H1 调试仪表盘 |
| `/stream` | 树莓派 H1 SSE 实时光谱流，FPS / 累计帧统计 |
| `/capture` | 本机 H1 单帧详情（含 47 + 1 + 3 + 16 + 614 全部参数）+ JSON/CSV 下载 |
| `/settings` | 本机 H1 曝光 / CIE / 工作模式 / 睡眠 |
| `/curve` | 本机 H1 效率曲线上传、校验、恢复出厂 |
| `/logs` | 协议字节级日志（Mock 模式自动拦截） |

## API（部分）

```text
GET    /api/connection                   连接状态
POST   /api/connection                   {mode:'mock'|'serial', port?}
DELETE /api/connection                   断开
GET    /api/device/info                  SN + 波长范围
GET    /api/device/exposure              {mode,timeUs,maxTimeUs}
PATCH  /api/device/exposure              部分字段
GET    /api/device/cie-mode
PUT    /api/device/cie-mode              {mode:'cie1931_2'|...}
PUT    /api/device/working-mode          {mode:'streaming'|'trigger'}
POST   /api/device/sleep                 进入睡眠
POST   /api/device/wake                  唤醒
POST   /api/device/capture[?tm30=1]      单帧采集
GET    /api/device/stream[?tm30=1]       SSE 流（每帧一个 `frame` 事件）
POST   /api/device/stream/stop           停止流
POST   /api/device/efficiency-curve      {ratios:number[]}
POST   /api/device/efficiency-curve/verify
POST   /api/device/efficiency-curve/reset
GET    /api/logs[?sinceId=N]             读取协议日志
POST   /api/logs/pause                   {paused:boolean}
POST   /api/logs/clear                   清空日志
```

错误统一为 JSON：`{ "error": "...", "code"?: number, "cmdType"?: number }`。
