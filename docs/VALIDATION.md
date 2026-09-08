# rc28 验证记录 / Validation

版本 `2.0.0rc28`；本地 macOS ARM64 / Python 3.12.13。源码 **492 项通过**，新增 23 项采样回归；冻结 rc27 对同一组新增测试为 **7 失败、16 通过**。针对性采样/几何测试 41 项通过，修改文件 Ruff 通过。安装包及精确提交的跨平台结果见发行记录；五条弃用警告来自 PyMuPDF SWIG。

## 缺陷与修复边界

同一原字体 B 在不同 PDF 位置，曲线采样数为 8.9999829965 与 9.0000771032；向上取整变为 9 与 10，造成内孔路径 39/40 点和一个像素的掩码差异。将距整数不超过 0.0001 的采样数对齐后，两处都命中现有 r2 的 B 模板。转换器和字库构建器共用纯数学函数；原控制点、坐标、配置容差不变，采样点数在这个有界条件下可能改变。没有扩大匹配掩码容差，也没有调用 OCR。

需从原 PDF 重新转换。已有 DXF 的轮廓识别代码未修改，不会补造旧 DXF 中的曲线信息。

## 本轮实测

| 检查 | 基线 | rc28 |
| --- | --- | --- |
| 四字体长行 PDF | rc27：14/16 完整，2316 字 | **16/16 完整，2320 字** |
| 十字体、对应字库 PDF | rc26：82/84 完整，1306 字 | **82/84，1306 字** |
| 十字库组合短行 DXF | rc26/27：63/84 完整，1244 字 | **63/84，1244 字** |
| BIM PDF | rc27：22 degraded、0 failed | **22 degraded、0 failed** |

长行 PDF 使用与 rc27 完全相同的输入字节和 SHA256。每个输出字形按原字体 cmap/BoundsPen、位置、来源句柄、模板摘要、保存 TEXT 及 FIT 端点独立核验。四处缺失的 B 全部补齐。仅四个 HATCH 的采样路径改变；其余原图元组码不变。四个轮廓的新旧边界最大距离 **0.000992 mm 以内**，独立对照 PDF 三次曲线（每段 2001 点）最大偏差由约 0.001115 mm 变为 **0.001188 mm 以内**，仍小于原转换容差 0.12 pt / 0.042334 mm。此结果明确包含采样几何变化，不宣称输出逐字节无损。

84 个对应字体 PDF 重新从原 PDF 转换，全部输出逐字核对，原图元组码保持一致；仍有两个 Jigmo 案例保留歧义。84 个已保存短 DXF 的全部既有识别字段和实体库组码保持一致（只排除验证过的写入时间），20 个完整英文字母样例全部通过。

22 份 BIM 实图覆盖本地 drawings 文件夹全部 22 个 PDF / 22 页。238 条恢复 TEXT / 1035 字不变，保存组码除两个 HEADER GUID 外与 rc27 一致。比例状态仍为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 13/22，九张已标定图仍未通过 0.2% 尺寸误差门槛，全部 22 张仍 degraded。没有重跑历史 rc11 的 4290-PDF 全语料。

证据：[曲线与字体](CURVE_SAMPLING_VALIDATION.json)、[BIM](validation.json)。[rc27 长行证据](LONG_TEXT_VALIDATION.json)、[rc26 字库证据](OPEN_FONT_VALIDATION.json) 保留其原版本，不冒充本轮全量结果。

## English

rc28 shares a bounded numeric sample-count rule between PDF conversion and font catalog building. An ideal count near 9 was observed as 8.999983 versus 9.000077 at two positions, producing different polylines and masks after ceil. Only counts within 0.0001 of an integer are snapped. Curve controls, coordinates, configured tolerance, exact glyph lookup, ambiguity checks and r2 catalogs remain unchanged. Reconvert original PDFs; existing flattened DXF curves are not inferred or rewritten.

The 23 new tests produce **7 failures and 16 passes on rc27**, then all pass after the fix. Source tests pass **492**, focused sampling/geometry checks pass 41, and scoped Ruff passes. Wheel and exact-commit platform evidence is recorded in the release.

The same 16 long-PDF byte streams improve **14/16→16/16 complete**, restoring four B characters (**2316→2320**). Every glyph is checked against original font labels/bounds/position and saved handles, digests, TEXT and FIT endpoints. Four HATCH sampling paths change; all other source entity tags are preserved. Old/new boundaries differ by less than **0.000992 mm**. Independent dense PDF cubic boundaries give maximum source error below **0.001188 mm** (previously about 0.001115 mm), within the original 0.12 pt / 0.042334 mm tolerance. This discloses actual sampling changes rather than claiming byte-identical geometry.

All 84 matching-face PDFs are reconverted and independently audited: **82 complete, 1306 characters**, unchanged original tags; two Jigmo cases remain partial. The 84 saved DXFs with all ten catalogs retain every existing recognition field and entity tag except validated writer time: **63 complete, 1244 characters**, all 20 full-alphabet cases complete.

All 22 local BIM PDFs are reconverted: **238 TEXT /1035 characters**, saved group pairs unchanged except two HEADER GUIDs, and zero conversion/audit failures. All remain degraded: 9 calibrated, 6 declared approximate, 6 paper, 1 unknown; geometry valid 13/22, and nine calibrated sheets still exceed the 0.2% dimension gate. Historical 4290-PDF results were not rerun. These corpora do not establish recognition for arbitrary fonts or full engineering acceptance.
