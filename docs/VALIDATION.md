# rc23 验证记录 / Validation

版本：`2.0.0rc23`。本地环境：macOS ARM64 / Python 3.12.13。

## 修复与拒绝边界

多字库把汉字内部短横分别标为“一、下划线、破折号”等时，整字可能被初次重叠检查拒绝。rc23 仅复核初次全字库扫描中已经具有唯一完整标签、且所属字体已锁定的候选。它必须通过原有单字体汉字片段规则，并在同一连续来源行中具有三个不同且全局无歧义的汉字锚点。复核所有原始竞争窗口的严格包含、字号和标签证据；不因字体锁定而忽略其他字体。

竞争窗口只能是明显较小的汉字、标点或中日韩笔画；窗口中的汉字标签必须唯一且得到当前字体精确支持。字母、数字、完整同形异字、跨界/等大轮廓、其他字体独有汉字和可能独立成行的小字继续拒绝。只发布完整父字，不猜内部片段的文字标签。报告最多保存 32 条详细复核证据，并单独统计截断数量，输出数量不受该报告上限限制。原始 DXF、PDF 转换和工程比例算法不变，不使用 OCR。

新增 **17 项回归**覆盖字库顺序、描边/填充、来源/位置/图层断开、锚点不足或重复、竞争字母/数字/汉字、完整标签冲突、等大片段、交错来源的小字行、原图元保留、幂等及报告上限。最初 15 项在 rc22 下为 4 个正例失败、11 个边界用例通过；最终源码 **399 项通过**，修改模块 Ruff 检查通过。

## 三类字库验证分别报告

| 验证方式 | 样例数 | rc22 完整恢复 | rc23 完整恢复 | rc23 部分/未确认 |
| --- | ---: | ---: | ---: | ---: |
| 每个 PDF 指定对应字体字库，重新 PDF→DXF→TEXT | 84 | 82 | 82 | 2 |
| 同源保存 DXF 同时加载全部十个字库 | 84 | 62 | 64 | 20 |
| 扩展 J 正常加载下载字库的完整转换；两种管线 × 组合/对应字体 | 4 | 2（历史安装包记录） | 4 | 0 |

第一类逐字核验 **1306 个发布字形**；第二类逐字核验 **1269 个发布字形**，比 rc22 增加两个。原字体 cmap / BoundsPen 与 PDF 生成位置作为标签和边界依据，核对保存来源句柄、字形摘要与取整精度；两类最大边界误差均为 **0.000866324 mm**，小于 0.05 mm 的曲线离散边界容差。所有先前发布字符和原始 DXF 实体组码保留，保存 DXF 审计错误/修复均为 0。另六个 `ABCD8w` PDF 重新转换，全部完整恢复且原几何与 rc22 一致。

十字库对照在移除恢复标记和输出文字的 DXF 副本上，分别执行冻结的 rc22 和当前 rc23 完整 DXF 识别入口，只缓存已校验的字库对象以避免重复磁盘解析。它不代表重新用十字库转换 84 个 PDF。第三类检查使用正常、未缓存的资源加载，补充验证完整转换入口。转换始终只用持久化 DXF/字库；原字体仅用于制作样例和独立核验。源码与隔离安装包、精确提交 CI 的结果另见发行记录。

两个补回的字都是遍黑体 `U+323B3` 的描边/填充样例。独立检查枚举父字内部每个连续源图元窗口，对照全部十个字库重新计算精确候选；每例六个竞争窗口的完整字体/标签集合与报告一致，三个锚点和父字均具有全局唯一标签。来源句柄、边界、严格包含、字号比例和连续来源也逐一核验；该检查不调用新增复核函数。逐项数据见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

逐字体仍有两例 Jigmo `建筑结构平面图` 只恢复 `筑结构平面`，其 廴/囗 竞争接近整字大小。十字库组合仍有 20 例部分或未确认，增加字库不保证更好。以上为 20 pt 定向样例，不是任意字体、字号、字重或 IVS 异体序列准确率。

## 22 份 BIM 实图与比例

当前 BIM 目录全部 **22 PDF / 22 页**使用下载的 r2 常用包复测，均产出可读 DXF，转换失败为 0，全部仍为 `degraded`，CLI 退出码 5。核对源文件清单、SHA256、预检页码、保存哈希、实际 TEXT 句柄与重新计算的尺寸验证；所有 DXF 审计错误/修复均为 0。

