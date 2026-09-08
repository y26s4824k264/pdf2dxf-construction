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

rc18 还提供 10 个独立开源字库及固定来源的重建工具；Jigmo 模板并集覆盖 Unicode 17 支持区段全部 102,998 个已分配汉字码点。逐字体指定对应字库的真实字体有 84 个公开结果的样例，rc26 下其中 82 个完整恢复、2 个部分恢复或未确认；覆盖与识别结果分开报告，见 [字库说明](OPEN_FONTS.md)。

rc22 增加同字体连续文字行的短笔画尺寸证据判断，使用相同 r2 字库，保留未确认的整字大小竞争轮廓。此前 rc21 额外核验全部旧描边模板保持一致，并为严格退化的轮廓增加填充表示；数字 `8` 与字母 `w` 的六个实字体描边/填充回归均通过。

项目采用 AGPL-3.0-only，第三方依赖与字体保留自身许可。维护者的来源授权声明见 [SOURCE_ORIGIN.json](../SOURCE_ORIGIN.json)。

### 可以核对的证据

| 证据 | 范围与限制 | 入口 |
| --- | --- | --- |
| 自动回归 | 图元、轮廓文本、字库、尺寸比例、R12、资源取消和发布包检查；执行结果以对应 CI 提交为准 | [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)、[tests](../tests) |
| rc28 实图回归 | 22 PDF / 22 页均产出 DXF；238 条恢复 TEXT、1035 个字符；22 份仍存在质量降级 | [验证记录](VALIDATION.md)、[摘要](validation.json) |
| 保存后复核 | 历史 rc20 修复填充经独立绕数及已保存 HATCH 核对；rc28 检查输出 SHA256、实际 TEXT 句柄内容、尺寸和源预检证据；不等于所有图元视觉保真 | [验证记录](VALIDATION.md) |
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

The project exposes geometric Chinese/English glyph matching, repeated-template consistency and font-locking rules for inspection and regression testing. It distinguishes paper, declared, calibrated and user-confirmed scales. Source/wheel distributions and bilingual documentation aim to make this conversion boundary reusable by other CAD/BIM tools. rc18 adds ten separately licensed open-font catalogs and pinned, reproducible builds. Jigmo covers all 102,998 assigned Han codepoints in supported Unicode 17 ranges; 84 real-font probes using their respective catalogs disclose 82 complete and 2 partial/unconfirmed cases with rc26. Template coverage is reported separately from recognition outcomes. See [open-font resources](OPEN_FONTS.md). rc22 adds bounded same-font row and scale evidence for undersized Han fragments, reusing r2 while preserving unresolved full-size alternatives. rc21 verifies preservation of every legacy raw template and adds exact filled representations; six additional real-font 8/w probes pass. The code license is AGPL-3.0-only; third-party licenses still apply.

### Evidence and present maturity

The public [test suite](../tests) covers geometry, outlined text, catalogs, dimensions, R12, resource cancellation and packaging. [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) identifies the exact tested commits and platforms.

The rc28 real-drawing run covers 22 PDFs / 22 pages. All produced DXFs; 238 TEXT entities containing 1035 characters were recovered. All 22 retained degraded quality status. Historical rc20 fill repairs were checked against independent source winding and persisted HATCH regions, including engineering scaling. rc28 compares all saved DXF group pairs to rc27, excluding only two HEADER GUIDs. Saved-output hashes, actual text handles, dimension validation and preflight evidence were checked. See [validation](VALIDATION.md) and its [JSON summary](validation.json). These results are not a claim of universal font coverage or complete visual/engineering acceptance.

This is a newly public project without established public-adoption evidence. Internal test counts are not downloads, users or industry adoption. Earlier maintenance work is summarized in [CHANGELOG](../CHANGELOG.md); the standalone GitHub history begins with the public snapshot rather than invented backdated commits.

### Maintenance and use of Codex

The maintainer plans to use Codex to reproduce reported bugs, create distributable regression fixtures, review patches, diagnose CI failures, assess dependency changes and keep release notes and bilingual documentation aligned. Any API-backed issue triage or pull-request review would be a future maintainer workflow, not an already deployed service.

Codex has assisted the current source review, fixes, testing and release preparation. Conversion itself remains local and algorithmic: no API, OCR or language model is needed to invent or recover drawing labels. Geometry and quality-gate changes require maintainer review. Private customer drawings are excluded from the public corpus and are not sent to external APIs by default.

Near-term priorities are reproducible cross-platform releases, clearly licensed synthetic/public fixtures, and defects that could corrupt text or scale evidence. Unknown fonts, scanned inputs and mixed-scale sheets retain explicit limitations. Requested support would fund real maintenance work; it would not be evidence of ecosystem adoption or endorsement by a funding organization.

rc27 的维护工作修复已匹配长文字在 96 字边界整行丢失的问题，新增 26 项回归。16 个真实字体长行 PDF 增加 2030 个此前未输出字符，每个输出字形的原字体位置、轮廓句柄和文本定位均独立核验；既有短文本和 BIM 比例结果保持不变。见[验证记录](VALIDATION.md)。这说明 Codex 用于复现缺陷、编写回归、维护中英文档和核对发布包的实际工作，不代表项目采用量或资助资格。

