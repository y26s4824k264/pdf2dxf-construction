# rc48：旋转中文轮廓确认与原角度 TEXT

基础、梁主图中存在 90° 旋转中文。转正后的完整几何与已有 HZTXT 数值字库吻合；此前以水平轴建立字形和排版模型，旋转轮廓不能按该模型确认。局部回放已复现“顶标高”“抗震等级”等情况，不需要 OCR 或新字体。

## 证据与输出

- 只对 90°、180°、270° 作精确轴交换和符号变换，不任意拟合旋转、斜切或拉伸原始几何。原实体保持不变。
- 每字须满足完整来源、同层连续绘制、完整字体单元、打印格网、全部提供字库的 Unicode 唯一性，以及原有完整几何/拓扑误差界，字形到字库的上限仍为 2%。
- 每个目标还须与同页此前严格水平行中两个互不重叠的同字、同字库实例通过完整路径、端点及双向覆盖核对。按相近墨迹高度优先选择既有有限参照；缺笔、不同字、重复位置或其他页面不作支持。孤立补字、短标签及本轮旋转结果不能成为新参照。
- 转正行至少有三个不同汉字、一个模板含八条连接后笔画的复杂字，并通过同一尺度、基线和实际字距模型；不同方向或分段存在冲突时拒绝，不跨缺失来源补字。
- 用已有字形所对应的数值字库描述子建立完整半径预筛，不用 top-k 截断；预筛命中后仍由全部提供的描边字库检查歧义，不缩小最终字符候选集。
- 每字输出独立纯 TEXT。FIT 起终点、文字高度和 rotation 对应原墨迹框及方向，报告保留角度、来源、数值字库和独立参照。匹配轮廓默认保存在关闭的备份层，不推断未识别字符或插入空格。

运行时只读保存 DXF 和数值模板，不读源 PDF 或字体，不用 OCR、AI、语义或人工标签赋值。既有十三套字库兼容，无需重建；字体及派生模板仍为外部资源，不进入公开发行。

## 验证范围与限制

回归覆盖三种角度及输出保存回读、原始几何和幂等性；拒绝字体未锁定、独立参照不足、同位置重描、无打印格网、异页、缺笔、镜像、跨层、来源不完整、同形异字和字距异常。

仅在基础、梁两张代表页的已保存完整 DXF 上回放文字、比例校验、最终输出和回读，对照此前字符值与几何指纹及新增文字。源图局部截图仅用于人工核对，不参与识别；没有重新提取 PDF 或重跑历史全集。

此路线不会确认任意角度、未知字体、缺失来源或手写签名。未通过证据的内容继续保留轮廓，不能将恢复计数当作全文召回率或独立印刷字数。工程比例仍需可核对尺寸证据，纸面毫米不能直接作为工程毫米建模。

## English

Some main-plan Han outlines are quarter-turned. Their upright geometry matches the existing HZTXT numeric catalog; the previous horizontal cell/layout model could not admit them. Apply exact 90/180/270-degree coordinate turns for comparison only. Preserve complete original entities and the existing font error cap.

Every target needs a complete same-layer source, a verified printer lattice, a unique label across supplied stroke catalogs, and two spatially independent earlier strict upright occurrences of that character and font on the same page. Reuse the complete-path/endpoint/bidirectional-coverage verifier. Newly recovered, single-anchor and repeated-label glyphs never seed this pass. Require a coherent row of at least three distinct Han including a complex eight-stroke template, with no competing source segmentation or direction.

A complete radius prefilter searches only earlier known template labels for speed; every surviving window still undergoes the full supplied-font ambiguity check. Emit separate plain TEXT with original ink bounds, FIT endpoints, height and rotation, retaining source/reference evidence. No OCR, PDF/font reads at recognition time, semantic completion or inferred characters.

Only the foundation/beam representative saved DXFs are replayed. Preserve earlier labels, geometry and unresolved outlines. Arbitrary-angle text, handwriting and unknown engineering scale remain outside this verified route. Private drawings, fonts and numeric catalogs are excluded from public distributions.
