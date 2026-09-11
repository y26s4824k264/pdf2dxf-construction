# rc34 验证记录 / Validation

版本 `2.0.0rc34`。本地 macOS ARM64 / Python 3.12.13：源码和隔离安装 wheel 各 **732 项测试通过**；全库 Ruff **29→0**，并在四个平台/版本的 CI 作业中加入 lint 门槛。精确提交的远端 CI 在发布前核验，见发行页和 [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)。

## 缺字修复与排版证据

| 已知字体样例，同时加载十个字库 | rc33 | rc34 |
| --- | --- | --- |
| 84 个短行完整数 | 69 | 84 |
| 短行恢复字符数 | 1255 | 1310 |
| 16 个长行完整数 | 16 | 16 |
| 长行恢复字符数 | 2320 | 2320 |

此前 15 个不完整短行全部补齐，新增确认 55 字。100 个保存 DXF 重新识别，全部原图元组码保持一致；同样的 100 个原始字体 PDF 重新转换，共恢复 3,630 字，逐字核对原字体 cmap、来源句柄、指纹、DXF 坐标及实际保存 TEXT。最大字形外框误差 **0.000866324 mm**，低于 0.05 mm 审计容差；DXF audit 错误和修复数均为 0。

r3 / v3 字库新增原字体 em 外框与水平字距。原始描边、填充分别记录有效外框，忽略不产生任何笔画的 moveTo；填充外框不包含共线零面积轮廓。全部原有 246,293 条模板、2,288,068 个匹配索引键和码点映射不变。十个来源字体、版权和许可不变。

新增证明仅适用于水平等比例汉字行：至少三个不同、整字标签唯一的完整轮廓，至少一个原本无歧义的候选，字身尺度、基线、原字体字距和连续来源同时一致。布局容差为 0.01 em；轮廓掩码与拓扑仍要求精确一致。整字异名、竞争字母/数字、任意竞争汉字、跨字切分、独立小字行和证据中断仍保持歧义。报告 `font_layout_evidence` 记录字身、基线、字距、父字和所有内部竞争窗口；详细证据最多 32 条，额外行计数单列。

v1/v2 继续完整校验并可读取；它们没有排版尺寸，需下载 r3 或从原字体重建才能启用新增证明。构建缓存必须符合新格式，不能误复用旧 r2。运行识别只读已保存 DXF 和字库，不用 OCR、词义猜测，也不读取 PDF 或原字体。

## 历史图纸部分复测

历史清单共 **4,290 份去重 PDF /12,577 页**。按用户要求停止耗时的全量转换，并等待在途任务自然结束；本轮完成 **4,251 份 PDF 中的 4,253 页**，尚有 **8,324 页未测**，不是全集完成。其中 4,119 份覆盖全部页，132 份只覆盖部分页。原 BIM22 的 22 个源文件哈希/页号包含在历史清单和本次已完成结果中。每个已完成页检查 PDF 哈希、实际代码指纹、十套资源身份、持久化 DXF SHA256、ezdxf audit、原生 TEXT/MTEXT 句柄与内容、图片依赖，以及保存后比例/尺寸报告一致性；结束后再次核对全部已完成 DXF 摘要。

| 已完成范围结果 | 页数/数量 |
| --- | --- |
| 已转换并独立复核 | 4253 页 |
| 转换或保存完整性失败 | 0 页 |
| 通过 model_ready 门槛 | 1072 页 |
| 保留待复核 | 3181 页 |
| 工程比例未确认 | 1698 页 |
| 尺寸误差超门槛 | 1005 页 |
| 原生文字图元逐句柄比较 | 2,608,690 |
| 独立检查的尺寸 | 136,525 |

表中的问题类别可能重叠，不能相加作总页数。`model_ready` 与转换总体状态 `ok/degraded` 是不同字段；完整计数见[历史集覆盖摘要](FULL_CORPUS_VALIDATION.json)。使用 `scale_mode=auto`，不通过强制比例使图纸达标。纸面输出、未知或冲突比例仍须复核；字形 em 尺度仅是文字证据，不替代工程尺寸标定。

早期诊断批次不计入以上页数。期间修复了软蒙版、图片重采样尺寸和裁剪作用域；当时已完成的 1,490 页中，799 页无源图片且无 raw/final IMAGE，确认不受媒体修改影响后保留本轮结果，691 个含图像页全部重转。最终 **3,454 页由最终代码转换，799 页保留经范围核验的本轮结果**，每页实际指纹单列，不将保留页声称为再次转换。私有 PDF、原字体、文件名和路径不公开。已知字体样例完整恢复不代表任意字体达到 100%，部分历史集复测也不是文字准确率统计。

