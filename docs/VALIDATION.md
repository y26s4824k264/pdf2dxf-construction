# rc26 验证记录 / Validation

版本：`2.0.0rc26`。本地环境：macOS ARM64 / Python 3.12.13。

## 修复与可复现问题

此前，多标签轮廓窗口被标记为歧义而不生成 `GlyphMatch`，后续只比较唯一候选，导致这类窗口从重叠判断中消失。例如原本被内部“一”轮廓阻止的完整“图”，增加一个把该轮廓标成“二”的字库后，反而被接受，甚至可以参与字体锁定。这不是更多字库提供了确认依据。

rc26 保留歧义窗口的半开区间，先拒绝与其重叠的唯一候选，再执行已有的唯一候选重叠判断。排序、前缀最大端点和二分查找避免新增逐候选扫描全部歧义窗口；相邻端点不算重叠。完整父字、内部子字形、跨字边界窗口和单个字库内部的多标签均适用。已有字体锁定及来源行复核可在锚点和全部竞争窗口证据成立时恢复完整字形；不能用受阻候选先建立自己的字体锁定。

新增 `font_ambiguous_overlap_rejections` 记录初次扫描受阻候选数，不等于最终未输出字符数。几何、字库数据、数值取整规则、比例门槛均未修改。恢复继续只消费保存的 DXF 与 `.p2dfont`，不使用 OCR 或原字体文件。

## 回归与原轮廓证据

新增 **19 项回归全部在冻结 rc25 上复现错误输出或错误字体锁定**，修复后通过。覆盖同库/跨库同形标签、汉字/字母/数字竞争、字库顺序、描边/填充、完整父字/内部子字/跨界、相邻端点、原实体保留及幂等。原有含歧义标点的 `ABCDi` 样例仍恢复完整，但必须经过四个独立字母锚点支持的同行复核；`ABCi` 不能再依赖自身冲突字形达到四字母锁定门槛。

针对性 70 项、最终全量源码 **443 项**及修改文件 Ruff 通过。安装 wheel 与精确提交的跨平台 CI 结果见本版本发行记录；CI 在每个平台分别验证源码与隔离安装包。五条 DeprecationWarning 来自 PyMuPDF SWIG。

| 定向样例 | 基线 | rc26 |
| --- | ---: | ---: |
| 十字库同时加载，84 个保存 DXF 完整恢复 | rc25：70/84 | **63/84** |
| 十字库输出字符 | rc25：1275 | **1244** |
| 十字库的完整 52 字母样例 | rc25：20/20 | **20/20** |
| 各自对应字体，84 个 PDF 完整恢复 | rc24：82/84 | **82/84** |
| 对应字体的输出字符 | rc24：1306 | **1306** |
| 额外 ABCD8w PDF | 历史：6/6 | **6/6** |

84-DXF 对照缓存一次已校验的全部十个字库对象，在同一原始图元的副本上分别运行冻结 rc25 与 rc26。独立审计不调用新二分算法，直接枚举所有区间对，核对初始候选集合；并从 DXF 原子重新计算每个歧义窗口的精确掩码、摘要、拓扑、标签与边界。共核验 **24 个歧义窗口、20 个受重叠阻止的唯一候选**。原始唯一候选与全部冲突预测在两版一致，修复只使原先遗漏的冲突继续生效。

八个罕见汉字样例因失去无冲突字体锚点，共少输出 **31 个字符**；其中一个样例在基线就不完整，因此完整样例数减少七个。不能据此认定 31 个旧标签全部错误，也不能把这次变化称为识别率提升。未确认轮廓全部保留。另有 **10 个完整父字**通过既有来源行复核恢复；每个父字内的全部子窗口、精确预测、独立锚点、源句柄、包含关系、高度和连续来源均重新核验，其中两个此前绕过了这一步。

84 个对应字体 PDF 本轮全部重新执行 PDF→DXF→TEXT，82 个完整恢复，两个 Jigmo 常用汉字样例继续保留完整轮廓竞争。两组输出分别对 **1244 / 1306 个字形**核对原字体 cmap、BoundsPen、生成坐标、保存 TEXT、源句柄和字形摘要；最大边界差 **0.000867 mm 以内**，审计容差 0.05 mm。原字体仅用于独立审计，不用于运行时匹配。两组所有原始模型空间实体组码在去除恢复层/XDATA 标记后与 rc23 相同，保存 DXF 审计错误/修复均为 0。

另外 **16 个正常资源加载 PDF 检查**不复用缓存：八个英文/扩展 J 完整样例、四个因组合字库歧义正确保留轮廓的样例，以及这四个使用对应字体字库时的完整输出。16 个预期结果全部通过，包含 12 个完整输出和 4 个保留歧义的结果，不能把它们称为 16 个完整识别。隔离 wheel 使用同一入口并验证 worker 导入安装包。完整逐项数据见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)，安装包结果见本版本发行记录。

## BIM 实图与比例限制

