# rc24 验证记录 / Validation

版本：`2.0.0rc24`。本地环境：macOS ARM64 / Python 3.12.13。

## 修复与拒绝边界

同时加载十个字库时，DejaVu Sans 和遍黑体 P1/P2 的小写 `i` 竖笔画与另一个字体的标点轮廓相同，导致完整字母被重叠检查拒绝。rc24 对已有唯一整字标签、且字体已经锁定的英文候选增加来源行复核。必须有同一连续来源行的四个不同（不区分大小写计数）、全局无歧义字母锚点，单字体扫描也必须接受完整候选。

所有原始竞争窗口都要严格包含在父字内，低于父字高度，且每个候选标签均属于 Unicode 标点。竞争字母、数字、汉字、符号、整字同形、跨界/等高轮廓和不足行内锚点继续拒绝。原有汉字三锚点、0.72 字高及内部汉字标签一致性规则不变。只发布完整父字，不猜片段标签，不使用 OCR。报告新增脚本类型和高度参照字段，保留原计数与 32 条详细证据上限。

新增 **17 项回归**，覆盖字库顺序、描边/填充、原图元保留、幂等、竞争标签、完整同形、等高片段、锚点不足/重复以及来源/位置/图层断开。相同测试在 rc23 上为四个预期正例失败、13 个边界用例通过；rc24 全量源码 **416 项通过**，修改模块 Ruff 检查通过。

## 按字库选择与验证入口分别报告

| 验证方式 | 样例数 | rc23 完整 | rc24 完整 | rc24 部分/未确认 |
| --- | ---: | ---: | ---: | ---: |
| 原 PDF 指定对应字体字库，重新 PDF→DXF→TEXT | 84 | 82 | 82 | 2 |
| 同源保存 DXF 同时加载十个字库 | 84 | 64 | 70 | 14 |
| 正常加载下载的十字库，三个字体英文与扩展 J 的描边/填充 PDF | 8 | 未按本矩阵重跑 | 8 | 0 |

十字库组合中，十种字体的 **20 个大小写 52 字母描边/填充样例全部完整恢复**。本轮补回的六个字符均为 `i`。独立原字体 cmap / BoundsPen 和 PDF 生成位置核验覆盖 **1275 个组合字库字形、1306 个对应字体字形**，最大边界误差均为 **0.000866324 mm**，小于 0.05 mm 的曲线离散边界容差。所有已有发布字符与原始 DXF 图元保留，保存 DXF 审计错误/修复均为 0。六个 `ABCD8w` PDF 也重新转换，完整恢复且原几何与 rc23 一致。

十字库对照在移除恢复标记和输出文字的保存 DXF 副本上，分别执行冻结 rc23 和当前 rc24 完整识别入口，只缓存已校验字库对象。它不代表另外重新转换 84 个 PDF。八个正常加载资源的完整 PDF 转换补充验证实际入口。源码和隔离安装包的测试、精确提交 CI 结果另见发行记录。原字体只供样例制作和独立核验，运行时识别读取持久化 DXF 与字库。

独立证据检查枚举八个行复核父字（六个英文、两个既有汉字）内部的每个连续源图元窗口，对照全部十个字库重算候选。完整字体/标签集合、父字与锚点的全局唯一标签、来源句柄、边界、严格包含、字号参照和来源连续性均与报告一致。该检查不调用新增行复核决策函数。逐项数据见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

对应字体仍有两例 Jigmo `建筑结构平面图` 只恢复 `筑结构平面`，其 廴/囗 竞争接近整字大小。十字库组合仍有 14 个汉字样例部分或未确认。以上均为 20 pt 定向样例，不代表任意字体、字号、字重或 IVS 异体序列准确率；更多字库仍可能增加歧义。

## BIM 实图与工程比例

当前 BIM 目录全部 **22 PDF / 22 页**使用下载的 r2 常用包复测，均产出可读 DXF，转换失败为 0，全部仍为 `degraded`，CLI 退出码 5。核对源文件清单、SHA256、预检页码、输出哈希、实际 TEXT 句柄与重新计算的尺寸验证；DXF 审计错误/修复均为 0。

