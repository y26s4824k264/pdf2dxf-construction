# rc21 验证记录 / Validation

版本：`2.0.0rc21`。本地环境为 macOS ARM64 / Python 3.12.13。

## 本轮修复

Jigmo 的 `w` 包含约 0.00689 mm 的零面积闭合线段，旧字库与描边候选/填充输出的拓扑不一致。直接从字库删除这些线段又会破坏数字 `8` 的描边匹配。rc21 的 v2 字库保留原始描边模板，并追加有效填充模板；两种表示都要求精确的掩码、拓扑与宽高比。原始 DXF 路径、转换和工程比例算法没有变化。

同一字符的两套精确表示发生严格包含时，仅在额外路径全部闭合且共线时保留完整原始描边匹配。不同标签和其他重叠继续保留歧义，字体锁定和连续成行检查照常执行。新增 **28 项回归**覆盖退化/非退化路径、零面积但非共线的自交轮廓、极小有效面、仅退化描边、原几何保留、幂等、同形冲突、描边顺序、旧字库兼容、新资源缓存及损坏元数据。

## 全量字库与真实字体样例

从相同已锁定源字体重新构建 10 个字库。全部 **245,496 个旧描边模板记录逐条一致**，新增 **797 个填充表示**，总计 **246,293 个模板表示**。唯一码点数与表示总数分开统计；这些数量跨字体求和，不是不同汉字数量。每个新填充表示的 17 组采样均用独立的闭合多边形凸包零面积判断核对。无法生成稳定填充备选的字符保留原描边并记录原因。

同一批 **84 个真实字体 PDF** 完整恢复从 rc20 的 **62 个提高到 68 个**，另 **16 个部分恢复或未确认**，转换失败为 0。十个字库的 **20 个完整 52 字母描边/填充样例均通过**；本轮补齐 Jigmo 三个字体两种输出中的 `w`。加测六个 `ABCD8w` 描边/填充 PDF 均完整恢复，并与旧字库输出对照。所有先前已发布字符均保留。

逐字复核全部 **1262 个已发布字形**的原字体 cmap 标签、字库摘要、取整精度、来源句柄和位置。使用原字体 BoundsPen 对齐 PDF 生成坐标，允许 0.05 mm 的曲线离散边界误差，最大实测 **0.000866324 mm**。84 个样例的所有原始 DXF 实体组码与 rc20 相同（仅还原文字恢复的图层/XDATA后比较），额外六个数字样例同样保留原几何。所有保存文件的 DXF 审计错误/修复均为 0。字体副本在生成 PDF 后移除，转换运行时只使用 DXF 和持久化字库。

剩余 16 个汉字样例涉及内部轮廓与“一/囗/廴”等字形竞争，继续保留几何，不按上下文补猜。本次为 20 pt 定向样例，不代表任意字体、字号、字重或 IVS 异体序列的准确率。Jigmo 并集仍覆盖 Unicode 17 支持区段全部 **102,998 个已分配汉字码点**，这是模板覆盖。逐项数据见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

## 22 份 BIM 实图与比例

新版常用资源包下，**22 PDF / 22 页均产出 DXF**，转换失败为 0，全部仍为 `degraded`（CLI 退出码 5）。核对当前 BIM 文件夹的 PDF 清单、输入 SHA256、预检页码、输出哈希、实际 TEXT 句柄和重新计算的尺寸验证；所有 DXF 审计错误/修复均为 0。

22 个保存 DXF 的**全部组码值与 rc20 一致，仅 HEADER 的两个 GUID 允许变化**，覆盖块内容、几何坐标、属性、文字、来源引用和 INSERT 变换。恢复结果仍为 **238 条 TEXT / 1035 个字符**；外部字库仍未获得字体锁定，未增加外部字符。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。没有把转换成功当作工程验收通过。公开摘要见 [validation.json](validation.json)。本次批次耗时约 308 秒，未将单次计时当作性能结论。

历史 rc11 的 4290 份去重 PDF / 12577 页只代表基础转换测试。本轮复测限于上述 22 份实图、84 个字体样例和六个额外数字样例；未重新验收全部历史语料。rc20 的独立填充修复证据保留在历史发行记录与 JSON 的历史字段中。

## 安装与分发

本地源码完整回归 **365 项通过**，修改模块的 Ruff 检查通过。发行记录保存隔离安装 wheel 与精确 GitHub CI 提交的结果；[CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)覆盖 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码、sdist→wheel、元数据、公开内容、依赖和隔离安装包检查。五条 DeprecationWarning 来自 PyMuPDF SWIG。真实字体与内部 BIM 数据在本地验证，不冒充矩阵平台上的全资源测试。

新版 `r2` 资源需要 **rc21+**；rc21 保持旧 v1 字库可读。要获得本次填充表示，需要同时更换资源包或重建字库，仅升级 Python 包不改变旧资源。源字体与许可不变，资源哈希重新公布。wheel、sdist 与源码 ZIP 排除字体程序、外部字库、私有 PDF/DXF 和内部路径报告；独立资源 ZIP 保留各字体许可。见 [开源字库](OPEN_FONTS.md)。

## English

rc21 fixes Jigmo w's mismatch caused by a tiny zero-area closed contour. Removing all such contours would regress stroked 8, so schema v2 preserves every raw stroke template and adds an exact filled representation. Strict same-label subsets retain the complete raw match only when extra paths are closed and collinear. Competing labels and other overlaps remain ambiguous; font/run gates remain. DXF geometry and engineering-scale algorithms are unchanged. Twenty-eight new regressions cover geometry, ordering, ambiguity, old catalogs, build caches and malformed representation data.

All **245,496 legacy raw template records** match exactly. The rebuilt ten catalogs add **797 fill representations**, totaling **246,293 representations** across font faces. Every alternate is checked at all 17 sampling divisors using an independent convex-hull-area oracle. An unsupported alternate never discards the original glyph. Unicode 17 assigned-Han coverage remains **102,998** in the Jigmo union; coverage is distinct from recognition.

The same **84 real-font probes** improve from **62 to 68 complete**, with **16 partial/unconfirmed** and zero failures. All twenty 52-letter stroke/fill cases pass. Six additional real-font ABCD8w probes pass without geometry changes. All prior published characters are preserved. All **1262 published glyphs** are checked against source labels/bounds, catalog digests and source handles; maximum bounds error is **0.000866324 mm** against 0.05 mm. Original DXF entity tags match rc20 in all 84 cases; audits have zero errors/fixes. Sixteen Han cases retain competing internal contours. These 20 pt probes do not establish universal font/size/weight or IVS accuracy.

All **22 BIM PDFs** produce saved DXFs and remain degraded. Every saved group-code value matches rc20 apart from two HEADER GUIDs, including blocks, source references, geometry, text and transforms. Fresh preflight, hashes, TEXT handles and dimension validation are checked. Results remain **238 TEXT / 1035 characters**, zero external font locks or published external characters, scale states **9 calibrated / 6 declared approximate / 6 paper / 1 unknown**, and **13/22 geometry-valid**. Nine calibrated drawings still fail the dimension-error gate. The batch takes about 308 seconds; no performance improvement is claimed. The historical corpus was not rerun.

Local source tests pass **365 tests**; modified modules pass Ruff. Release notes identify isolated-wheel results and the exact four-job CI run. New r2 resources require rc21+, while old v1 catalogs remain readable; upgrading the Python package alone does not rebuild templates. Sources/licenses stay unchanged, and new asset digests are published. Main distributions exclude external fonts/catalogs and private drawings. Optional resource ZIPs retain original font licenses.
