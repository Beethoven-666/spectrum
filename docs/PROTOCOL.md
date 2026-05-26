# H1 光谱仪串口协议契约 (PROTOCOL.md)

**版本**: v1 (基于 `2977826138H1开发者文档_v1.pdf`)
**状态**: SDK 实现依据，三种 SDK 必须严格对齐此文件

这是三个 SDK（C++/Python/Node.js）的权威协议规范。本文件中的所有字节序列、字段顺序、长度、校验算法都必须 1:1 实现。

---

## 1. 链路层

| 项 | 值 |
|----|----|
| 波特率 | 115200 bps |
| 数据位 | 8 |
| 停止位 | 1 |
| 校验 | NONE |
| 流控 | NONE |
| 字节序 | 小端 (little-endian) — 适用于所有 u16/u32/i16/float |

Float = IEEE 754 binary32。

---

## 2. 帧结构

### 2.1 命令帧（主机 → 设备）

```
+--------+--------+----------+----------+-----------+----------+----------+
| 0xCC   | 0x01   | totalLen | cmdType  | cmdData   | checksum | 0x0D 0x0A|
| (1B)   | (1B)   | (3B LE)  | (1B)     | (N B)     | (1B)     | (2B)     |
+--------+--------+----------+----------+-----------+----------+----------+
```

- `totalLen` 是整帧总字节数（含头尾），= 9 + N，编码为 3 字节小端 uint
- `checksum` = (`0xCC` + `0x01` + totalLen.bytes + cmdType + cmdData.bytes) & 0xFF

### 2.2 响应帧（设备 → 主机）

```
+--------+--------+----------+----------+-----------+----------+----------+
| 0xCC   | 0x81   | totalLen | dataType | validData | checksum | 0x0D 0x0A|
| (1B)   | (1B)   | (3B LE)  | (1B)     | (N B)     | (1B)     | (2B)     |
+--------+--------+----------+----------+-----------+----------+----------+
```

- `dataType` 必须等于请求的 `cmdType`
- 同 `totalLen`、`checksum` 计算

### 2.3 校验和算法

```c
uint8_t checksum(const uint8_t* bytes, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) sum += bytes[i];
    return (uint8_t)(sum & 0xFF);
}
```

把 `len` 设为"checksum 字段在帧中的位置"。验证响应时：算同样的 sum，比对 checksum 字节。

### 2.4 totalLen 编码

`totalLen` 是 3 字节小端 uint24。例：1706 = `0xAA 0x06 0x00`；13 = `0x0D 0x00 0x00`。

---

## 3. 命令表（共 20 条）

### 3.1 速查表

| Code | 名称 | cmdData | 响应 validData |
|------|------|---------|----------------|
| 0x04 | StopCapture | (空) | (空，无响应) |
| 0x08 | GetDeviceInfo | u8 (length=0x18) | 24B SN |
| 0x0A | SetExposureMode | u8 | u8 status |
| 0x0B | GetExposureMode | (空) | u8 mode |
| 0x0C | SetExposureTime | u32 us | u8 status |
| 0x0D | GetExposureTime | (空) | u32 us |
| 0x0F | GetWavelengthRange | (空) | u16 start + u16 end |
| 0x13 | SetMaxExposureTime | u32 us | u8 status |
| 0x14 | GetMaxExposureTime | (空) | u32 us |
| 0x23 | SendEfficiencyCurve | (special, 见 §3.16) | (无中间响应) |
| 0x25 | ResetEfficiencyCurve | (空) | u8 status |
| 0x27 | VerifyEfficiencyCurve | (空) | u8 status |
| 0x32 | CaptureSingleNoTm30 | (空) | SpectrumFrame (见 §4) |
| 0x33 | StartStreamNoTm30 | (空) | SpectrumFrame 流 |
| 0x34 | CaptureSingleWithTm30 | (空) | SpectrumFrameWithTm30 |
| 0x35 | StartStreamWithTm30 | (空) | SpectrumFrameWithTm30 流 |
| 0x36 | SetCieMode | u8 | u8 status |
| 0x37 | GetCieMode | (空) | u8 mode |
| 0x40 | EnterExitSleep | (空) | (无响应) |
| 0x41 | SetWorkingMode | u8 | u8 status |

### 3.2 设备状态码

