# rc33 验证记录 / Validation

版本 `2.0.0rc33`，本地 macOS ARM64 / Python 3.12.13。源码 **696 项通过**，新增 5 项回归。安装 wheel 和精确提交 CI 在发布时另行核验；最新结果见发行记录。[逐项证据](FONT_CATALOG_LOADING_VALIDATION.json)保留本轮完整测量和对照结果。

## 字库加载

单次加载内只计算一次每条模板的 NFKC 字符映射，各索引共享结果。实际 cmap 的原始轮廓优先，缺失的标签才使用首个别名。汉字分类改用排序区间边界的二分查询，覆盖统计使用等价的 NumPy 区间计数。全部哈希、元数据、轮廓摘要、歧义和覆盖计数校验继续执行；字库格式和资源字节不变，没有持久缓存或跳过校验。

| 七轮交替独立进程测量 | rc32 | rc33 |
| --- | --- | --- |
| 十字库完整加载中位耗时 | 2.367754 秒 | 2.228805 秒 |
| 进程峰值 RSS 中位数 | 900.2 MiB | 872.3 MiB |

加载中位耗时减少 **5.9%**，峰值内存中位数减少 **27.9 MiB**。这是本机这一工作量的观察结果，不是所有平台、PDF 或识别阶段均有相同提速。计时包括正常校验和全部索引构建，排除资源清单发现和逐字段摘要审计；GC 保持启用，使用相同十个 r2 文件、交替启动全新进程。每条原始/填充 mask、digest、lookup 值、别名映射、模板对象引用及其余 dataclass 字段均对照一致，共 **246,293 条模板、2,288,068 个索引键**。

新增测试遍历全部 **1,114,112 个 Unicode 码点**，证明汉字区间分类与原约定完全相同，包含间隙、相邻边界、兼容区、代理码点和扩展 J 端点。其余测试检查别名排在实际码点前时的 raw/fill 优先级，以及错误的汉字覆盖计数仍被拒绝。码点分类校验不代表能识别全部码点或任意字体。

## 识别和保存结果

| 本轮实际执行范围 | 结果与 rc32 的关系 |
| --- | --- |
| 十字库、84 个保存短行 DXF | 69/84 完整、1255 字，全部识别字段与图元一致 |
| 十字库、16 个保存长行 DXF | 16/16 完整、2320 字，全部识别字段与图元一致 |
| 2 个 193 字原字体 PDF 重新转换 | 描边/填充共 386 字，正常资源加载，保存结果一致 |
| 2 张本机 PDF 图纸重新转换 | 1 ok、1 degraded，文字、几何与比例门槛结果一致 |

100 个 DXF 重新执行轮廓恢复，对比整个识别报告、整个实体库（仅经核验的写入时间可变）和全部原图元。四个 PDF 通过 Converter 重新转换，同一输入 SHA256、同一请求，核对全部识别字段（仅运行时间可变）、全部 DXF 组码（仅两个 HEADER GUID 可变），并再次验证保存产物摘要、尺寸数量与误差。两张本机图纸的外部字体锁和新增轮廓文字仍为 0，未通过门槛的图纸仍待复核。

安装包另从源码目录之外重新转换同样四个 PDF，并核对父进程、子进程均加载 site-packages，防止工作目录使安装版意外调用源码。该项在发布前与最终源码逐字段及逐组码对齐；不是新增四个不同样本。

本轮没有增加识别率。短行仍有 15 个不完整样例：14 个无独立字体锁，1 个存在较大的内部标点竞争。未知文字保留轮廓，未知或冲突比例继续明确报告；没有新增 OCR、近似匹配、猜字或门槛放宽。r2 字库无需重下。

历史 **4290 份 /12577 页**、原 BIM22、84 个对应字体 PDF 和 rc32 的其余 10 个新增语料页均未重跑。rc32 的 94 份 /155 页内容检查和 12 页转换是历史证据，见[rc32 记录](LONG_ROW_WINDOW_VALIDATION.json)。本轮 100 个 DXF 不能计作 100 次 PDF 转换。

全库 Ruff 仍报告 29 条 rc32 已有问题，涉及未改动文件，已与 rc32 原文件及完整诊断逐条核对；本次改动运行时和测试文件通过 Ruff。五条已有测试弃用警告来自 PyMuPDF SWIG。私有 PDF、原字体、文件名和完整路径不进入公开包。

## English

All **696 source tests pass**, including five new Unicode/alias/count regressions. Reusing one NFKC mapping per template, binary Han-range classification and vectorized coverage counting retain every loader check and raw/fill/cmap priority. Seven alternating fresh processes with GC enabled load the same ten r2 catalogs: median time **2.368→2.229 s**, median peak RSS **900.2→872.3 MiB**. Every dataclass field, mask, digest, lookup value and alias/template reference matches rc32 across 246,293 templates and 2,288,068 keys. This local workload is not a universal speed guarantee.

Fresh recognition of **100 saved DXFs** preserves complete reports and entity data: short84 remains **69 complete /1255 characters**, long16 remains **16 complete /2320 characters**. Four actual PDF reconversions use normal resource loading and original hashes: two open-font PDFs recover 386 characters; two private drawing pages retain one pass and one degraded scale result. Saved reports, group-code pairs and dimension checks match rc32. The source-free installed wheel reconverts the same four inputs before publication and is compared with final source; it adds no new sample coverage.

Every Unicode codepoint is checked for unchanged Han-range classification, not recognition coverage. Fifteen short cases remain incomplete and both private drawings lack an external font lock. Historical4290, BIM22, matching-face84 and the other ten rc32 additional corpus pages are not rerun. Reuse unchanged r2 fonts. Full-tree Ruff retains 29 verified pre-existing findings in unchanged files; changed files pass. Private source files and paths are excluded. See the [complete evidence](FONT_CATALOG_LOADING_VALIDATION.json).
