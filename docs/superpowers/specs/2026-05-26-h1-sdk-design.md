# H1 光谱仪 SDK 设计文档

**日期**: 2026-05-26
**版本**: v1
**状态**: Approved
**参考**: [H1 开发者文档 v1](../../2977826138H1开发者文档_v1.pdf)

## 1. 目标

为 H1 光谱仪设备提供 C++、Python、Node.js 三个原生 SDK，覆盖文档定义的全部 20 条命令，可用于桌面应用、后台服务、嵌入式三类场景。

**核心质量要求**：
- 准确：协议层每个字节都与文档对齐；测试基于文档中给出的实例 hex 串
- 高效：协议层零拷贝（或近似），单帧解析 <1ms（不含 IO 等待）
- 易用：每个 SDK 符合本语言惯例，开箱即用

## 2. 架构

**方案 A：三个独立 SDK + 共享协议契约**。三个 SDK 互不依赖，各自用本语言原生实现。通过 `docs/PROTOCOL.md`（含字节级 layout + 测试向量）保证语义一致。

理由：协议简单稳定（20 个命令、固定帧结构、单字节 checksum），不值得 codegen；115200bps 串口下性能瓶颈在硬件，FFI 包装层无价值；用户期望原生 SDK。

## 3. 目录布局

```
spectrum/
├── docs/
│   ├── 2977826138H1开发者文档_v1.pdf       # 原始厂商文档
│   ├── PROTOCOL.md                          # 共享协议契约（权威）
│   └── superpowers/specs/                   # 设计文档
├── sdk/
│   ├── cpp/      include/h1/  src/  examples/  tests/  CMakeLists.txt
│   ├── python/   h1_sdk/  examples/  tests/  pyproject.toml
│   └── nodejs/   src/  examples/  test/  package.json  tsconfig.json
└── .gitignore
```

## 4. 协议契约（节选 — 完整版见 `docs/PROTOCOL.md`）

### 4.1 串口参数
115200bps / 8N1 / NONE

### 4.2 帧结构

**命令帧（主机→设备）**
```
0xCC 0x01 | totalLen[3B LE] | cmdType[1B] | cmdData[N B] | checksum[1B] | 0x0D 0x0A
```
- `totalLen` = 整帧总字节数 = 9 + N
- `checksum` = 此字节之前所有字节之和 & 0xFF

**响应帧（设备→主机）**
```
0xCC 0x81 | totalLen[3B LE] | dataType[1B] | validData[N B] | checksum[1B] | 0x0D 0x0A
```
- `dataType` == 请求时的 `cmdType`

### 4.3 数值约定
所有 multi-byte 整数和 float 都是**小端**（low byte first）。Float 是 IEEE 754 32-bit。

### 4.4 命令一览（20 条）

| Code | 名称 | cmdData | 返回有效数据 |
|------|------|---------|--------------|
| 0x04 | 停止采集 | 空 | 无（仅停止） |
| 0x08 | 获取设备信息 | `0x18` (长度=24) | 24B SN ASCII |
| 0x0A | 设置曝光模式 | `mode: u8` (0=manual, 1=auto) | u8 状态 |
| 0x0B | 获取曝光模式 | 空 | u8 mode |
| 0x0C | 设置曝光值 | `us: u32` | u8 状态 |
| 0x0D | 获取曝光值 | 空 | u32 us |
| 0x0F | 获取光谱波长范围 | 空 | `start: u16` + `end: u16` |
| 0x13 | 设置最大曝光时间 | `us: u32` | u8 状态 |
| 0x14 | 获取最大曝光时间 | 空 | u32 us |
| 0x23 | 发送效率曲线 (分包) | 见 §4.6 | — |
| 0x25 | 效率曲线恢复出厂 | 空 | u8 状态 |
| 0x27 | 校验并计算效率曲线 | 空 | u8 状态 |
| 0x32 | 单帧采集（不含 TM30） | 空 | SpectrumFrame |
| 0x33 | 连续采集（不含 TM30） | 空 | SpectrumFrame 流 |
| 0x34 | 单帧采集（含 TM30） | 空 | SpectrumFrame + TM30 |
| 0x35 | 连续采集（含 TM30） | 空 | SpectrumFrame + TM30 流 |
| 0x36 | 设置 CIE 模式 | `mode: u8` | u8 状态 |
| 0x37 | 获取 CIE 模式 | 空 | u8 mode |
| 0x40 | 进入/退出睡眠 | 空 | 无 |
| 0x41 | 设置工作模式 | `mode: u8` (0=streaming, 1=trigger) | u8 状态 |