响应 validData 是 u8 时（设置类命令）：
- `0x00` — 成功
- `0x15` — 命令包不合法
- `0xFF` — 设备不支持或参数超范围

SDK 应把 `0x15` 和 `0xFF` 转换为 `DeviceError`。

### 3.3 枚举值

**ExposureMode** (cmd/resp 0x0A, 0x0B)
- `0x00` Manual
- `0x01` Auto

**WorkingMode** (cmd 0x41)
- `0x00` Streaming
- `0x01` Trigger

**CieMode** (cmd 0x36, resp 0x37)
- `0x00` CIE 1931 2°
- `0x01` CIE 1964 10°
- `0x02` CIE 2015 2°
- `0x03` CIE 2015 10°

**ExposureStatus** (SpectrumFrame 第一字节)
- `0x00` Normal
- `0x01` Over (过曝)
- `0x02` Under (欠曝)

### 3.4 命令详细（带测试向量）

每个命令给出：
- 命令构造（hex）
- 典型响应（hex 或字段说明）

---

#### CMD 0x04 — 停止采集

**命令**: `CC 01 09 00 00 04 DA 0D 0A`

```
header        : CC 01
totalLen      : 09 00 00       (= 9)
cmdType       : 04
cmdData       : (empty)
checksum      : DA             (= 0xCC+0x01+0x09+0x00+0x00+0x04 = 0xDA)
footer        : 0D 0A
```

**响应**: 无（设备静默停止）

---

#### CMD 0x08 — 获取设备信息

**命令**: `CC 01 0A 00 00 08 18 F7 0D 0A`

```
totalLen      : 0A 00 00       (= 10)
cmdType       : 08
cmdData       : 18             (期望长度 = 24)
checksum      : F7
```

**响应（SN = `H11B6V10534CFPD-100-0002`）**:
```
CC 81 21 00 00 08
48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32
B5 0D 0A
```
- totalLen = 0x21 = 33
- dataType = 08
- validData = 24 字节 ASCII SN
- checksum = 0xB5

---

#### CMD 0x0A — 设置曝光模式

**命令（手动）**: `CC 01 0A 00 00 0A 00 E1 0D 0A`
**命令（自动）**: `CC 01 0A 00 00 0A 01 E2 0D 0A`

**响应（成功）**: `CC 81 0A 00 00 0A 00 61 0D 0A`
**响应（非法 0x15）**: `CC 81 0A 00 00 0A 15 76 0D 0A`
**响应（不支持 0xFF）**: `CC 81 0A 00 00 0A FF 60 0D 0A`

---

#### CMD 0x0B — 获取曝光模式

**命令**: `CC 01 09 00 00 0B E1 0D 0A`
**响应（手动）**: `CC 81 0A 00 00 0B 00 62 0D 0A`
**响应（自动）**: `CC 81 0A 00 00 0B 01 63 0D 0A`

---

#### CMD 0x0C — 设置曝光值

cmdData: 4 字节 u32 小端，单位 us。

**命令（设 100ms = 100000us = 0x000186A0）**: `CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A`

```
totalLen      : 0D 00 00       (= 13)
cmdType       : 0C
cmdData       : A0 86 01 00    (LE u32 = 100000)
checksum      : 0D             (sum = 0x20D & 0xFF)
```

**响应（成功）**: `CC 81 0A 00 00 0C 00 63 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 0C 15 78 0D 0A`
**响应（超范围）**: `CC 81 0A 00 00 0C FF 62 0D 0A`

---

#### CMD 0x0D — 获取曝光值

**命令**: `CC 01 09 00 00 0D E3 0D 0A`
**响应（100000us）**: `CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A`
- validData = LE u32

---

#### CMD 0x0F — 获取光谱波长范围

**命令**: `CC 01 09 00 00 0F E5 0D 0A`
**响应（340~1050）**: `CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A`
- validData = `54 01 1A 04` = `u16 start=0x0154=340` + `u16 end=0x041A=1050`
- checksum = 0xDC

---

#### CMD 0x13 — 设置最大曝光时间

cmdData: 4 字节 u32 小端，单位 us。

**命令（设 5000ms = 5000000us = 0x004C4B40）**: `CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A`

**响应（成功）**: `CC 81 0A 00 00 13 00 6A 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 13 15 7F 0D 0A`

---

#### CMD 0x14 — 获取最大曝光时间

**命令**: `CC 01 09 00 00 14 EA 0D 0A`
**响应（1000000us = 0x000F4240）**: `CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A`