所有保存 DXF 的**全部组码与 rc23 一致，仅 HEADER 两个 GUID 变化**，包括块、坐标、属性、来源、文字和 INSERT 变换。结果保持 **238 TEXT / 1035 字符**、外部字体 262 个候选、0 字体锁定、0 外部发布字符。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。不能将产出 DXF 当作工程验收通过。公开摘要：[validation.json](validation.json)。

历史 rc11 的 4290 份去重 PDF / 12577 页仅代表基础转换测试，本轮没有重新验收全部历史语料。rc20 填充修复、rc21 字库构建和 rc22 汉字片段记录保留为历史证据；本轮无性能提升结论。

## 分发

两个 r2 ZIP 的字节和 SHA256 不变：10 个字库保留 245,496 个原始记录及 797 个填充表示，共 246,293 个表示。Jigmo 并集覆盖 Unicode 17 支持范围内 102,998 个已分配汉字码点；模板覆盖不等于识别成功。资源加载仍支持 rc21+，本轮英文复核需要 rc24，无需重建字库。

源码、wheel、sdist 排除私有 PDF/DXF、外部字体/字库和个人文件路径。独立字体 ZIP 保留原许可。CI 覆盖 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码、构建、元数据、内容、依赖和隔离安装包验证。真实字体与 BIM 回归在本地执行，不代表每个 CI 环境均测试全部资源。五条 DeprecationWarning 来自 PyMuPDF SWIG。

## English

rc24 restores globally unique whole Latin glyphs blocked by punctuation contours from another catalog. The initial scan must already lock the font; four distinct globally unambiguous Latin anchors (case-insensitive) must occur in the same continuous source row, and the single-font scan must accept the parent. Every competing window remains checked for strict containment, shorter height and punctuation-only labels. Letters, digits, Han, symbols, whole-label conflicts, crossing/full-height contours and insufficient anchors remain unresolved. Existing Han rules are unchanged. No OCR or semantic guessing is used. Seventeen new regressions bring source tests to **416 passing tests**; scoped Ruff passes.

**All-ten-catalog DXF probes improve 64/84→70/84 complete**, restoring six `i` characters and completing all **20 uppercase/lowercase 52-letter stroke/fill probes** across ten faces. Fourteen Han cases remain partial/unconfirmed. **Matching-face PDF probes remain 82/84 complete**, with two partial Jigmo cases. Eight separate normal-loading PDF conversions (three English faces plus Extension J, both pipelines, all ten catalogs) pass, as do six ABCD8w PDFs. The 84-DXF comparison executes frozen rc23 and current rc24 on persisted-DXF copies, caching only validated catalogs; it is not 84 additional PDF conversions. Release records separately identify isolated-wheel and exact-commit CI checks.

Independent cmap/BoundsPen checks cover **1275 combined-catalog and 1306 matching-face glyphs**, with maximum bounds error **0.000866324 mm** against 0.05 mm. Prior characters and original entities are preserved; saved DXF audits have zero errors/fixes. A separate oracle enumerates all internal source windows for eight rechecked parents (six Latin, two existing Han), verifying all catalog/label predictions, global label uniqueness, source handles, bounds, strict containment, height references and source continuity without calling the row-recheck decision. These targeted 20 pt probes do not establish arbitrary-font accuracy.

All **22 BIM PDFs / 22 pages** produce DXFs and remain degraded. Every saved group-code value matches rc23 except two HEADER GUIDs. Fresh hashes, preflight, TEXT handles and saved dimension validation are checked. Totals remain **238 TEXT / 1035 characters**, 262 font candidates, zero font locks/external characters, scale states **9 calibrated / 6 declared approximate / 6 paper / 1 unknown**, and **13/22 geometry-valid**. Nine calibrated drawings still fail the dimension-error gate. The historical corpus was not rerun.

Both **r2 assets are reused byte-for-byte**; template coverage and historical build evidence stay distinct from recognition results. Main distributions exclude private drawings and external fonts; resource ZIPs retain original notices. Full real-font/BIM checks are local, not claimed for every CI environment.