设备状态码：`0x00`=成功，`0x15`=命令非法，`0xFF`=不支持/超范围。

### 4.5 SpectrumFrame 数据 layout

不含 TM30（cmdType 0x32/0x33）：
```
exposureStatus      u8       1 字节
exposureTimeUs      u32      4 字节
photometric         f32 × 47   188 字节
blueHazard          f32 × 1    4 字节
nir                 f32 × 3    12 字节
plant               f32 × 16   64 字节
spectrumCoefficient i16        2 字节
rawSpectrum         u16 × M    2M 字节
                              (M = wavelengthEnd - wavelengthStart + 1)
```
含 TM30（cmdType 0x34/0x35）：在 plant 和 spectrumCoefficient 之间插入 `tm30: f32 × 614` (2456 字节)。

**关键换算**：actualSpectrum[i] = rawSpectrum[i] / 10^spectrumCoefficient

### 4.6 效率曲线上传协议
1. 发起始包：`cmdType=0x23, cmdData=0x04`
2. 拆包发送 ratio 数组（每包 cmdData ≤ 999 字节），每包都用 `cmdType=0x23`
3. 发 `cmdType=0x27` 触发校验+计算

### 4.7 校验和算法（伪代码）
```
checksum = sum(all bytes from header[0] through last data byte) & 0xFF
```

## 5. 测试向量（取自 PDF 实例）

| 操作 | 字节序列 |
|------|----------|
| 命令 - 获取波长 | `CC 01 09 00 00 0F E5 0D 0A` |
| 响应 - 波长 340~1050 | `CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A` |
| 命令 - 停止 | `CC 01 09 00 00 04 DA 0D 0A` |
| 命令 - 设备信息 | `CC 01 0A 00 00 08 18 F7 0D 0A` |
| 响应 - SN `H11B6V10534CFPD-100-0002` | `CC 81 21 00 00 08 48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 B5 0D 0A` |
| 命令 - 设手动曝光 | `CC 01 0A 00 00 0A 00 E1 0D 0A` |
| 响应 - 成功 (0x0A) | `CC 81 0A 00 00 0A 00 61 0D 0A` |
| 响应 - 非法 (0x0A) | `CC 81 0A 00 00 0A 15 76 0D 0A` |
| 响应 - 不支持 (0x0A) | `CC 81 0A 00 00 0A FF 60 0D 0A` |
| 命令 - 设曝光 100ms | `CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A` |
| 响应 - 曝光值 100000us | `CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A` |
| 命令 - 设最大曝光 5000ms | `CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A` |
| 响应 - 最大曝光 1000000us | `CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A` |
| 命令 - 设 CIE2015 2° | `CC 01 0A 00 00 36 02 0F 0D 0A` |
| 响应 - CIE 2015 2° | `CC 81 0A 00 00 37 02 90 0D 0A` |
| 命令 - 单帧采集 | `CC 01 09 00 00 32 08 0D 0A` |
| 命令 - 连续采集 | `CC 01 09 00 00 33 09 0D 0A` |
| 命令 - 单帧+TM30 | `CC 01 09 00 00 34 0A 0D 0A` |
| 命令 - 连续+TM30 | `CC 01 09 00 00 35 0B 0D 0A` |
| 命令 - 效率曲线起始 | `CC 01 0A 00 00 23 04 FE 0D 0A` |
| 命令 - 校验效率曲线 | `CC 01 09 00 00 27 FD 0D 0A` |
| 命令 - 恢复曲线 | `CC 01 09 00 00 25 FB 0D 0A` |
| 命令 - 设 trigger 模式 | `CC 01 0A 00 00 41 01 19 0D 0A` |
| 命令 - 睡眠 | `CC 01 09 00 00 40 16 0D 0A` |

## 6. 数据结构（每语言一份，命名按惯例）

### 6.1 PhotometricParams（47 float，顺序与文档表 1 一致）

```
X, Y, Z,                          // CIE1931 三刺激
x, y,                             // CIE1931 色度坐标
uk, vk,                           // CIE1960 色度坐标
u_prime, v_prime,                 // CIE1976 色度坐标
CCT,                              // 色温
Nit,                              // 亮度
r_ratio, g_ratio, b_ratio,        // 红/绿/蓝比 (%)
DUV,                              // 色度偏移
Ra,                               // 显色指数 (R1-15 均值)
R1..R15,                          // 显色指数
Lp,                               // 峰值波长 (nm)
HW,                               // 半峰宽 (nm)
Ld,                               // 主波长 (nm)
purity,                           // 色纯度 (%)
SP,                               // 明暗视觉比
SDCM_k,                           // 色容差
k,                                // 色温 k
lux, Ee, fc,                      // 照度 / 辐照度 / 英尺烛光
CQS,                              // 色质指数
GAI_EES,                          // 8 标准+EES 色域指数
GAI_BB_8,                         // 8 标准+黑体色域
GAI_BB_15,                        // 15 标准+黑体色域
EML,                              // 视黑素等效勒克斯
M_EDI                             // 视黑素等效日光照度
```