## 图片与裁剪修复

[PyMuPDF 的 Pixmap 契约](https://pymupdf.readthedocs.io/en/latest/pixmap.html)允许颜色空间为空的蒙版仅含 alpha 通道。旧代码删除唯一通道会导致图片遗漏，现保留其样本供合成。图片被高分辨率蒙版重采样时，IMAGE/IMAGEDEF 和像素裁剪现在使用实际 PNG 尺寸，同时保持正确的毫米尺寸。

裁剪通过原生绘制顺序和嵌套 clip/pop 作用域绑定到具体图片，核验绘制、图片与裁剪计数；保留旋转、连续图片各自的裁剪边界，完全不可见的图片不再错误显示。无法确认的裁剪明确报告 SOURCE_GRAPHICS_INCOMPLETE。13 项媒体回归覆盖 8 组像素/尺寸、2 组旋转和连续裁剪、完全裁空以及两种取消信号。

所有 100 个字体 PDF 已用最终代码重新转换并重新审计坐标。新增资料的 26 个含图像抽样页也重新转换，46 个无图片页保留经范围核验的本轮结果。见[修复及范围证据](MEDIA_REPAIR_VALIDATION.json)。

## 本机新增资料抽查

当前 BIM 文件夹比历史清单新增 24 份规范、定额资料，共 8,712 页。本轮另取每份首、中、末页抽查，共 **72 页**，均完成转换及保存后复核，audit 错误/修复和原生文字缺失均为 0；比较 18,073 个原生文字图元。72 页都没有可确认的工程比例，保留待复核。这是抽查，不是 8,712 页全量测试；不混入历史清单已完成页统计。[抽查证据](ADDITIONAL_DOCUMENT_VALIDATION.json)。

## English

Both the source and source-free installed wheel pass **732 tests**. Full-tree Ruff goes from **29 findings to zero**, with lint added to every CI job. The 15 incomplete short cases are resolved: **84/84 short and 16/16 long** known-font fixtures complete with all ten catalogs. Actual reconversion of all 100 original font PDFs restores 3,630 characters. Every glyph is checked against its original font cmap/position and saved TEXT; maximum ink-bounds error is **0.000866324 mm**. Original DXF entities remain intact.

Schema v3 adds em-space ink bounds and advance to unchanged r2 geometry/labels. Raw/fill representations receive appropriate bounds; move-only contours are excluded. The extra proof requires three distinct uniquely labeled whole Han glyphs, an uncontested candidate, uniform scale, common baseline, matching advance and contiguous provenance. Exact masks/topology remain mandatory. Whole aliases, crossing windows, conflicting letters/digits or arbitrary Han, independent small-text rows and discontinuous evidence are rejected. Legacy catalogs remain readable but require rebuilding for layout data. Runtime outline recognition uses persisted DXF/catalogs only, without OCR or source-font/PDF access.

The historical manifest contains **4,290 documents /12,577 pages**. At the user's request, further dispatch stopped and in-flight conversions drained normally. This run completes **4,253 pages from 4,251 PDFs**, leaving **8,324 pages untested**; this is partial coverage, not a complete corpus rerun. Of the tested documents, 4,119 have every page covered and 132 have partial coverage. Completed pages have zero conversion/integrity/audit failures: 1072 are model-ready and 3181 require review. Checks compare 2,608,690 native text entities and 136,525 dimensions. Scale-unconfirmed and dimension-error counts are 1698 and 1005, with possible overlap. Media fixes cover soft masks, resampled image dimensions and native clipping scope. All 691 previously completed media pages were reconverted; 3,454 pages use the final runtime, while 799 verified no-media pages retain actual earlier fingerprints from this run. All 100 font PDFs were reconverted and coordinate-audited using the final runtime. No guessed scale is used and conversion coverage is not text-recognition accuracy.

Separately, 24 newly added standards/reference PDFs contain 8,712 pages. First/middle/last-page sampling checks 72 pages and 18,073 native text entities, with zero conversion/integrity/audit failures. All 72 retain unconfirmed engineering scale. This sample is not exhaustive coverage of the 8,712 pages and is separate from the historical partial run. See [sampling evidence](ADDITIONAL_DOCUMENT_VALIDATION.json).

See [complete evidence](FONT_LAYOUT_VALIDATION.json), [corpus summary](FULL_CORPUS_VALIDATION.json) and [font resources](OPEN_FONT_VALIDATION.json). Private inputs and path-bearing reports are excluded. Five upstream PyMuPDF SWIG deprecation warnings remain, separate from lint findings.
