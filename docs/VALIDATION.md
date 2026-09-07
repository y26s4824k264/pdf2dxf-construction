# rc22 验证记录 / Validation

版本：`2.0.0rc22`。本地环境为 macOS ARM64 / Python 3.12.13。

## 本轮修复与证据

遍黑体部分扩展汉字的内部短笔画精确匹配到“一”，导致完整整字和子轮廓一起被拒绝。rc22 使用相同的 r2 字库，在整字精确匹配且严格包含所有冲突子轮廓时，检查同一字体、同一连续来源文字行中的两个无歧义汉字锚点。父字与锚点至少包含三个不同标签；每个子轮廓高度必须小于最小锚点的 0.72 倍，低于已有同尺度汉字成行门槛。可独立成行的小字、等大候选、交叉、跨字体、同形异字和不连续来源仍保持歧义。正常字体锁定与成行发布规则继续执行；不使用 OCR 或词义猜测。

报告保存候选父字、子轮廓和锚点的源句柄、字形指纹、边界与尺寸比例，最多 32 条详细证据并单列截断计数。新增 **17 项回归**覆盖描边/填充、不同轮廓顺序、证据不足、同形冲突、跨字体、独立小字行、来源/位置断开、原几何保留、幂等和报告上限。原始 DXF 路径、转换与工程比例算法不变。

## 字库与真实字体样例

继续使用 rc21 的两个 **r2 ZIP，SHA256 完全相同**，没有重建字库。十个字库保留 **245,496 个原始描边记录和 797 个填充备选，总计 246,293 个表示**；跨字体求和并非不同汉字数量。逐条模板核验属于 rc21 的历史构建证据。Jigmo 并集覆盖 Unicode 17 支持区段全部 **102,998 个已分配汉字码点**，这是模板覆盖。

逐个指定对应字体字库的同一批 **84 个真实字体 PDF** 完整恢复从 rc21 的 **68 个提高到 82 个**，另 **2 个部分恢复**，转换失败为 0。十个字库的 **20 个完整 52 字母描边/填充样例均通过**；本轮补齐 14 个遍黑体扩展汉字样例。六个额外 `ABCD8w` 描边/填充 PDF 也用 rc22 重新转换，全部完整恢复，原几何与 rc21 一致。

全部 **1306 个发布字形**均复核原字体 cmap 标签、字库指纹、取整精度、来源句柄和位置。原字体 BoundsPen 对齐 PDF 生成坐标，允许 0.05 mm 的曲线离散边界误差，最大实测 **0.000866324 mm**。84 个样例所有原始 DXF 实体组码与 rc21 相同（仅还原文字恢复的图层/XDATA后比较）；所有先前发布字符保留。保存 DXF 审计错误/修复均为 0。生成 PDF 后移除字体副本，转换运行时只用 DXF 和持久化字库。

另行读取保存报告，绕过新的重叠判断函数，核验 **14 个样例、18 个整字候选、20 个子轮廓**的实际源句柄、边界、严格包含、无歧义标签、字库指纹与尺寸比例。最大子轮廓/锚点高度比约 **0.095731**。候选消歧与字体锁定共同使输出增加 **44 个字符**，不能把候选计数当作新增 TEXT 数量。

剩余两例是 Jigmo 的 `建筑结构平面图` 描边/填充，实际为 `筑结构平面`。`建` 内的 `廴` 接近整字高度，`图` 内的 `囗` 与整字边界相同，当前证据无法排除竞争解释，继续保留几何。本次为 20 pt 定向样例，不代表任意字体、字号、字重或 IVS 异体序列的准确率。逐项预期/实际结果见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

隔离安装包另测两个 r2 资源同时加载的情况：遍黑体扩展 J `U+323B0–U+323B3` 的描边/填充均只恢复前三字，末字存在跨字体候选冲突；从下载目录单独指定对应字体后，两例完整恢复。该检查单独报告，不计入上述 84 个逐字体样例；所有输出 DXF 审计错误/修复均为 0。

## 22 份 BIM 实图与比例

使用已经下载的 r2 常用资源包复测当前 BIM 目录全部 **22 PDF / 22 页**：均产出可读 DXF，转换失败为 0，全部仍为 `degraded`（CLI 退出码 5）。核对 PDF 清单、输入 SHA256、预检页码、输出哈希、实际 TEXT 句柄和重新计算的尺寸验证；所有 DXF 审计错误/修复均为 0。

所有保存 DXF 的**全部组码值与 rc21 一致，仅 HEADER 的两个 GUID 变化**，覆盖块、几何、属性、文字、来源句柄与 INSERT 变换。结果仍为 **238 条 TEXT / 1035 个字符**；外部字库 262 个候选、0 字体锁定、0 外部发布字符。比例为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。转换成功不等于工程验收通过。公开摘要见 [validation.json](validation.json)。本次批次约 316 秒，单次计时不作为性能结论。

