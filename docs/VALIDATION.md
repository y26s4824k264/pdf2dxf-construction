# rc20 验证记录 / Validation

版本：`2.0.0rc20`。本地环境为 macOS ARM64 / Python 3.12.13。

## 本轮修复与边界

某些带自接触或原路返回线段的 PDF 轮廓，经 `make_valid` 修复后成为 Polygon 与零面积 LineString 混合的 GeometryCollection。旧实现丢弃了整个集合，造成填充和字形笔画缺失。rc20 复用递归几何拆分函数，保留其中全部有效面及源轮廓方向。孔洞继续服从原填充规则；零面积线段不产生填充，独立描边仍保留。[Shapely 官方文档](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html)说明了此类混合输出。

新增 **17 项回归**覆盖两种填充规则、正反方向、孔洞、多面、零面积退化、PDF→保存后的 HATCH、独立描边和裁剪。旧 rc19 对前 11 个几何样例的结果为 10 个失败、1 个零面积负例通过；修复后 17 项全部通过。未更改字库、识别阈值、OCR 策略或工程比例算法。一般复杂非零绕数填充算法未在本轮重写；下述独立绕数验证针对本次发生变化的真实填充记录。

## 字体样例

同一批 **84 个真实字体 PDF** 重新转换，完整恢复从 rc19 的 **61 个提高到 62 个**，另 **22 个部分恢复或未确认**，转换失败为 0。Jigmo 扩展 I 填充样例补齐 `U+2EBF3`，完整恢复 `U+2EBF0..U+2EBF3`。源 PDF 两个被丢弃轮廓中的面分别约为 41.071608、15.271747 pt²；已对照 Poppler 渲染的原 PDF 与修复前后保存的 HATCH。先补齐转换几何，再由既有 DXF 字形算法确认 TEXT。

样例为 20 pt 描边折线及填充贝塞尔 PDF，包含 52 字母、字体包含时的“建筑结构平面图”、扩展 A 与补充平面区段开头的 3–4 个已映射汉字。生成后删除临时源字体副本，运行时只读持久化 DXF 与字库。

逐字复核全部 **1256 个已发布字形**的 cmap 标签、字库摘要、取整精度、来源句柄及位置。原字体 BoundsPen 排除只有移动指令而无线段的空轮廓；允许曲线离散造成 0.05 mm 边界误差，实测最大 **0.000867 mm**。83 个样例的原始实体组码与 rc19 相同，仅还原恢复图层/XDATA 后比较；另一个是本次修复的填充样例。84 份保存后的 DXF 审计错误/修复均为 0。

剩余 22 个样例包括 16 个汉字内部轮廓与“一/囗/廴”等字形竞争的样例，以及 6 个 Jigmo 英文样例中的退化 `w`。`w` 含不足 0.007 mm 的小线段，描边过滤和填充拓扑仍存在差异。它们继续保留几何，未放宽歧义拒绝规则。这组定向样例不是代表性准确率基准，不表示任意字体、字号或异体字均通过。逐项结果见 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。

## 22 份 BIM 实图与比例

常用资源包下，**22 PDF / 22 页均产出 DXF**，转换失败为 0，全部仍为 `degraded`（CLI 退出码 5）。逐份核对输入 SHA256、预检页码、输出哈希、实际 TEXT 句柄内容和重新计算的尺寸验证，DXF 审计错误/修复均为 0。

独立核验本次变化的 **9,895 条填充记录**：对原 PDF 边界离散线段做节点化和面划分，再用有符号射线交叉次数决定每个面是否填充，不调用 `make_valid` 或源方向启发式来生成预期区域。所有变化区域均与该绕数结果对齐，裁剪记录的修复结果没有变化。曲线采样复用既有解析/离散实现，这不是独立验证所有贝塞尔近似精度。

再按源序号读取保存后的纸面 DXF HATCH，核对全部 9,895 条记录，区域对称差面积实测为 **0 mm²**。最终 DXF 包括块定义共增加 **14,345 个 HATCH**，22 份均受影响。一条源填充可产生多个面，因此记录数与 HATCH 数不同。最终块内 HATCH 也逐项与纸面区域按报告比例放大后的结果比较，允许面积差 `max(1e-8 mm², 预期面积 × 1e-8)`，全部通过。

