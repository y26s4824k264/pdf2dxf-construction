# rc27 验证记录 / Validation

版本：`2.0.0rc27`。本地环境：macOS ARM64 / Python 3.12.13。

## 修复内容

rc26 中，连续行有 97 个精确匹配字符、字体也已确认时，仍因单条 TEXT 的 96 字限制而整行不输出。独立保存 DXF 复现：96 字输出 96 字，97 和 200 字均输出 0；候选字数及字体锁定均正确。

rc27 只在匹配、歧义判断和字体确认结束后，按原顺序将长行分成不超过 96 个 Unicode 码点的 TEXT。97 字分为 95+2，193 字为 96+95+2，避免孤立单字尾段。每段继续独立通过原有文字共识检查；不足依据的数字段、未知字形和同形冲突保留轮廓。段间不跨原始识别行拼接，每段的 FIT 插入/对齐点、字形指纹和源句柄取自自身的实际轮廓。短行输出保持原样，原几何和比例门槛不变。

新增 `long_text_runs_split` / `long_text_segments` 统计被分段原行与候选段数，包含后续未发布段；最终以 `accepted` 和保存 DXF 的 TEXT 为准。本轮不改变字体匹配、锚点和来源行复核阈值，不使用 OCR。

## 回归与真实字体证据

新增 **26 项回归**。同一批最终测试在冻结 rc26 代码上为 **21 项失败、5 项通过**；失败均对应长行漏输出。修复后全量源码 **469 项通过**，针对性 117 项通过，修改文件 Ruff 通过。覆盖 96/97/192/193/289 字、中英文、描边/填充、补充平面汉字、段尾、源句柄不重不漏、定位点、几何保留、幂等以及未知/歧义/数字段拒绝。安装包与精确提交的 CI 结果见本版本发行记录。五条 DeprecationWarning 来自 PyMuPDF SWIG。

使用思源黑体、思源宋体、DejaVu Sans、DejaVu Serif 四个真实开源字体，分别生成 97 / 193 字的 20 pt 描边与贝塞尔填充 PDF，共 **16 个新样例、2320 个源字符**。页面按实际字体 advance 展宽，运行时只接收 PDF 和原有 r2 字库；原字体用于生成及独立核验。

| 长文本 PDF | 冻结 rc26 | rc27 |
| --- | ---: | ---: |
| 完整恢复 | 0/16 | **14/16** |
| 输出字符 | 286 | **2316** |
| 字形匹配候选 | 与 rc27 相同 | 与 rc26 相同 |
| 原始模型空间实体变化 | — | **0** |

新增输出 **2030 个已匹配字符**。这改善了匹配结果转 TEXT 的长行处理，不代表字形匹配准确率提高。所有旧输出字符保留；每个新旧输出字形均按原字体 cmap/BoundsPen 和生成位置核对，逐项检查字形摘要、源句柄、保存 TEXT 以及每段 FIT 两个定位点。2316 个字形最大边界差为 **0.000431 mm 以内**，审计容差 0.05 mm。原模型空间全部实体组码在去除恢复层/XDATA 后与冻结 rc26 副本一致；保存 DXF 审计错误与修复均为 0。

两个 DejaVu Sans 填充样例仍部分恢复：97 字缺第 54 字的 `B`，193 字缺第 54/106/158 字的 `B`（一基序号）。这些字符在 rc26 中也未匹配，两版候选数和这两例输出完全相同。原轮廓继续保留，本轮未更改匹配阈值以补出它们。逐项预期、实际、缺字位置及来源核验见 [LONG_TEXT_VALIDATION.json](LONG_TEXT_VALIDATION.json)。

原有 **84 个短文本 DXF**使用全部十个 r2 字库重新识别：每个既有报告字段与 rc26 完全一致，新增两个长行计数均为 0。全部实体库组码也一致，仅排除已验证格式的 ezdxf 保存时间，包括文字、原几何、块和资源；审计错误/修复为 0。仍为 **63/84 完整，21 个部分或未确认，1244 字符**，全部 **20 个完整 52 字母样例通过**。此项是保存 DXF 回归，缓存一次已校验字库，不是重新转换 84 个 PDF。

## BIM 实图与分发

本轮用不变的 r2 core 资源重新转换 **22 PDF / 22 页**，全部产出真实保存 DXF，转换失败 0；全部仍为 `degraded`，CLI 退出码 5。输入 SHA256/预检、保存输出 SHA256、TEXT 句柄及尺寸验证重新核对。所有 DXF 组码与 rc26 一致，仅两个 HEADER GUID 不同。

