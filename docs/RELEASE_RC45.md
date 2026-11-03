# rc45：重复字形复核和实测字距 / Repeat verification and measured tracking

## 拒绝原因

基础正文“采用国标图集”的“集”已通过完整数值字形的几何界和连续双向覆盖，但打印量化令第一档包络在临界处多出一个微小孔洞；逐笔分段又不同，rc44 因而继续保留轮廓。同页其他位置已有算法严格确认的该字，可作为额外的独立几何证据。

梁图“结构层高”的四个字本身均已匹配，实际排版却在字体默认字距之外增加了统一间距。旧规则只接受默认字距，不能将它们组为可信文字行；也不能为了输出整行而压缩字距或添加 Unicode 空格。

## 修复约束

- 只暂存通过完整数值字库几何界、连续双向覆盖、唯一 Unicode 标签且具有已验证打印格网的候选。几何超限、来源不完整、多个标签或候选过载均不能进入复核。
- 参考仅来自同页、同一已锁定字库此前严格确认的成行字形，排除单字锚定结果和本轮新恢复字。每字最多保留八个位置不重叠的参考，目标也不能与参考重叠；至少两个参考须分别在原误差限内通过完整逐笔、端点与双向覆盖对应。
- 新候选还须通过完整字体单元及重新组行校验。仅进行一次复核，不用新恢复结果自举或污染外部字库。报告记录目标和参考的来源句柄、来源编号、误差预算与确认方式。
- 统一附加字距只在字体已由普通多行锁定后验证，要求同层、来源连续、至少四种不同汉字，字号、字宽和基线一致；用全部墨迹框共同拟合字形尺度、起点和统一附加字距，再逐项检查残差。仅接受有界正字距，三个字、不规则间距、基线不符或未锁定字体均拒绝。
- 有附加字距的行按原始墨迹框分别输出每字纯 TEXT，报告保留整行字符值与实测间距；不插空格、不把字形拉宽填满间隔、不改动原图元。普通连排文字的旧规则保持。

运行时仍仅读取持久化 DXF 与数值字库，不读取字体或源 PDF，不使用 OCR、AI 或词义补字。既有字库无需重建。字体、派生资源及私有图纸不公开分发。

## 验证边界

新增真实打印格网的合成字形回归：两个独立参考的正例，以及单个参考、无参考、同位置重描、无种子的新候选互相支持、缺失笔画的负例。另验证统一/不规则字距、基线、短行和字体锁，保存后核对单字 TEXT 的字符值与插入位置。只回放基础、梁两张代表页保存 DXF，保留已有字符及原始几何并核对新增文字，不重跑历史 PDF 全集。

不满足独立几何或排版证据的内容继续保留轮廓，本版不代表任意字体或全文百分百恢复。工程比例仍需独立尺寸证据，两张代表页的未知比例状态保持。

## English

A printer-lattice perturbation can change an uncertainty envelope's hole count even when complete font geometry passes the unchanged distance budget. Recheck such uniquely labelled candidates only against at least two non-overlapping, previously strictly confirmed occurrences from the same locked numeric font catalog. Each reference must pass complete per-path/end-point correspondence at the original budget. New recoveries and singleton anchors never seed references; only one recheck is allowed. Preserve complete-source, font-cell and row checks, and record supporting source handles.

Some four-Han headings have deliberate uniform tracking. After independent ordinary rows have locked the font, fit the observed glyph bounds with separate font scale and tracking parameters, requiring four distinct labels, continuous same-layer source paints and consistent baseline/width/size. Reject short, irregular or unlocked rows. Emit each glyph as separate plain TEXT at its original ink bounds; never insert spaces or stretch glyphs across the measured gaps.

Runtime input remains saved DXF plus numeric templates, without font/PDF access, OCR or semantic completion. Existing catalogs remain compatible. Focused regression and the two representative saved drawings cover the change; no historical corpus rerun or universal accuracy claim is made. Unconfirmed text and engineering scale remain explicit.
