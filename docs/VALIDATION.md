# rc32 验证记录 / Validation

版本 `2.0.0rc32`，本地 macOS ARM64 / Python 3.12.13。源码 **691 项通过**，新增 60 项回归；五条已有弃用警告来自 PyMuPDF SWIG。安装包及精确提交的 CI 结果见发行记录。

| 本轮范围 | rc31 基线 | rc32 |
| --- | --- | --- |
| 十字库、16 个真实字体 97/193 字长行 | 8 完整，2226 字 | **16 完整，2320 字** |
| 十字库、84 个保存短行 DXF | 69 完整，1255 字 | **69 完整，1255 字** |
| 新选历史及本机 PDF，12 页实际转换 | 1 ok，11 degraded | **1 ok，11 degraded** |

16 个长行 PDF 是四个真实开源字体的描边/填充样例，全部使用原 PDF SHA256。rc31 对相同保存 DXF 加载十字库的结果为基线；rc32 重新转换原 PDF。每个字均与原字体 cmap、独立 BoundsPen 位置、来源句柄和模板摘要核对，全部 TEXT 插入点/FIT 端点核验通过，最大边界误差 **0.000430637 mm**；原始图元组码与 rc31 相同。不是 16 份未经标注的工程图均已识别。

短行 84 个 DXF 的全部原图元、保存实体库以及既有识别字段保持一致；仍有 15 个不完整样例，14 个无独立字体锁、1 个有较大内部标点竞争。没有放宽近似匹配、冲突、独立锚点或尺寸门槛。

## 历史语料与本机 PDF

在 Downloads、Desktop、Documents、Code 四个目录搜索到 6101 个 PDF 路径；不是整台机器所有位置的普查。以目录层次和确定性散列顺序选取 64 份历史文件及 32 个其他路径，内容去重后为 **94 份（64 历史、30 其他）**。检查首/中/末代表页，共 **155 页**，无读取错误。记录页尺寸、旋转、原生文字、矢量路径、图片及字体元数据；这一步不等同于转换。

从中另选 6 个历史页、6 个新增本机页，使用正常 core r2 字库、原页码和相同请求，分别运行隔离安装 rc31 与当前源码。12 页均生成 DXF。逐一复验源文件及所有产物 SHA256、保存报告、比例误差、全部文字和 DXF 组码（仅两个 HEADER GUID 可变）。共比较 **6197364 个组码对、2668 个文字实体**，读取审计错误和修复均为 0。

这 12 页为 **1 ok、11 degraded**：3 calibrated（其中 2 页未通过 0.2% 尺寸误差门槛）、2 paper、7 unknown。几何通过 10/12。外部字体锁和新增轮廓文本均为 0，因此不能称为文字完整恢复。未确认的轮廓和工程比例继续保留。私有 PDF、原字体、文件名及完整路径不进入公开包；公开证据使用散列案例标识。

历史全部 4290 份 /12577 页未重跑；原有 BIM22、84 个对应字体 PDF 及 12 个含“建”的长行 PDF 也未重跑。本轮仅报告上述实际覆盖，rc31 的 84/84 结果保留在[历史证据](HALF_ENCLOSURE_VALIDATION.json)。

## 回归与算法边界

旧版本对最终 60 项新回归为 **36 失败、24 通过**，36 项均为首/中/末位置的真实漏字复现。修复仅将“整行长度不得超过 96”改为“每个候选使用最多 96 字的局部窗口”。覆盖单字库汉字片段、多字库汉字/英文、描边/填充、97/193 字、来源断裂、窗口外锚点、原图元与幂等。短行判定不变，新恢复字不提供独立锚点。详见[逐例证据](LONG_ROW_WINDOW_VALIDATION.json)。

## English

All **691 source tests pass**, including 60 new regressions. Sixteen 97/193-character PDFs from four real fonts, with all ten catalogs, improve **8→16 complete and 2226→2320 characters**. rc31 baseline recognition uses the same saved DXFs; rc32 reconverts the unchanged PDFs. Every character is checked against original cmap/BoundsPen positions, handles, mask digests and saved TEXT endpoints; source geometry is preserved. The 84 short DXFs retain 69/84 completeness and existing entity/report fields.

A search of four local roots lists 6101 PDF paths. Deterministic directory-stratified selection and content deduplication inspect **94 documents /155 representative pages** without read errors; this is metadata/content inspection, not full conversion. Twelve selected historical/additional pages are converted using identical requests against isolated rc31 and current code. All generate DXF: **1 ok, 11 degraded**; scales are 3 calibrated (2 fail the 0.2% dimension gate), 2 paper and 7 unknown. Geometry passes 10/12. All source/artifact hashes, saved validations, 6197364 group pairs and 2668 TEXT/MTEXT entities are checked. External font locks and new outline text remain zero. Private drawings are not published.

The corrected new-test baseline yields **36 missing-text failures and 24 passes**. Local 96-glyph windows retain geometry, ambiguity and independent-anchor requirements. Historical 4290-document/12577-page conversion, BIM22, 84 matching-face PDFs and twelve long 建 PDFs are not rerun. Reuse unchanged r2 resources. The historical 84/84 result does not imply universal font accuracy.