rc27 fixes matched long rows disappearing at the 96-glyph output boundary, with 26 new regressions. Sixteen real-font long PDFs gain 2030 previously unpublished characters; each published glyph, source handle and TEXT position is independently checked. Existing short-text and BIM scale results remain unchanged. See [validation](VALIDATION.md). This is concrete Codex-assisted reproduction, regression, documentation and release work, not evidence of adoption or funding eligibility.

rc28 将字体漏识别追溯到 PDF 数值取整，新增 23 项回归并逐项审计曲线误差；16 个既有长行 PDF 全部恢复，r2 字库不变。修复证据同时披露四处采样几何的微小变化及仍未通过的 BIM 工程门槛。

rc28 traces glyph misses to PDF numeric sampling ties, adds 23 regressions and audits source-curve error. All 16 existing long PDFs complete with unchanged r2 catalogs. The evidence discloses four small sampling changes and remaining BIM engineering gates.

rc29 复用已有 Shapely/GEOS 与 FontTools，加入闭合部首消歧和 36 项回归，公开中英算法比较、许可来源与失败边界。84 字体 PDF 增加两字，22 BIM 图纸工程质量门槛不变；不将代码测试通过等同于任意字体识别或 OpenAI 福利资格。

rc29 reuses existing open-source geometry tools, adds 36 regressions and publishes bilingual algorithm/license/limitation evidence. Two glyphs are restored across 84 matching-face PDFs; engineering gates remain unchanged. Passing tests does not establish universal font accuracy or OpenAI program eligibility.

## rc30 可复核进展 / Reviewable progress

新增 38 项回归，源码 566 项通过。补齐内部标点复核、已有结果的证据连接和长行局部搜索：十字库组合多恢复 8 字，新增 12 个长行 PDF 全部完整。逐字位置、来源图元、拒绝原因和原几何对照随中英说明公开；BIM 工程比例门槛保持不变。这些是可审查的技术贡献，不代表 OpenAI 项目福利已获批准。详见 [本轮验证](OUTLINE_ROW_VALIDATION.json)。

Thirty-eight regressions bring source tests to 566. Punctuation rechecks, verified-stage connections and bounded row search restore eight combined-catalog characters and complete twelve new long PDFs. Published evidence covers glyph positions, provenance, rejection reasons and unchanged geometry. Engineering scale gates remain unchanged; these reviewable contributions do not establish OpenAI program approval.

## rc31 可复核进展 / Reviewable progress

新增 65 项回归，源码 631 项通过。半包围与有界证据链使对应字体 PDF 样例达到 84/84 完整恢复，公开声明 100% 只适用于该组样例；组合字库为 69/84，剩余原因及 BIM 工程比例限制一并披露。新增 12 个长行 PDF 的 1740 字均与原字体位置、摘要和来源图元独立对照。详见 [验证证据](HALF_ENCLOSURE_VALIDATION.json)。这些是可审查的维护成果，不代表 OpenAI 福利资格或批准。

Sixty-five regressions bring source tests to 631. Half-enclosures and bounded proof chains complete 84/84 matching-face probes, with an explicit limit on the 100% claim. Combined catalogs remain 69/84 and engineering-scale limits are disclosed. All 1740 characters in twelve new long PDFs pass original-font position, digest and provenance checks. These reviewable maintenance results do not establish OpenAI eligibility or approval.

## rc32 可复核维护 / Reviewable maintenance

本轮复现并修复两处长行消歧上限，新增 60 项回归。十字库 16 个 PDF 的 2320 字逐字核验，补回 94 字；94 份本机/历史 PDF 的代表页检查及 12 页隔离版本对照记录了实际限制。原图纸不进入公开包。中英文文档、安装包、跨平台 CI 与精确提交一起核验；这些维护证据不代表 OpenAI 福利资格或批准。见[验证记录](VALIDATION.md)。

This release reproduces and fixes two long-row ambiguity limits, adds 60 regressions and independently audits all 2320 characters in 16 all-ten-catalog PDFs, restoring 94. Representative inspection of 94 historical/local PDFs and twelve isolated-version comparisons disclose real limits. Private drawings are excluded from public artifacts. Bilingual documentation, packages, cross-platform CI and exact commits are verified; this maintenance evidence does not establish OpenAI eligibility or approval.

## rc33 字库索引维护 / Catalog index maintenance

对 Unicode 索引构建进行有边界的性能优化，并核对全部模板字段和原始几何；696 项测试、100 个 DXF 和 4 个 PDF 转换覆盖本次改动。该轮改善加载开销，不增加识别覆盖率。详见[验证记录](VALIDATION.md)。这些公开维护记录可用于项目说明，不代表 OpenAI 福利资格或审批结论。

This bounded Unicode-index optimization compares all catalog fields and original geometry. Validation covers 696 tests, 100 DXF recognitions and four PDF conversions. It improves loading overhead without increasing recognition coverage. See [validation](VALIDATION.md). These maintenance records support the project description and do not establish OpenAI benefit eligibility or approval.
