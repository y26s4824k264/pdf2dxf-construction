# rc31 验证记录 / Validation

版本 `2.0.0rc31`；本地 macOS ARM64 / Python 3.12.13。源码 **631 项通过**，新增 65 项回归。五条已有弃用警告来自 PyMuPDF SWIG；安装包与精确提交的跨平台执行结果见发行记录。

## 100% 的范围

**指定对应字体字库的 84 个既有 PDF 样例，现在全部完整恢复，共 1310 字。** 每个输出字形均与原字体 cmap、独立 BoundsPen、生成位置、模板摘要和来源句柄核对。这里的 100% 仅表示该组已知字体样例完整，不代表任意字体、全部汉字组合或工程质量均通过。

| 本轮实测 | rc30 基线 | rc31 |
| --- | --- | --- |
| 对应字体字库，84 个原 PDF 重转 | 82 完整，1308 字 | **84 完整，1310 字** |
| 同时加载十字库，84 个已保存 DXF 重识别 | 67 完整，1253 字 | **69 完整，1255 字** |
| 原有四字体 97/193 字长行，16 个 PDF 重转 | 16 完整，2320 字 | **16 完整，2320 字** |
| 新增含“建”的 Jigmo 97/193 字长行，12 个 PDF | 0 完整，1728 字 | **12 完整，1740 字** |
| BIM 文件夹全部 22 个 PDF / 22 页重转 | 22 degraded，0 failed | **22 degraded，0 failed** |

组合字库仍有 15 个不完整样例：14 个无法建立独立字体锁，另 1 个受到较大的内部标点轮廓竞争。所有 20 个 A–Z/a–z 完整字母样例保持通过。选择图纸实际字体的字库更有效；不能为凑齐输出而忽略已知冲突。

## 修复与独立证据

Jigmo“建”的整字与“廴”正字轮廓都能精确匹配，旧规则只处理全封闭部首。新规则检查半包围结构：部首及其余轮廓均为有效多边形，所有实际多边形与部首严格分离；两部分凸包内部重叠且互不包含，其余部分仅超出部首边界的一侧。仍需独立字体锁、正字模板和三个不同的原始无冲突汉字锚点。

兼容部首“⼵”和正字“廴”在该字体中使用不同轮廓。Unicode NFKC 仅提供部首身份；实际几何须精确匹配同字体的正字 cmap 模板。封闭内孔规则继续核对原有康熙别名字形。凸包仅作为临时几何证据，不改写、修复或简化任何原始路径；复用既有 Shapely/GEOS，无新增运行时依赖或 OCR。

新增长行测试暴露了“图建”和“建图”的顺序问题，现采用有界的逐轮确认：只有上一轮已确认、且绑定实际证明字体的字形可以连接下一轮证据；任何新字均不能充当独立锚点。每个候选仍须在最多 96 个邻接字形中找到三个原始锚点，最多 96 轮，不能循环自证或跨字体借用确认结果。详情最多 32 条，另记截断数量；193 字末尾案例可能省略“建”的详细判断记录，但其 TEXT 来源、字形摘要和独立位置核验仍完整保留。

初始 25 个 DXF 用例在 rc30 上为 **6 失败、19 通过**，六个失败均复现漏字。后续七个依赖链用例在连接修复前为 **5 失败、2 通过**；跨字体连接反例在绑定字体前也能复现一次错误输出。最终 65 项覆盖描边/填充、首中末位置、别名字形差异、正字缺失、非部首汉字、重叠/接触/无效多边形、旋转/统一缩放、字体及来源边界、远处字体锁、循环举证拒绝、长链预算、原图元保持与幂等。94 字候选链仅确认仍能在 96 字窗口内找到三个原始锚点的前 93 字。

84 个对应字体 PDF 使用相同输入 SHA256，原始图元组码与 rc30 一致；最大字形边界误差 **0.000867 mm 以内**。组合字库新增的两个 Jigmo 案例共 14 个输出字形全部独立核验，最大误差 **0.000088 mm 以内**。其余 82 个案例的全部既有识别字段与实体库组码保持一致，仅排除新增/变化的部首诊断字段和已验证的写入时间；84 个案例原始图元组码均不变。

