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

## rc19 数值取整边界 / Numeric rounding boundaries

字体匹配保留 4 位归一化栅格精度，并核对 3 位、5 位取整形成的有限掩码变体。差异仅发生在距离半像素取整边界不超过 0.0005 像素的顶点；每个候选仍须与持久化字库中的完整拓扑和掩码摘要精确相同。所有变体、所有字库的候选标签一起检查，只要出现不同文字就拒绝，不按分数或字频猜测。源 DXF 坐标不变，旧字库无需重建。

报告中的 `font_numeric_variant_masks` 记录额外的不同掩码数，`font_numeric_stabilized_matches` 记录字体锁定后依赖 3/5 位变体的匹配数（不等于最终写入字符数）。每条 accepted 记录的 `font_raster_round_decimals` 与 `template_fingerprints` 按字符对应，可核对使用的取整精度和字库摘要。内置人工审核模板仍使用原指纹。

Font matching retains the four-decimal normalized raster and checks bounded three/five-decimal variants. Only vertices within 0.0005 pixels of a half-pixel boundary can change raster positions. Every candidate still needs an exact persisted mask digest, topology and aspect match. Conflicting labels across any variant or catalog are rejected, including conflicts with a primary match. Saved geometry is unchanged and existing catalogs need no rebuild. Reports expose additional masks, stabilized matches after font locking, and per-character rounding precision/digests. These are bounded serialization alternatives, not fuzzy image matching or OCR.
