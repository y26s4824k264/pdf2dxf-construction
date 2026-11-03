# rc42：SHX 正文单线字形 / SHX stroke Han

## 原因与修复

基础、梁图的说明文字是多笔开放 SHX 描边，标题中的宋体则是闭合填充。rc41 的新增矢量路径只处理 HATCH，既有固定像素指纹也不能覆盖这些量化后的开放笔画，因此增加宋体模板并不能恢复这类正文。

从本机提供的字库识别出相符的 HZTXT 字形程序。三个独立人工核对字符的笔数分别为 5、3、11，边界误差均低于墨迹高度 0.6%；公开发行不包含客户图纸、原始字体或它们的派生矢量资源。构建器读取基础 `AutoCAD-86 bigfont 1.0`，要求明确指定 GBK；按严格双字节往返映射取得 Unicode，直接执行有界字形程序，保留原始 em 外框、字距和笔画，不以文件名猜字。

两个连续笔段在提笔处完全共端点时，PDF 可能将其记成一笔。模板和观察路径只统一这种零长度提笔，全部线段和原始坐标保留；真实端点间隙绝不连接。原 DXF 仍保留原实体，只增加 TEXT 或按用户策略关闭备份层。

候选用完整半径检索而非 top-k 选最像，要求唯一标签、完整来源绘制、每一笔端点与整条路径双向覆盖。内含部件不能遗漏同一字体单元中的相邻笔画。源序连续和同层是组行前提；有分支或重叠竞争的排版解释继续拒绝。字体仍须至少两行、每行至少五种不同汉字确认，确认后可接受至少两种不同汉字的完整短片段。孤立字不因此自动通过。

用整行全部字框拟合一个横向尺度、一个纵向尺度和基线，再逐项核对残差，避免逐字比例的像素误差累积；不增加 tracking、不插入空格、不补未知字符。已核对的字体排版还用于组行，不再因“工”等字的墨迹较矮而误拆。基本笔画边界限值仍为 0.6%；仅全部观察顶点支持纸面 600 DPI 栅格时允许欧氏距离所需的像素对角线预算，上限仍为 2%。

完整转换测试还发现来源编号 `0` 被 `or -1` 错误改写，导致第一笔来源序列断裂。两个图形内核现在保留真实的零编号，缺失编号才使用 -1。

SHX 大字型和双字节编号的定义见 [Autodesk Big Font 文档](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-Customization/files/GUID-DE0CCC57-AC55-4CDC-887E-730FC90364E4.htm)。本版不支持扩展 `7,0` 子字形，也不自动推断 Shift-JIS、Big5 或其他编码。构建报告保留跳过项；本机选中的字库包含 6,763 个可用汉字程序，不代表任何图纸或所有字体的识别率。

## 验证边界

新增回归覆盖合成 SHX 二进制、明确编码、编译后删除字体、完整无文本层 PDF→DXF→TEXT、零长度提笔、真实间隙、同形异字、短行不得建立字体锁、损坏记录、循环子字形、资源契约、CLI 和幂等；闭合填充与旧精确路径继续回归。

只选基础、梁两张代表页进行转换与段落核对，不重跑历史全集。不支持的数字/标点、未知字体、同形冲突和孤立字符继续保留几何；新路径不是全图全文恢复。工程比例仍需独立尺寸证据，新增中文不得用来猜测工程尺寸。具体运行结果与源摘要保存在本机检查报告中，不随发行附上私有图纸。

## English

The representative body notes use multiple open SHX strokes, while the previously identified title font uses closed filled outlines. The fill-only fallback cannot recognize the former. Compile basic bigfont programs with explicit GBK labels, bounded records/subshape expansion and actual font advances. Runtime input remains saved DXF plus persisted numeric templates; no font/PDF access, OCR or semantic completion.

Normalize exactly coincident consecutive pen endpoints without dropping segments or bridging real gaps. Require complete source paints and font cells, unique complete-radius labels, per-stroke bidirectional coverage and coherent source-contiguous rows. Two independent rows with five distinct Han labels confirm the font; subsequent short rows need two distinct labels. Branching and conflicting interpretations remain unresolved.

Fit one affine placement to all ink bounds of a row, with no additional tracking or inferred spaces, and use the verified layout to group short-ink characters. A verified paper-mm printer lattice permits a bounded Euclidean diagonal allowance, retaining the 2% cap. Preserve actual source sequence zero in both kernels. Original DXF geometry remains available according to the chosen preservation policy.

Only two representative pages are checked. Supported-font coverage is not universal recognition accuracy; unsupported encodings/extended subshapes, unknown fonts, isolated characters, ambiguous glyphs and unsupported symbols remain geometry. Engineering scale still needs independent evidence. External fonts, derived catalogs and private drawings are excluded from public distributions.
