# 字符支持 / Character support

rc17 补齐纯英文和扩展汉字的轮廓识别通路。它仍然是 DXF 字形几何匹配，不调用 OCR 或语言模型。

| 字符 | 字库构建与输出 |
| --- | --- |
| A–Z、a–z | 全部 52 个字母可构建和匹配，输出保留大小写；纯英文可独立锁定字体 |
| 汉字基本区、扩展 A–J | 使用 Unicode 17.0 区段；补充平面汉字与基本区使用同一套识别和输出检查 |
| 兼容汉字、全角字符 | 使用既有的单码位 NFKC 标准化；不是逐码位保留原兼容写法 |
| 中英混排 | 同一字库的精确匹配允许大小写字高差异；不根据上下文补猜未知字符 |
| 数字与标点 | 字库可包含，但它们不能作为纯英文字体锁定证据；尺寸仍需独立几何验证 |

```sh
pdf2dxf font-catalog build /path/to/font.ttf --charset english -o latin.p2dfont
pdf2dxf font-catalog build /path/to/cjk.ttf --charset chinese -o cjk.p2dfont
pdf2dxf font-catalog inspect latin.p2dfont
pdf2dxf font-catalog inspect cjk.p2dfont
pdf2dxf convert input.pdf -o output.dxf --outline-chinese required \
  --outline-font-catalog latin.p2dfont --outline-font-catalog cjk.p2dfont
```

`chinese` 已包含可打印 ASCII；同一中英文字体通常只需构建一个字库。`english_letters` 报告大写、小写、缺字与已映射数量；`han_range_coverage` 报告各汉字区段的已映射数量。这些是字体覆盖统计，不能当成某张图纸的识别准确率。`--outline-chinese` 参数名为兼容既有调用保留，现也控制英文与中英混排轮廓恢复。

字体锁定要求同一连续片段至少三个不同汉字或四个不同英文字母（忽略大小写计数），也可使用三个已审核汉字锚点。掩码和拓扑必须精确匹配，宽高比须通过逐候选检查。存在多个可行标签时继续保留几何，不选择最像的字。锁定后的英文/混排片段至少含两个字母或汉字；孤立单字不因此自动确认。

纯填充 PDF 字形先持久化为 DXF HATCH，再读取其闭合折线边界；有同源描边时复用描边，避免重复计入。描边与填充分别保持源绘制顺序，不将混合两类图元的半个字拼成完整字形。非平面、开放或含圆弧凸度的 HATCH 不参与这条识别路径。已确认的原轮廓和填充默认保存在关闭的备份层，重复执行不会重复写入 TEXT。

字库默认保留 5 组旧采样，并增加 8–36 pt 中 12 个常用字号对应的曲线采样，共 17 组。采样比值保留小数，避免贝塞尔曲线被取整为不同点数；逐点坐标和 DXF 几何不作修改。其他字号或转换容差仍可能不匹配。rc17 可读取旧版字库；使用这些新采样构建的字库需要 rc17 或更新版本。

范围限制：只支持字体实际提供的二维轮廓；未知字体、同形歧义、扫描页、旋转文字和缺少来源映射的独立 DXF 均可能保持几何。当前水平片段最长 96 个字符，不凭轮廓间隙猜补空格。没有一个内置小字典可以代表所有字体和所有汉字；本包不捆绑外部字体或外部 `.p2dfont`。原生 PDF 文本的转换不依赖这些轮廓锁定规则。

验证覆盖真实 DejaVu Sans / Serif / Sans Mono 的完整 52 字母 PDF 转换（描边折线与纯填充贝塞尔两条路径）、保留基线和字距的中英混排，以及由程序生成字体映射覆盖的汉字基本区与扩展 A–J。程序化测试证明 Unicode 通路与确定性匹配，不代表对应区段的所有真实字形都经过验证。

## English

rc17 supports all 52 ASCII English letters in catalog construction and verified outline recovery, preserving case. English-only text can lock a font without Chinese anchors. Unified Han ideographs and extensions A–J use the same Unicode 17.0 checks through persisted DXF and TEXT output, including supplementary planes. Compatibility mappings retain the existing single-codepoint NFKC normalization.

