# rc50：旋转单字与双字标注

## 原因与修复

基础图的部分“梁、标、高”和梁图“级”已通过完整数值字库、同页两处此前严格确认的独立参照及逐笔双向覆盖，但未形成至少三个不同汉字的连续排版行。原旋转路线将它们一并拒绝；这不是字库只有 2% 的识别率，也不是需要提高字形误差上限。

保留三字及更长行的既有规则，新增有限的短标注确认：

- 每字仍需同页已锁定字库、完整且连续的同层来源、打印格网、原字库几何误差界、完整字体单元及至少两处此前严格行确认的空间独立参照。新补字、短标签或旋转结果不能反向成为参照。
- 单字和双字分别在 0/90/180/270 度搜索全部所供描边字库；字符及方向必须唯一。不因另一字符未在参照行出现而忽略它，也不忽略拓扑仍待独立确认的竞争候选。搜索过载和任何竞争均保守拒绝。
- 单字不得与同方向其他已支持候选相接或重叠，避免将失败文字行或竞争分段当作孤立文字。双字须有两个不同汉字，排版尺度、基线和字距一致，且至少一个字满足既有复杂笔画门槛。
- 每字仍按实际墨迹位置、角度和 FIT 范围分别输出纯 TEXT。字形到数值字库的原误差预算不变（基准 0.6%，只有确认打印格网时可动态到最高 2% 墨迹高度）；参照比较继续独立传播双方预算，不能回流放宽字库匹配。

报告新增 `font_stroke_rotated_short_glyph_matches` 计数，行证据的 `orientation_policy` 区分全字库四方向唯一性与已有三种字符行排版证明。原数值字库无需重建，原始图元完整保留在关闭的 `PDF_OUTLINE_BACKUP` 图层。

运行识别只读保存 DXF 与数值字库，不用 OCR、AI、PDF 像素、外部字体读取或语义补字。源图局部图像仅用于人工核对新增位置，不参与赋值。

## 验证范围

新增回归使用真实数值字库与保存 DXF，覆盖三个旋转方向的单字、复杂双字，以及参照不足、同位置重描、异页、缺笔、来源缺失、无格网、同形异字、异向异字、附加笔画和不一致字距。另用真实打印格网与重新分段的窄环构造严格候选和不同 Unicode 的拓扑待确认候选，验证短标注不能忽略后者。

只回放基础、梁两张代表页的完整保存 DXF，对比 rc49 的字值与字形指纹、可核对的原始几何、最终 TEXT 位置和方向以及保存后审计；不重跑历史全集，也不重新提取 PDF。

未确认的斜向字形、缺少独立参照或未满足完整几何的文字继续保留轮廓。新增数量不是全文召回率；工程比例仍须独立尺寸证据，纸面毫米不可直接作为工程毫米建模。

## English

Some complete foundation and beam glyphs already pass their numeric-font geometry and two independent earlier strict observations, but the quarter-turn route previously required a coherent row of at least three distinct Han. Add bounded single- and two-character admissions without changing the original glyph-to-font budget.

Short labels must have exactly one character/orientation interpretation across all supplied stroke fonts and all four quarter turns, including unseeded labels and topology-deferred rivals. Retain complete same-layer provenance, a verified printer lattice, a locked font, full path correspondence, complete cells and two spatially independent earlier strict references. Isolated candidates cannot touch competing supported spans. Two-character rows require distinct labels, coherent measured layout and an existing complex-glyph proof. Recovered glyphs never seed further decisions.

Keep long-row behavior, original geometry, ink bounds, rotation and separate plain TEXT output compatible. Runtime reads saved DXF and numeric catalogs only, without OCR, source PDF/font access or semantic completion. Regression checks cover valid orientations and adversarial geometry/provenance/reference/layout cases, including a real printer-rounded topology-deferred Unicode rival. Only the foundation/beam representative saved DXFs are replayed, preserving previous labels and raw geometry. Unresolved outlines and unknown engineering scale remain explicit; these results do not establish corpus-wide recall or engineering acceptance.
