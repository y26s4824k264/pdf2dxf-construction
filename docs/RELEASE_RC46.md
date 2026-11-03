# rc46：孤立汉字的独立几何复核 / Independent isolated Han verification

## 匹配失败原因

“板、梁、柱”等表格单元格的完整字形已经通过数值字库几何匹配，但既有孤立字确认要求邻近正文行、共同基线和有界来源间隔。表格标题与正文处于不同位置、图层或字号，无法借用这条行锚定规则。不能通过猜测表格含义给字赋值，也不能把孤立偏旁或图形线段当成完整字。

## 修复边界

- 保留完整来源、连续来源编号、单字内部同层、完整字体单元、完整线网误差界、双向覆盖及 Unicode 唯一性校验。已有行锚定和普通文字行规则不变。
- 新的孤立字复核只在字体已由至少两条、每条五种不同汉字的普通行锁定后使用；候选须由全部顶点证明既有纸面打印格网，且只有一套已锁定的候选字库。
- 同一来源、同一页、同一数值字库，至少两个此前严格确认的同字字形须与目标位置相互独立，分别在原误差限内通过完整逐笔、端点和双向覆盖对应。每字最多八个参考；同位置重描不算两个参考。参考可来自其他图层或字号，目标字的所有来源绘制仍须同层完整。
- 不使用单字锚定、新恢复的交叉笔画字、拉开字距的行或本轮新恢复孤立字作为参考，不递归自举。字形缺失、同形异字、无字体锁、无打印格网、跨页参考、仅一个独立参考均不能放行。
- 按目标原始墨迹框和数值字库度量输出单字纯 TEXT；不与附近文字拼接、不插空格、不改原图元。报告保存来源句柄、来源编号、参考来源、几何误差、格网、字形放置和目标图层。

运行时只读持久化 DXF 与数值字库，不读取字体或源 PDF，不使用 OCR、AI 或词义补字。现有十二套字库无需重建，原字体、派生字库和客户图纸不随开源包分发。

## 验证

合成保存 DXF 回归覆盖跨图层、不同字号的完整孤立字恢复及保存后 TEXT 位置；负例覆盖参考不足、未确认孤立字互相支持、同位置重描、缺笔、无格网、字内混层、跨页、无字体锁和同形异字。只回放基础、梁两张代表页的保存 DXF，核对原字符、原始几何、新增字和最终保存回读，不重跑历史 PDF 全集。

孤立字不能凭名称或字库包含该字自动确认。不满足独立几何证据的内容继续保留轮廓；这不是任意字体或全文百分百恢复结论。工程比例仍需独立尺寸证据，未确认状态保持。

## English

Complete Han shapes in separate table cells can match their numeric font while failing the existing local-row anchor's baseline, layer or source-gap constraints. After ordinary multi-row evidence has locked the font, confirm an isolated, uniquely labelled, printer-lattice-verified complete glyph only against at least two spatially independent, previously strict row occurrences from the same source page and numeric catalog. Reference layers and sizes may differ; every paint within the target must remain complete, source-contiguous and on one layer. Use the unchanged full-geometry budget and complete per-path/end-point correspondence.

Only one locked candidate catalog may support the new route. Duplicate positions, insufficient references, missing strokes, Unicode aliases, missing lattice evidence and cross-page references are rejected. Newly recovered, row-anchored, spaced-row and topology-rechecked glyphs never seed the new route. Emit a separate plain TEXT at the target ink bounds and record its geometric provenance. Existing catalogs remain compatible; no OCR, AI, semantic completion or direct PDF recognition is introduced.

Regression covers acceptance and refusal cases, followed by only the two representative saved-DXF replays. Preserve all prior labels and original geometry, retain unresolved outlines and unknown engineering scale, and make no corpus-wide or universal-font accuracy claim.
