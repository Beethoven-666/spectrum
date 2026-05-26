# H1 调试台 (`h1-webui`)

基于 Next.js 15 (App Router) + shadcn/ui 的 H1 光谱仪开发调试 Web UI。
复用本仓库的 [`@h1/sdk`](../sdk/nodejs/) 进行所有协议通信。

## 模式

- **Mock 模式（默认）**：内置 `MockSerialPort` + 合成数据生成器，无需任何硬件即可使用。
- **真实串口**：通过环境变量 `H1_PORT=/dev/cu.usbserial-XXXX` 切换，或在 UI 顶部"连接"侧栏中选择"串口"页签。

## 环境变量

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `H1_MOCK` | 设为 `1` 时强制 Mock | 未设置时也默认 mock |
| `H1_PORT` | 真实串口路径 | 仅当无 `H1_MOCK` 且需要硬件时设置 |

## 开发

仓库根目录提供 workspace 脚本：

```bash
# 1) 安装并构建 SDK（webui 引用 dist/）
npm install
npm run build:sdk

# 2) 启动 dev server（默认 mock 模式）
npm run dev:webui
# 或
H1_MOCK=1 npm run dev -w h1-webui

# 3) 构建
npm run build:webui
```

启动后访问 <http://localhost:3000>。

## 路由

| 页面 | 说明 |
| --- | --- |
| `/` | 仪表盘：连接信息、单帧快速采集 |
| `/stream` | SSE 实时光谱流，FPS / 累计帧统计 |
| `/capture` | 单帧详情（含 47 + 1 + 3 + 16 + 614 全部参数）+ JSON/CSV 下载 |
| `/settings` | 曝光 / CIE / 工作模式 / 睡眠 |
| `/curve` | 效率曲线上传、校验、恢复出厂 |
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
