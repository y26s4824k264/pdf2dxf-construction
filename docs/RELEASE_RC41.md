# rc41：填充笔画保留与矢量中文模板 / Filled ink and vector Han templates

## 修复

旧 nonzero 填充用“合并同向轮廓，再扣除反向轮廓”近似。当路径包含外框、孔洞、孔洞内笔画时，最后一次扣孔也会删除内部笔画。一处人工核对的“图”字在 PDF 有六条有效边界，旧 DXF 仅四条；按完整源路径绕数分类后恢复为六条，无新增或丢失填充面积。新实现对平面分区内每个面的代表点计算总绕数，nonzero 保留非零绕数，even-odd 保留奇数绕数；单个有效简单环仍走快速路径。不降低坐标精度、不简化轮廓。

同时修正矩形路径方向：此前忽略 PyMuPDF `re` 的 orientation，混合矩形与线段会得到错误绕数。其方向定义见 [PyMuPDF get_drawings](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_drawings)。PDF→DXF 阶段修复填充，文字确认阶段始终读取已保存的 DXF。

固定 56 像素指纹无法覆盖打印量化、重新采样和横向压缩的所有轮廓。新增可选 `.p2dvec`：从源字体实际 cmap 及 nonzero 填充边界构建 Unicode、em 外框、advance、完整归一化折线和检索描述子。运行时不访问 PDF、字体程序、图片或 OCR。

候选检索使用距离函数的 Lipschitz 界与完整半径查询，不截断成 top-k 后选“最像”。最终还要求轮廓嵌套关系相同、双向整条边界被误差缓冲覆盖、所有可行标签唯一。基本误差限为字形墨迹高度的 0.6%；仅纸面毫米 DXF 的全部有效顶点支持 600 DPI 栅格时允许有证据的量化预算，上限 2%。逐字报告实际误差、限值与栅格步长，不将其当工程比例或识别准确率。

完整来源绘制不可截取部首补字。连续绘制序列、同层、相近 em 尺寸/压缩比例、基线和 advance 还须一致；至少两行、每行至少五种不同汉字才能锁定字体，且只输出这些合格行。短行、缺笔、交叠、同形异字、竞争字库或不完整来源均保留几何。旧精确路径不放宽，新格式当前只支持汉字，英文仍用既有精确字库。

## 验证与边界

新增测试覆盖嵌套笔画、方向反转、相交/异向填充、自交、原路返回、真实 PDF→持久化 DXF 的笔画保留，以及合成字体的压缩/重采样、多行确认、同形异字、缺笔、来源断点、文件损坏、CLI 和幂等。外部字体文件移走后仍可仅用持久化模板恢复 TEXT。来源 DXF 图元按用户策略保留。

只选基础、梁、楼梯三类代表页；不重跑历史 PDF 全集。对应字体版本、完整来源、字高与量化误差仍影响恢复；零散候选不等于已确认文字，资源覆盖也不等于全图准确率。未确认的工程比例继续保持纸面坐标。客户 PDF、原始字体和外部 `.p2dfont` / `.p2dvec` 不进入源码发行和 wheel。

用户新提供的 CAD 字库包含不同字体版本；字体名称相同不证明字形相同。此次本机找到的另一版本字体可与已标注的内嵌子集逐字核验，但这只证明对应字形，不使未知正文全部自动正确。商业字体及其派生矢量字库不作为开源资源发布，使用者须自行提供有权使用的字体。

## English

The old nonzero approximation subtracted holes after unioning all exterior-direction paths, deleting ink islands inside holes. Resolve planar faces by the total winding of every original path, or winding parity for even-odd fills. Honor rectangle orientation when combining rectangles with other paths. A reviewed source glyph retains all six effective boundaries rather than the previous four. Precision is retained; no outline simplification is added.

Optional `.p2dvec` catalogs store actual cmap labels, canonical nonzero filled boundaries, layout metrics and validated numeric arrays. The existing exact matcher is retained. Runtime input remains persisted DXF; no PDF/font access, pixels, OCR, language model or semantic completion. Complete-radius retrieval, nesting topology, full bidirectional boundary coverage and unique labels precede layout checks. The default 0.6% ink-height error can increase only with verified saved paper-mm printer-grid evidence, capped at 2%, and is reported per glyph.

A font needs two independent source-contiguous rows, each with at least five distinct Han labels. Partial paints, ambiguous shapes, missing strokes and isolated short rows remain geometry. Vector recovery currently supports Han only; existing exact catalogs retain Latin support. Font coverage is not recognition accuracy. Only representative structural pages are checked; historical corpus results are not rerun. Private drawings, fonts and derived external catalogs are excluded from public distributions. Unconfirmed engineering scale remains explicit.