历史 rc11 的 4290 份去重 PDF / 12577 页只代表基础转换测试；本轮复测限于 22 份实图、84 个字体样例及六个额外数字样例，未重新验收全部历史语料。rc20 填充修复与 rc21 字库重建证据明确保留为历史数据。

## 安装与分发

本地源码完整回归 **382 项通过**，修改模块的 Ruff 检查通过。发行记录保存隔离安装 wheel 与精确 GitHub CI 提交结果；[CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)覆盖 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码、sdist→wheel、元数据、公开内容、依赖和隔离安装包检查。五条 DeprecationWarning 来自 PyMuPDF SWIG。真实字体与内部 BIM 数据在本地验证，不冒充矩阵平台的全资源测试。

v2 字库加载要求 **rc21+**；本轮短笔画判断需要 **rc22**。已有 r2 资源可以直接使用，无需重新下载或构建。wheel、sdist 和源码 ZIP 排除字体程序、外部字库、私有 PDF/DXF 与内部路径报告；独立资源 ZIP 保留各字体许可。见 [开源字库](OPEN_FONTS.md)。

## English

rc22 resolves short internal Han contours competing with an exact complete glyph using strict containment, the same catalog, a continuous source row, two uncontested anchors and at least three distinct Han labels including the parent. Each child must be below 0.72 times the smallest anchor height, the existing same-scale Han row threshold. Independent small-text rows, equal-size/crossing alternatives, conflicting labels, cross-font conflicts and discontinuous sources remain ambiguous. Font locks and publication gates still apply. No OCR or semantic guessing is used; geometry and engineering-scale algorithms are unchanged. Seventeen new tests cover evidence boundaries, stroke/fill ordering, preserved geometry, idempotence and bounded reports.

The exact same **r2 resource ZIPs** are reused, with unchanged SHA256 digests. They retain **245,496 raw records plus 797 fill alternates, totaling 246,293 representations** across ten faces. Record-by-record rebuild verification is historical rc21 evidence. Jigmo covers **102,998 assigned Unicode 17 Han codepoints**; template coverage is distinct from recognition.

The same **84 real-font probes**, each using its matching font catalog, improve from **68 to 82 complete**, with **2 partial** and zero conversion failures. All twenty 52-letter stroke/fill cases pass. Six additional ABCD8w PDFs are rerun with rc22 and pass, with geometry unchanged from rc21. All **1306 published glyphs** match source cmap labels/bounds, catalog fingerprints and source handles; maximum bounds error is **0.000866324 mm** against 0.05 mm. Original DXF entity tags match rc21 in all 84 cases; all previous published characters remain and audits have zero errors/fixes.

A separate audit reads persisted fragment evidence without calling the new overlap resolver: **14 cases, 18 parent candidates and 20 children** match actual DXF handles/bounds, exact catalog fingerprints, containment and anchor/scale evidence. Maximum child/anchor height ratio is **0.095731**. Candidate resolution plus font locking yields **44 additional published characters**. The two remaining Jigmo common-Han cases output `筑结构平面` from `建筑结构平面图`: full-size 廴/囗 competitors remain unresolved. These 20 pt probes do not establish universal font, size, weight or IVS accuracy.

All **22 BIM PDFs** produce saved DXFs and remain degraded. Every saved group-code value matches rc21 apart from two HEADER GUIDs. Fresh preflight, hashes, TEXT handles and dimension validation are checked. Results remain **238 TEXT / 1035 characters**, **262 font candidates / 0 font locks / 0 external published characters**, scale states **9 calibrated / 6 declared approximate / 6 paper / 1 unknown**, and **13/22 geometry-valid**. Nine calibrated drawings still fail the dimension-error gate. The batch took about 316 seconds; no performance improvement is claimed. The historical corpus was not rerun.

Local source tests pass **382 tests**; modified modules pass Ruff. Release notes identify isolated-wheel results and the exact four-job CI run. Schema v2 requires rc21+; this fragment resolver requires rc22. Existing r2 downloads need no rebuilding. Main distributions exclude external fonts/catalogs and private drawings, and optional font ZIPs retain their original licenses.

Separate installed-wheel checks load both downloaded r2 bundles together: Plangothic `U+323B0–U+323B3` stroke/fill cases recover only the first three characters due to cross-font contour-label conflicts. Selecting the matching face from the same downloads restores both cases completely. These four selection checks are separate from the 84 per-font probes; saved DXF audits have zero errors/fixes. Catalog selection remains a documented recognition boundary.