### 6.2 其他结构
- `BlueHazardParams`: `Eb` (蓝光危害加权辐照度 W/m²)
- `NirParams`: `redEe` (701-780), `nirEeA` (781-800), `nirEeB` (>800)
- `PlantParams` (16): `PAR, Eca, Ecb, Eb, Ey, Er, Erb_ratio, PPFD, PPFDb, PPFDy, PPFDr, PPFDfr, PPFDr_ratio, PPFDy_ratio, PPFDb_ratio, YPFD`
- `Tm30Params` (614 float, 按顺序): `referenceSpectrum[401]`, `Eab[99]`, `Rf`, `Rg`, `chromaShift[16]`, `hueShift[16]`, `colorFidelity[16]`, `cesAbTest[16][2]`, `cesAbReference[16][2]` （合计 401+99+1+1+16+16+16+32+32 = 614）
- `SpectrumFrame`: 见 §4.5
- `WavelengthRange`: `start: u16`, `end: u16` (nm)
- `DeviceInfo`: `serialNumber: string` (24 字符)

## 7. API 设计

### 7.1 C++ API (C++17, `namespace h1`)

```cpp
// 枚举
enum class ExposureMode : uint8_t { Manual = 0, Auto = 1 };
enum class WorkingMode : uint8_t { Streaming = 0, Trigger = 1 };
enum class CieMode : uint8_t { Cie1931_2 = 0, Cie1964_10 = 1, Cie2015_2 = 2, Cie2015_10 = 3 };
enum class ExposureStatus : uint8_t { Normal = 0, Over = 1, Under = 2 };

// 串口抽象
class ISerialPort {
public:
    virtual ~ISerialPort() = default;
    virtual size_t write(const uint8_t* data, size_t len) = 0;
    virtual size_t read(uint8_t* buf, size_t max_len, std::chrono::milliseconds timeout) = 0;
    virtual void close() = 0;
};
std::unique_ptr<ISerialPort> openSerialPort(const std::string& path, int baud = 115200);

// 异常
class H1Error : public std::runtime_error { ... };
class ProtocolError : public H1Error { ... };
class TimeoutError : public H1Error { ... };
class DeviceError : public H1Error { uint8_t code() const; uint8_t cmdType() const; };

// 设备
class Device {
public:
    explicit Device(std::unique_ptr<ISerialPort> port);
    ~Device();

    DeviceInfo       getDeviceInfo();
    WavelengthRange  getWavelengthRange();

    void             setExposureMode(ExposureMode);
    ExposureMode     getExposureMode();
    void             setExposureTimeUs(uint32_t us);
    uint32_t         getExposureTimeUs();
    void             setMaxExposureTimeUs(uint32_t us);
    uint32_t         getMaxExposureTimeUs();

    void             setCieMode(CieMode);
    CieMode          getCieMode();
    void             setWorkingMode(WorkingMode);
    void             enterSleep();
    void             exitSleep();

    SpectrumFrame    captureSingle(bool includeTm30 = false);

    void             startStreaming(std::function<void(SpectrumFrame)> onFrame,
                                    bool includeTm30 = false,
                                    std::function<void(std::exception_ptr)> onError = nullptr);
    void             stopStreaming();
    bool             isStreaming() const;

    void             uploadEfficiencyCurve(const std::vector<float>& ratios);
    void             verifyAndComputeEfficiencyCurve();
    void             resetEfficiencyCurve();

private:
    struct Impl;
    std::unique_ptr<Impl> pimpl_;
};
```

### 7.2 Python API (Python 3.9+)

