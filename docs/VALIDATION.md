# rc29 验证记录 / Validation

版本 `2.0.0rc29`；本地 macOS ARM64 / Python 3.12.13。源码 **528 项通过**，新增 36 项闭合部首/拓扑回归。实现前首批 14 个用例在 rc28 上为 **2 失败、12 通过**；两个失败均为应恢复的整字缺失。五条已有弃用警告来自 PyMuPDF SWIG。安装包和精确提交的跨平台结果见发行记录。

## 修复与验证

Jigmo 的“图”整字及其“囗”部首都已精确匹配，旧规则因部首与整字同高而拒绝。rc29 在既有字体锁之后，以同字体康熙部首别名、两个严格嵌套闭环、其余完整路径全部位于内孔、三个独立同行汉字锚点进行有限消歧。任何边界接触、越界、其他标签或额外重叠窗口仍会阻止输出。“建”的“廴”没有封闭内孔，不符合该规则，继续保留歧义。

新增测试覆盖线条/填充 DXF、独立字体锁、原图元组码不变、重复执行、同高独立部首、锚点不足或重复、来源序列断开、垂直错行、整字别名冲突、其他字体的冲突和别名、错误别名字形、开环/自交/退化边界、接触/越界及凹边界穿越。FontTools PointInsidePen 独立确认凹边界反例的所有顶点均在内部，完整线段检查仍正确拒绝。严格包含使用已有 Shapely/GEOS，无新增依赖；没有 OCR、几何修复或原轮廓重写。

| 本轮实测 | rc28 基线 | rc29 |
| --- | --- | --- |
| 十字体对应字库，84 个 PDF 重转 | 82 完整，1306 字 | **82 完整，1308 字** |
| 同时加载十字库，84 个已保存 DXF 重识别 | 63 完整，1244 字 | **63 完整，1245 字** |
| 四字体 97/193 字长行，16 个 PDF 重转 | 16 完整，2320 字 | **16 完整，2320 字** |
| BIM 文件夹全部 22 个 PDF / 22 页重转 | 22 degraded，0 failed | **22 degraded，0 failed** |

对应字库的 Jigmo 线条和填充各补回一个“图”，两个案例仍缺“建”，因此完整案例数没有上升。十字库组合仅填充案例补回“图”；线条案例还有额外冲突。其余 83 个十字库案例的全部既有识别字段与实体库组码保持一致（仅规范化已验证的写入时间），每个案例原始图元组码均不变。

84 个对应字体 PDF 使用相同源文件及 SHA256，逐字对照原字体 cmap、独立 BoundsPen、PDF 生成位置、模板摘要、来源句柄和保存 TEXT。所有原始图元组码与 rc28 一致；字形边界最大误差 **0.000867 mm 以内**，低于该检查的 0.05 mm 门槛。16 个长行 PDF 同样使用完全相同的输入字节，全部 2320 字逐项审计，原始图元组码保持一致，最大边界误差 **0.000431 mm 以内**，TEXT 插入与 FIT 端点检查通过。字体文件仅供独立测试核验，识别运行时不读取。

22 个 BIM PDF 保持 **238 TEXT / 1035 字**；DXF 全部组码除两个 HEADER GUID 外与 rc28 相同。读取、哈希、来源句柄和保存后复验通过，DXF audit 无错误或修复。工程状态仍为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 13/22，九张已标定图仍未通过 0.2% 尺寸误差门槛。没有重跑历史 rc11 的 4290-PDF 语料，也没有证明任意字体或全部工程质量合格。

证据：[本轮轮廓验证](CONTOUR_TOPOLOGY_VALIDATION.json)、[BIM](validation.json)、[开源算法与许可](OPEN_OUTLINE_ALGORITHMS.md)。历史 [rc28 曲线](CURVE_SAMPLING_VALIDATION.json)、[rc27 长行](LONG_TEXT_VALIDATION.json)、[rc26 字库](OPEN_FONT_VALIDATION.json) 保留原版本标识。

## English

rc29 adds a post-lock enclosure proof for a uniquely matched whole Han glyph competing with one radical. The same locked catalog must supply the matching Kangxi alias. Two valid nested rings must strictly contain every remaining full path, supported by three distinct uncontested anchors in the same source row. Boundary contact, crossing edges, extra interpretations and cross-font conflicts remain rejected. Jigmo 图 improves; the open radical in 建 stays unresolved.

All **528 source tests pass**, including 36 new regressions. Before implementation, the initial 14-case DXF suite produced two failures and 12 passes on rc28. Tests cover persisted stroke/fill DXFs, unchanged source tags, idempotence, independent locking, absent/wrong/foreign aliases, ambiguity, row breaks, invalid rings and concave crossings. FontTools independently verifies the point-containment counterexample; Shapely/GEOS checks entire edges. No dependency, OCR or geometry repair is added.

Fresh conversions of all 84 matching-face PDFs retain **82 complete cases**, while published characters increase **1306→1308**. Each new Jigmo case still lacks 建. Recognition of 84 saved DXFs with all ten catalogs retains **63 complete cases**, increasing **1244→1245**; only the filled Jigmo case qualifies. Source geometry is unchanged in every case. The other 83 retain every existing report field and entitydb tag except validated writer time.

All 16 long PDFs remain complete with **2320 characters**. The matching-face and long-PDF audits verify original PDF hashes, font cmap/BoundsPen positions, saved source handles, template digests and TEXT placement. Maximum glyph bounds errors are below **0.000867 mm** and **0.000431 mm**, respectively, within the 0.05 mm audit threshold. All original entity tags remain unchanged from rc28.

All 22 BIM PDFs are reconverted: **238 TEXT /1035 characters**, no conversion/audit failures, and identical DXF group pairs except two HEADER GUIDs. All remain **degraded**: scale states 9 calibrated, 6 declared approximate, 6 paper, 1 unknown; geometry valid 13/22. Nine calibrated drawings still exceed the 0.2% dimension gate. The historical 4290-PDF corpus is not rerun. These results establish bounded regressions, not arbitrary-font recognition or complete engineering acceptance.
