# rc30 验证记录 / Validation

版本 `2.0.0rc30`；本地 macOS ARM64 / Python 3.12.13。源码 **566 项通过**，新增 38 项回归；五条已有弃用警告来自 PyMuPDF SWIG。安装包与精确提交的跨平台执行结果见发行记录。

## 修复与证据

三个缺口已修复：唯一精确汉字被其他字体的内部小标点阻断时，允许通过三个独立同行汉字锚点复核；先前通过来源行复核的字形可以连接后续部首拓扑证据，但不能成为独立锚点；闭合部首确认改为最多检查 96 个相邻字形的局部搜索，不再因整行超过 96 字直接拒绝。新部首候选不能互相连接或证明彼此，未知间隙和来源、图层、行位置断开继续阻止确认。

仍需同字体精确标签、部首别名、严格封闭拓扑和三个不同的原始无冲突锚点；字母、数字、其他汉字、整字别名及过大或跨界竞争轮廓继续拒绝。报告增加成功证据的局部路径、已确认连接字，以及部首候选的拒绝原因、来源句柄和截断计数；详细记录最多各 32 条，仅覆盖该阶段实际评估的候选，不是全部未知字清单。复用既有 Shapely/GEOS、FontTools，无新增依赖或 OCR。

初始 23 个阶段/长行用例在 rc29 上为 13 失败、10 通过：10 个失败复现漏字，另 3 个 96 字用例文字已正确，仅缺新增路径证据。后续 10 个内部标点用例在修复前为 4 失败、6 通过。完整 38 项覆盖描边/填充、字库顺序、原几何保留、幂等、相互举证拒绝、字体/来源/图层边界、96/97/193 字、局部搜索预算和诊断截断。

| 实测范围 | rc29 基线 | rc30 |
| --- | --- | --- |
| 对应字体字库，84 个原 PDF 重转 | 82 完整，1308 字 | **82 完整，1308 字** |
| 同时加载十字库，84 个已保存 DXF 重识别 | 63 完整，1245 字 | **67 完整，1253 字** |
| 原有四字体 97/193 字长行，16 个 PDF 重转 | 16 完整，2320 字 | **16 完整，2320 字** |
| 新增 Jigmo 97/193 字，图在首/中/末，描边/填充，12 个 PDF | 0 完整，1728 字 | **12 完整，1740 字** |
| BIM 文件夹全部 22 个 PDF / 22 页重转 | 22 degraded，0 failed | **22 degraded，0 failed** |

十字库组合的五个案例增加 8 字：思源黑体、宋体描边各补“面图”，Jigmo 描边补“面图”，遍黑体兼容区两个样例各补一个“𠄢”。Jigmo 的“面”由内部标点复核确认后连接“图”的拓扑证据。其余 79 个案例保持全部既有识别字段与实体库组码一致，仅排除新增诊断字段和经验证的写入时间。所有 84 个案例原始图元组码均不变；20 个大小写 52 字母样例全部完整。

五个改变的案例共 28 个输出字形均对照原字体 cmap、独立 BoundsPen、生成位置、模板摘要及来源句柄，最大边界误差 **0.000094 mm 以内**。84 个对应字体 PDF 使用相同输入 SHA256，独立核对全部 1308 个输出字形，最大边界误差 **0.000867 mm 以内**。16 个原有长行 PDF 核对全部 2320 字、插入点和 FIT 端点，最大边界误差 **0.000431 mm 以内**。原始图元均与 rc29 相同。

新增 12 个 Jigmo 长行 PDF 以隔离安装的 rc29 wheel 为基线，使用完全相同的输入字节；所有案例旧版各漏一个“图”。rc30 的全部 1740 字对照原字体 cmap/BoundsPen、位置、模板摘要、来源句柄及保存 TEXT 对齐点，最大误差 **0.000087 mm 以内**，原始几何不变。所有边界审计门槛为 0.05 mm。测试文本由“筑结构平面”和一个“图”构成，未包含仍有歧义的“建”，不能将其视为任意汉字测试。字体文件仅用于生成/独立审计，识别运行时不读取。