---

#### CMD 0x23 — 发送效率曲线（分包）

**约束**：波特率 ≥ 115200。

**步骤 1 — 发送起始包**:
`CC 01 0A 00 00 23 04 FE 0D 0A`
- cmdData = `0x04`（标识此为起始包）

**步骤 2 — 分包发送 float 数组**:
- 每包总长 ≤ 999 字节（因此 cmdData 部分 ≤ 990 字节，即一次最多 247 个 float）
- 每包 cmdType 都是 `0x23`
- cmdData = 该包的 ratio 字节流（小端 float32）
- 顺序拼接构成完整的 ratio 数组

**示例（PDF 节选）— 661 个 1.5 拆 3 包发送**:
- ratio[0..247]: 第一包 cmdData = 247 × `00 00 C0 3F`
- ratio[248..495]: 第二包
- ratio[496..660]: 第三包（165 个）

**步骤 3 — 校验并计算**: 见 CMD 0x27

---

#### CMD 0x25 — 效率曲线恢复出厂

**命令**: `CC 01 09 00 00 25 FB 0D 0A`
**响应（成功）**: `CC 81 0A 00 00 25 00 7C 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 25 15 91 0D 0A`
**响应（不支持）**: `CC 81 0A 00 00 25 FF 7B 0D 0A`

---

#### CMD 0x27 — 校验并计算效率曲线

**命令**: `CC 01 09 00 00 27 FD 0D 0A`
**响应（成功）**: `CC 81 0A 00 00 27 00 7E 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 27 15 93 0D 0A`
**响应（失败 0xFF）**: `CC 81 0A 00 00 27 FF 7D 0D 0A`

失败原因（设备日志）：
1. 设备不支持修改效率曲线
2. 发送的 ratio 长度异常
3. 写入 flash 失败

---

#### CMD 0x32 — 单帧采集（不含 TM30）

**命令**: `CC 01 09 00 00 32 08 0D 0A`
**响应**: SpectrumFrame（无 TM30），见 §4

---

#### CMD 0x33 — 连续采集（不含 TM30）

**命令**: `CC 01 09 00 00 33 09 0D 0A`
**响应**: SpectrumFrame 流，每帧独立成包

发送 CMD 0x04 可停止流。

---

#### CMD 0x34 — 单帧采集（含 TM30）

**命令**: `CC 01 09 00 00 34 0A 0D 0A`
**响应**: SpectrumFrameWithTm30，见 §4

---

#### CMD 0x35 — 连续采集（含 TM30）

**命令**: `CC 01 09 00 00 35 0B 0D 0A`
**响应**: SpectrumFrameWithTm30 流

---

#### CMD 0x36 — 设置 CIE 模式

cmdData: u8 mode 见 §3.3。

**命令（CIE2015 2°）**: `CC 01 0A 00 00 36 02 0F 0D 0A`
**响应（成功）**: `CC 81 0A 00 00 36 00 8D 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 36 15 8C 0D 0A`
**响应（不支持）**: `CC 81 0A 00 00 36 FF 8C 0D 0A`

---

#### CMD 0x37 — 获取 CIE 模式

**命令**: `CC 01 09 00 00 37 0D 0D 0A`
**响应（CIE2015 2°）**: `CC 81 0A 00 00 37 02 90 0D 0A`

---

#### CMD 0x40 — 进入/退出睡眠

**命令**: `CC 01 09 00 00 40 16 0D 0A`
**响应**: 无

调用一次进入睡眠，再调用一次退出。

---

#### CMD 0x41 — 设置工作模式

cmdData: u8 见 §3.3 WorkingMode。

**命令（trigger 模式）**: `CC 01 0A 00 00 41 01 19 0D 0A`
**命令（streaming 模式）**: `CC 01 0A 00 00 41 00 18 0D 0A`

**响应（成功）**: `CC 81 0A 00 00 41 00 98 0D 0A`
**响应（非法）**: `CC 81 0A 00 00 41 15 AD 0D 0A`
**响应（失败）**: `CC 81 0A 00 00 41 FF 97 0D 0A` (检查曝光时间是否超出 trigger 模式有效范围 7~59ms)

---

## 4. SpectrumFrame 数据 layout

### 4.1 不含 TM30（响应 0x32 / 0x33）

validData 字段按以下顺序紧凑排列：

