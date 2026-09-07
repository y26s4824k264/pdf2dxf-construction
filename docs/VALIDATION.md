# rc19 验证记录 / Validation

版本：`2.0.0rc19`。本地环境为 macOS ARM64 / Python 3.12.13。

## 本轮文字修复

对同一批 84 个真实字体 PDF 重新转换，完整恢复从 rc18 的 **57 个提高到 61 个**，另 **23 个部分恢复或未确认**；0 个转换失败。7 个样例补回合计 8 个字符，原来已恢复的文字没有减少。思源黑体、思源宋体及三种 DejaVu 均在描边与填充两条 PDF 路径完整恢复 52 个大小写字母；遍黑体两个分包的描边路径也补齐了字母 `s`。

根因是 PDF 数值保存使归一化顶点出现约 0.00007–0.00021 像素的偏移，跨过栅格取整边界。rc19 检查有限的 3/4/5 位取整变体，每个候选仍要求持久化字库中的掩码摘要与拓扑精确匹配，并通过宽高比检查；不同变体或字库给出不同文字时拒绝。没有 OCR、语义猜字或 DXF 坐标修改，旧字库无需重建。规则及报告字段见 [字符支持](CHARACTER_SUPPORT.md)。

新增 8 项自动回归覆盖描边/填充边界恢复、超界变形拒绝、同库/跨库标签冲突、源几何保留、幂等和最终已锁定字库的证据归属。用旧 rc18 扫描函数复现：两个恢复正例失败，两个超界拒绝负例通过；新实现全部通过。

## 真实字体与保存后的证据

84 个样例包含 52 字母、字体包含时的“建筑结构平面图”，以及扩展 A 和补充平面各区段开头的 3–4 个已映射汉字。20 pt 描边折线和填充贝塞尔 PDF 经持久化 DXF 恢复 TEXT；生成后删除临时源字体副本，转换运行时只读 DXF 和字库。

逐个核对全部 **1255 个已发布字形**的标签、字库摘要、取整精度、来源句柄和位置。使用原字体 cmap 与独立 BoundsPen 计算 PDF 生成位置处的字形边界，排除只有移动指令、没有任何线段的空轮廓；允许 0.05 mm 的曲线离散边界差异，实测最大 **0.000867 mm**。84 份 DXF 的原始实体组码与 rc18 对齐，仅还原恢复专用图层/XDATA 后比较；均一致，审计错误/修复均为 0。

剩余 23 个样例中，16 个受“一、囗、廴”等字内轮廓的竞争汉字歧义影响；6 个 Jigmo 英文样例仍缺 `w`，其字体包含不足 0.007 mm 的退化线段，描边候选过滤及填充路径的拓扑不一致；1 个 Jigmo 扩展 I 填充样例也存在拓扑差异。这些继续保留原几何，没有放宽汉字重叠或字体锁定门槛。逐项预期、实际文本、位置复核和前后差异见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

这组样例用于复现具体路径，并非代表性准确率基准，更不等于任意字体、字号、异体字和图纸都已通过。

## 字库与分发

复用 rc18 的 10 个独立字库，共 **245,496 个模板**，来源锁、资源 SHA256 和原始许可保持不变。Jigmo 模板并集覆盖 Unicode 17 支持区段全部 **102,998 个已分配汉字码点**；这是模板覆盖，IVS/IVD 多码点异体序列尚未支持。[字库说明](OPEN_FONTS.md) 提供下载和重建方式。

本地源码完整回归 **320 项通过**；隔离安装 wheel 的执行结果随发行记录保存。[GitHub CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) 在 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 运行源码测试、sdist→wheel、`twine check`、公开分发检查、`pip check` 及隔离安装包测试。精确提交和 CI run 以发行说明为准；84 个字体样例和内部 BIM 图纸在本地执行，不冒充矩阵平台的全量资源测试。五条 DeprecationWarning 来自 PyMuPDF SWIG。