结果保持 **238 TEXT / 1035 字符**；内置精确匹配 1042，外部候选 262，外部字体锁定及发布字符均为 0。比例为 9 calibrated、6 declared_approximate、6 paper、1 unknown；geometry_valid 为 **13/22**，九份已标定图仍超出 **0.2%** 尺寸误差门槛。未放宽工程质量要求，见[脱敏摘要](validation.json)。

主源码、wheel、sdist 排除私有 PDF/DXF、外部字体/字库与个人路径。两个 r2 ZIP、245496 个原模板与 797 个填充表示不变，无需重新下载。隔离安装包另取四个新长行 PDF，用下载的字库包正常加载，并验证 worker 从 site-packages 导入；结果在发行记录中单列。

CI 覆盖 Ubuntu/Python 3.10、Ubuntu/3.13、macOS/3.12、Windows/3.12 的源码和隔离安装包。真实字库、长行及 BIM 语料为本地验证，不表示各 CI 平台运行了这些资源。历史 rc26 的 **82/84 对应字体 PDF**、rc25 加载性能和 rc11 的 **4290 PDF / 12577 页**保留原版本标记，本轮未重跑这些批次。当前仍为预发布，不声明任意字体、所有长行或工程质量全部通过。

## English

rc27 fixes already matched long outline rows disappearing at the 96-glyph TEXT limit. On frozen rc26, 96 confirmed glyphs produce 96 characters, while 97 and 200 produce zero despite correct matching and font locks. After all existing matching/conflict/lock checks, rc27 emits bounded TEXT segments in original order. Lengths 97 and 193 become 95+2 and 96+95+2. Each segment retains its own publication-consensus gate, glyph source handles, fingerprints and FIT endpoints. Unknown/ambiguous glyphs and unsupported numeric segments remain geometry. Matching and scale thresholds are unchanged; no OCR is used.

Twenty-six added regressions give **21 failures and five passes on frozen rc26**, then pass after the fix. The source suite passes **469 tests**, focused checks pass 117, and scoped Ruff passes. Isolated-wheel and exact-commit CI results are recorded in the release.

Four real fonts (Source Han Sans/Serif, DejaVu Sans/Serif), two lengths (97/193) and stroke/filled-Bezier PDF paths produce **16 long-text cases containing 2320 source characters**. Complete cases improve **0/16→14/16**, and published characters **286→2316**, adding **2030** without changing matching-candidate counts. Every output glyph is independently checked against original cmap/BoundsPen at its generated position, with source handles, digests, persisted TEXT and segment endpoints. Maximum glyph bbox error is below **0.000431 mm** against a 0.05 mm audit tolerance. Original entity tags are preserved; DXF audits have zero errors/fixes.

Two DejaVu Sans filled cases remain partial: `B` at positions 54, or 54/106/158 (one-based). These already fail to match on rc26; both candidate counts and these two outputs are unchanged. Their outlines remain intact. This release improves publication of already matched text, not glyph-matching accuracy. [Detailed evidence](LONG_TEXT_VALIDATION.json) discloses all expected/actual text and missing positions.

All **84 existing short-DXF** recognition reports retain every prior field, with two new counters at zero. Every entitydb tag matches rc26 except the validated writer timestamp. Results remain **63/84 complete, 1244 characters**, including all **20 complete alphabet probes**. This uses cached validated catalogs and is not a rerun of 84 PDFs.

The fresh **22-PDF BIM batch** produces all DXFs but remains degraded (exit 5): **238 TEXT / 1035 characters**, 262 external candidates, zero external locks/characters. All saved group pairs match rc26 except two HEADER GUIDs. Geometry gates pass **13/22**; nine calibrated sheets still exceed the **0.2%** dimension-error gate. Input/output hashes, actual text handles and dimension evidence are verified. See the [sanitized summary](validation.json).

Existing r2 resources remain byte-identical. Four installed-wheel long-PDF checks use normal downloaded-bundle loading and source-free worker imports; release records report their results separately. Cross-platform CI tests source and installed wheels; real-font/BIM resources are local checks. Historical rc26 matching-face PDFs, rc25 performance and rc11 full-corpus results were not rerun. Arbitrary fonts, all long rows and full engineering acceptance remain unproven.