| 偏移 | 长度 | 字段 | 类型 |
|------|------|------|------|
| 0 | 1 | exposureStatus | u8 (见 ExposureStatus) |
| 1 | 4 | exposureTimeUs | u32 LE |
| 5 | 188 | photometric | f32 × 47 (见 §5.1) |
| 193 | 4 | blueHazard | f32 × 1 (Eb) |
| 197 | 12 | nir | f32 × 3 (RedEe, NirEeA, NirEeB) |
| 209 | 64 | plant | f32 × 16 (见 §5.4) |
| 273 | 2 | spectrumCoefficient | i16 LE (N) |
| 275 | 2M | rawSpectrum | u16 × M LE (M = wlEnd - wlStart + 1) |

**validData 总长** = 275 + 2M 字节

**totalLen** = validData + 9（头2 + len3 + dataType1 + checksum1 + footer2）

**典型值（M = 711）**:
```
validData = 275 + 1422 = 1697
totalLen  = 1697 + 9 = 1706 = 0xAA 0x06 0x00
```

PDF 给出的帧头：`CC 81 AA 06 00 32 00 C4 09 00 00 ...`
- exposureStatus = 0x00 (Normal)
- exposureTimeUs = `C4 09 00 00` = 0x9C4 = 2500 µs

### 4.2 含 TM30（响应 0x34 / 0x35）

| 偏移 | 长度 | 字段 |
|------|------|------|
| 0 | 1 | exposureStatus |
| 1 | 4 | exposureTimeUs |
| 5 | 188 | photometric |
| 193 | 4 | blueHazard |
| 197 | 12 | nir |
| 209 | 64 | plant |
| 273 | 2456 | tm30 (f32 × 614) |
| 2729 | 2 | spectrumCoefficient |
| 2731 | 2M | rawSpectrum |

**validData 总长** = 2731 + 2M

**典型值（M = 711）**:
```
validData = 2731 + 1422 = 4153
totalLen  = 4153 + 9 = 4162 = 0x42 0x10 0x00
```

PDF 给出的帧头：`CC 81 42 10 00 34 00 C4 09 00 00 ...`

### 4.3 光谱真实值换算

```
actualSpectrum[i] = rawSpectrum[i] / (10 ^ spectrumCoefficient)
```

`spectrumCoefficient` 是 i16（可为正可为负）。例如 N=2，rawSpectrum=1300，实际值=13.0。

---

## 5. 数据表字段顺序（**严格按此顺序解析 float 数组**）

### 5.1 PhotometricParams (47 float)

| Idx | 名称 | 单位 | 说明 |
|-----|------|------|------|
| 0 | X | — | CIE1931 X |
| 1 | Y | — | CIE1931 Y |
| 2 | Z | — | CIE1931 Z |
| 3 | x | — | CIE1931 色度坐标 x |
| 4 | y | — | CIE1931 色度坐标 y |
| 5 | uk | — | CIE1960 u |
| 6 | vk | — | CIE1960 v |
| 7 | u_prime | — | CIE1976 u' |
| 8 | v_prime | — | CIE1976 v' |
| 9 | CCT | K | 色温 |
| 10 | Nit | nit | 亮度 |
| 11 | r_ratio | % | 红色比 |
| 12 | g_ratio | % | 绿色比 |
| 13 | b_ratio | % | 蓝色比 |
| 14 | DUV | — | 色度偏移；\|DUV\|>0.05 时 CCT 仅供参考 |
| 15 | Ra | — | 显色指数 (R1-15 均值) |
| 16-30 | R1..R15 | — | 显色指数 |
| 31 | Lp | nm | 峰值波长 |
| 32 | HW | nm | 半峰宽 |
| 33 | Ld | nm | 主波长 |
| 34 | purity | % | 色纯度 |
| 35 | SP | — | 明暗视觉比 |
| 36 | SDCM_k | — | 在色温 k 下的色容差 |
| 37 | k | — | 色温 k |
| 38 | lux | lx | 照度 |
| 39 | Ee | W/m² | 辐照度 |
| 40 | fc | fc | 英尺烛光 |
| 41 | CQS | — | 色质指数 |
| 42 | GAI_EES | — | 8 标准色 + 等能量谱色域指数 |
| 43 | GAI_BB_8 | — | 8 标准色 + 黑体色域指数 |
| 44 | GAI_BB_15 | — | 15 标准色 + 黑体色域指数 |
| 45 | EML | lx | 视黑素等效勒克斯 |
| 46 | M_EDI | lx | 视黑素等效日光照度 |

