# 开源轮廓算法调研 / Open outline algorithms

核查日期 / Reviewed: 2026-09-08. 区分已采用算法、参考实现和未引入的数据。以下项目都不保证任意字体的汉字识别。

| 项目 / Project | 能力与决策 / Capability and decision | 上游许可 / License |
| --- | --- | --- |
| [Shapely / GEOS](https://shapely.readthedocs.io/en/stable/reference/shapely.contains_properly.html) | **已采用**严格包含，完整路径必须在内孔中，边界相接也拒绝。Adopted full-path containment; shared boundaries fail. | Shapely [BSD-3-Clause](https://raw.githubusercontent.com/shapely/shapely/main/LICENSE.txt)；GEOS 单独保留 [LGPL 2.1 文本](https://raw.githubusercontent.com/libgeos/geos/main/COPYING)。 |
| [FontTools PointInsidePen](https://fonttools.readthedocs.io/en/latest/pens/pointInsidePen.html) | 已有字体构建依赖；本轮用作独立测试，证明顶点在内部不能排除线段穿越凹边界。Existing build dependency and independent point-in-path test oracle. | [MIT](https://raw.githubusercontent.com/fonttools/fonttools/main/LICENSE) |
| [FontForge](https://fontforge.org/docs/scripting/python/fontforge.html) | `contour.similar` 可作轮廓误差诊断；未引入原生运行时。Contour-comparison reference; not integrated. | [整体 GPL-3.0-or-later，部分文件 BSD](https://raw.githubusercontent.com/fontforge/fontforge/master/LICENSE)；复制代码须逐文件核查。 |
| [skia-pathops](https://github.com/fonttools/skia-pathops) | 曲线布尔运算，可研究字库构建时的交叠轮廓；有原生 C++/Cython 依赖，本轮未引入。Curve boolean operations; future catalog-building candidate. | [BSD-3-Clause](https://github.com/fonttools/skia-pathops/blob/main/LICENSE)；Skia 及第三方组件保留各自许可。 |
| [OpenCV matchShapes](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html) | Hu 矩比较，适合候选排序/诊断；不凭相似分数自动写 TEXT。Hu similarity does not establish a Unicode label. | [Apache-2.0](https://raw.githubusercontent.com/opencv/opencv/4.x/LICENSE) |

## rc29 采用的规则

识别器只读取持久化 DXF 和 `.p2dfont`。先按现有精确掩码、轮廓结构和比例匹配，再建立字体锁。新增复核仅处理“一个整字候选 + 一个部首候选”的重叠分量；任何多标签窗口或第三种解释均保留歧义。

部首必须在同一已锁定字库中具有康熙部首区 U+2F00–U+2FD5 的持久化别名，并匹配实际摘要、轮廓数和比例，不能借另一个字体的别名。两个闭合、有效、严格嵌套的环必须把其余完整路径包在内环内部，不得接触或穿越边界。同一连续来源行内还须有三个不同、无冲突的汉字锚点。新候选不参与建立字体锁，也不能充当自己的锚点。

这是基于精确字形与上下文证据的有限消歧。算法只读几何，不做 union、buffer、简化或多边形修复。报告的 `font_enclosed_radical_evidence` 保存来源句柄、模板摘要、部首码点、字体和锚点，最多 32 条并单独计数截断；原轮廓的保留策略仍由用户选择。

Jigmo 的“图”符合这条证据链；“建”的“廴”没有封闭内孔，仍保留歧义。跨字体冲突仍会阻止输出。结果见 [验证记录](VALIDATION.md) 和 [结构证据](CONTOUR_TOPOLOGY_VALIDATION.json)。r2 字库格式和字节不变，无需重新下载。

## 部件数据候选

[CJKVI IDS](https://github.com/cjkvi/cjkvi-ids) 可辅助研究汉字结构；`ids.txt` 涉及 CHISE 条款，其他数据注明 GPLv2，不能统一当成 MIT。[Make Me a Hanzi](https://github.com/skishore/makemeahanzi) 提供笔画/字典数据，`dictionary.txt` 与 `graphics.txt` 采用不同许可，图形源于特定 Arphic 字体。两者本轮均没有下载、复制或用于识别。部件描述可以约束候选，实际 DXF 字形仍须独立几何证据；这是本项目的工程判断。

## rc29 English

The new rule runs after an independent font lock. It considers exactly one complete Han glyph and one enclosing radical, both uniquely matched by the existing exact mask/topology/aspect checks. A persisted Kangxi alias in the same locked catalog must match the actual digest, contour count and aspect. Two valid, strictly nested closed rings must enclose every remaining complete path. Touching or crossing fails. Three distinct uncontested Han anchors must share the continuous source row. Proposed glyphs cannot create their own lock, serve as anchors or bridge gaps between anchor rows. Hidden ambiguous windows and additional interpretations remain unresolved.

Shapely/GEOS supplies the read-only predicate. FontTools provides an independent point-in-path test oracle: a concave example shows why checking only vertices is insufficient. No OCR, geometry repair, boolean union, simplification or conversion-time source-font lookup is added. Neither similarity nor enclosure alone authorizes a TEXT label. Bounded provenance is retained in the report.

Jigmo 图 meets this limited proof; the open radical in 建 does not. Existing r2 resources remain unchanged. FontForge and skia-pathops are research references. IDS/stroke datasets are not imported; their licenses and font-specific coverage must be evaluated separately if adopted. See the validation record for measured results and remaining limits.

## rc30 来源行与阶段证据 / Source rows and staged evidence

仅被其他字体内部小标点阻断、但在当前字体已有唯一精确标签的汉字，现在可通过三个独立同行汉字锚点复核。竞争窗口必须严格属于整字来源范围，几何包含且明显小于锚点；字母、数字、其他汉字、跨界或整字别名冲突仍会拒绝。此前已通过来源行复核的字形可以连接后续闭合部首的证据路径，但不计入独立锚点。每个闭合部首候选最多检查 96 个相邻字形，找到三个不同的原始无冲突锚点即停止，因此 97/193 字长行不必整体小于 96 字。新提出的闭合部首候选不能互相连接或证明彼此。

十字库组合为 **67/84 完整、1253 字**，其中全部 20 个大小写 52 字母样例保持完整。新增 12 个 Jigmo 长行 PDF 全部完整，1740 字逐项核验。“建”的开放部首仍不满足封闭拓扑；未知字体和同形歧义不能靠相似度猜字。r2 字库格式和字节不变。报告新增有界的拒绝原因、来源句柄和局部路径，仅覆盖本阶段评估过的部首候选，不能视为全部未知字清单。详见 [逐项证据](OUTLINE_ROW_VALIDATION.json)。

Han glyphs uniquely matched in the locked font may be rechecked when their only competitors are small contained punctuation, supported by three independent Han anchors. Letters, digits, unsupported Han labels, crossing spans and whole-glyph aliases still fail. Earlier verified row results may connect a later enclosure proof but cannot become independent anchors. The local search visits at most 96 adjacent glyphs and stops at three distinct original uncontested anchors; proposed enclosures never connect each other. Long rows therefore need not fit inside a single 96-glyph window.

All-ten-catalog probes reach **67/84 complete, 1253 characters**; all 20 full alphabet probes remain complete. Twelve new Jigmo long PDFs complete with 1740 independently checked characters. Open-radical 建 remains unresolved. Bounded rejection details cover evaluated radical proposals only. Existing r2 files remain byte-identical; see [evidence](OUTLINE_ROW_VALIDATION.json).

## 本轮算法选择 / Algorithm selection in rc30

继续复用 Shapely/GEOS 对完整路径做严格包含；[DE-9IM 关系模式](https://shapely.readthedocs.io/en/stable/reference/shapely.relate_pattern.html)可表达几何拓扑关系。本轮补齐的是已验证阶段之间的连接和局部搜索，已有依赖足够支持，没有增加运行时库。[FontTools interpolatable](https://fonttools.readthedocs.io/en/latest/varLib/interpolatable.html)检查字体 master 间的插值兼容问题，可用于字库质量诊断；它不会从 DXF 轮廓确定 Unicode 标签。相似度、仿射拟合或 IDS 部件描述不足以直接确认“建”，这是当前证据边界下的工程判断。

Shapely/GEOS already supplies full-path topology predicates, so the staged/local search repair adds no runtime dependency. FontTools interpolatable checks compatibility between font masters and is a catalog-quality reference, not a DXF-to-Unicode recognizer. Similarity, affine fitting or IDS structure alone does not establish the missing 建 label under this project's evidence requirements.

## rc31 半包围与有界证据链 / Half-enclosures and bounded proof chains

Jigmo 的“建”整字及“廴”正字轮廓均已精确匹配。“廴”是一个有效闭合多边形，与其余所有轮廓多边形互不相交；两部分凸包的内部重叠且互不包含，其余部分仅越过部首边界的一侧，另外三侧严格位于边界内。满足该半包围结构后，仍须实际正字模板、Unicode 康熙部首身份、独立字体锁和三个不同的原始无冲突汉字锚点。兼容部首可以有不同描画；不能要求其摘要与正字相同。原封闭内孔规则保留原有的精确部首别名字形检查。

只允许上一轮已经证实的字连接后续证据，并保留实际证明它的字体；新候选不能在同一轮互相举证，也不能替代独立锚点。每个候选最多检查 96 个相邻字形、整体最多 96 轮。测试中的 94 字候选链只确认仍能在 96 字窗口内找到原始三个锚点的前 93 字，最后一字保留为轮廓。报告记录证明轮次、连接字的字体、半包围方向、凸包交叠面积、最小间距、码点及来源句柄；详细证据仍有 32 条上限。

对应字体 PDF 为 **84/84 完整、1310 字**，组合十字库为 **69/84、1255 字**。剩余 14 个组合样例无法建立独立字体锁，另 1 个仍有较大的内部标点竞争。请按图纸真实字体选字库；同时加载更多字库不保证更好效果。新增 12 个含“建”的 97/193 字长行 PDF 全部完整，1740 字独立核验。r2 文件不变；[逐项证据](HALF_ENCLOSURE_VALIDATION.json)明确限定 100% 的样例范围。

The exact whole glyph and canonical 廴 outline support a half-enclosure proof: valid polygons are disjoint, their convex hull interiors overlap without containment, and remaining bounds protrude through exactly one radical side. Three distinct original uncontested Han anchors and the independently locked canonical cmap outline remain mandatory. Unicode identifies the radical; compatibility glyphs may have different drawings. The previous closed-counter alias-geometry check is preserved.

Only earlier-round verified results may connect a later proof, restricted to the font that proved them; they never become anchors. Each search visits at most 96 neighboring glyphs, with at most 96 rounds. A 94-proposal chain confirms only its first 93 glyphs while all three original anchors remain within the window. Reports retain proof rounds, font-bound bridges, geometry and source handles with bounded detail.

Matching-face probes reach **84/84 complete, 1310 characters**; combined catalogs reach **69/84, 1255 characters**. Fourteen combined cases lack an independent font lock; one retains a large punctuation conflict. Twelve new long 建 PDFs complete with 1740 independently checked characters. This is a bounded corpus result, not universal font accuracy. Reuse unchanged r2 resources; see [evidence](HALF_ENCLOSURE_VALIDATION.json).

本轮复用 Shapely/GEOS 的 [convex_hull](https://shapely.readthedocs.io/en/stable/reference/shapely.convex_hull.html)、[overlaps](https://shapely.readthedocs.io/en/stable/reference/shapely.overlaps.html) 和 [disjoint](https://shapely.readthedocs.io/en/stable/reference/shapely.disjoint.html)，不新增依赖。凸包仅作为临时空间证据，不替换或简化原始路径。部首映射使用 Python 标准库 Unicode NFKC；[Unicode 康熙部首表](https://www.unicode.org/charts/PDF/U2F00.pdf)和[规范化标准](https://www.unicode.org/reports/tr15/)解释兼容映射及字形差异。没有复制 Unicode 字体或码表图形。

Existing Shapely/GEOS predicates supply temporary spatial evidence without changing source paths. Python's Unicode NFKC supplies the radical mapping, not the glyph identity. The linked primary references document these primitives; this project's combined admission rule still requires independently verified labels and anchors. No new dependency, OCR, approximate-label inference or Unicode font data is introduced.
