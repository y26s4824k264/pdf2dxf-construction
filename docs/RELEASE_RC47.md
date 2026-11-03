# rc47：零字高 SHX 与重复复杂短标注

## 原因与修复

主图小字“圆心”与用户字库的 GBCBIG 几何吻合，和原 HZTXT 是不同的字形。GBCBIG 的源定义为 `above=0, below=64, modes=2`，旧编译器拒绝零字高，不能生成其数值模板。源元数据本身异常，不能把 below 当实际字高来放大排版容差。

新编译器保留源 above/below，只在 above 为零且 below 为正时解释受限字形程序，再以完整可用汉字的墨迹高度中位数向上取整建立统一数值尺度。子集构建也扫描完整汉字集建立同一尺度；不依赖当前图纸或人工标签。记录 `height_policy=full_han_median_ink_height_v1`、参考字数及原始字段。非零字高字体保持原归一化、数组及标识兼容性；全零、非法或循环程序继续拒绝。中文字体名按已明确的 GBK 编码读取。该尺度仅用于字形模板，不是工程比例。

GBCBIG 数值字库包含 6,762 个可用汉字，一项退化字形仍跳过，不能把字库数量当作图纸识别率。原字体和派生字库仅在本机，不进入 GitHub/PyPI。

## 短标注确认

普通字体锁仍要求两行、每行五种不同汉字。只有两个不同汉字的标注不据此全局锁定字体。新增独立的标签确认：

- 每字须通过完整来源、同层连续绘制、完整字体单元、全字库 Unicode 唯一性、原有矢量几何和拓扑校验；所有观察顶点须证明既有纸面打印格网。
- 标签最多八字，至少两种不同汉字，至少一个字在观察与模板中均含八条完整连接后笔画；简单线段、偏旁或重复单字不能进入。
- 字形尺度、字宽、基线及相邻墨迹间隔必须一致。完整标签须出现在至少四个互不重叠的位置；同位置重描不算独立证据。
- 每个目标分别与另外三个独立位置比较全部对应字的逐笔、端点和双向覆盖，并核对整组归一化墨迹框及实际字距。字形到数值字库的原误差限（最高 2%）保持；两个已验证观察之间的比较使用两份误差界之和，并传播参考 X 缩放，报告记录此预算，不把它用于字库放行。不按词义选字，不跨缺失来源拼接，不推断未知字符。
- 只同时确认这组已通过数值模板的重复标签，不全局锁定新字体，不让它们作为其他识别路线的种子。超过六十四个同类候选时保守拒绝，报告记录目标及参考来源、误差限和排版残差。
- 每字按原墨迹框单独输出纯 TEXT，不用整词拉伸或插空格来补字距。

运行时输入仍为保存 DXF 与数值模板，不读取源 PDF 或字体，不用 OCR、AI 或语义补字。比例、拆框和建模继续使用统一 DXF 流程。

## 验证范围

新增回归覆盖零字高、全零拒绝、子集尺度一致、小单位字库的归一化不变和中文字体名，以及四处复杂短标签的正例；拒绝参考不足、同位置重描、字距异常、缺笔、无格网、同形异字及简单符号组合。保持旧短行不能锁定全字体的回归。

仅回放基础、梁两张代表页保存 DXF，核对旧字符值和指纹、原始图元、新文字及最终回读，不重新提取 PDF 或重跑历史全集。重叠绘制不增加独立支持数；恢复统计可以含原始重叠来源，不能视为独立印刷字数。未知字体、手写签名、未获确认的旋转字形等继续保留轮廓，不代表所有中文或任意字体恢复。工程比例仍需独立尺寸证据。

字段含义参考 [Autodesk Text Font Descriptions](https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-Customization/files/GUID-9BBE5B28-DF02-4EC5-863A-BA04AB6F5EF1.htm)；零字高行为与本包处理以实际源字节和完整字形几何为证，不假定原元数据正确。

## English

Some deployed GBCBIG fonts declare zero ascent. Preserve that provenance and derive a numeric normalization scale from the complete usable Han ink-height median, consistently across subset builds. Do not use the descent byte as typographic scale or infer engineering dimensions. Preserve existing nonzero-ascent catalogs and reject invalid or all-zero definitions.

Complex labels of two or more distinct Han can be verified at four independent locations without globally locking their font. Every glyph still needs complete, same-layer contiguous source paints, a verified printer lattice, a unique Unicode label across the supplied catalogs, and the unchanged full-geometry/topology budget. At least one glyph must have eight complete joined strokes in both observation and template. Compare every target with three spatially independent occurrences, checking full path/end-point correspondence and relative ink bounds/spacing. The mutual observation comparison propagates both independently verified font error bounds, including reference X rescaling; the original glyph-to-font cap remains 2%. Duplicate locations, incomplete strokes, aliases, inconsistent layouts, simple symbols and excessive candidate groups are rejected. These admissions never seed other recognition routes.

Emit separate plain TEXT at original ink bounds. Runtime reads saved DXF and numeric catalogs only, without OCR, font/PDF access or semantic completion. Only the foundation/beam representative saved drawings are replayed; preserve old labels, raw geometry, unresolved outlines and unknown engineering scale. Private fonts, catalogs and drawings are excluded from public distributions.