非填充实体的坐标、属性和 INSERT 变换在全部块定义中与 rc19 对齐；比较忽略实体自身句柄和所有者句柄，并将尺寸证据中的来源句柄解析为目标实体内容后核对。新增实体引起的句柄变化没有被当作几何变化，来源引用也没有被直接丢弃。恢复文字及边界保持一致。

恢复结果仍为 **238 条 TEXT / 1035 个字符**；外部字库为 262 个候选、0 个字体锁定、0 个外部字符写入。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。保留这些限制，不以补回填充宣称工程质量全部通过。公开摘要见 [validation.json](validation.json)。本次批次约 303 秒，rc19 记录约 296 秒；单次计时不能证明性能变化。

历史 rc11 的 4290 份去重 PDF / 12577 页只代表基础转换测试。本轮复测为上述 22 份实图和 84 个字体样例，未重新验收全部历史语料。

## 安装与分发验证

本地源码完整回归 **337 项通过**。发行记录保存隔离安装 wheel 的结果；[GitHub CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)在 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 执行源码测试、sdist→wheel、`twine check`、公开分发检查、`pip check` 及隔离安装包测试。精确提交和 CI run 以对应发行说明为准；84 个字体样例和内部 BIM 图纸在本地执行，不冒充矩阵平台的全量资源测试。五条 DeprecationWarning 来自 PyMuPDF SWIG。

复用 rc18 的 10 个独立字库，共 **245,496 个模板**，资源 SHA256 和原许可不变。Jigmo 并集覆盖 Unicode 17 支持区段全部 **102,998 个已分配汉字码点**；这是模板覆盖，IVS/IVD 多码点异体序列尚未支持。[字库说明](OPEN_FONTS.md)提供下载和重建方式。wheel、sdist 和源码 ZIP 排除字体程序、外部字库、私有 PDF/DXF 和内部路径报告；独立字库 ZIP 保留各字体原许可。

## English

rc20 fixes missing fills when polygon repair returns a GeometryCollection containing polygonal regions and zero-area lines. It recursively retains the polygonal parts with source winding and holes, while separately requested strokes remain. Seventeen regressions cover fill rules, winding, holes, multiple faces, degeneracy, persisted HATCH output, strokes and clips. The old implementation fails ten positive geometry fixtures and passes the zero-area negative fixture. Matching catalogs, thresholds and scale algorithms are unchanged; this does not rewrite general nonzero-fill semantics.

The same **84 real-font probes** now have **62 complete and 22 partial/unconfirmed** results, with zero conversion failures. Jigmo's Extension I fill case regains `U+2EBF3`. Source PDF rendering and saved HATCH geometry were compared. All **1256 published glyphs** were checked against source cmap labels, independent bounds, catalog digests and source handles; maximum bounds error is **0.000867 mm** against a 0.05 mm allowance. Original entity tags match rc19 in the other 83 cases; all 84 audits have zero errors/fixes. Six Jigmo English cases still miss a degenerate `w`; sixteen Han cases retain competing internal contours. These targeted probes are not a representative accuracy benchmark.

All **22 BIM PDFs / 22 pages** produced DXFs and remain degraded. An independent face-polygonization and signed-ray winding oracle validates all **9,895 changed fill records**, reusing existing curve sampling. Persisted paper-DXF HATCH regions match with **zero symmetric-difference area**. Final DXFs gain **14,345 HATCH entities**, including block contents; their regions also match the recorded paper-to-model scale. All nonfill entity tags, text and INSERT transforms match rc19 after normalizing handles and resolving dimension-source references to entity contents. This is bounded evidence for the changed fills, not universal visual acceptance.

Outputs remain **238 TEXT entities / 1035 characters**, 262 external candidates, zero font locks and zero external characters. Scale states remain 9 calibrated, 6 declared approximate, 6 paper and 1 unknown; 13/22 pass the geometry gate. Nine calibrated drawings still exceed the dimension-error gate. The batch took about 303 seconds versus a recorded 296 seconds for rc19; no speed improvement is claimed. Historical rc11 counts do not establish current full-corpus acceptance.

Local source tests pass **337 tests**. Release records identify isolated-wheel results and the exact four-job CI run; full font/BIM probes are local. Ten rc18 catalogs and their licenses are reused unchanged: **245,496 templates**, including all **102,998 assigned Han codepoints** in supported Unicode 17 ranges. Template coverage is distinct from recognition, and IVS sequences are unsupported. Main distributions exclude private drawings, source fonts and external catalogs.