22 个 BIM PDF 保持 **238 TEXT / 1035 字**，全部保存 DXF 组码除两个 HEADER GUID 外与 rc29 一致。输入哈希、TEXT 句柄与保存后验证一致，DXF audit 无错误或修复。比例为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 13/22，九张已标定图仍未通过 0.2% 尺寸误差门槛。没有重跑历史 rc11 的 4290-PDF 语料；未知字体、Jigmo“建”和工程质量问题仍有边界。

证据：[本轮逐项验证](OUTLINE_ROW_VALIDATION.json)、[BIM](validation.json)、[开源算法](OPEN_OUTLINE_ALGORITHMS.md)。历史 [rc29 拓扑](CONTOUR_TOPOLOGY_VALIDATION.json)、[rc28 曲线](CURVE_SAMPLING_VALIDATION.json)、[rc27 长行](LONG_TEXT_VALIDATION.json)、[rc26 字库](OPEN_FONT_VALIDATION.json) 保留原版本标识。r2 字库无需重下。

## English

rc30 repairs three evidence-flow gaps: uniquely matched Han glyphs blocked only by small internal punctuation can pass a three-anchor row recheck; earlier verified glyphs may connect a later enclosure proof without becoming independent anchors; and a bounded local search visits at most 96 adjacent glyphs instead of rejecting an entire long row. New enclosure proposals never connect each other. Exact labels, same-font aliases, closed topology, three distinct original uncontested anchors and all conflict/source boundaries remain required.

All **566 source tests pass**, including 38 new regressions. The initial 23 cases produced 13 failures on rc29: ten missing-text failures and three already-correct 96-glyph cases missing new path evidence. Ten later punctuation cases produced four missing-text failures before that fix. Coverage includes stroke/fill DXFs, catalog order, source geometry, idempotence, independent evidence, broken boundaries, 96/97/193-glyph rows, local search limits and bounded diagnostics. Rejection details cover only evaluated radical proposals, not every unknown glyph. No runtime dependency or OCR is added.

The 84 all-ten-catalog saved DXFs improve **63→67 complete, 1245→1253 characters**. Five cases restore eight characters: 面图 in Source Han Sans/Serif and Jigmo stroke cases, plus 𠄢 in two Plangothic compatibility probes. All 20 alphabet cases remain complete. Original entity tags match rc29 in all 84; the other 79 cases retain existing report fields and entitydb tags except intentional diagnostic additions and validated writer time. All 28 published glyphs in the changed cases pass independent original-font bounds, digest and handle checks, with error below **0.000094 mm**.

All 84 matching-face PDFs retain **82 complete, 1308 characters**; all 16 existing long PDFs retain **16 complete, 2320 characters**. Identical input hashes, original geometry, glyph provenance and positions are independently verified. Maximum bounds errors are below **0.000867 mm** and **0.000431 mm**.

Twelve new Jigmo PDFs place 图 at the start/middle/end of 97/193-character stroke/fill rows. The isolated installed rc29 baseline misses one 图 in every case; rc30 completes all twelve (**1728→1740 characters**). All 1740 glyphs and TEXT alignment endpoints pass an original-font audit, below **0.000087 mm**, with unchanged source geometry. The fixture repeats 筑结构平面 and one 图, excluding unresolved 建. Audit tolerance is 0.05 mm; source fonts are not accessed during recognition.

All 22 BIM PDFs are reconverted with **238 TEXT /1035 characters**, zero conversion/audit failures and unchanged group pairs except two HEADER GUIDs. All remain **degraded**: 9 calibrated, 6 declared approximate, 6 paper, 1 unknown; geometry valid 13/22. Nine calibrated drawings still exceed the 0.2% dimension gate. Historical 4290-PDF validation is not rerun. These bounded results do not establish arbitrary-font recognition or complete engineering acceptance. Reuse unchanged r2 resources.
