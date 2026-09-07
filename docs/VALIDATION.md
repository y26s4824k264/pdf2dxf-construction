# rc25 验证记录 / Validation

版本：`2.0.0rc25`。本地环境：macOS ARM64 / Python 3.12.13。

## 字库加载优化

本轮仅优化 `.p2dfont` 加载与索引构建：大多数无歧义匹配键共享不可变标签元组，只为实际冲突积累集合并最终排序；每行二进制摘要一次解包，保留完整 16 字节及首次出现顺序；歧义检查按需遍历摘要，不再提前展开整行键。保留 ZIP 文件集合、大小、SHA256、数据集摘要、NPY 形状、字库身份、Unicode、拓扑、别名和歧义计数的全部校验。

| 同时加载十个 r2 字库 | rc24 | rc25 |
| --- | ---: | ---: |
| 中位加载耗时 | 5.759 秒 | 2.311 秒 |
| 进程峰值 RSS 中位数 | 1,097,023,488 字节 | 888,520,704 字节 |
| 模板表示 | 246,293 | 246,293 |
| 匹配键 | 2,288,068 | 2,288,068 |

三轮交替运行，每次使用独立 Python 进程并同时保留十个字库。计时只包括 `load_font_catalog`，指纹核对在计时与内存采样之后；操作系统文件缓存已预热。加载耗时约减少 **60%**，进程峰值 RSS 约减少 **19%**。这是同一台机器上的字库加载对照，不是 PDF 全流程提速，也不是所有机器的性能保证。

六次运行的所有字库字段逐项指纹一致，包括模板顺序、字节摘要/掩码、拓扑、别名映射、模板引用、匹配键顺序与完整冲突标签、宽高比索引及歧义计数。10 个输入字库 SHA256 与公开 r2 清单一致。原始测量和逐项记录见 [CATALOG_LOADING.json](CATALOG_LOADING.json)。

## 回归证据

新增 **8 项兼容性检查**，在冻结 rc24 加载器与 rc25 上均通过：v1/v2、1/3/32 个摘要变体、首尾和内部 NUL 字节、去重与顺序、拓扑、规范掩码缺失拒绝，以及大量同形标签与单码位 NFKC 别名。原有篡改、格式和轮廓恢复用例继续运行。全量源码 **424 项通过**；修改模块和新增测试的 Ruff 检查通过。安装包与精确提交的 CI 结果另见本版本发行记录。

84 个保存 DXF 副本使用新加载器读取全部十个字库后重新识别，与 rc24 比较**每个识别报告字段、全部实体库标签和句柄**。仅排除已检查格式的 `EZDXF_META/WRITTEN_BY_EZDXF` 保存时间；原图元、文字、块、样式和资源引用均一致。结果仍为 **70 个完整、14 个部分或未确认，1275 个发布字符**；十字体的 **20 个大小写 52 字母描边/填充样例全部完整**。保存 DXF 审计错误和修复均为 0。

以上 84 个用例缓存了已校验字库对象，属于保存 DXF 的识别回归。另取三个英文字体及扩展 J 的描边/填充 PDF，共 **8 个样例**，通过正常无缓存资源加载重新执行 PDF→DXF→TEXT，全部完整恢复。该入口也用于隔离 wheel 验证；发行记录明确列出完成结果。运行时继续只从持久化 DXF 和字库恢复文字，不使用 OCR 或原字体文件。

## 保留的历史结果与限制

- **rc24 对应字体 PDF：82/84 完整**，两个 Jigmo 样例仍有完整汉字轮廓竞争。本轮未重新转换这 84 个 PDF；本轮 84-DXF 对照使用组合字库，二者不能混为一次测试。
- **rc24 BIM：22 PDF / 22 页**均产出 DXF，仍全部 `degraded`；238 TEXT / 1035 字符，0 外部字库发布字符。比例状态为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 为 13/22。九份已标定图仍超出 0.2% 尺寸误差门槛。本轮未重跑该批次，几何和比例算法未修改。原有摘要保留 rc24 标记：[validation.json](validation.json)。
- 历史 rc11 的 **4290 份去重 PDF / 12577 页**仅代表当时的基础转换测试，本轮未重跑。
- 十字库的 **14 个汉字样例**仍部分或未确认。定向 20 pt 样例不能证明任意字体、字号、字重或 IVS 异体序列的准确率。模板覆盖不等于文字识别成功，产出 DXF 不等于工程验收通过。

## 分发

两个 r2 ZIP 的字节及 SHA256 不变，包含 245,496 个原始模板和 797 个填充表示。无需重新下载或重建。主源码、wheel、sdist 排除私有 PDF/DXF、外部字体/字库和个人路径；独立资源包保留原许可。

CI 验证 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码、构建、元数据、分发内容、依赖和隔离安装包。上述真实字库性能与实图回归为本地验证，不代表所有 CI 平台均运行这批资源。五条 DeprecationWarning 来自 PyMuPDF SWIG。

## English

rc25 reduces temporary index allocations, decodes each digest row in one operation, and checks ambiguity without eagerly materializing all match keys. Unique keys share immutable label tuples; actual conflicts retain set accumulation and a final sort. All archive, hash, shape, identity, Unicode, topology, alias and ambiguity validations are retained, including v1 compatibility.

Three alternating fresh-process trials on one macOS ARM64 host measured ten-catalog loading at a median **5.759→2.311 seconds**, with median process peak RSS **1,097,023,488→888,520,704 bytes**: about **60% less loading time and 19% lower peak RSS**. All catalogs remain resident together. OS file caches are warm; fingerprinting occurs after timing/RSS sampling. These are local loader measurements, not end-to-end PDF or cross-platform performance claims.

Every catalog field, all **246,293 templates and 2,288,068 lookup keys**, their iteration order, masks/digests, template references, normalization and ambiguity indexes match rc24 across all six runs. Input hashes match the r2 release manifests. [Raw measurements and regression data](CATALOG_LOADING.json) are published.

Eight new characterization tests pass on both the frozen rc24 loader and rc25, covering legacy/current schemas, 1/3/32 variants, opaque NUL-containing digests, ordering/deduplication, topology, canonical-mask rejection and many Unicode label collisions. The source suite passes **424 tests**; scoped Ruff passes. Isolated-wheel and exact-commit CI results are recorded in the release.

All **84 saved-DXF recognition reports** match rc24 in every field. Every entitydb tag and handle also matches, except the validated ezdxf writer timestamp. Geometry, recovered text, blocks, styles and references are preserved. Results remain **70 complete / 14 partial or unconfirmed**, with **1275 published characters** and all **20 English alphabet probes** complete; audits report zero errors/fixes. These runs reuse validated catalog objects. Eight additional normal-loading PDF conversions cover three Latin faces and Extension J in both stroke/fill pipelines; all complete. The same entry point is used for isolated-wheel verification.

The **82/84 matching-face PDFs and 22 BIM PDFs** retain their explicitly versioned **rc24** evidence and were not rerun in rc25. All 22 BIM drawings were degraded; nine calibrated sheets exceeded the 0.2% dimension-error gate. The historical 4290-PDF corpus was not rerun. No geometry, scale, recognition threshold or font-resource change is included. Remaining ambiguity is preserved as geometry. Reuse the existing r2 bundles; main distributions exclude private drawings and external font resources.
