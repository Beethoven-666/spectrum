# Acquisition 样本完整预览设计

**日期**: 2026-05-31
**状态**: 已批准实施
**页面**: `http://croprix-spectrum.local:3005/acquisition`

## 1. 背景

`/acquisition` 页面已经包含采集、样本、设置和标定四个操作区。当前“样本”页可以看到 ROI 缩略图、样本 ID、采集时间、质量、距离、角度、H1 曝光状态和下载按钮，但不能在浏览器中直接查看样本包的关键内容。

后端现状已经具备这些基础能力：

- `GET /samples` 返回样本摘要列表。
- `GET /samples/{sample_id}` 返回索引行、`metadata.json` 和 `quality.json`。
- `GET /samples/{sample_id}/preview` 返回 ROI 预览图。
- 样本目录中已经写入 `d455/color.jpg`、`d455/depth.png`、`h1/spectrum.json`、`metadata.json`、`quality.json` 等文件。

因此，本功能不改变采集流程、不改变样本目录结构，重点补齐样本列表页的完整预览体验和安全的只读文件暴露边界。

## 2. 目标

- 在“样本”页中为每条样本提供完整预览入口。
- 使用右侧抽屉保留样本列表上下文，便于连续复核样本。
- 预览内容覆盖 ROI、大图、D455 color/depth、H1 光谱曲线、metadata 和 quality JSON。
- 后端只暴露预定义样本文件，不提供任意路径读取。
- 缺失文件、旧样本或 schema 变化时局部降级，不影响整个页面。

## 3. 非目标

- 不新增独立样本详情路由。
- 不做样本删除、标注、审核状态、重采或 ROI 重新保存。
- 不做点云 3D 查看。
- 不修改采集、曝光、几何计算或 SQLite 索引写入逻辑。
- 不把样本目录变成通用文件浏览器。

## 4. 交互设计

样本行保留现有摘要信息和下载按钮，并新增“预览”按钮。点击“预览”后，在当前页面右侧打开 `Sheet` 抽屉。抽屉打开时设置当前 `selectedSampleId`，并通过 SWR 请求 `GET /api/acquisition/samples/{sample_id}` 拉取权威详情。

抽屉内容使用 tabs：

- `概览`: ROI 大图、质量状态、采集时间、距离、角度、曝光状态、warnings、主 RGB 状态、标定版本和下载入口。
- `D455`: 展示 D455 color 图、depth 图、serial、profile、intrinsics 摘要。
- `H1 光谱`: 读取 `h1/spectrum.json` 中的 `wavelengths` 和 `actual_spectrum`，复用现有 `SpectrumChart`。
- `JSON`: 只读格式化展示 `metadata` 和 `quality`。

切换样本时复用同一个 Sheet，只替换 `selectedSampleId` 并重新拉取详情。样本列表仍按当前刷新机制更新，不因为预览详情加载而阻塞。

## 5. API 设计

新增只读白名单文件端点：

- `GET /samples/{sample_id}/files/d455/color.jpg`
- `GET /samples/{sample_id}/files/d455/depth.png`
- `GET /samples/{sample_id}/files/h1/spectrum.json`

实现原则：

- 先通过 `coordinator.store.get_sample(sample_id)` 确认样本存在。
- 只允许后端代码中显式枚举的相对路径。
- 文件不存在时返回 404。
- 不接受客户端传入任意相对路径。
- 不触发采集设备、不修改 SQLite、不生成新文件。

Next.js 现有 `/api/acquisition/*` 代理继续透传这些端点。

## 6. 前端组件边界

为避免继续扩大 `webui/src/app/acquisition/page.tsx` 的职责，将预览拆成小组件：

- `SamplePreviewSheet`: 抽屉、详情请求、tabs 布局、加载和错误状态。
- `SampleOverview`: ROI 图和关键指标。
- `SampleD455Preview`: D455 color/depth 图片和设备摘要。
- `SampleSpectrumPreview`: H1 光谱解析和 `SpectrumChart` 渲染。
- `JsonBlock`: 只读格式化 JSON。

类型定义放在 `webui/src/lib/acquisition-client.ts`：

- `SampleDetailResponse`
- `SampleSpectrum`

样本行只负责触发 `onPreview(sample.id)`，不解析详情数据。

## 7. 状态与错误处理

- Sheet 加载中显示骨架或简洁等待状态。
- 样本详情 404 时显示“样本不存在或索引已过期”，并保留关闭能力。
- ROI、D455 color、D455 depth 任一图片 404 时，只在对应图片区显示缺失状态。
- H1 光谱缺少 `wavelengths` 或 `actual_spectrum` 时，显示“该样本没有可绘制光谱”，不影响 JSON tab。
- JSON 展示只使用 `/samples/{sample_id}` 已返回的 `metadata` 和 `quality`。
- 所有预览失败都不影响下载按钮和样本列表刷新。

## 8. 测试计划

后端：

- 扩展 acquisition API 测试，采集 mock 样本后验证白名单文件端点返回 `d455/color.jpg`、`d455/depth.png` 和 `h1/spectrum.json`。
- 验证未知文件 key 返回 404。
- 验证不存在的 `sample_id` 返回 404。

前端：

- 运行项目现有 TypeScript、lint 或 build 检查。
- 启动 mock acquisition service 和 WebUI 后，用浏览器打开 `/acquisition`。
- 采集一条 mock 样本，打开样本预览 Sheet，确认 `概览`、`D455`、`H1 光谱`、`JSON` 四个 tab 都有内容或明确降级状态。

## 9. 后续扩展

如果后续要做标注、审核、删除、重采或点云 3D 查看，应复用本次的样本详情组件，再考虑新增 `/acquisition/samples/{id}` 独立详情页。独立详情页不进入本次实施范围。
