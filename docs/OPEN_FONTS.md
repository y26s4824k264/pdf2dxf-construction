# 开源字库 / Open font catalogs

rc18 提供独立的 `.p2dfont` 资源包，无需安装系统字体。字体只在构建字库时读取，转换时只读取持久化 DXF 和字库文件，不联网、不使用 OCR。

## 下载与使用

从 [rc31 发行页](https://github.com/y26s4824k264/pdf2dxf-construction/releases/tag/v2.0.0rc31) 下载需要的 ZIP，并用发行页的 SHA256SUMS.txt 校验。解压到自己的字库目录；主 wheel 和源码包不包含字体或这些资源包。

| 资源 | 字体来源（各取一个静态字重/字面） | 大小 |
| --- | --- | --- |
| `PDF2DXF-fonts-core-2026.09.07-r2.zip` | 思源黑体 SC Regular 2.005、思源宋体 SC Regular 2.003、DejaVu Sans / Serif / Sans Mono 2.37 | 约 27 MiB |
| `PDF2DXF-fonts-extended-2026.09.07-r2.zip` | Jigmo / Jigmo2 / Jigmo3 2025-09-12、遍黑体 P1 / P2 Regular 2.9.5795 | 约 52 MiB |

```sh
pdf2dxf font-catalog inspect-bundle \
  catalogs/PDF2DXF-fonts-core-2026.09.07-r2/font-bundle.json

pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required --scale-mode declared \
  --outline-font-bundle catalogs/PDF2DXF-fonts-core-2026.09.07-r2/font-bundle.json
```

`convert`、`batch`、`regress` 都接受 `--outline-font-bundle`，可重复传入两个包。只需要某个字体时，继续使用 `--outline-font-catalog .../catalogs/cjk-sans-sc-regular.p2dfont`。少量、接近原图字体的字库通常更合适；多个字体可能增加歧义和内存开销。加载失败会明确报错，不忽略损坏的包继续运行。

Python 接口复用同样的校验：

```python
from pdf2dxf_stable import Converter, ConversionRequest
from pdf2dxf_stable.engine.text.font_bundle import load_font_bundle

bundle = load_font_bundle('catalogs/PDF2DXF-fonts-core-2026.09.07-r2/font-bundle.json')
request = ConversionRequest(
    outline_chinese='required',
    outline_font_catalogs=bundle['catalog_paths'],
    scale_mode='declared',
)
result = Converter().convert('input.pdf', 'output/drawing.dxf', request)
```

## 覆盖与识别边界

Jigmo 三个字库并集覆盖 Unicode 17 基本区、扩展 A–J、兼容区及其补充区全部 **102,998 个已分配汉字码点**，逐项与官方 UnicodeData.txt 对齐。各字体的可绘制码点、汉字区段、52 个英文字母、同形歧义和缺字均有统计，见 [机器可读验证](OPEN_FONT_VALIDATION.json)。字库中忽略的 U+3000 是没有轮廓的全角空格，不属于缺失汉字。

覆盖指字库中有相应轮廓模板，不等于任意字体识别率。真实字体的描边与填充 PDF 测试包含完整恢复、部分恢复和未确认场景，逐项公开预期和实际 TEXT。逐个指定对应字库时，十个字库的大小写 52 字母描边/填充样例均完整恢复；rc22 下剩余 2 个 Jigmo 汉字样例仍有整字大小的轮廓竞争造成的未确认字符。结果不作为代表性准确率基准。

- 每个字重、斜体和地区字形可能不同，本版不声称覆盖这些字体的所有变体。
- `.p2dfont` 当前只使用单码点 cmap；IVS/IVD 多码点异体序列不在支持范围内。
- 扫描图、不同字体的相似字、字体缺字、几何退化与证据冲突保持原几何，不用语义猜字。
- 汉字至少三个不同字或英文至少四种字母的一致连续精确匹配才能独立锁定字体；写 TEXT 仍须通过连续成行等检查。
- 完整字母/汉字内部的标点轮廓片段不再导致整字被误拒绝。竞争字母、竞争汉字、相同范围或交叉重叠仍保留为歧义。

## 许可、来源和重建

[OPEN_FONTS.lock.json](OPEN_FONTS.lock.json) 固定每个官方下载的版本/提交、URL、大小与 SHA256；ZIP 中取出的字体和版权/许可证文本也各自固定哈希。来源字体名称仅用于署名，不作为衍生资源的新字体名称。

- 思源黑体、思源宋体、遍黑体保留 SIL OFL 1.1。
- Jigmo 字体保留 CC0 1.0；其仓库构建脚本的 MIT 不能代替字体许可证。
- DejaVu 保留原始 Bitstream Vera / Arev 条款及完整 LICENSE、AUTHORS、README。
- `.p2dfont` 是由字体轮廓生成的衍生资源，随包保留对应许可和版权。项目代码的 AGPL 不替代这些许可。私有系统字体、客户 PDF/DXF 不进入资源包。

资源包内含 `font-bundle.json`、`SOURCE_LOCK.json`、`COVERAGE.json`、`NOTICE.md` 和原始许可证文本。校验器检查相对路径、符号链接、重复条目、文件长度与哈希、许可证引用和字库内在完整性；哈希校验用于检测损坏，下载来源仍须可信。

从源码根目录运行，安装本包后即可构建；字体只写入指定缓存，不安装到操作系统：

```sh
python tools/build_open_font_bundle.py \
  --lock docs/OPEN_FONTS.lock.json --cache tmp/open-font-downloads \
  --group core --output tmp/PDF2DXF-fonts-core-2026.09.07-r2

python tools/build_open_font_bundle.py \
  --lock docs/OPEN_FONTS.lock.json --cache tmp/open-font-downloads \
  --group extended --output tmp/PDF2DXF-fonts-extended-2026.09.07-r2
```

缓存齐全后可以加 `--offline`。构建中断后，使用新的 `--output`，通过 `--catalog-cache 旧目录/catalogs` 复用已完成且重新验证的字库。已有输出目录、损坏缓存、不同源字体或不同构建参数不会被静默覆盖。默认构建保留 17 组采样参数，并显示进度；本次 v2 字库需要 rc21+；rc21 仍可读取旧 v1 字库。旧缓存不会被当作符合新构建策略的缓存跳过。

## English

Two optional resource ZIPs contain ten static font-face catalogs: Source Han Sans/Serif SC Regular and three DejaVu regular faces in **core**; Jigmo's three plane files and Plangothic's two regular parts in **extended**. Download the desired assets from the [rc31 release](https://github.com/y26s4824k264/pdf2dxf-construction/releases/tag/v2.0.0rc31), compare the release checksums, unpack, and use `--outline-font-bundle path/to/font-bundle.json`. The option is repeatable for convert/batch/regress. Individual `.p2dfont` paths remain supported. The Python example above verifies the same bundle before passing its catalog paths to the existing request API.

Jigmo's catalog union covers all **102,998 assigned Han codepoints** in Unicode 17's unified, A–J and compatibility ranges, checked against the official UnicodeData.txt. Coverage is not universal recognition accuracy. Real outlined-PDF tests publish complete, partial and unconfirmed results; All ten catalogs recover the full 52-letter stroke/fill test strings; sixteen Han cases still retain competing-contour ambiguities. Unknown geometry remains available. IVS/IVD sequences and every weight/regional variant are not supported by this release. See the [validation data](OPEN_FONT_VALIDATION.json) for exact inputs and results.

Source versions, URLs, byte counts and hashes are pinned in the source lock. The build commands above download only when explicitly invoked, verify both archives and selected members, preserve original copyright/license notices and produce separately downloadable catalogs. Use `--offline` with a complete cache; interrupted builds can reuse verified catalog files via `--catalog-cache` with a new output directory. Conversion reads persisted DXF/catalogs only, with no font installation, OCR or network access.

Source Han and Plangothic retain OFL 1.1; Jigmo font data retains CC0 1.0; DejaVu retains its Bitstream Vera/Arev terms. These derived resources keep the source licenses. The code's AGPL does not replace them. Resource IDs are project-local, and original font names serve attribution only. Neither the wheel nor the source distribution includes font binaries, customer drawings or these optional ZIPs.

## rc21 资源兼容 / Resource compatibility

`r2` 是相同已锁定源字体的重建资源，许可不变。v2 字库按每码点“原始描边在前、可选填充在后”保存，最多两种表示；只移除构建时严格闭合且全部共线的零面积轮廓来生成填充模板。原始描边模板、DXF 坐标和绘制内容保持原样。`mapped_codepoints` 统计唯一码点，`templates` 统计表示总数，`fill_variants` 单独统计新增表示。新资源需要 rc21+；旧 v1 字库仍可读取，但不会自动获得新表示，仅升级 Python 包不足以补齐这些样例。

The `r2` assets rebuild the same pinned sources under their original licenses. Schema v2 stores the raw stroke representation first and an optional filled representation second, with at most two rows per codepoint. Only exactly closed collinear source contours are omitted from the fill alternate; raw templates and saved DXF geometry remain. Inspection separates unique mapped codepoints, total template representations and additional fill variants. These resources require rc21+; legacy v1 catalogs remain readable, but upgrading Python alone does not rebuild their templates.

## rc22 继续使用 r2 / Reuse r2

rc22 的改动在 DXF 候选识别，两个 r2 ZIP 与 rc21 发行资源的 SHA256 完全相同。已有 r2 字库可以直接使用，无需下载或重建。v2 字库加载仍要求 rc21+；要使用本轮汉字短笔画判断，升级到 rc22。

rc22 changes DXF candidate resolution. Both r2 ZIPs retain exactly the rc21 SHA256 digests. Existing r2 downloads work without rebuilding. Schema v2 still requires rc21+; the new Han fragment resolution requires rc22.

## 字库选择影响识别 / Catalog selection affects recognition

84 个真实字体样例逐个指定生成该样例的字体字库，不是同时加载十个字库。rc22 的隔离安装包曾另测遍黑体扩展 J 的 `U+323B0–U+323B3`：同时加载 core + extended 时，描边/填充都只恢复前三字，末字因跨字体轮廓冲突保留几何；从相同下载资源中单独指定 `han-gothic-part2.p2dfont` 时，两例均完整恢复。增加字体数量不保证恢复更多文字；应优先提供与图纸字体相符的字库，避免不必要的竞争候选。

The 84 probes each use the catalog for the font that generated that PDF, rather than all ten catalogs together. Historical rc22 installed-wheel checks used Plangothic Extension J `U+323B0–U+323B3`: loading core + extended recovers only the first three characters in both stroke and fill, preserving the last glyph because other fonts introduce conflicting contour labels. Selecting `han-gothic-part2.p2dfont` from the same download restores all four in both cases. More catalogs do not guarantee more recovered text; supply the font faces relevant to the drawing. See [validation data](OPEN_FONT_VALIDATION.json).

rc23 在上述扩展 J 例子的整字标签唯一、字体已锁定且同一行三个汉字锚点无歧义时，核验所有内部片段，描边/填充均补齐第四字。正常加载两个资源包或单独对应字库的四项完整转换检查均通过。对同一批 84 个保存 DXF 同时加载十字库，完整恢复从 rc22 的 62 个增至 64 个，仍有 20 个部分恢复或未确认；逐字体 PDF 样例仍为 82/84。字库更多不等于识别更好，建议继续按图纸实际字体选择。资源内容和 SHA256 不变。

rc23 restores the fourth Extension J character in both pipelines after checking the globally unique parent, established font lock, three unambiguous same-row Han anchors and all internal fragments. Four complete conversion checks with normal resource loading pass for combined bundles or the matching face. On the same 84 persisted DXFs with all ten catalogs loaded, complete cases improve from 62 to 64, leaving 20 partial/unconfirmed; matching-face PDF probes remain 82/84. More catalogs can still reduce recognition. Resource bytes and SHA256 digests are unchanged.

## rc24：多字库英文恢复 / Latin recovery across catalogs

rc24 在已有字体锁定和同一连续行四个不同字母锚点成立时，复核完整英文字母内部、严格更矮的标点轮廓。三种字体的描边/填充样例均补回小写 `i`。同时加载十个字库，20 个大小写 52 字母样例全部完整恢复；整体 84 个 DXF 样例为 70 个完整、14 个部分或未确认。对应字体的 84 个 PDF 仍为 82 个完整。八个正常加载字库的英文/扩展 J PDF 检查全部通过。竞争字母、数字、汉字、符号和整字标签继续保留歧义；字库字节和 SHA256 不变。

rc24 checks shorter internal punctuation only after an established font lock and four distinct globally unambiguous same-row Latin anchors. Six stroke/fill cases regain `i`. All-ten-catalog recovery now completes all 20 English alphabet probes, and 70/84 DXF probes overall; 14 remain partial/unconfirmed. Matching-face PDFs remain 82/84. Eight normal-loading Latin/Extension J PDF checks pass. Competing letters, digits, Han, symbols and whole-glyph labels remain unresolved. Existing r2 bytes and hashes are unchanged.

## rc25：字库加载优化 / Catalog loading

同一批 r2 字库加载中位耗时从 5.76 降至 2.31 秒，进程峰值内存约减少 19%；数据完整性和歧义校验不变。详见 [实测与范围](VALIDATION.md) 和 [逐项数据](CATALOG_LOADING.json)。不需要重新下载或构建字库。

The same r2 catalogs load in a median 2.31 seconds versus 5.76 seconds, with about 19% lower process peak RSS in local trials. Integrity and ambiguity checks remain intact; no catalog rebuild or download is required. See [method and scope](VALIDATION.md) and [measurements](CATALOG_LOADING.json).

## rc26：保留歧义轮廓 / Ambiguous windows

修复后，同形多标签窗口继续阻止与其重叠的候选，不能再作为字体锚点。组合十字库的完整样例为 **63/84**（此前 70/84），21 个部分或未确认；八个样例因锚点不足共保留 31 个旧输出字符的原轮廓。逐字体指定对应字库仍 **82/84**，全部 20 个完整英文字母样例通过。不是所有减少输出的标签都已被证明错误，组合更多字库也不保证更好识别。请依据图纸的实际字体选择字库，不为追求输出数量而删除已知冲突证据。资源字节不变，详见 [验证记录](VALIDATION.md)。

Ambiguous multi-label windows now block overlapping candidates and cannot act as font-lock anchors. With all ten catalogs, **63/84** probes complete (previously 70/84); eight cases with insufficient anchors withhold 31 prior characters while retaining their outlines. Matching-face PDFs remain **82/84** and all 20 alphabet probes pass. Withheld labels are not necessarily wrong. Select catalogs based on the actual drawing font, without discarding known conflicting evidence merely to increase output. Resource bytes remain unchanged; see [validation](VALIDATION.md).

## rc27：长行输出 / Long rows

无需更新字库。rc27 修复 96 字以上已匹配行不输出的问题；16 个真实字体长文本 PDF 为 14 个完整、2 个部分恢复，发布字符由 286 增至 2316，原字体匹配候选数不变。原有 84 个短文本 DXF 仍为 63/84，21 个部分或未确认。历史 rc26 对应字体 84-PDF 结果仍标记为 rc26，本轮未重跑该批 PDF。详见 [验证记录](VALIDATION.md) 和 [长行逐项证据](LONG_TEXT_VALIDATION.json)。

Reuse unchanged catalogs. rc27 fixes publication of matched rows longer than 96 glyphs. Sixteen new real-font long PDFs yield 14 complete and 2 partial cases, with 286→2316 published characters and unchanged matching-candidate counts. The existing 84 short DXFs remain 63/84 complete; the historical rc26 matching-face PDF batch was not rerun. See [validation](VALIDATION.md) and [long-row evidence](LONG_TEXT_VALIDATION.json).

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