PDF 列表原文（CSV 形式）:
```
X,Y,Z,x,y,u,v,u',v',CCT,Nit,r_ratio,g_ratio,b_ratio,DUV,
Ra,R1,R2,R3,R4,R5,R6,R7,R8,R9,R10,R11,R12,R13,R14,R15,
Lp,HW,Ld,purity,SP,SDCM/k,k,lux,Ee,fc,CQS,
GAI_EES,GAI_BB_8,GAI_BB_15,EML,M_EDI
```

### 5.2 BlueHazardParams (1 float)
| Idx | 名称 | 单位 | 说明 |
|-----|------|------|------|
| 0 | Eb | W/m² | 蓝光危害加权辐照度 |

### 5.3 NirParams (3 float)
| Idx | 名称 | 范围 | 单位 |
|-----|------|------|------|
| 0 | redEe | 701-780 nm | W/m² |
| 1 | nirEeA | 781-800 nm | W/m² |
| 2 | nirEeB | >800 nm | W/m² |

### 5.4 PlantParams (16 float)
| Idx | 名称 | 单位 | 说明 |
|-----|------|------|------|
| 0 | PAR | — | 光合有效辐射 |
| 1 | Eca | W/m² | 叶绿素 A 加权辐照度 |
| 2 | Ecb | W/m² | 叶绿素 B 加权辐照度 |
| 3 | Eb | W/m² | 蓝紫辐照度 (400-500) |
| 4 | Ey | W/m² | 黄绿辐照度 (500-600) |
| 5 | Er | W/m² | 红橙辐照度 (600-700) |
| 6 | Erb_ratio | % | 红蓝辐照度比 |
| 7 | PPFD | µmol/(m²·s) | 光合光子通量密度 (400-700) |
| 8 | PPFDb | µmol/(m²·s) | 蓝紫 (400-500) |
| 9 | PPFDy | µmol/(m²·s) | 黄绿 (500-600) |
| 10 | PPFDr | µmol/(m²·s) | 红橙 (600-700) |
| 11 | PPFDfr | µmol/(m²·s) | 远红橙 (700-780) |
| 12 | PPFDr_ratio | % | 红橙比 |
| 13 | PPFDy_ratio | % | 黄绿比 |
| 14 | PPFDb_ratio | % | 蓝紫比 |
| 15 | YPFD | µmol/(m²·s) | 产生的光子通量密度 |

### 5.5 Tm30Params (614 float)

按以下偏移和数量解析：

| 偏移 (float index) | 数量 | 字段 |
|--------------------|------|------|
| 0 | 401 | referenceSpectrum[401] |
| 401 | 99 | Eab[99] |
| 500 | 1 | Rf |
| 501 | 1 | Rg |
| 502 | 16 | chromaShift[16] |
| 518 | 16 | hueShift[16] |
| 534 | 16 | colorFidelity[16] |
| 550 | 32 | cesAbTest[16][2] (16 对 a',b'，每对相邻两个 float = a' 然后 b') |
| 582 | 32 | cesAbReference[16][2] |
| **Total** | **614** | |

---

## 6. 错误检测（SDK 必须实现）

收到任何响应帧时，按下列顺序检查：

1. **帧头**: 字节[0..1] 必须 = `CC 81`
2. **totalLen**: 解析后必须等于实际收到的字节数
3. **帧尾**: 最后两个字节必须 = `0D 0A`
4. **校验和**: checksum 字段必须 = sum(从帧头到 validData 末尾) & 0xFF
5. **dataType**: 必须等于请求时发送的 cmdType（流式响应除外，按当前流模式判断）
6. **设备状态码**: 若 validData 是 u8 status：
   - `0x00` 成功
   - `0x15` 抛 `DeviceError` (code=0x15, "invalid command")
   - `0xFF` 抛 `DeviceError` (code=0xFF, "unsupported or out of range")

任何 1-5 失败：抛 `ProtocolError`。
串口 read 超时：抛 `TimeoutError`。

---

## 7. 默认超时建议