16 个既有长行 PDF 的全部 2320 字、TEXT 插入点及 FIT 端点再次核验，最大边界误差 **0.000431 mm 以内**。新增 12 个长行 PDF 由“筑结构平面图”及一个“建”构成，覆盖 97/193 字、首/中/末、描边/填充。隔离安装的 rc30 wheel 与当前代码转换完全相同的输入字节；全部 1740 字逐项核对原字体位置、摘要、来源句柄和保存 TEXT 对齐点，原始几何不变。所有字形边界审计门槛为 0.05 mm，逐例测量见 JSON。源字体只用于生成和独立审计，不供识别运行时读取。

22 份 BIM PDF 保持 **238 TEXT / 1035 字**，全部保存 DXF 组码除两个 HEADER GUID 外与 rc30 一致，读取、哈希、来源句柄和保存后复验通过，DXF audit 无错误或修复。工程状态仍为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 13/22，九张已标定图仍未通过 0.2% 尺寸误差门槛。历史 rc11 的 4290-PDF 语料未重跑；不能把可读取 DXF 或字体样例通过等同于工程验收。

证据：[本轮逐项验证](HALF_ENCLOSURE_VALIDATION.json)、[BIM](validation.json)、[开源算法](OPEN_OUTLINE_ALGORITHMS.md)。历史 [rc30 来源行](OUTLINE_ROW_VALIDATION.json)、[rc29 拓扑](CONTOUR_TOPOLOGY_VALIDATION.json)、[rc28 曲线](CURVE_SAMPLING_VALIDATION.json)、[rc27 长行](LONG_TEXT_VALIDATION.json) 保留原版本标识。r2 字库无需重下。

## English

The 84 existing **matching-face PDF probes now complete 84/84, with 1310 independently audited characters**. This bounded 100% result applies only to those known-font fixtures, not arbitrary fonts, all character combinations or engineering acceptance. All-ten-catalog saved DXFs improve **67→69 complete, 1253→1255 characters**. Fourteen remaining cases lack an independent font lock; one retains a large internal punctuation conflict. All 20 full alphabet probes remain complete.

Jigmo 建 now passes a half-enclosure proof: the exact canonical radical and remaining valid polygons are disjoint, their convex hull interiors overlap without containment, and remaining bounds protrude through exactly one radical side. Unicode NFKC establishes the radical identity; the actual canonical cmap outline establishes its geometry. The compatibility radical may use a different drawing. Existing closed-counter alias checks remain unchanged. Shapely/GEOS supplies temporary spatial evidence without changing source paths or adding a dependency.

Only earlier-round verified results may connect later evidence, restricted to the catalog that actually proved them. New results never supply independent anchors. Each proof must reach three distinct original uncontested Han anchors within 96 adjacent glyphs; at most 96 rounds prevent unbounded work. A 94-proposal chain correctly stops after 93 when its original anchors leave the local window. Bounded detail may omit a late glyph, while its TEXT provenance, template digest and independent position audit remain complete.

All **631 source tests pass**, including 65 new regressions. The initial 25 cases produced six missing-text failures on rc30. Seven later chaining cases produced five failures before that fix; an additional cross-font bridge case exposed incorrect evidence transfer. Tests cover positive and negative geometry, font identity, source boundaries, independent anchors, bounded chains, unchanged source entities and idempotence.

All 84 matching-face PDFs reuse identical input bytes and preserve original geometry; maximum bounds error is below **0.000867 mm**. The two changed all-ten-catalog cases independently verify all 14 output glyphs below **0.000088 mm**. The other 82 retain existing recognition fields/entity tags except intentional radical diagnostics and validated writer time. All 84 preserve source entity tags.

The 16 existing long PDFs retain **2320 characters**, with original-font bounds, digests, handles and TEXT endpoints checked below **0.000431 mm**. Twelve new Jigmo 97/193-glyph PDFs place one 建 at the start/middle/end of stroke/fill rows. Against an isolated installed rc30 baseline using identical PDFs, they improve **0→12 complete, 1728→1740 characters**, preserving original geometry. All glyphs and TEXT alignment endpoints are independently audited within 0.05 mm; fonts are not accessed at recognition time.

All 22 BIM PDFs are rerun, retaining **238 TEXT /1035 characters**, zero conversion/audit failures and identical DXF group pairs except two HEADER GUIDs. All remain degraded: 9 calibrated, 6 declared approximate, 6 paper, 1 unknown; geometry valid 13/22. Nine calibrated drawings still exceed the 0.2% dimension gate. The historical 4290-PDF corpus was not rerun. Existing r2 resource files remain byte-identical.
