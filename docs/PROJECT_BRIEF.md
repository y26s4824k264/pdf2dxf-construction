# 项目说明与维护计划 / Project brief and maintenance plan

## 简体中文

### 解决的问题

施工图常以 PDF 交付，下游 CAD/BIM 工具需要可读取、持久化且可追溯的 DXF。PDF 文字可能已变成轮廓，纸面坐标也不等于工程尺寸。单纯成功导出，无法证明文字恢复正确或工程比例可信。

PDF2DXF Construction 提供独立 Python 包与 CLI，负责 PDF→DXF、经几何证据确认的轮廓转 TEXT，以及尺寸证据支持的比例换算。图框拆分、构件建模和工程量计算由下游共享 DXF 算法处理。本包保存未知轮廓和比例限制，供下游决定是否采用。

### 对开源生态的价值

- 以真实 DXF 和 JSON 证据作为可复用接口，便于 CAD/BIM 工具接入。
- 公开中文、英文轮廓的拓扑/几何匹配、字体锁定与连续行校验代码和测试。
- 区分工程比例、纸面输出和待复核状态，避免静默猜测尺寸。
- 提供中英 README、源码包、wheel 和来源固定的独立开源字库，便于复现与贡献。

当前 rc34 的字形工作补齐此前 15 个短行缺字样例：同时加载十个字库，84/84 短行及 16/16 长行完整；100 个原始字体 PDF 实际重新转换并逐字核对，共 3,630 字。源码和隔离安装 wheel 各通过 732 项测试，29 条旧 lint 已清零并加入 CI。

r3 字库增加原字体 em 外框和字距证据，保留 r2 的全部轮廓、拓扑、码点与匹配索引。它通过字身尺寸、基线、字距及来源顺序来确认部分整字内部的竞争轮廓；不使用 OCR 或语义猜字。Jigmo 模板并集仍覆盖 Unicode 17 支持区段的 102,998 个已分配汉字码点。模板覆盖、样例完整率和任意字体准确率分别报告。

### 可核对的证据

| 证据 | 范围与限制 | 入口 |
| --- | --- | --- |
| 自动测试和 lint | 代码、几何、文字、比例、资源限制和发布包；远端结果以对应提交为准 | [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)、[tests](../tests) |
| 原始字体 PDF 复测 | 100 个已知字体样例，逐字核对实际 TEXT 和坐标；不是任意字体准确率基准 | [字库验证](OPEN_FONT_VALIDATION.json) |
| 历史图纸部分复测 | 4,251 份 PDF /4,253 页；按用户要求停止全量，8,324 页未测；待复核不计作工程通过 | [验证记录](VALIDATION.md) |
| 来源和维护记录 | 固定字体来源、保留许可，公开可复现修改和回归结果 | [来源锁](OPEN_FONTS.lock.json)、[CHANGELOG](../CHANGELOG.md)、[来源声明](../SOURCE_ORIGIN.json) |

项目采用 AGPL-3.0-only，第三方依赖及字体保留自身许可。客户 PDF/DXF、私有系统字体和路径报告不进入公开仓库。维护者的来源授权声明见 SOURCE_ORIGIN.json。

### OpenAI 开源项目申请说明

本项目可用公开源码、缺陷修复、自动测试、字体来源锁定、真实转换复核和中英维护文档说明工作内容。Codex 辅助缺陷定位、实现和证据核验；维护者负责最终代码与发布决定。

测试页数、模板覆盖和 AI 辅助工作量不等于社区采用规模。没有经核实的下载量、用户数、生态影响力或资助结果时，不填写推测数字。这些资料可作为申请项目介绍和维护记录，不代表已经符合福利资格、获得 OpenAI 认可或通过审批。

### 后续维护

优先扩充有真实字体与字符真值的样例，验证不同字号、变体和绘制方式；保持整字歧义、未知比例及扫描图的明确边界。新增算法须保留原图元并补充可复现的正反例。IVS/IVD、任意未知字体和所有工程图纸的 100% 识别仍不作承诺。

## English

### Problem and reusable interface

Construction PDFs may contain outlined text and paper-space coordinates. Downstream CAD/BIM tools need readable, persisted and traceable DXF. Successful export alone does not establish correct text or engineering scale.

PDF2DXF Construction is a standalone Python package and CLI for PDF→DXF, evidence-backed outline-to-TEXT recovery and scale conversion supported by dimension geometry. Frame splitting, component modeling and quantities belong to downstream shared DXF algorithms. Unknown outlines and scale limitations remain explicit.

### Current maintenance evidence

rc34 resolves the 15 previously incomplete short cases. With all ten catalogs loaded, 84/84 short and 16/16 long rows complete. All 100 original font PDFs are reconverted and checked against original cmap labels, coordinates and saved TEXT, totaling 3,630 characters. Both source and isolated installed-wheel suites pass 732 tests; all 29 legacy lint findings are fixed and lint becomes a CI gate.

The r3 resources add original-font em bounds and advance while preserving all r2 geometry, topology, mappings and lookup keys. Uniform scale, baseline, advance and provenance provide an additional whole-glyph check without OCR or semantic guessing. Jigmo's union retains coverage of 102,998 assigned Han codepoints in supported Unicode 17 ranges. Template coverage, fixture completeness and universal accuracy are separate measures.

Review the [font evidence](OPEN_FONT_VALIDATION.json), [validation record](VALIDATION.md), [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml), [source lock](OPEN_FONTS.lock.json) and [changelog](../CHANGELOG.md). The code uses AGPL-3.0-only; dependencies and font resources retain their own licenses. Private drawings, system fonts and path-bearing reports are excluded.

### OpenAI open-source application context

Public code, reproducible fixes, automated tests, pinned font provenance, actual conversion audits and bilingual maintenance documents can describe the project. Codex assists diagnosis, implementation and verification; the maintainer owns final code and release decisions.

Test counts, template coverage and AI-assisted work are not adoption metrics. Unverified download counts, user numbers, ecosystem impact or funding outcomes must not be presented as facts. These documents support a project introduction and maintenance record; they do not establish eligibility, endorsement or approval for OpenAI benefits.

### Maintenance priorities

Expand fixtures with known fonts and character truth across sizes, variants and rendering methods. Preserve original entities and add positive and negative cases for new algorithms. Keep unknown text, unconfirmed scale and scanned drawings explicit. IVS/IVD support, arbitrary unknown fonts and 100% recognition of all engineering drawings remain future work rather than release claims.