```python
# h1_sdk/__init__.py 暴露:
from .device import Device, AsyncDevice
from .types import (
    SpectrumFrame, PhotometricParams, BlueHazardParams,
    NirParams, PlantParams, Tm30Params, WavelengthRange, DeviceInfo,
    ExposureMode, WorkingMode, CieMode, ExposureStatus,
)
from .errors import H1Error, ProtocolError, TimeoutError, DeviceError

# 同步 Device
class Device:
    def __init__(self, port: str | serial.Serial, baudrate: int = 115200): ...
    def __enter__(self) -> "Device": ...
    def __exit__(self, *exc) -> None: ...
    def close(self) -> None: ...

    def get_device_info(self) -> DeviceInfo: ...
    def get_wavelength_range(self) -> WavelengthRange: ...
    def set_exposure_mode(self, mode: ExposureMode) -> None: ...
    def get_exposure_mode(self) -> ExposureMode: ...
    def set_exposure_time_us(self, us: int) -> None: ...
    def get_exposure_time_us(self) -> int: ...
    def set_max_exposure_time_us(self, us: int) -> None: ...
    def get_max_exposure_time_us(self) -> int: ...
    def set_cie_mode(self, mode: CieMode) -> None: ...
    def get_cie_mode(self) -> CieMode: ...
    def set_working_mode(self, mode: WorkingMode) -> None: ...
    def enter_sleep(self) -> None: ...
    def exit_sleep(self) -> None: ...
    def capture_single(self, include_tm30: bool = False) -> SpectrumFrame: ...
    def stream(self, include_tm30: bool = False) -> Iterator[SpectrumFrame]: ...
    def upload_efficiency_curve(self, ratios: Sequence[float]) -> None: ...
    def verify_and_compute_efficiency_curve(self) -> None: ...
    def reset_efficiency_curve(self) -> None: ...

# 异步变体（asyncio）
class AsyncDevice:
    async def get_device_info(self) -> DeviceInfo: ...
    # ... 所有方法对应的 async 版本
    async def stream(self, include_tm30: bool = False) -> AsyncIterator[SpectrumFrame]: ...
```

### 7.3 Node.js API (TypeScript, package `@h1/sdk`)

```typescript
import { EventEmitter } from 'events';
import type { SerialPort } from 'serialport';

export class Device extends EventEmitter {
    constructor(port: SerialPort | string, options?: { baudRate?: number });

    getDeviceInfo(): Promise<DeviceInfo>;
    getWavelengthRange(): Promise<WavelengthRange>;
    setExposureMode(mode: ExposureMode): Promise<void>;
    getExposureMode(): Promise<ExposureMode>;
    setExposureTimeUs(us: number): Promise<void>;
    getExposureTimeUs(): Promise<number>;
    setMaxExposureTimeUs(us: number): Promise<void>;
    getMaxExposureTimeUs(): Promise<number>;
    setCieMode(mode: CieMode): Promise<void>;
    getCieMode(): Promise<CieMode>;
    setWorkingMode(mode: WorkingMode): Promise<void>;
    enterSleep(): Promise<void>;
    exitSleep(): Promise<void>;
    captureSingle(includeTm30?: boolean): Promise<SpectrumFrame>;

    startStreaming(includeTm30?: boolean): Promise<void>;
    stopStreaming(): Promise<void>;

    uploadEfficiencyCurve(ratios: number[] | Float32Array): Promise<void>;
    verifyAndComputeEfficiencyCurve(): Promise<void>;
    resetEfficiencyCurve(): Promise<void>;

    close(): Promise<void>;

    // Events
    on(event: 'frame', listener: (frame: SpectrumFrame) => void): this;
    on(event: 'error', listener: (err: Error) => void): this;
    on(event: 'close', listener: () => void): this;
}
```

## 8. 错误处理

三语言对齐的异常层级：

| Type | 触发条件 |
|------|----------|
| `H1Error` | 基类 |
| `ProtocolError` | 帧头/尾不匹配、checksum 失败、totalLen 与实际不符、dataType 与请求 cmdType 不匹配 |
| `TimeoutError` | 串口 read 超时（默认 1000ms，可配置） |
| `DeviceError` | 响应有效数据 = 0x15 (命令非法) 或 0xFF (不支持/超范围)，含命令码和原始字节 |

C++ 是 `std::runtime_error` 子类；Python 是 `Exception` 子类；Node 是 `Error` 子类。`TimeoutError` 命名 Python 端可能与内置冲突，使用 `H1TimeoutError`。

## 9. 测试策略

### 9.1 协议层单元测试（必须 100% 覆盖）
- 用 §5 中所有 hex 串作为 fixture
- 双向测试：构造命令 → 字节匹配；解析响应字节 → 字段匹配
- 边界用例：checksum 错、帧头错、长度错、错误码

### 9.2 端到端测试
- 实现 MockSerialPort：可预设"收到 X 命令，回 Y 响应"
- 用 mock 跑完整的 Device 类，每个公开方法至少一个用例
- 覆盖 streaming 启停、TM30 切换、错误传播

