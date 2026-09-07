# rc17 验证记录 / Validation

版本：`2.0.0rc17`。本地最终运行环境为 macOS ARM64 / Python 3.12.13。

## 自动回归与字符范围

源码完整回归 **281 项通过**。其中新增 55 项覆盖以下路径：

- 真实 DejaVu Sans、Serif、Sans Mono 字体的全部 52 个大小写字母，通过描边折线 PDF 与纯填充贝塞尔 PDF 恢复为保存后的 TEXT；转换前删除源字体文件。
- 汉字基本区、扩展 A–J、兼容汉字区与补充区，分别通过直接 DXF 和 PDF→DXF→TEXT；这些使用程序生成的 cmap/轮廓，证明 Unicode 输出通路，不表示所有真实汉字字形已逐字测试。
- 中英混排、表意数字〇、纯英文锁定、不足四种字母和大小写重复拒绝、覆盖/缺字报告。
- 旧采样字库和新小数采样字库重载、非有限容差拒绝、原填充保留、重复恢复幂等、非平面/开放/bulge 填充保留。
- 实图发现的回归：独立填充操作不得打断已确认的描边文字。修复后新增了交错绘制序列测试。

五条 DeprecationWarning 来自 PyMuPDF SWIG。真实字体来自测试依赖 Matplotlib；仓库、wheel 和源码包不复制这些字体文件。更完整的识别边界见 [字符支持](CHARACTER_SUPPORT.md)。

[GitHub CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) 配置 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12 和 Windows/3.12。每个作业运行源码测试、sdist→wheel 构建、`twine check`、公开分发检查、`pip check` 及隔离源码的安装包回归。平台执行结论须核对发行目标提交对应的 run，发行说明附具体链接；本地 281 项结果不代替远端 CI 结果。

## 22 份实图重新验证

在最后一次运行代码修复后，重新转换内部 22 份 PDF / 22 页，启用内置中文字库、旧版外部宋体 `.p2dfont`、`outline_chinese=required`、`scale_mode=declared`。**22/22 生成 DXF，0 个转换失败**。全部仍为 `degraded`，批处理退出码 5。

逐份重开 DXF：审计错误/修复均为 0；输入 SHA256、预检页码、输出哈希、实际恢复 TEXT 句柄和内容均核对通过。独立重新计算保存后尺寸验证，与每份转换报告一致。

内置模板恢复 **238 条 TEXT / 1035 个字符**，与 rc16 一致。外部宋体有 44 个孤立候选，0 个字体锁定、0 个外部字符写入。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1；geometry_valid 为 13/22。九份已标定图纸仍超过 0.2% 尺寸误差门槛，不调宽阈值。

全部 22 份保存后的 DXF 与 rc16 逐组码比较，除文件头 `$FINGERPRINTGUID` / `$VERSIONGUID` 外完全一致，包括文字、实体顺序、几何、属性和来源 XDATA。此对比证明本轮未改变这些实图的既有输出，不构成所有图元的独立视觉保真证明。机器可读摘要见 [validation.json](validation.json)。

历史 rc11 对 4290 份去重 PDF / 12577 页做过基础转换测试。本轮只复测上述 22 份实图，不能把历史结果算作 rc17 的全语料文字和比例验收。私有 PDF、截图、系统字体、外部字库和含本机路径的内部报告不随包分发。

## English

The final local macOS ARM64 / Python 3.12.13 source run passed **281 tests**, including 55 new regressions. All 52 ASCII letters were recovered from three real fonts through both stroked polygon and filled Bézier PDFs. Synthetic fonts exercise unified Han, extensions A–J and compatibility ranges through persisted DXF and TEXT; these are Unicode-path tests, not exhaustive real-glyph accuracy measurements.

The final runtime was rerun against **22 PDFs / 22 pages**: zero conversion failures, 238 recovered TEXT entities / 1035 characters, and zero saved-DXF audit errors/fixes. All outputs remain degraded; 13 pass the geometry gate, and nine calibrated sheets still exceed the dimension-error threshold. The external Songti catalog produced 44 isolated candidates and no published characters. Every DXF group pair matches rc16 except the two header GUIDs. Private drawings/fonts are excluded.

CI runs source and isolated installed-wheel tests on Ubuntu/Python 3.10 and 3.13, macOS/3.12 and Windows/3.12, together with build, metadata, dependency and public-content checks. Check the exact release target's CI run linked from its release notes; local results do not substitute for those runs. Successful export does not imply universal font recognition or engineering acceptance.
