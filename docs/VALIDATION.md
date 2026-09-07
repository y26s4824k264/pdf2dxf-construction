# rc18 验证记录 / Validation

版本：`2.0.0rc18`。本地执行环境为 macOS ARM64 / Python 3.12.13。

## 字库与真实字体

10 个静态字体字库共 **245,496 个模板**，分为常用资源包与扩展汉字资源包。下载、归档成员、字体源文件和字库均核对大小及 SHA256，原始许可证随独立资源包保留。Unicode 17 官方 UnicodeData.txt 与 Jigmo 三个字库逐码点比对：所支持汉字基本区、扩展 A–J、兼容区及其补充区的 **102,998 个已分配码点全部有模板**。

真实字体共执行 **84 个样例**：52 个大小写字母、字体包含时的“建筑结构平面图”，以及扩展 A 和补充平面各区段开头的 3–4 个已映射汉字；分别生成 20 pt 描边折线 PDF 和填充贝塞尔 PDF，经持久化 DXF 恢复 TEXT。转换前删除临时源字体副本。**57 个样例完整恢复，27 个部分恢复或未确认**，没有转换失败，实际文本均为预期文本的有序子序列。这个检查不能独立证明所有位置的识别准确率，也不是代表性准确率基准。

思源黑体及三种 DejaVu 的两个 PDF 路径均完整恢复 52 字母；其他字体仍有采样和同形/分段歧义造成的缺字。实际预期、结果和分字体统计全部公开在 [OPEN_FONT_VALIDATION.json](OPEN_FONT_VALIDATION.json)。同时加载两个资源包（10 个字库）的思源黑体填充样例完整恢复“建筑结构平面图”，仍只有具备证据的一个字体被锁定。

修复了完整字内的标点片段导致整字被拒绝：旧 rc17 对两个最小回归样例失败，新实现通过；四个竞争字母/汉字的负例继续拒绝重叠。新规则仍要求完整精确字形、共享字体、严格包含及后续字体/成行确认。

## 自动回归与发行包

本地源码完整回归 **312 项通过**。新增 31 项自动回归覆盖可复现离线构建、归档及缓存校验、完整 TEXT 链路、损坏/缺失字库、许可证引用、路径逃逸、符号链接、输入覆盖保护，以及字内标点/竞争文字的区别。完整源码、隔离安装 wheel 的执行数量与结果随发行记录保存。五条 DeprecationWarning 来自 PyMuPDF SWIG。

[GitHub CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) 在 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 运行源码测试、sdist→wheel、`twine check`、公开分发检查、`pip check` 及隔离源码安装包测试。对应执行结果以发行说明中的精确提交和 CI run 为准；资源字库全量构建及 84 个真实字体样例在本地执行，不冒充矩阵上也运行了全量资源测试。

Python wheel、sdist、公开源码 ZIP 继续排除字体程序、字库、私有 PDF/DXF 和内部路径报告。两个可选字库 ZIP 单独校验，保留各字体许可，不改成项目代码的 AGPL。

## 22 份 BIM 实图

使用最终识别规则与常用资源包重新转换 22 PDF / 22 页：**22 个 DXF、0 个转换失败**；全部仍为 `degraded`，CLI 退出码 5。逐份核对输入 SHA256、预检页码、输出哈希、实际 TEXT 句柄及内容、重新计算的尺寸验证；保存后 DXF 审计错误/修复均为 0。

内置模板仍恢复 **238 条 TEXT / 1035 个字符**。外部资源出现 262 个候选、0 个字体锁定、0 个外部字符写入。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22，九份已标定图仍超过 0.2% 尺寸误差门槛。

全部 22 份 DXF 与 rc17 逐组码比较，除了文件头 `$FINGERPRINTGUID` / `$VERSIONGUID` 外完全一致。文字、几何、实体顺序、属性与来源 XDATA 保持一致；此对比不是每个图元独立视觉保真的证明。公开摘要见 [validation.json](validation.json)。

历史 rc11 的 4290 份去重 PDF / 12577 页是基础转换测试，不是 rc18 全语料文字与工程质量验收。本轮复测范围为上述 22 份实图和 84 个字体样例。模板覆盖不代表任意字体识别；IVS/IVD 多码点异体序列未实现。

## English

Ten optional catalogs contain **245,496 templates**. The Jigmo union covers all **102,998 assigned Han codepoints** in the supported Unicode 17 unified, A–J and compatibility ranges, checked against official UnicodeData.txt. Source/archive-member hashes and original notices are retained. This is template coverage, not arbitrary-font recognition accuracy.

**84 real-font cases** use 20 pt stroked polygons and filled Bézier PDFs through persisted DXF to TEXT: **57 complete, 27 partial or unconfirmed**, with no conversion failures or published strings outside the expected ordered subsequences. Source Han Sans and three DejaVu faces recover all 52 letters on both paths. Other faces retain sampling and ambiguity limits. These are disclosed probes, not a representative accuracy benchmark; all case results are [published](OPEN_FONT_VALIDATION.json). A combined ten-catalog run restores the common Han phrase and locks only the evidenced font.

The local source suite passed **312 tests**. 31 added regressions cover offline resource builds, integrity, original notices, protected inputs, and complete-glyph punctuation fragments versus competing letters/Han. Each CI job verifies source and isolated wheel tests plus distribution/dependency checks; the release identifies the actual target run. Full resource builds and real-font probes were executed locally, not across every CI platform.

The final BIM run produced 22/22 DXFs, with zero conversion failures or saved-DXF audit errors/fixes; all remain degraded. Recovered output stays at 238 TEXT entities / 1035 characters. The new core catalogs yield 262 candidates, zero locks and zero published external characters. Scale/quality gates match rc17. Every DXF group pair matches rc17 except two header GUIDs. Historical rc11 corpus counts do not represent current full-corpus text/engineering acceptance.
