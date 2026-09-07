# PDF2DXF Construction

**简体中文** | [English](README.en.md)

[![Package checks](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml/badge.svg)](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)

版本：`2.0.0rc20`（预发布）。

面向施工图的独立 Python PDF→DXF 转换包，输出真实、可读取、持久化的 DXF，提供轮廓文字恢复与比例证据报告。图框拆分与 BIM 建模由下游 DXF 流程负责。Python 代码不需要 CAD 程序，PyMuPDF、NumPy、OpenCV 等依赖仍使用原生二进制 wheel。轮廓文字恢复只读取已保存的 DXF 图元和持久化 `.p2dfont`，不使用 OCR、ONNX Runtime 或 PDF 像素。FontTools 只负责预先把用户提供的 OpenType 轮廓字体编译为字库；转换时不再打开字体文件。

项目采用 [AGPL-3.0-only](LICENSE)，支持遵守许可证条件的使用、修改、商业使用和再分发。公开仓库与安装包见 [GitHub](https://github.com/y26s4824k264/pdf2dxf-construction) / [Releases](https://github.com/y26s4824k264/pdf2dxf-construction/releases)。第三方依赖与外部字体保留其原有许可，详见 [NOTICE](NOTICE) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 安装与使用

要求 Python 3.10+；本轮本地验证 macOS ARM64 / Python 3.12。最新跨平台执行结果见上方 CI 与[验证记录](docs/VALIDATION.md)。建议使用独立虚拟环境，以下为 macOS/Linux 命令；Windows 对应可执行文件位于 `.venv\Scripts\`：

```sh
git clone https://github.com/y26s4824k264/pdf2dxf-construction.git
cd pdf2dxf-construction
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pdf2dxf convert input.pdf -o output/drawing.dxf --pages 1
```

无系统字体的服务器若需要 `--emit-r12`，安装 `'.[render]'`，提供 MTEXT 拆分所需的字体度量。此时使用 Matplotlib 自带字体并报告 `R12_FONT_METRICS_FALLBACK`，中文字体外观仍需复核；通用 DXF 保留原生 MTEXT。项目不内置系统字体文件。

## 可选开源字库

rc18 新增思源黑体/宋体、DejaVu、Jigmo 和遍黑体共 10 个可下载字库。Jigmo 字库并集与 Unicode 17 官方表对齐，覆盖基本区、扩展 A–J 和兼容区全部 102,998 个已分配汉字码点。字体、字重和轮廓采样仍影响实际识别；覆盖不等于任意字体识别成功。

下载、许可证、`--outline-font-bundle` 用法和可复现构建见 [开源字库说明](docs/OPEN_FONTS.md)，完整/部分/未确认样例见 [真实字体验证](docs/OPEN_FONT_VALIDATION.json)。资源包独立于 Python 主包，转换时不联网。

## 从 OpenType 字体构建完整映射字库

支持从 TTF、OTF、TTC、OTC 的任意 face 生成持久化字库。集合字体先列出 face，再选择索引：

```sh
.venv/bin/pdf2dxf font-catalog faces /path/to/font.ttc
.venv/bin/pdf2dxf font-catalog build /path/to/font.ttc \
  --face-index 3 --charset chinese -o catalogs/font-face-3.p2dfont
.venv/bin/pdf2dxf font-catalog inspect catalogs/font-face-3.p2dfont
```

默认 `chinese` 范围按 Unicode 17.0 覆盖统一汉字及扩展 A–J、兼容汉字、部首、笔画、注音符号、CJK 标点/符号和可打印 ASCII（含 A–Z、a–z）。`--charset english` 单独构建可打印 ASCII 字库；`--charset all` 保存字体中全部有轮廓的 Unicode 映射。只收入该字体实际映射且具有二维轮廓的字符。兼容码位按单字符 NFKC 归一为标准文本；不能归一的同形异字保持歧义，不发布。

`font-catalog inspect` 会列出 52 个英文字母的覆盖和缺字，并按汉字区段报告数量。识别条件与范围见[字符支持说明](docs/CHARACTER_SUPPORT.md)。

转换时可重复传入多个不同字体或 face 的字库：

```sh
.venv/bin/pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required \
  --outline-font-catalog catalogs/font-face-3.p2dfont \
  --outline-font-catalog catalogs/another-font.p2dfont \
  --scale-mode declared
```

字库先用至少 3 个相邻且互不相同的汉字、4 个相邻且不同的英文字母（不同字母按不区分大小写计数），或 3 个内置人工审核汉字锚点精确匹配锁定字体。纯英文无需汉字锚点；输出保留大小写。锁定后才允许对应字库的连续文字写入 `TEXT`。匹配要求归一后的 56×56 掩码、轮廓数和闭合拓扑完全一致，并逐个候选复核宽高比；不做近邻猜字。跨字库冲突、无法区分的同形异字、重叠切分、证据不足、孤立单字和未知轮廓保留为几何。

`.p2dfont` 只含 Unicode 码位、拓扑、归一化掩码、几组曲线离散指纹和来源字体 SHA256，不嵌入字体程序。生成后可移走字体文件，转换仍可运行。每个字体文件只覆盖它自身具有的字形；要覆盖多种图纸字体，应分别构建并重复传入对应字库。

将轮廓中文恢复为可编辑文字，并在证据允许时按唯一题栏比例等比放大：

```sh
.venv/bin/pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required --scale-mode declared
```

流程先生成并保存纸面 DXF，再读取其中带 PDF 来源 XDATA 的 `LINE` / `LWPOLYLINE`；加载外部字库时也读取纯填充 `HATCH` 的闭合折线边界。每个字形按平移与统一缩放归一化，同时核对栅格掩码、轮廓数量、闭合拓扑、点数和源绘制顺序。内置字典要求人工复核标签和多份源 PDF 的一致性；外部字库要求 cmap 来源与上述字体锁定证据。连续结果至少含两个汉字、构成完整 `1:n`，或在字体锁定后至少含两个中英文字母/汉字，才写入 `TEXT`。

`--outline-chinese auto` 在字典缺失或损坏时保留原轮廓并写警告；`required` 会明确失败。已确认文字写入 `PDF_TEXT_RECOVERED_NOOCR` 并带 `PDF2DXF_GLYPH` XDATA；对应原轮廓和填充默认移入关闭的 `PDF_OUTLINE_BACKUP`，仍可追溯。单字、未知、歧义或不连续候选继续保持原几何。重复运行不会重复插入文字；`keep` 模式下即使用户修改了已恢复文本，也按恢复位置保留该修改。

确认只需要纸面坐标时：

```sh
pdf2dxf convert input.pdf -o output/drawing.dxf --scale-mode page
```

已人工确认图纸全页比例为 1:100，输出单位为米时：

```sh
pdf2dxf convert input.pdf -o output/drawing.dxf --scale-mode manual --manual-scale 100 --units m
```

`manual_scale` 表示纸面毫米到实际毫米的统一倍率。`declared` 只在独立尺寸证据未确认、仅检测到一个独立比例且不存在尺寸冲突或表格/说明页证据时使用该倍率；结果标记为 `declared_approximate`，不冒充工程比例已确认。多比例图纸不能套用一个全页比例。没有可靠标定证据时输出保留纸面坐标，默认毫米；`--units` 仅换算坐标单位，不证明工程比例。旋转、CropBox、原生文字和矢量轮廓保留。

```python
from pdf2dxf_stable import Converter, ConversionRequest
result = Converter().convert('input.pdf', 'output/drawing.dxf', ConversionRequest())
print(result.status, result.report_path)
```

## 报告与能力边界

- `geometry_valid`：DXF 结构、已发现的几何转换错误和外部图片检查；不等于逐实体视觉保真证明。
- `scale_status`：`unknown` / `paper` / `declared_approximate` / `user_confirmed` / `calibrated`。
- `model_ready`：必须通过几何门槛且比例已确认，自动标定还要求有可复核尺寸；R12 兼容输出始终需复核。它不表示文字、构件、BIM 模型或工程量已识别。
- 无可核验 DIMENSION 时，`dimension_validation_status=unavailable`，误差为 null；不记成误差 0。
- 持久化 DXF 尺寸证据模块保留 81 个工程数字字形模板；数字只有通过尺寸线、界线、比例和尺寸链约束后才成为工程证据。
- 内置轮廓文字字典含 101 个完整几何模板、63 个字符。93 个模板由至少两个不同源 PDF 的相同人工复核标签和完整字形精确一致确认；8 个仅用于完整 `1:60` / `1:90`，还要求独立工程数字字典证据。外部 `.p2dfont` 只有通过三字字体锁定后才能扩充字符，运行时不读取 PDF 或字体文件，不调用 OCR。
- 比例在持久化纸面 DXF 上计算：尺寸文字 → 尺寸线 → 两端尺寸界线交点 → 横竖方向独立拟合 → 留出尺寸验证 → 总分尺寸链闭合。缩短的尺寸线端点不能代替尺寸界线交点。默认模式下图名的 `1:n` 仅作为旁证；显式选择 `declared` 时，唯一且无冲突的独立 `1:n` 可作为近似等比换算证据。
- 字符按实际邻接关系分组，微小字高差和坐标平移不会再把数字串拆开或漏掉窗编号前缀。分叉、重叠及未知字形保留为待确认，不拼出数字后缀。
- 连续字符之间的明显大间距用于分隔邻近注记，避免把旁边轴号笔画粘到尺寸末尾。文本去重在各块定义和模型/图纸空间内进行，仅隐藏位置、字高、样式等全部属性一致的重复实体；不同块参照的正常文字和原始字符保留。
- 长引线穿过小字形时，按实际端点连接区分相交与连接，避免吞掉闭合的 0。尺寸标注相同投影跨度却给出不同数值时，保留两条记录并排除出比例拟合。
- 相同投影端点的重复尺寸只用一次拟合或留出，其他标注保存为 `check_only` 并记录 `duplicate_of`。最终验证重新计算两轴拟合、留出残差和尺寸链，核对每个已写入 DIMENSION 的存在、端点及标签，并按纸面坐标快照核对可见尺寸线、界线及文字的内容和位置。缺少源图元快照的旧报告不能通过新的自动标定复核，需重新转换。
- 尺寸链要求连续分尺寸同图层、同基线，总尺寸在附近（可位于另一图层）；不能跨图纸位置拼接投影相同的标注。基线容差为纸面 0.07 mm，总分尺寸间距最多为两者较大字高的 12 倍，超出范围保留待确认。支持最多 64 段、每组最多 2000 次搜索；多个几何解或搜索不完整均不确认，不按标签和挑选路径。
- 原生文字带明确 `mm`、`cm`、`m` 后缀时，可读取 `1m`、`2.5m`、`0.5m`、`.5m`、`5cm` 并换算为毫米。零值、负值及无单位的单个数字不作为尺寸。基线和界线之间仍须有可核对的跨度；当前不配对纸面跨度小于 0.5 mm 的尺寸。
- 短尺寸会放大 PDF 坐标舍入误差。全局比例拟合只用纸面跨度至少 15 mm 的尺寸；短尺寸仍保留在证据和最终 DXF 独立测量中，不调大 0.2% 质量门槛。
- `dimension_evidence` 保存文字及界线 handles、纸面端点、标签毫米值、拟合/留出角色、换算值、原始误差和尺寸链。工程图无后缀尺寸采用毫米惯例，并记录 `architectural_mm_convention`；非毫米单位声明会拒绝自动标定。
- 一个页面出现多个有支持的比例组、多个比例声明、单轴证据或尺寸冲突时，保留纸面 DXF并分别报告各比例组，不强制使用主比例。目录、做法表、门窗表和建筑说明也保持纸空间。自动多视口分割不在本包职责内；公共请求与 CLI 只提供 `auto`、`sheet`、`blocks`，下游系统应复用自己的 DXF 图框流程。
- 已校准的单比例图会真正缩放所有图元；`mode=blocks` 将模型收纳到一个块。保留原始纸面 DXF，便于追溯。原生/已确认尺寸存入关闭的 `PDF_DIMENSION_EVIDENCE` 图层；源尺寸线继续可见，恢复的文字位于 `PDF_TEXT_RECOVERED_NOOCR`。
- `editable` / `hybrid` 当前均保留原生可编辑文字与未识别轮廓。`text_mode=outline`、非 `compatible` 曲线模式、非 `hatch` 填充模式和 `mode=split` 均不在公共请求 schema 中；无效值会直接拒绝。
- `path_text_policy` 控制已确认文字对应原轮廓的处理；默认 `off_layer` 保存在关闭的备份层，`keep` 保持可见，`drop` 删除已确认轮廓。
- `strict_validation=False` 可放宽“未确认比例”对 `valid` 的影响，始终不会令 `model_ready` 变为 true。
- 最终验证从模型空间逐层跟踪块参照，按块的平移、旋转、缩放、基点及阵列位置换算尺寸。未引用的块不参与；证据尺寸丢失、重复放置、位置改变或块引用循环会阻止质量通过。遍历上限为 32 层、100000 个尺寸、参照和待核对源图元实例，达到上限明确报错。
- 可选 `legacy-r12` 降级保留隐藏/冻结图层、文字样式、FIT/ALIGNED 对齐点及倾斜/镜像属性；MTEXT 按附着点、旋转、换行与格式拆为 TEXT，字体度量仍取决于可用字体。HATCH 转边界、IMAGE 转边界并记录降级。曲线离散容差按输出单位换算为 0.05 mm，阵列参照保留全部有效单元；零间距轴先合并，避免无效重复遍历。R12 不支持现代 `$INSUNITS`，单位另存 `PDF2DXF_STABLE` XDATA 和 JSON 报告。

重新验证已有输出：

```sh
pdf2dxf validate output/drawing.dxf
pdf2dxf validate output/drawing.r12.dxf --profile legacy-r12
# 报告另存或改名时显式指定：
pdf2dxf validate moved.dxf --report drawing.report.json
```

验证命令自动查找相邻报告（含多页和 R12 文件），读取该页的实际请求与证据，并核对 DXF SHA256。整体移动目录可保留文件名；重命名 DXF 后须同步报告中的 artifact/validation 文件名。报告损坏、缺失所需证据或 DXF 内容改变时明确拒绝。没有报告时仅执行独立 DXF 检查，不将比例视为已确认。`--json` 不能覆盖输入、DXF 或验证所用的转换报告；转换输出必须以 `.dxf` 结尾。

DXF、`images/`、`.report.json` 应一起保留。图片文件按内容哈希命名，移动目录后相对引用仍可解析。`*_work_*` 保留该次中间 DXF、原始阶段 JSON 和日志，用于追溯；每次任务使用独立目录。报告中包含工作文件路径，请通过最终 `artifacts` 列表获取交付 DXF。`.dxf.lock` 是输出互斥锁文件，应保留以避免并发 inode 竞态。

`convert` / `batch` 退出码：`0` 全部门槛通过，`5` 失败或存在质量降级；加 `--allow-quality-degradation` 时有 DXF 的降级返回 `2`。应同时读取 JSON，`degraded` 可能是几何可读但工程比例未知。任务启动后的失败会尝试保存报告，不把旧输出文件计入本次 artifacts。参数或路径冲突在启动前拒绝，使用退出码 `2` 和 stderr 错误提示。Ctrl+C 返回 `130`，终止活动转换的子进程树并通知批处理停止启动新文件；已开始的转换保留可写出的报告，批处理总表可能尚未生成。

## 资源限制和批处理

默认每页 2560 MiB、1800 秒、临时目录 20480 MiB。输入预检、修复、页码读取和源文件哈希在独立受监督子进程执行，使用同一组资源上限；结果及资源测量保存为报告的 `input_validation`。随后逐页监控提取、嵌套子进程、格式导出与验证；每 0.1 秒采样进程树 RSS，每 0.5 秒检查工作目录。超过限制会终止进程树并写 `MEMORY_LIMIT` / `PAGE_TIMEOUT` / `TEMP_DISK_LIMIT`。预检和每页分别计时，采样监控允许短暂超出阈值，并非操作系统硬内存隔离。输出锁等待也受 `timeout_seconds` 限制，超时为 `OUTPUT_LOCK_TIMEOUT`，可以取消。

伪装扩展名的非 PDF 与需要密码的 PDF 分别返回 `NOT_PDF`、`PASSWORD_REQUIRED`；请先解锁加密文件。可选 qpdf / mutool 修复工具单次超时 300 秒，某个工具失败后继续尝试下一种修复方式，整体仍受预检资源限制。

轮廓连通分组完成后立即释放空间索引，识别按方向逐次处理，不保留未通过的完整候选对象。中间路径暂存在当前页工作目录，计入临时目录限额，处理完即删除。

```sh
pdf2dxf batch input_directory -o output_directory --workers 1 \
  --outline-chinese required --scale-mode declared
pdf2dxf regress input_directory -o regression_directory --workers 1 \
  --outline-chinese required --scale-mode declared
```

批处理目录名使用文件名与源文件绝对路径哈希，同名文件不会覆盖。JSON/YAML 清单可使用路径列表或 `documents` / `files` / `corpus` 列表；相对路径基于清单目录。重复的规范路径只处理一次；空输入、非法清单和非 PDF 路径明确拒绝。`workers` 是批处理并发文档数，单文档页按序运行，资源限制按每个活动文档计。大型轮廓图纸建议从 `--workers 1` 开始。回归两次重新计算 DXF，不使用旧版本跨任务输出缓存。自动回归还要求质量通过，未确认工程比例的文件会列为未通过，即使字节一致。

rc20 修复部分自接触 PDF 轮廓在几何修复后丢失填充的问题。84 个真实字体样例中，完整恢复由 61 个提高到 62 个，另 22 个仍部分恢复或未确认；22 份 BIM 图纸也补回了原先漏掉的填充。来源、保存后的几何与比例核验见 [验证记录](docs/VALIDATION.md)。

## 验证

```sh
python -m pip install '.[test]'
python -m pytest -q tests
python -m build
```

回归测试覆盖轮廓中文、外部字体字库、尺寸链/留出标定、图片迁移、块变换、R12、输出完整性、资源限制及 CLI 文件保护。安装 wheel 后可运行 `python tools/test_installed_wheel.py`，从临时目录验证安装结果。

历史 rc11 对 4290 份去重 PDF、12577 页完成过基础转换复核；它不代表当前轮廓文字算法已覆盖全部历史图纸。内部原图、截图和路径报告不分发，公开摘要与本轮验证范围见 [验证记录](docs/VALIDATION.md)。未知字体、复杂裁剪、扫描图和多比例图仍有能力边界，不能将生成 DXF 等同于工程质量全部通过。

## 代码结构

只保留 `pdf2dxf_stable` 包和 `pdf2dxf` 命令。版本号集中在 `version.py`；不再保留旧顶层 v14/v17/v18/v19/v20 入口或兼容空壳。

```text
pdf2dxf_stable/
  core.py, request.py, cli.py      公共入口、请求、结果
  profiles.py, validation.py      DXF 输出规范、质量门槛
  saved_validation.py             已发布 DXF、报告与 SHA256 复核
  dimension_instances.py          模型空间块变换与尺寸实例
  preflight.py, repair.py         受监督的输入预检与修复
  supervision.py, locking.py     可取消进程限制、输出互斥
  resources.py, r12_fonts.py     外部图片发布、R12 字体度量
  engine/
    pdf.py, pipeline.py, worker.py  PDF 转换流程
    geometry/                     PDF 矢量、媒体、原生文字
    calibration/                  持久化 DXF 比例证据
    text/                         DXF 字形模板、字体字库、尺寸文字与轮廓文字恢复
```

基础图元和施工图处理仍分层，是当前引擎的实际依赖。历史 DXF 的 XDATA 标识和 schema 版本保留，用于读取来源信息；无调用的图框/多视口仿射导出、视口曲线裁剪、旧 metadata/finalize 和重复内部验证实现已删除，`scikit-learn` 也不再是依赖。历史迁移说明见 CHANGELOG；内部源图审核资料不随发布目录分发。

## 许可证与参与

本包的维护者已于 2026-09-07 授权公开发布其提供的源码、随包衍生字形数据和回归样本，该声明记录在 [SOURCE_ORIGIN.json](SOURCE_ORIGIN.json)。来源声明不是独立的第三方权利核验；原作者和依赖的版权声明继续保留。Python 主包不分发原始客户图纸、系统字体或外部 `.p2dfont`；本项目提供的可选开源字库以独立资源包保留各自许可。

AGPL 不是无条件授权。分发受其覆盖的软件或提供修改版网络服务时，须履行适用的许可证保留、修改声明和相应源码提供等义务；完整条款以 [LICENSE](LICENSE) 为准。[PyMuPDF 的 AGPL / 商业许可说明](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)继续适用。转换不会使你获得输入图纸或字体的新权利。

欢迎提交 [Issues](https://github.com/y26s4824k264/pdf2dxf-construction/issues) 和 Pull Requests。开发流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，敏感缺陷见 [SECURITY.md](SECURITY.md)。

项目定位、可核验结果与维护计划见 [项目说明](docs/PROJECT_BRIEF.md)。