### 9.3 真实硬件测试（手动）
- 标记 `@hardware` / `pytest.mark.hardware` / `it.skipIf(!process.env.H1_PORT)`
- 不进入 CI，本地开发者手动跑

### 9.4 覆盖目标
- 协议编解码：100%
- 命令封装：≥ 80%
- 流式：核心路径覆盖（开始、收 N 帧、停止）

## 10. CLI 与示例

每个 SDK 提供以下示例 + 一个 CLI 工具：

**示例（5 个，三语言相同）**
1. `01_device_info` — 连接、获取 SN 和波长范围，打印
2. `02_capture_once` — 单帧采集，打印曝光状态、CCT、Ra、lux
3. `03_stream` — 连续采集 10 帧（自动停止）
4. `04_exposure_control` — 切换手动→设值→切自动，对比
5. `05_efficiency_curve` — 上传一条全 1.0 的曲线（demo）

**CLI 子命令统一**：
- `h1 info` — 设备信息
- `h1 capture [--tm30] [--port /dev/...]` — 单帧
- `h1 stream [--count N] [--tm30] [--csv file]` — 流式
- `h1 set-exposure <us>` / `h1 get-exposure`
- `h1 set-mode <auto|manual>` / `h1 get-mode`
- `h1 reset-curve`

实现选择：C++ 用 [CLI11](https://github.com/CLIUtils/CLI11)（header-only, 可 vendor）；Python 用 `argparse`；Node 用 `commander`。

## 11. 构建与分发

### 11.1 C++
- CMake 3.16+，target-based
- 输出 target：`h1::sdk`（静态库），用户 `target_link_libraries(myapp PRIVATE h1::sdk)`
- 测试用 [doctest](https://github.com/doctest/doctest)（header-only，via FetchContent）
- 不强制 Boost / Qt，零运行时依赖
- 编译：C++17，`-Wall -Wextra -Wpedantic`
- 平台：macOS / Linux (termios) + Windows (Win32 COM API)

### 11.2 Python
- PEP 621 `pyproject.toml`，hatchling backend
- 包名：`h1-sdk`，模块名：`h1_sdk`
- 依赖：`pyserial >= 3.5`
- 开发依赖：`pytest`, `pytest-asyncio`, `pytest-cov`
- 支持 Python 3.9+

### 11.3 Node.js
- 包名：`@h1/sdk`，TypeScript 写源码
- 依赖：`serialport >= 12`
- 输出：CJS + ESM + `.d.ts`（用 tsup 或 tsc 双 build）
- `package.json` `exports` field 配置 dual-package
- Node 18+
- 测试用 vitest

## 12. 交付物清单

### 文档
- [x] 本设计文档
- [ ] `docs/PROTOCOL.md` — 详细协议契约（含所有 20 条命令的字节级 layout 和测试向量）
- [ ] 每个 SDK 的 README.md（安装 / 快速开始 / API 参考链接）

### C++ SDK
- [ ] `sdk/cpp/include/h1/*.hpp` — 公开头文件
- [ ] `sdk/cpp/src/*.cpp` — 实现
- [ ] `sdk/cpp/tests/*.cpp` — doctest 单测
- [ ] `sdk/cpp/examples/*.cpp` — 5 个示例 + CLI
- [ ] `sdk/cpp/CMakeLists.txt` — 构建脚本
- [ ] `sdk/cpp/README.md`

### Python SDK
- [ ] `sdk/python/h1_sdk/*.py` — 包源码
- [ ] `sdk/python/tests/test_*.py` — pytest 单测
- [ ] `sdk/python/examples/*.py` — 5 个示例 + CLI
- [ ] `sdk/python/pyproject.toml`
- [ ] `sdk/python/README.md`

### Node.js SDK
- [ ] `sdk/nodejs/src/*.ts` — TypeScript 源码
- [ ] `sdk/nodejs/test/*.test.ts` — vitest 单测
- [ ] `sdk/nodejs/examples/*.ts` — 5 个示例 + CLI
- [ ] `sdk/nodejs/package.json` + `tsconfig.json`
- [ ] `sdk/nodejs/README.md`

### 验证
- [ ] C++ `cmake --build build && ctest --test-dir build` 通过
- [ ] Python `pytest` 通过
- [ ] Node.js `npm test` 通过

## 13. 已废弃 / 不做的事

- ❌ 不做语言间 FFI 绑定
- ❌ 不做 codegen
- ❌ 不依赖 Boost / Qt
- ❌ 不实现 GUI
- ❌ 不发布到 PyPI / npm（仅源码可用，留给用户决定）
- ❌ 不做 protocol fuzzing（超出 SDK 范围）