| 操作 | 建议超时 |
|------|----------|
| 设置/获取类命令 (小响应) | 1000 ms |
| 单帧采集 (0x32/0x34) | max(2 × exposureTime, 5000) ms |
| 设备信息/波长范围 | 1000 ms |
| 效率曲线上传起始 | 1000 ms |
| 效率曲线计算 (0x27) | 10000 ms |

---

## 8. 实现注意点

1. **流式采集没有显式开始响应**：发送 0x33/0x35 后直接进入接收循环，每个完整帧推给上层。
2. **流式停止**：发送 0x04 后**继续**读 1~2 帧（设备 buffer 中可能还有），然后停止。
3. **TM30 切换**：流式过程中切换含/不含 TM30 必须先停止再重启。
4. **句柄安全**：所有发送操作要互斥（同一时刻只能有一个 in-flight 请求 + 可选的流式接收）。
5. **效率曲线上传**：起始包后立即发数据包，不要等响应；最后用 0x27 触发计算。
6. **设备睡眠后**：唤醒前所有命令会超时；建议唤醒发 0x40，然后 sleep 100ms 再后续命令。
7. **trigger 模式约束**：曝光时间必须 7~59 ms，且必须是手动曝光模式。

---

## 9. SDK 测试矩阵

每个 SDK 必须有这些单元测试用例（hex 来自 §3 各命令小节）：

### 9.1 编码测试（构造命令 → 字节对比）
- StopCapture → `CC 01 09 00 00 04 DA 0D 0A`
- GetDeviceInfo → `CC 01 0A 00 00 08 18 F7 0D 0A`
- SetExposureMode(Manual) → `CC 01 0A 00 00 0A 00 E1 0D 0A`
- SetExposureMode(Auto) → `CC 01 0A 00 00 0A 01 E2 0D 0A`
- GetExposureMode → `CC 01 09 00 00 0B E1 0D 0A`
- SetExposureTime(100000) → `CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A`
- GetExposureTime → `CC 01 09 00 00 0D E3 0D 0A`
- GetWavelengthRange → `CC 01 09 00 00 0F E5 0D 0A`
- SetMaxExposureTime(5000000) → `CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A`
- GetMaxExposureTime → `CC 01 09 00 00 14 EA 0D 0A`
- SendEfficiencyCurveStart → `CC 01 0A 00 00 23 04 FE 0D 0A`
- VerifyEfficiencyCurve → `CC 01 09 00 00 27 FD 0D 0A`
- ResetEfficiencyCurve → `CC 01 09 00 00 25 FB 0D 0A`
- CaptureSingleNoTm30 → `CC 01 09 00 00 32 08 0D 0A`
- StartStreamNoTm30 → `CC 01 09 00 00 33 09 0D 0A`
- CaptureSingleWithTm30 → `CC 01 09 00 00 34 0A 0D 0A`
- StartStreamWithTm30 → `CC 01 09 00 00 35 0B 0D 0A`
- SetCieMode(Cie2015_2) → `CC 01 0A 00 00 36 02 0F 0D 0A`
- GetCieMode → `CC 01 09 00 00 37 0D 0D 0A`
- EnterExitSleep → `CC 01 09 00 00 40 16 0D 0A`
- SetWorkingMode(Trigger) → `CC 01 0A 00 00 41 01 19 0D 0A`

### 9.2 解码测试（字节 → 字段对比）
- DeviceInfo response: bytes → SN = `"H11B6V10534CFPD-100-0002"`
- WavelengthRange response: bytes → `{start: 340, end: 1050}`
- GetExposureTime response (`CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A`) → 100000
- GetMaxExposureTime response (`CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A`) → 1000000
- GetCieMode response (`CC 81 0A 00 00 37 02 90 0D 0A`) → CieMode.Cie2015_2
- Set success response → 不抛
- Set failure response 0x15 → 抛 `DeviceError(code=0x15)`
- Set failure response 0xFF → 抛 `DeviceError(code=0xFF)`

### 9.3 校验和测试
- 篡改任意中间字节后 → 抛 `ProtocolError`
- 截断帧 → 抛 `ProtocolError` 或 `TimeoutError`

### 9.4 SpectrumFrame 解码测试
- 用合成数据：47+1+3+16 float 全 0、coefficient=2、raw 711 个递增 u16
- 验证 photometric/blue/nir/plant 各字段位置正确
- 验证 actualSpectrum = raw / 100
- 同样测含 TM30 的版本（验证 tm30 在正确偏移）
