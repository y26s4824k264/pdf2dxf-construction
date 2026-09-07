# 项目说明与维护计划 / Project brief and maintenance plan

[简体中文](#简体中文) | [English](#english)

## 简体中文

### 解决的问题

施工图常以 PDF 交付，后续 CAD/BIM 工具需要可持久化、可追溯的 DXF。PDF 中的文字可能已经变成几何轮廓，纸面坐标也不等于真实工程尺寸。若只追求“成功导出”，错误文字、未经确认的比例和兼容格式损失容易进入后续处理。

PDF2DXF Construction 提供一个可独立安装的 Python 包和 CLI，负责 PDF→DXF、经过验证的轮廓文字转 TEXT，以及基于尺寸几何的比例换算和质量报告。它把无法确认的轮廓与比例保留为明确限制，供下游 CAD/BIM 流程决定是否采用。图框拆分、构件建模和工程量计算由下游共享 DXF 算法负责。

### 对开源生态的价值

- 提供 CAD/BIM 输入转换边界，允许其他工具直接消费真实 DXF 与 JSON 证据。
- 将中英文字形几何匹配、重复一致性和字体锁定规则以源码和回归测试公开，便于复现和改进。
- 把工程比例、纸面比例和人工确认分开，报告独立尺寸复核结果，减少静默猜测。
- 使用开源 Python 工具链，发布源码包与 wheel，提供中英说明，降低复现和贡献的准备成本。

rc18 还提供 10 个独立开源字库及固定来源的重建工具；Jigmo 模板并集覆盖 Unicode 17 支持区段全部 102,998 个已分配汉字码点。真实字体有 84 个公开结果的样例，其中 57 个完整恢复、27 个部分恢复或未确认；覆盖与识别结果分开报告，见 [字库说明](OPEN_FONTS.md)。

项目采用 AGPL-3.0-only，第三方依赖与字体保留自身许可。维护者的来源授权声明见 [SOURCE_ORIGIN.json](../SOURCE_ORIGIN.json)。

### 可以核对的证据

| 证据 | 范围与限制 | 入口 |
| --- | --- | --- |
| 自动回归 | 图元、轮廓文本、字库、尺寸比例、R12、资源取消和发布包检查；执行结果以对应 CI 提交为准 | [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)、[tests](../tests) |
| rc18 实图回归 | 22 PDF / 22 页均产出 DXF；238 条恢复 TEXT、1035 个字符；22 份仍存在质量降级 | [验证记录](VALIDATION.md)、[摘要](validation.json) |
| 保存后复核 | 检查输出 SHA256、实际 TEXT 句柄内容、尺寸和源预检证据；不等于所有图元视觉保真 | [验证记录](VALIDATION.md) |
| 维护记录 | 修复和整理历史写入 CHANGELOG；GitHub 从独立快照首次公开，不伪造历史提交 | [CHANGELOG](../CHANGELOG.md)、[来源](../SOURCE_ORIGIN.json) |

本项目刚开始公开发布，尚无成熟的公开采用或社区规模证据。历史内部测试数量不是下载量、用户数或行业采用量；不以其替代开源生态影响力数据。

### 维护重点与 Codex 用途

以下是维护计划，不表示自动化已上线或任务已经完成：

1. 对公开 issue 和真实缺陷构建脱敏、可分发的最小回归样本，优先修复文本误认、比例证据冲突和平台安装失败。
2. 使用 Codex 辅助分析报错、编写回归测试、审查修改和解释 CI 失败；由维护者审核涉及几何或质量门槛的变更。
3. 用 Codex/API 辅助依赖升级审查、发行说明、中英文档一致性和打包检查。API 不是转换运行时的必要依赖，也不用来猜补图纸文字或尺寸。
4. 持续扩大有明确授权的程序生成与公开测试样本；把未知字体、扫描 PDF 和多比例页面作为明确能力边界，不以近邻猜字提高“成功率”。
5. 保持 Linux/macOS/Windows 的测试矩阵和可下载发行包，逐项记录运行验证与未验证的差异。

现有维护过程已使用 Codex 协助代码检查、修复、测试与发布准备；仓库尚未配置基于 API 的自动 PR 审查或自动合并。支持资源若获批准，将用于上述维护工作，不用于创建未经证实的识别结果。敏感客户图纸不会作为公开 issue 附件或默认发送到外部 API。

## English

### Problem and ecosystem value

Construction drawings often arrive as PDFs, while downstream CAD/BIM tools need persisted DXF entities and traceable coordinates. Outlined text is geometry, and paper coordinates do not establish engineering dimensions. Treating every successful export as accepted engineering data can propagate text errors, unsupported scale assumptions and compatibility losses.

PDF2DXF Construction is an independently installable Python package and CLI for PDF-to-DXF conversion, verified outline-to-TEXT recovery and evidence-based scale reports. Its output contract is a real DXF plus JSON evidence. Unknown outlines and unconfirmed scales remain explicit. Frame splitting, component modeling and quantity takeoff stay in downstream DXF algorithms.

The project exposes geometric Chinese/English glyph matching, repeated-template consistency and font-locking rules for inspection and regression testing. It distinguishes paper, declared, calibrated and user-confirmed scales. Source/wheel distributions and bilingual documentation aim to make this conversion boundary reusable by other CAD/BIM tools. rc18 adds ten separately licensed open-font catalogs and pinned, reproducible builds. Jigmo covers all 102,998 assigned Han codepoints in supported Unicode 17 ranges; 84 real-font probes disclose 57 complete and 27 partial/unconfirmed cases. Template coverage is reported separately from recognition outcomes. See [open-font resources](OPEN_FONTS.md). The code license is AGPL-3.0-only; third-party licenses still apply.

### Evidence and present maturity

The public [test suite](../tests) covers geometry, outlined text, catalogs, dimensions, R12, resource cancellation and packaging. [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) identifies the exact tested commits and platforms.

The rc18 real-drawing run covers 22 PDFs / 22 pages. All produced DXFs; 238 TEXT entities containing 1035 characters were recovered. All 22 retained degraded quality status. Saved-output hashes, actual text handles, dimension validation and preflight evidence were checked. See [validation](VALIDATION.md) and its [JSON summary](validation.json). These results are not a claim of universal font coverage or complete visual/engineering acceptance.

This is a newly public project without established public-adoption evidence. Internal test counts are not downloads, users or industry adoption. Earlier maintenance work is summarized in [CHANGELOG](../CHANGELOG.md); the standalone GitHub history begins with the public snapshot rather than invented backdated commits.

### Maintenance and use of Codex

The maintainer plans to use Codex to reproduce reported bugs, create distributable regression fixtures, review patches, diagnose CI failures, assess dependency changes and keep release notes and bilingual documentation aligned. Any API-backed issue triage or pull-request review would be a future maintainer workflow, not an already deployed service.

Codex has assisted the current source review, fixes, testing and release preparation. Conversion itself remains local and algorithmic: no API, OCR or language model is needed to invent or recover drawing labels. Geometry and quality-gate changes require maintainer review. Private customer drawings are excluded from the public corpus and are not sent to external APIs by default.

Near-term priorities are reproducible cross-platform releases, clearly licensed synthetic/public fixtures, and defects that could corrupt text or scale evidence. Unknown fonts, scanned inputs and mixed-scale sheets retain explicit limitations. Requested support would fund real maintenance work; it would not be evidence of ecosystem adoption or endorsement by a funding organization.