Use `--charset english` for printable ASCII, `chinese` for CJK plus ASCII, or `all` for every drawable mapping in the supplied font. Inspect `english_letters` for available/missing English letters and `han_range_coverage` for mapped counts by Han range. Coverage is not recognition accuracy on a drawing.

A font requires three distinct adjacent Han characters, four distinct adjacent English letters (counted case-insensitively), or three reviewed Han anchors. Exact mask/topology and per-template aspect checks precede publication. A locked English/mixed run requires at least two letters/Han characters. Unknown and ambiguous shapes stay as geometry; digits cannot establish an English lock.

Filled PDF glyphs are matched only after their closed polygon boundaries are persisted as DXF HATCH; matching uses existing strokes when both representations share the same source. Stroke and fill runs retain separate source ordering; mixed-representation fragments are not assembled into a glyph. Unsupported hatch geometry remains unchanged. The default catalog now has 17 sampling variants: the five legacy variants plus twelve common PDF font sizes from 8 to 36 pt, preserving fractional tolerance ratios. Other sizes or curve tolerances may remain unmatched. rc17 reads old catalogs; catalogs built with the new sampling set require rc17 or later. Original geometry is preserved by default, and recovery is idempotent.

Only mapped two-dimensional outlines are supported. Unknown fonts, scans, rotated text and independent DXF without converter source mappings can remain geometry. Horizontal runs are limited to 96 characters; spaces are not inferred from gaps. External fonts/catalogs are not bundled. Native PDF text does not require outline font locking. Real-font alphabet tests and synthetic Unicode-range tests establish their stated paths, not universal accuracy for every font or ideograph.