所有保存 DXF 的**全部组码与 rc22 一致，仅 HEADER 两个 GUID 变化**，包括块、坐标、属性、来源、文字和 INSERT 变换。结果仍为 **238 TEXT / 1035 字符**，外部字体 262 个候选、0 字体锁定、0 外部发布字符。比例为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。不能将转换成功当作工程验收通过。单次批次约 308 秒，不作为性能提升结论。公开摘要：[validation.json](validation.json)。

历史 rc11 的 4290 份去重 PDF / 12577 页仅代表基础转换测试，本轮没有重新验收全部历史语料。rc20 填充修复、rc21 字库构建和 rc22 片段核验记录明确保留为历史证据。

## 分发

两个 r2 ZIP 与 rc22 的 SHA256 完全相同：10 个字库共 245,496 个原始记录和 797 个填充表示，合计 246,293 个表示。Jigmo 并集覆盖 Unicode 17 支持范围内 102,998 个已分配汉字码点；模板覆盖不等于识别成功。资源加载仍支持 rc21+；本轮来源行复核需要 rc23，无需重建字库。

源码、wheel、sdist 排除私有 PDF/DXF、外部字体/字库和个人文件路径。独立字体 ZIP 保留原许可。CI 覆盖 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码、构建、元数据、内容、依赖和隔离安装包验证。真实字体/内部 BIM 回归在本地执行，不冒充跨平台全资源测试。五条 DeprecationWarning 来自 PyMuPDF SWIG。

## English

rc23 rechecks a globally unique whole Han candidate only after the initial all-catalog scan has locked its font. The existing single-font fragment rule must succeed, with three distinct globally unambiguous Han anchors in the same continuous source row. Every original competing window remains checked for strict containment, smaller size and supported labels. Complete-label conflicts, letters/digits, crossing/full-size contours, foreign-only Han labels and possible independent small-text rows remain unresolved. Only the whole parent is published. No OCR, semantic guessing, DXF geometry or engineering-scale change is involved. Seventeen new regressions bring the local source suite to **399 passing tests**; scoped Ruff passes.

Results are separated by selection and workflow. The **84 matching-face PDFs remain 82 complete / 2 partial**. Rechecking the same **84 persisted DXFs with all ten catalogs improves 62→64 complete, with 20 partial/unconfirmed**, adding two characters. The DXF comparison executes frozen rc22 and current rc23 recognition independently, caching only validated catalog objects; it is not 84 additional PDF conversions. Four separate normal-resource-loading PDF conversions (Extension J stroke/fill × combined/matching catalogs) all recover completely. Six ABCD8w PDFs also pass unchanged. Release records separately identify isolated-wheel and exact-commit CI results.

Independent source cmap/BoundsPen checks cover **1306 matching-face glyphs and 1269 combined-catalog glyphs**, with maximum bounds error **0.000866324 mm** against 0.05 mm. Every previous character and original DXF entity tag is preserved; saved audits have zero errors/fixes. For both restored U+323B3 parents, a separate audit enumerates every internal source-atom window against all ten catalogs: all six competing font/label sets per case match the recorded evidence, with globally unique parent/anchor labels and verified source handles, bounds, containment, size and source continuity. It does not call the new row-recheck function. These 20 pt probes do not establish arbitrary-font, size, weight or IVS accuracy.

All **22 BIM PDFs / 22 pages** produce DXFs and remain degraded. Every saved group-code value matches rc22 apart from two HEADER GUIDs. Fresh preflight, hashes, text handles and dimension validation are verified. Totals remain **238 TEXT / 1035 characters**, 262 font candidates, zero font locks/external characters, scale states **9 calibrated / 6 declared approximate / 6 paper / 1 unknown**, and **13/22 geometry-valid**. Nine calibrated drawings still fail the dimension-error gate. The 308-second single run is not a performance claim; the historical corpus was not rerun.

Both **r2 assets are reused byte-for-byte**. Template coverage and historical rebuild evidence remain separate from recognition outcomes. Main distributions exclude private drawings and external font resources; optional ZIPs retain original notices. The four-platform CI checks source and installed packages. Full font-resource and BIM checks are local, not claimed for every CI platform.
