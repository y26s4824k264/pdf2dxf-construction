# rc35: paint fidelity and downstream scale evidence

## 中文

本轮范围是透明度、虚线和依赖包接入，不是历史全集重跑，也不承诺任意字体 100% 识别。

- 零透明度不再被 `or 1.0` 改成不透明；原图元保留并标记不可见。半透明密集线合并后保留透明度。不可见几何不参与文字和尺寸证据。
- 奇数虚线数组按 PDF 规则重复；非零相位、跨路径段连续性、裁剪前的绘制区间得到保留。未裁剪的三次曲线子段仍为 SPLINE。跨子路径重新开始虚线状态。
- `PDF2DXF_COORDS` XDATA 保存最终验证器的比例状态、是否可建模、单位和页号，包含块内图元。纸面毫米、声明比例、几何检查不通过或 R12 输出均不会因此被当成已确认的工程坐标。
- `DRAWING_TEXT_RUN` 保留逐字符位置，同时记录字符顺序、数量和 SHA-256。下游只合并完整且未改写的字符组；漏字、重复或改字都不合并。可见的非空白字符参与此校验，不凭字典补全文字。

代表图纸使用安装后的 wheel 和 r3 十字库，结果见 [结构化记录](RC35_VALIDATION.json)：

| 样例 | 尺寸证据 | P95 相对误差 | 比例与接入结果 |
|---|---:|---:|---|
| 建筑平面，第 1 页 | 25 条 | 0.1280% | 已校准；规范化和独立图框 DXF 均通过比例门槛 |
| 结构墙柱，第 1 页 | 53 条 | 0.1886% | 已校准；规范化和独立图框 DXF 均通过比例门槛 |
| 给排水目录，第 1 页 | 0 条 | 不适用 | 保持纸面坐标，不可建模；包保留 2 个图片附件，项目明确拒绝仅存 DXF 的导入 |

本地源码和安装包套件各通过 754 项；末次虚线端点修正另通过 20 项绘制回归，三张样例均无零长度虚线数组，无需重转。最终发布提交的跨平台结果以 CI 为准。三个输出 DXF 均审计无错误、无修复，几何验证通过。现有尺寸误差门槛为 0.2%。代表样例没有发布原始图纸、派生图形或本机路径。

边界：部分裁剪的零长度虚线圆点仍报告 `PDF_DASH_CLIPPED_DOT_UNSUPPORTED`，不能宣称已无损恢复。既有复杂曲线裁剪仍可能使用明确报告的折线回退。R12 不支持现代透明度；需要透明度时使用 universal DXF。[DXF 属性支持范围](https://ezdxf.readthedocs.io/en/stable/tutorials/common_graphical_attributes.html)。

## English

This release fixes opacity and dash handling and adds a downstream coordinate contract. It does not rerun the historical corpus or claim universal font recognition.

Zero-opacity geometry stays invisible, merged dense strokes retain alpha, and invisible paths cannot provide glyph or dimension evidence. Odd dash arrays repeat correctly; phase, path continuity and clipping order are retained. Unclipped cubic dash portions remain SPLINEs.

`PDF2DXF_COORDS` stores the saved validator's decision on entities, including block contents. `DRAWING_TEXT_RUN` carries character order, count and a content hash without moving glyphs. A downstream reader can join complete unchanged runs and reject incomplete or edited evidence.

Three representative pages were tested with the installed wheel and all ten r3 catalogs. Architectural and structural pages passed 25 and 53 dimension checks, respectively, with P95 relative errors of 0.1280% and 0.1886% against the existing 0.2% limit. Their normalized and independently saved frame DXFs retain the scale decision. The directory page remains in paper coordinates; its two image sidecars are preserved by the package, and a DXF-only application storage adapter rejects the unsupported import explicitly. The local source and installed-wheel checkpoints each passed 754 tests; the final endpoint-dot correction passed 20 focused paint regressions and does not affect these three samples. CI verifies the final release commit. All three saved DXFs pass audit and geometry validation. No private drawing content is included in this release.

Partially clipped zero-length dash dots remain an explicit unsupported case; existing complex curve clipping may use a reported polyline fallback. R12 cannot preserve modern transparency. Use the universal profile when alpha matters.
