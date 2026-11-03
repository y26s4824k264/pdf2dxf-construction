# rc44：交叉笔画重分段 / Repartitioned crossing strokes

“层”的整幅线网与原字形边界相符，但 PDF 在交叉处将一笔的尾段移到了另一条路径。路径数甚至可以相同，逐笔端点对应仍会失败；其他重分段还会改变路径数。字形识别不能将这种绘制路径划分当作字符身份。

## 匹配约束

- 所有候选仍须通过原有完整线网 Hausdorff 界和连续双向覆盖，误差预算不变：通常为墨迹高度的 0.6%，仅观察顶点证实纸面 600 DPI 格网时使用既有有界量化预算，上限 2%。
- 保留原有逐笔端点与完整路径对应校验。其失败时，才比较完整线网在一倍、两倍误差半径下的矢量包络拓扑：连接分量数及各分量孔洞数都须一致。两倍包络只用于拓扑核对，不扩大原始线网的几何误差界，不修改或重绘 DXF。
- 单线字库检索覆盖所有数值模板，不以路径数过滤竞争字符。相同线网、不同分段方式不能隐藏另一个 Unicode；多个标签或候选超限均拒绝，不使用 top-k 猜字。
- 来源绘制必须完整，同层、来源连续、完整字体单元、多行字库锁定及排版校验保持。扫描窗口允许至多两倍源字体标称笔画数、最多 128 个来源实体，单字最大范围、点数和路径数限制保持；超过限制的内容保留几何。
- 原始字体、PDF 和 OCR 不参与运行时文字确认。旧 rc42/rc43 数值字库无需重建；字体及派生资源不随主包公开分发。

包络连接状态可能因像素误差发生跳变，因此没有用新包络规则替换已验证的严格逐笔规则。二者是同一完整几何误差门槛之后的两种确认方式。填充轮廓的既有拓扑路径保持不变。

## 验证范围

新增回归覆盖交叉处改道、不同路径数、隐藏的同形异字、缺失分支拒绝、连接分量和孔洞，以及无文本层合成 PDF 经公开 Converter 保存 DXF 后恢复 TEXT。基础、梁两张代表页复用已保存的 DXF，回放文字、校准、最终输出与回读；不重跑历史 PDF 全集。新增字仍需逐处对照源图，保留已有字形证据和原始图元。

未知字体、模糊或未满足完整来源/排版证据的候选继续保留轮廓；本版不代表全文恢复或百分百准确率。工程比例仍由独立尺寸证据决定，两张代表页继续明确标记未知比例。

## English

PDF may repartition a stroke at a crossing, moving its tail to another path even when the path count stays unchanged. Keep the complete-network Hausdorff bound and continuous bidirectional coverage. Retain strict per-path validation; if it fails, require matching connected components and per-component hole counts in vector uncertainty envelopes at one and two times the existing error budget. The wider envelope is only a topology check, never an increased geometry tolerance or a change to saved DXF.

Search every stroke template, independently of path count, so repartitioning cannot hide a competing Unicode label. Ambiguous or overloaded results remain geometry. Complete-source, font-cell, independent font-lock and row-placement requirements remain in force. Existing numeric catalogs remain compatible; runtime has no font/PDF access, OCR or semantic completion.

Regression cases include rerouting, changed path counts, hidden aliases, missing branches, network topology and text-free synthetic PDF conversion through the public API. Only the two representative saved DXFs are replayed and read back, without a historical corpus rerun. Unknown text and unconfirmed engineering scale remain explicit.