Unicode ranges: [Unicode 17.0 Blocks](https://www.unicode.org/Public/17.0.0/ucd/Blocks.txt). Test fonts are supplied by the test dependency Matplotlib and retain their upstream notices; they are not copied into this repository or its distributions.

## rc18 开源资源与完整轮廓 / Open resources and complete glyphs

新增 10 个独立字库、官方来源锁定清单与整包校验入口，见 [开源字库](OPEN_FONTS.md)。Jigmo 三个字库合并覆盖 Unicode 17 支持区段全部 102,998 个已分配汉字码点；多码点异体序列不在本版范围内。真实字体仍存在曲线采样与同形歧义造成的未确认字，逐项证据见 [验证数据](OPEN_FONT_VALIDATION.json)。

rc18 只将同一源轮廓区间中、完整精确字母/汉字内部严格包含的标点候选作为字内片段排除，避免一个竖画与竖排破折号相同就拒绝整个字形。候选须共享匹配字体，仍需连续成行和字体锁定。竞争字母、竞争汉字、相同区间和交叉重叠不适用此规则，继续保留歧义。

Ten optional catalogs and pinned sources are documented in [open resources](OPEN_FONTS.md). The complete-glyph rule suppresses only strictly contained punctuation fragments sharing a matching font with an exact Latin/Han glyph. It does not choose between competing letters or Han characters, equal spans or crossing overlaps. Font-lock and run checks remain mandatory. Unicode coverage is distinct from actual recognition; IVS sequences are not supported.

## rc20 填充轮廓保留 / Preserve repaired fills

部分自接触或带原路返回线段的 PDF 填充轮廓，在几何修复后会成为 Polygon 与零面积线段混合的 GeometryCollection。rc20 提取其中全部有效面，保留源轮廓方向和孔洞；零面积线段不产生填充，PDF 明确要求的描边仍独立输出。修复发生在 PDF→DXF 转换阶段，字形确认继续读取已保存的 DXF。

该修复使 Jigmo 扩展 I 的填充样例补齐 `U+2EBF3`。外部字库、精确匹配、字体锁定和重叠歧义规则均未改变；6 个 Jigmo 英文样例中的退化 `w` 与 16 个汉字轮廓竞争样例仍部分恢复或未确认。详见 [验证记录](VALIDATION.md)。

Some self-touching or retraced PDF contours repair into a GeometryCollection containing polygonal regions and zero-area lines. rc20 retains every polygonal region with source winding and holes; separately requested strokes remain. This repairs geometry during PDF→DXF conversion. Character confirmation still consumes persisted DXF and unchanged catalogs/matching gates. Jigmo's Extension I fill probe now includes `U+2EBF3`; the remaining English `w` and competing-Han cases are disclosed in [validation](VALIDATION.md).

## rc19 数值取整边界 / Numeric rounding boundaries

字体匹配保留 4 位归一化栅格精度，并核对 3 位、5 位取整形成的有限掩码变体。差异仅发生在距离半像素取整边界不超过 0.0005 像素的顶点；每个候选仍须与持久化字库中的完整拓扑和掩码摘要精确相同。所有变体、所有字库的候选标签一起检查，只要出现不同文字就拒绝，不按分数或字频猜测。源 DXF 坐标不变，旧字库无需重建。

报告中的 `font_numeric_variant_masks` 记录额外的不同掩码数，`font_numeric_stabilized_matches` 记录字体锁定后依赖 3/5 位变体的匹配数（不等于最终写入字符数）。每条 accepted 记录的 `font_raster_round_decimals` 与 `template_fingerprints` 按字符对应，可核对使用的取整精度和字库摘要。内置人工审核模板仍使用原指纹。

Font matching retains the four-decimal normalized raster and checks bounded three/five-decimal variants. Only vertices within 0.0005 pixels of a half-pixel boundary can change raster positions. Every candidate still needs an exact persisted mask digest, topology and aspect match. Conflicting labels across any variant or catalog are rejected, including conflicts with a primary match. Saved geometry is unchanged and existing catalogs need no rebuild. Reports expose additional masks, stabilized matches after font locking, and per-character rounding precision/digests. These are bounded serialization alternatives, not fuzzy image matching or OCR.

## rc21 描边与填充双表示 / Exact stroke and fill representations

Jigmo 的 `w` 含不足 0.007 mm 的退化闭合线段：描边候选过滤和纯填充输出均可能不包含它。相反，数字 `8` 的较大零面积线段可保留在描边 DXF 中。rc21 同时保存原始描边与有效填充两套精确模板，避免为补齐 `w` 而破坏 `8`。全部旧描边模板逐条保持一致；填充备选若不支持或采样拓扑不稳定，仅跳过备选并记录原因，不丢失原字符。

两套模板匹配到同一字符的严格包含区间时，只有额外源路径全部为闭合共线零面积轮廓，才保留完整描边区间；不同标签、交叉重叠与非零面积差异继续拒绝。该规则不删除或重写 DXF 路径。字体锁定和连续成行检查仍然必需。报告 `font_contained_fill_variants_suppressed` 记录这种重复备选。v2 字库需要 rc21+，旧 v1 字库继续可读。

Jigmo w has a tiny degenerate contour that may be absent from stroke candidates or filled output, while larger zero-area contours in 8 can remain in stroke DXF. rc21 retains every raw template and adds an exact filled alternate, avoiding regressions from replacing raw topology. Unsupported/unstable alternates are skipped without losing the original glyph. A strictly contained same-label match is suppressed only when both forms match exactly and the extra source paths are closed collinear contours; the complete raw match retains them. Different labels, crossing overlaps and nonzero-area differences remain ambiguous. Font/run gates still apply, DXF paths are unchanged, and the report counts suppressed duplicate fill variants. New v2 catalogs require rc21+; old v1 catalogs remain readable.

## rc22 短笔画与整字的尺寸证据 / Han fragment evidence

完整汉字已经精确匹配，但内部短笔画也匹配到“一”等汉字时，rc22 允许在以下证据同时存在时保留整字候选：整字严格包含所有冲突子轮廓；父字与子轮廓具有相同字库；同一连续来源文字行中至少两个无歧义汉字锚点，与父字合计至少三个不同标签；每个子轮廓高度小于最小锚点的 0.72 倍，无法满足已有同尺度汉字成行门槛。子轮廓能独立构成小字行时仍拒绝；等大、交叉、跨字体、同形异字和不足锚点的冲突继续保留歧义。正常字体锁定与成行发布检查仍须通过。

这不会删除或修改 DXF 路径，也不按词义猜字。`font_han_fragment_resolved_candidates` 和 `font_contained_han_fragments_suppressed` 统计候选处理；`font_han_fragment_evidence` 保存父字、子轮廓与锚点的源句柄、指纹和尺寸比例，最多 32 条，超过部分由 `font_han_fragment_evidence_truncated` 计数。实际输出仍以 `accepted` 和保存 DXF 的 TEXT 为准。无需重建 r2 字库。

When an exact whole Han glyph contains a competing short Han contour, rc22 requires strict containment, a common catalog, a continuous source row, two uncontested anchors and three distinct labels including the parent. Every child must be shorter than 0.72 times the smallest anchor, below the existing same-scale Han row threshold. Independent small-text runs, equal-size/crossing interpretations, cross-font conflicts and ambiguous labels remain unresolved. Font locks and publication gates still apply. Reports retain bounded source-handle, fingerprint and scale evidence at candidate-scan stage; published TEXT is counted separately. DXF geometry and r2 catalogs are unchanged.

## rc23 多字库来源行复核 / Cross-catalog row recheck

多字库扫描已经锁定某字体，但外部字体将完整汉字内部的短横标成下划线、破折号等候选时，rc23 可复核原先已有唯一整字标签的候选。必须满足原有单字体短笔画判断，且同一连续来源行中有三个不同的汉字锚点，它们在全体字库中均无标签歧义。页面其他位置的字体锁定不能代替这些行内证据。

复核保留全部原始窗口：每个竞争窗口必须严格包含于整字，且高度小于最小锚点的 0.72 倍。只接受汉字、标点与 U+31C0–U+31EF 笔画标签；窗口内的汉字标签必须唯一且当前字体也精确匹配该标签。竞争字母/数字、另一个整字标签、外部字体独有汉字、等大/交叉轮廓和可能独立成行的小字均保留歧义。不选择短横的最终文字标签；只发布通过核验的完整父字。

`font_row_recheck_scans` 记录额外单字体扫描，`font_row_recheck_matches` 记录补回候选，`font_row_recheck_evidence` 保存最多 32 条父字、三个锚点与所有竞争窗口的源句柄、标签、指纹和尺寸证据，超过部分由 `font_row_recheck_evidence_truncated` 计数。原有歧义/重叠计数描述初次全字库扫描，最终候选数包含复核结果；发布字符仍以 accepted 与保存 DXF 为准。单字库调用不走新增复核。

rc23 rechecks a globally unique complete Han candidate only after the all-catalog scan has locked its font. The existing single-font Han-fragment rule must succeed, and the same continuous source row must provide three distinct Han anchors without all-catalog label ambiguity. A font lock elsewhere on the page is insufficient. Every original competing window remains checked for strict containment and height below 0.72 times the smallest anchor. Labels are restricted to Han, punctuation and U+31C0–U+31EF strokes; any Han label must be unique and exactly supported by the selected font. Competing letters/digits, other complete labels, foreign-only Han labels, full-size/crossing contours and possible independent small-text rows remain unresolved. No fragment label is chosen for output; only the confirmed whole glyph is published. Additive report fields record extra scans, restored candidates and up to 32 detailed decisions, with a separate truncation count. Single-catalog recognition is unchanged.

## rc24：英文来源行复核 / Latin source-row recheck

已有字体锁定、完整字母在全体字库中标签唯一，且同一连续来源行有四个不同（不区分大小写计数）、全局无歧义的字母锚点时，才可复核遗漏候选。单字体扫描须接受完整候选；所有原始竞争窗口必须是严格内部的标点，且低于完整字母高度。竞争字母、数字、汉字、符号、跨界/等高轮廓和完整同形异字继续拒绝。汉字原有三锚点及 0.72 字高规则不变，不使用 OCR。

`font_row_recheck_evidence` 新增 `script`、`fragment_height_reference` 和 `fragment_height_reference_value`，标明汉字以最小锚点高度为基准，英文以完整父字高度为基准。原有复核计数、32 条详细证据上限及截断统计兼容。仅发布完整父字，不挑选内部标点的标签。

Latin recovery requires an existing font lock, a globally unique whole-letter label, four distinct unambiguous same-row Latin anchors (counted case-insensitively), successful local scanning and strict containment of every competing punctuation window below the parent height. Letters, digits, Han, symbols, crossing/full-height contours and whole-label conflicts stay unresolved. The existing Han rule is unchanged. Evidence now names its script and height reference; counts and the 32-record detail cap remain compatible.

## rc26：歧义窗口参与重叠判断 / Ambiguous-window overlap

同一原轮廓窗口可匹配多个字符时，即使不生成唯一候选，该窗口仍参与重叠判断。内部窗口、跨字边界窗口、覆盖子字形的完整歧义窗口都不能因增加字库而消失。半开区间的相邻端点不视为重叠。受阻候选不能先参与字体锁定，再用自己支持自己；已有来源行复核及全部原始冲突证据仍须通过。

新增 `font_ambiguous_overlap_rejections` 记录**初次扫描中**因多标签窗口而受阻的唯一候选数；`font_ambiguous_geometry_matches` 记录歧义窗口数，两者不是同一计数。已有同行锚点可能允许后续复核恢复完整父字，因此不能把初次拒绝数直接当作最终漏字数。最终输出以 `accepted` 和保存 DXF 中的 TEXT 为准。默认保留未确认原轮廓，不使用 OCR，不修改几何或缩放证据。

A window matching multiple labels remains an overlap conflict even without a unique candidate. Contained, crossing and whole-parent ambiguous windows cannot disappear when another catalog is added; adjacent half-open endpoints remain separate. Rejected candidates cannot bootstrap their own font locks. Existing anchored source-row rechecks must still account for every original conflict.

The additive `font_ambiguous_overlap_rejections` field counts unique candidates blocked during the initial scan; `font_ambiguous_geometry_matches` counts ambiguous windows. Later anchored rechecks may restore a whole parent, so initial rejections are not final missing-character counts. Use `accepted` and persisted DXF TEXT for output totals. Unconfirmed outlines, geometry and scale evidence remain intact; no OCR is used.

## rc27：长文字分段输出 / Long TEXT rows

字形已精确匹配并通过原有确认流程后，连续行超过 96 个字符时分成不超过 96 字的 TEXT；97 字分为 95+2，193 字分为 96+95+2，避免单字尾段。按 Unicode 码点计数，不切开补充平面汉字。每段独立执行原有发布共识检查：不足依据的纯数字段仍保留轮廓，未知或歧义字形不跨越拼接。每段的 FIT 定位点、字形指纹和源句柄来自该段实际轮廓。

`long_text_runs_split` 是被分段的原行数，`long_text_segments` 是这些行产生的候选段数，包含最终未发布的段。最终字符和实体数以 `accepted` 与保存 TEXT 为准。本轮不改变字形匹配、字体锚点或来源行复核门槛；未匹配的长行字符仍可能缺失，不使用 OCR。

After exact matching and the existing confirmation process, rows exceeding 96 Unicode codepoints are split into bounded TEXT payloads. Lengths 97 and 193 become 95+2 and 96+95+2, avoiding a one-glyph tail. Every segment still passes its own original publication-consensus check; unsupported numeric segments and unknown/ambiguous glyphs remain geometry. FIT endpoints, fingerprints and source handles are derived from each segment's actual outlines.

The two additive counters record source rows split and candidate segments, including segments later rejected. Use `accepted` and persisted TEXT for published totals. Font matching, locks and row-recheck thresholds are unchanged; this does not recover previously unmatched glyphs or invoke OCR.

## rc28：曲线采样稳定性 / Curve sampling stability

PDF 数值序列化可使同一曲线的理论采样数从 8.999983 变为 9.000077；直接向上取整会产生 9/10 点两种离散轮廓，进而改变掩码。rc28 将距离整数不超过 0.0001 的**采样数**对齐到该整数，其余取整决策、控制点、坐标、曲线容差及最大/最小采样数不变。转换器与字体构建器共用该规则。已有 r2 字库及精确掩码/拓扑/字体确认规则保持不变。

这修复从原 PDF 转换时的数值边界；不会猜测或重写旧 DXF 中已离散的轮廓。升级后请从原 PDF 重新转换。16 个原始长行 PDF 全部完整恢复，四处 B 漏字补齐；不能据此宣称任意字体识别率。详见[逐项证据](CURVE_SAMPLING_VALIDATION.json)。

PDF serialization can move the same curve's ideal count from 8.999983 to 9.000077, causing ceil to choose 9 versus 10 samples and different glyph masks. rc28 snaps only a **sample count** within 0.0001 of an integer; other rounding decisions, controls, coordinates, configured tolerance and sample limits remain unchanged. PDF conversion and font building share this rule. Exact masks, topology, font locks, ambiguity rejection and r2 resource bytes remain unchanged.

Reconvert the original PDF to benefit; this does not infer or rewrite curves already flattened in old DXFs. The original 16 long PDFs now complete, restoring four missing B characters. This is a bounded regression result, not universal font accuracy. See [evidence](CURVE_SAMPLING_VALIDATION.json).

## rc29 闭合部首消歧 / Enclosed radical disambiguation

同字体别名、严格内孔包含和三个独立同行锚点可复核部分整字/部首冲突。Jigmo 对应字库的“图”补回，“建”及额外跨字体冲突仍保留。字库不变；详见 [算法](OPEN_OUTLINE_ALGORITHMS.md) 与 [实测](CONTOUR_TOPOLOGY_VALIDATION.json)。

Same-font aliases, strict hole containment and three independent row anchors resolve a bounded class of glyph/radical conflicts. Jigmo 图 improves; 建 and additional multi-font conflicts remain unresolved. Resources are unchanged.

## rc30 来源行与阶段证据 / Source rows and staged evidence

仅被其他字体内部小标点阻断、但在当前字体已有唯一精确标签的汉字，现在可通过三个独立同行汉字锚点复核。竞争窗口必须严格属于整字来源范围，几何包含且明显小于锚点；字母、数字、其他汉字、跨界或整字别名冲突仍会拒绝。此前已通过来源行复核的字形可以连接后续闭合部首的证据路径，但不计入独立锚点。每个闭合部首候选最多检查 96 个相邻字形，找到三个不同的原始无冲突锚点即停止，因此 97/193 字长行不必整体小于 96 字。新提出的闭合部首候选不能互相连接或证明彼此。

十字库组合为 **67/84 完整、1253 字**，其中全部 20 个大小写 52 字母样例保持完整。新增 12 个 Jigmo 长行 PDF 全部完整，1740 字逐项核验。“建”的开放部首仍不满足封闭拓扑；未知字体和同形歧义不能靠相似度猜字。r2 字库格式和字节不变。报告新增有界的拒绝原因、来源句柄和局部路径，仅覆盖本阶段评估过的部首候选，不能视为全部未知字清单。详见 [逐项证据](OUTLINE_ROW_VALIDATION.json)。

Han glyphs uniquely matched in the locked font may be rechecked when their only competitors are small contained punctuation, supported by three independent Han anchors. Letters, digits, unsupported Han labels, crossing spans and whole-glyph aliases still fail. Earlier verified row results may connect a later enclosure proof but cannot become independent anchors. The local search visits at most 96 adjacent glyphs and stops at three distinct original uncontested anchors; proposed enclosures never connect each other. Long rows therefore need not fit inside a single 96-glyph window.

All-ten-catalog probes reach **67/84 complete, 1253 characters**; all 20 full alphabet probes remain complete. Twelve new Jigmo long PDFs complete with 1740 independently checked characters. Open-radical 建 remains unresolved. Bounded rejection details cover evaluated radical proposals only. Existing r2 files remain byte-identical; see [evidence](OUTLINE_ROW_VALIDATION.json).

## rc31 半包围与有界证据链 / Half-enclosures and bounded proof chains

Jigmo 的“建”整字及“廴”正字轮廓均已精确匹配。“廴”是一个有效闭合多边形，与其余所有轮廓多边形互不相交；两部分凸包的内部重叠且互不包含，其余部分仅越过部首边界的一侧，另外三侧严格位于边界内。满足该半包围结构后，仍须实际正字模板、Unicode 康熙部首身份、独立字体锁和三个不同的原始无冲突汉字锚点。兼容部首可以有不同描画；不能要求其摘要与正字相同。原封闭内孔规则保留原有的精确部首别名字形检查。

只允许上一轮已经证实的字连接后续证据，并保留实际证明它的字体；新候选不能在同一轮互相举证，也不能替代独立锚点。每个候选最多检查 96 个相邻字形、整体最多 96 轮。测试中的 94 字候选链只确认仍能在 96 字窗口内找到原始三个锚点的前 93 字，最后一字保留为轮廓。报告记录证明轮次、连接字的字体、半包围方向、凸包交叠面积、最小间距、码点及来源句柄；详细证据仍有 32 条上限。

对应字体 PDF 为 **84/84 完整、1310 字**，组合十字库为 **69/84、1255 字**。剩余 14 个组合样例无法建立独立字体锁，另 1 个仍有较大的内部标点竞争。请按图纸真实字体选字库；同时加载更多字库不保证更好效果。新增 12 个含“建”的 97/193 字长行 PDF 全部完整，1740 字独立核验。r2 文件不变；[逐项证据](HALF_ENCLOSURE_VALIDATION.json)明确限定 100% 的样例范围。

The exact whole glyph and canonical 廴 outline support a half-enclosure proof: valid polygons are disjoint, their convex hull interiors overlap without containment, and remaining bounds protrude through exactly one radical side. Three distinct original uncontested Han anchors and the independently locked canonical cmap outline remain mandatory. Unicode identifies the radical; compatibility glyphs may have different drawings. The previous closed-counter alias-geometry check is preserved.

Only earlier-round verified results may connect a later proof, restricted to the font that proved them; they never become anchors. Each search visits at most 96 neighboring glyphs, with at most 96 rounds. A 94-proposal chain confirms only its first 93 glyphs while all three original anchors remain within the window. Reports retain proof rounds, font-bound bridges, geometry and source handles with bounded detail.

Matching-face probes reach **84/84 complete, 1310 characters**; combined catalogs reach **69/84, 1255 characters**. Fourteen combined cases lack an independent font lock; one retains a large punctuation conflict. Twelve new long 建 PDFs complete with 1740 independently checked characters. This is a bounded corpus result, not universal font accuracy. Reuse unchanged r2 resources; see [evidence](HALF_ENCLOSURE_VALIDATION.json).

## rc32 长行局部消歧 / Local ambiguity review for long rows

汉字片段初筛及锁定字体后的同行复核均使用以候选为中心、最多 96 字的连续窗口；靠近行端时窗口向另一侧补齐。短行继续使用完整原行。全部几何、字体、来源边界、最小锚点字高及独立锚点条件不变；远处锚点不能跨越窗口提供证明，新恢复字不能充当独立锚点。超过 96 字的证据额外记录窗口来源范围和字形数量，TEXT 仍按最多 96 字分段。

Both Han-fragment screening and locked-font row rechecks now use a centered contiguous window of at most 96 glyphs, shifted inward at row ends. Short rows retain the complete original row. Geometry, font/source boundaries, minimum anchor height and independent-anchor requirements are unchanged. Distant anchors cannot cross the window and restored results cannot become independent anchors. Long-row evidence records the source span and glyph count; TEXT output retains its 96-glyph segmentation.

十字库长行 PDF 为 16/16、2320 字，比 rc31 多 94 字；84 个短行 DXF 保持 69/84。新增历史及本机 12 页转换对照不改变原文字、几何与比例状态，但外部轮廓字体尚未确认。见[本轮证据](LONG_ROW_WINDOW_VALIDATION.json)。此前 rc31 的对应字体 84/84 和 BIM22 结果保留历史版本，本轮未重跑这两批 PDF。

All-ten long PDFs complete 16/16 with 2320 characters, gaining 94 over rc31; short DXFs remain 69/84. Twelve historical/local pages preserve text, geometry and scale states but do not lock an external outline font. See [evidence](LONG_ROW_WINDOW_VALIDATION.json). Earlier rc31 matching-face 84/84 and BIM22 results retain their historical version; neither PDF batch is rerun here.
