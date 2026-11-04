# rc49：独立字形比较的误差传播

基础图仍有“梁”“顶”等轮廓，目标和同页已确认参照分别通过了 HZTXT 数值字库的完整几何校验，彼此逐笔比较却失败。此前的独立参照检查仅使用目标一侧的字库误差限，遗漏参照自身的打印量化误差。两个各自合格的观察，其相互偏差可以大于任一单独观察的误差界。

## 修复

每个目标到数值字库的边界、完整路径和拓扑校验保持不变，最高误差仍为字形墨迹高度的 2%；未通过该门槛的几何不能靠参照放行。两份已通过各自字库校验的观察，逐笔比较使用目标误差界加上传播到目标坐标系的参照误差界，并保留已有浮点裕量。

比较中的 X 归一化随两份观察的墨迹宽高比变化。参照字形的宽高比从实际路径计算：旋转确认会临时变换参照的位置框以判断空间独立性，其路径仍保持水平，不能拿该位置框代替路径宽高比。

仍须有两个互不重叠、此前严格行确认的同字及同字库参照；新补字、单字锚点、短标签和旋转确认不能自举为新参照。八个独立参照的上限、来源完整性、字体锁定、Unicode 歧义、打印格网及各路线排版门槛均保持。逐笔匹配继续核对路径数量、闭合性、端点、全部线段的双向覆盖及空间独立性，不只看轮廓采样距离。

证据记录 `pair_error_policy`、每个参照的原字库误差界 `reference_font_error_limits`，以及对应的相互比较限 `glyph_pair_error_limits`。这些比较限不回流到数值字库搜索，不改变字库身份、字符、模板或原始图元。已有十三套字库无需重建。

运行时仍只读保存 DXF 和数值字库，按原位置、方向输出纯 TEXT，不用 OCR、AI、源 PDF 像素、外部字体读取或语义补字。

## 验证范围

新增反例使用真实数值字库与保存 DXF：两份参照的内部笔画各偏移一个打印像素，目标反向偏移一个像素。每份观察均在原字库预算内，目标与参照的差异超过旧单侧限。修复后恢复目标，同时验证参照 X 缩放；缺笔、字库预算超限、参照不足、同位置重描和同形异字仍被拒绝。

只回放基础、梁两张代表页的已保存完整 DXF，检查旧字值及指纹、可核对原始几何、新增文字、位置/角度及最终保存回读。源图局部渲染仅作人工核对，不给运行时字符赋值；不重新提取 PDF 或重跑历史全集。

未满足完整几何或独立证据的轮廓继续保留；恢复数量不代表任意字体或全文召回率。工程比例仍须独立尺寸证据，纸面毫米不可直接视作工程毫米建模。

## English

Some remaining glyphs independently pass the numeric font geometry check but fail comparison with earlier confirmed observations. The previous independent-reference check used only the target's font bound, omitting reference uncertainty. Propagate both independently verified bounds, including reference X rescaling into target coordinates. Derive reference aspect from its actual upright paths; quarter-turn matching temporarily rotates position bounds solely for spatial-independence checks.

Keep the original glyph-to-font cap, at most 2% of observed ink height, unchanged. Pair limits never feed into font search. Continue requiring complete source, unique Unicode, locked fonts, printer evidence and the applicable layout gates, with two spatially independent earlier strict references and the existing eight-reference cap. Recovered or unconfirmed glyphs never bootstrap new references. Full path, endpoint, closure and bidirectional-coverage checks remain mandatory.

Record each reference font limit and the applied mutual-observation limit. Keep existing catalogs, source geometry and TEXT placement compatible. Runtime reads only saved DXF and numeric catalogs, without OCR, PDF/font reads or semantic completion. Only the foundation/beam representative saved DXFs are replayed; retain unresolved outlines and unknown engineering scale.
