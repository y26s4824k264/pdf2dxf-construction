# rc43：反向接笔和被分隔的单字 / Reversed joints and separated Han

基础图“幼”的原字形为五条笔画，PDF 将其中两条在共同末端反向合并。rc42 只统一正向首尾端点，因路径数不等而拒绝该字。现在仅在连续笔画端点坐标完全相同时允许反向连接；保留每条无向线段，不跨接真实间隙、不合并非连续笔画或内部交点。旧 rc42 字库仍核对其原始数组和摘要，在运行时以同一方式规范模板和观察路径，更新检索笔画数；无需重建既有资源。新构建资源声明 `exact_sequential_undirected_endpoint_v2`。

“年”“性”等字的笔画原本已匹配，但数字、标点或换行使它们成为单字片段，未达到 rc42 的两种不同汉字要求。本版仅为有独立局部证据的单字增加确认路径：字体仍需两行、每行五种不同汉字锁定；附近已确认文字行至少四种不同汉字，必须属于同层、同来源范围。用该行的实际横向尺度、纵向尺度和基线预测单字完整墨迹框，仍使用原有误差预算。

单字与确认行之间必须有真实、完整保存的来源绘制，全部位于有界间隔和文字高度范围内；来源绘制缺失、不同层、字号不符、基线不符、无局部行证据或模板歧义均拒绝。不以整数格假定数字或标点的字距，不给间隔赋 Unicode，不把间隔两侧强行合并成 TEXT。每个通过的单字保存字体、锚定行、来源序号、排版残差和预算证据。

运行时输入仍是持久化 DXF 与已编译数值字库，不读取源 PDF 或字体，不使用 OCR、AI 或语义补字。未确认轮廓继续保留。输出单字不代表整行文字完整，字库覆盖数不代表识别率。工程比例仍需独立尺寸证据；两张代表页保留未知比例状态。

新增回归覆盖四种接笔方向、旧字库兼容、被分隔单字的正例和字号/基线/来源缺失/错层/未锁定字体负例。代表图验证复用基础、梁两张已保存 DXF，重跑文字阶段并校验输出和回读，不重跑 PDF 历史全集。客户图纸、原始字体、派生字库均不公开分发。

## English

Consecutive SHX strokes may meet at either endpoint and be reversed when a PDF combines them. Normalize exact endpoint joints on both observed paths and templates, preserving every undirected segment. Never bridge a real gap or join nonconsecutive paths/interior intersections. Existing rc42 catalogs keep their original arrays and identities; runtime search uses normalized path counts. New resources declare the v2 joint policy.

An isolated Han candidate can be confirmed only after the usual two independent five-distinct-Han rows lock its font. A nearby verified row with four distinct Han supplies the actual X/Y scales and baseline. The complete glyph bounds must agree within the unchanged budget, with the same source scope and layer. Every intervening paint must be complete and inside the bounded visible gap; missing paints, incompatible sizes/baselines/layers, ambiguous templates or missing row evidence reject the candidate. Gap characters and spacing are never inferred, and separated TEXT entities remain separate. Reports retain explicit anchor and residual evidence.

Runtime recognition remains persisted-DXF geometry plus numeric font templates, without PDF/font access, OCR or semantic completion. Only the two representative saved drawings are replayed; this is not a historical-corpus rerun or a claim of complete text recovery. Engineering scale remains independently gated. Private drawings/fonts/catalogs are excluded from public distributions.