wheel、sdist 和源码 ZIP 排除字体程序、字库、私有 PDF/DXF 及内部路径报告。可选字库 ZIP 单独保留字体原许可，不改成项目代码的 AGPL。

## 22 份 BIM 实图

常用资源包下，22 PDF / 22 页均产出 DXF，转换失败为 0，全部仍为 `degraded`（CLI 退出码 5）。逐份核对输入 SHA256、预检页码、输出哈希、实际 TEXT 句柄内容和重新计算的尺寸验证；保存后的 DXF 审计错误/修复均为 0。

恢复结果保持 **238 条 TEXT / 1035 个字符**，外部字库仍为 262 个候选、0 个字体锁定、0 个外部字符写入。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。

22 份 DXF 与 rc18 逐组码比较，除了文件头 `$FINGERPRINTGUID` / `$VERSIONGUID` 外完全一致。文字、几何、实体顺序、属性和来源保持一致；这不等于所有图元都已独立视觉验收。公开摘要见 [validation.json](validation.json)。本次批次耗时约 296 秒，rc18 记录约 255 秒；本次同时运行字体回归，不能据此归因性能差异或宣称速度提升，数值变体也增加了匹配计算。

历史 rc11 的 4290 份去重 PDF / 12577 页只代表基础转换测试。本轮复测为上述 22 份实图和 84 个字体样例，未重新验收全部历史语料。

## English

On the same **84 real-font PDF probes**, complete recovery improves from **57 to 61**, with **23 partial/unconfirmed** and zero conversion failures. Seven cases gain eight characters; previously published characters remain. Both PDF paths restore all 52 letters for Source Han Sans/Serif and three DejaVu faces; the Plangothic stroke paths also recover `s`.

Bounded three/four/five-decimal raster variants address numeric serialization near half-pixel boundaries. Each candidate requires an exact persisted mask digest, topology and aspect match. All variant/catalog label conflicts remain rejected. Runtime uses persisted DXF and catalogs, without OCR or source-font access. Eight regressions cover boundary recovery, larger deformations, same/cross-catalog ambiguity, geometry retention and idempotence; the old scanner fails the two positive fixtures.

All **1255 published glyphs** were checked against source cmap labels, independent glyph bounds at the PDF generation positions, catalog digests and source handles. BoundsPen excludes move-only contours without segments; the 0.05 mm bound allows curve discretization, with a measured maximum of **0.000867 mm**. All original entity tags match rc18 after removing only recovery layer/XDATA changes. All 84 saved-DXF audits have zero errors/fixes. The 23 remaining cases comprise 16 competing-Han-contour cases, six Jigmo English cases missing a degenerate-contour `w`, and one Jigmo Extension I fill topology mismatch. These remain geometry. [Case-level evidence](OPEN_FONT_VALIDATION.json) is public; this is not a representative or universal accuracy benchmark.

The ten rc18 catalogs and original licenses are reused unchanged: **245,496 templates**, including all **102,998 assigned Han codepoints** in supported Unicode 17 ranges. Template coverage is distinct from recognition; IVS sequences are unsupported. Local source tests pass **320 tests**; release records identify isolated-wheel and four-platform CI results. Resource probes are local, not claimed as full CI matrix runs.

The BIM regression produces **22/22 DXFs**, zero conversion failures and zero audit errors/fixes. All remain degraded. Output stays at **238 TEXT entities / 1035 characters**, with 262 external candidates, zero locks and zero external characters. Scale states are 9 calibrated, 6 declared approximate, 6 paper and 1 unknown; 13/22 pass the geometry gate. Nine calibrated drawings still exceed the dimension-error gate. Every DXF group pair matches rc18 except two header GUIDs. This batch took about 296 seconds versus the recorded 255 seconds for rc18, with concurrent probe activity; no speed improvement is claimed. Historical rc11 counts do not represent current full-corpus text or engineering acceptance.