本轮使用不变的 r2 core 资源，重新转换内部 **22 PDF / 22 页**。22 份均产出保存 DXF，转换失败 0；全部仍为 `degraded`，CLI 退出码 5。重新核对输入 SHA256/预检、保存输出 SHA256、实际 TEXT 句柄和尺寸验证；所有 DXF 组码与 rc24 相同，仅两个 HEADER GUID 不同。审计错误和修复均为 0。

结果为 **238 TEXT / 1035 字符**；内置精确匹配 1042，外部字库候选 262，字体锁定及外部发布字符均为 0。比例状态：9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 为 **13/22**。九份已标定图仍超出 **0.2%** 尺寸误差门槛，不放宽阈值，不把产出 DXF 当成工程验收通过。公开脱敏摘要见 [validation.json](validation.json)。

历史 rc11 的 **4290 份去重 PDF / 12577 页**仅代表当时的基础转换测试，本轮未重跑。历史 rc20 填充修复及 rc25 加载性能证据保留原版本标记；本轮没有重新做性能测量。rc25 的加载优化代码保持原样：[CATALOG_LOADING.json](CATALOG_LOADING.json)。

## 分发与范围

仍为预发布。组合字库的 **21 个样例**部分恢复或未确认；对应字体两个 Jigmo 样例仍未补齐。定向 20 pt 样例不能证明任意字体、字号、字重或 IVS 异体序列的准确率。模板覆盖不等于识别成功。

两个 r2 ZIP 的字节和 SHA256 不变，含 245,496 个原始模板、797 个填充表示，无需重新下载或重建。源码、wheel、sdist 排除私有 PDF/DXF、外部字体/字库与个人路径，独立资源包保留原许可。CI 范围为 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12；真实字库和 BIM 语料为本地验证，不表示各 CI 平台也运行了这些资源。

## English

rc26 fixes ambiguous source windows disappearing from overlap checks when they do not create a unique `GlyphMatch`. Adding another catalog could previously admit a conflicting parent or child and allow it to bootstrap its own font lock. Sorted half-open spans, prefix maximum endpoints and binary search retain these conflicts without a new all-pairs loop. Adjacent endpoints remain separate. Established source-row rechecks may restore a whole glyph only with independent anchors and all original conflict evidence. Geometry, catalog bytes, raster rounding and scale thresholds remain unchanged; runtime matching uses persisted DXF and catalogs without OCR or source fonts.

All **19 added regressions fail on frozen rc25** for incorrect TEXT or font-lock behavior and pass after the fix. Seventy focused tests, **443 source tests** and scoped Ruff pass. Isolated-wheel and exact-commit CI results are recorded in the release; five warnings are from PyMuPDF SWIG.

Across 84 persisted DXFs with all ten catalogs cached together, complete cases change from **70/84 to 63/84**, with **1244 characters instead of 1275**. All **20 full-alphabet probes remain complete**. Independent all-pairs overlap checks verify 24 ambiguous windows and 20 blocked unique candidates; raw candidates and conflict predictions match frozen rc25 exactly. Eight rare-Han cases lose sufficient font-lock anchors, withholding 31 prior characters while retaining their original outlines. This does not establish that every withheld label was wrong and is not an accuracy increase. Ten whole parents pass existing anchored row rechecks; every internal competing window and all source, containment, height and anchor evidence were independently recomputed.

All 84 matching-face PDFs were freshly converted and remain **82/84 complete**, with two unresolved Jigmo common-Han cases. Independent original-font cmap/BoundsPen checks validate all **1244 combined-catalog and 1306 matching-face output glyphs**, source handles, digests and positions; maximum bbox error is below **0.000867 mm** against a 0.05 mm audit tolerance. All original modelspace entity tags equal rc23 after removing only recovery metadata, and all saved-DXF audits have zero errors/fixes. Six ABCD8w PDF probes also pass.

Sixteen normal uncached resource-loading checks produce **12 complete outputs and four correctly withheld ambiguous runs**. They cover positive English/Extension J cases and conflicting Han cases under combined versus matching-face catalog selection. All 16 expected outcomes pass; these are not 16 complete recognitions. The same entry point is used for installed-wheel checks with source-free worker resolution. [Detailed font evidence](OPEN_FONT_VALIDATION.json) and the release record distinguish these scopes.

The fresh **22-PDF BIM batch** produces all DXFs with zero conversion failures, but all remain degraded (CLI exit 5). All saved DXF group pairs match rc24 except two HEADER GUIDs. Input/output hashes, actual TEXT handles and dimension validation are verified: **238 TEXT / 1035 characters**, 262 external candidates, zero external locks/characters; scales are 9 calibrated, 6 declared approximate, 6 paper, 1 unknown. The geometry gate passes **13/22**; nine calibrated drawings still exceed the **0.2%** dimension-error limit. See the [sanitized summary](validation.json).

The historical rc11 4290-PDF/12577-page corpus was not rerun. rc20 fill-repair and rc25 performance evidence remain explicitly historical; rc25 loading code is unchanged and no new timing claim is made. Reuse identical r2 resources. These targeted probes do not establish arbitrary-font recognition, cross-platform real-corpus acceptance or full engineering readiness.
