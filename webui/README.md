# Spectrum 采集台 (`h1-webui`)

基于 Next.js 16 (App Router) + shadcn/ui 的树莓派 H1 + D455 多模态采集 Web UI。
所有 H1 操作经 Python acquisition service 网关，Web UI 不直接打开串口。

## 模式

- **树莓派真实采集（默认）**：`/acquisition` 通过 `ACQUISITION_API_BASE_URL` 访问 acquisition service，读取真实 H1/D455 状态。
- **H1 调试页**：`/debug`、`/capture`、`/settings`、`/curve` 等页面的 `/api/device/*` 路由代理到 acquisition `/h1/*`，与采集页共用同一串口锁。
- **Mock 模式**：启动 acquisition 时加 `--mock`（或配置 `mock: true`），Web UI 无需额外环境变量。

## 环境变量

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `ACQUISITION_API_BASE_URL` | acquisition service 地址 | `http://127.0.0.1:8000` |

## 开发

仓库根目录提供 workspace 脚本：

```bash
# 1) 安装并构建 SDK（webui 引用 dist/）
npm install
npm run build:sdk

# 2) 启动 dev server（需 acquisition service 在线）
npm run dev:webui
# Mock：在另一终端启动 acquisition --mock

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
GET    /api/connection                   acquisition H1 网关状态
GET    /api/device/info                  SN + 波长范围（代理 /h1/info）
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
