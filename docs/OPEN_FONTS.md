# 开源字库 / Open font catalogs

rc34 使用 r3 资源，新增原字体 em 坐标中的字形外框和水平字距，用于核验整行字身尺寸、基线和字距。描边和填充分别记录有效外框。十套资源的原有 246,293 条模板、归一化轮廓、拓扑、码点映射和 2,288,068 个匹配索引键与 r2 完全一致；字体来源和许可不变。

## 下载与使用

从 [rc34 发行页](https://github.com/y26s4824k264/pdf2dxf-construction/releases/tag/v2.0.0rc34) 下载 ZIP，并核对 SHA256SUMS.txt。资源包独立于源码和 wheel，无需安装系统字体。

| 资源 | 来源字体 |
| --- | --- |
| `PDF2DXF-fonts-core-2026.09.11-r3.zip` | 思源黑体 SC Regular 2.005、思源宋体 SC Regular 2.003、DejaVu Sans / Serif / Sans Mono 2.37 |
| `PDF2DXF-fonts-extended-2026.09.11-r3.zip` | Jigmo / Jigmo2 / Jigmo3 2025-09-12、遍黑体 P1 / P2 Regular 2.9.5795 |

```sh
pdf2dxf font-catalog inspect-bundle \
  catalogs/PDF2DXF-fonts-core-2026.09.11-r3/font-bundle.json

pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required --scale-mode declared \
  --outline-font-bundle catalogs/PDF2DXF-fonts-core-2026.09.11-r3/font-bundle.json \
  --outline-font-bundle catalogs/PDF2DXF-fonts-extended-2026.09.11-r3/font-bundle.json
```

`convert`、`batch`、`regress` 可重复传入 `--outline-font-bundle`。单独指定一个字体可使用 `--outline-font-catalog .../catalogs/cjk-sans-sc-regular.p2dfont`。来源字体已知时优先提供对应字库；增加字体数量仍可能引入同形歧义与内存开销。资源损坏或不兼容会明确报错。

```python
from pdf2dxf_stable import Converter, ConversionRequest
from pdf2dxf_stable.engine.text.font_bundle import load_font_bundle

bundle = load_font_bundle('catalogs/PDF2DXF-fonts-core-2026.09.11-r3/font-bundle.json')
request = ConversionRequest(outline_chinese='required',
    outline_font_catalogs=bundle['catalog_paths'], scale_mode='declared')
result = Converter().convert('input.pdf', 'output/drawing.dxf', request)
```

## 识别证据与边界

新检查仅补充水平、等比例的汉字行：至少三个不同整字具有唯一的完整轮廓标签，至少一个原本无歧义的候选，原字体 em 尺寸、基线、相邻字距和 DXF 来源顺序同时一致。容差为 0.01 em，用于曲线离散外框误差；掩码和拓扑仍要求精确匹配。候选之间若有分支、来源跳号、整字同形异名、跨字重叠、竞争字母/数字、任意竞争汉字或独立小字行，保留歧义。该步骤不利用词义或上下文猜字。

同时加载十字库的 84 个短行样例从 69 个完整提升为 84 个，16 个长行仍全部完整。100 个原始字体 PDF 实际重新转换，共恢复 3,630 字。测试是已知字体样例，不是任意字体准确率。每例预期、实际 TEXT、源文件摘要和坐标核验见[机器可读证据](OPEN_FONT_VALIDATION.json)。

Jigmo 字库并集仍覆盖 Unicode 17 基本区、扩展 A–J 和兼容区的 102,998 个已分配汉字码点。覆盖不等于识别准确率。IVS/IVD 多码点异体序列、任意字重/斜体/地区字形、扫描图仍不在这一承诺内。未知文字保留原几何。

## 兼容与构建

r3 使用 `.p2dfont` v3，需要 rc34+；rc34 继续完整校验并读取 v1/v2。旧字库没有排版尺寸，升级 Python 包不会自动补上这些数据。要使用本轮新增证据，请下载 r3 或用原字体重新构建。v2 的原始描边/可选填充表示继续保留，新格式对每种表示记录对应有效外框。

[来源锁定文件](OPEN_FONTS.lock.json)固定官方下载版本、提交、大小与 SHA256，以及压缩包内字体和许可文本的哈希。

```sh
python tools/build_open_font_bundle.py \
  --lock docs/OPEN_FONTS.lock.json --cache tmp/open-font-downloads \
  --group core --output tmp/PDF2DXF-fonts-core-2026.09.11-r3

python tools/build_open_font_bundle.py \
  --lock docs/OPEN_FONTS.lock.json --cache tmp/open-font-downloads \
  --group extended --output tmp/PDF2DXF-fonts-extended-2026.09.11-r3
```

缓存齐全时可加 `--offline`。`--catalog-cache 旧目录/catalogs` 仅复用与当前格式、源字体和构建参数一致的字库，不把旧 r2 缓存当作新格式。已有输出目录不会被覆盖。转换阶段只读保存的 DXF 与字库，不联网、不读字体、不用 OCR。

## 许可

思源黑体、思源宋体与遍黑体保留 SIL OFL 1.1；Jigmo 字体保留 CC0 1.0；DejaVu 保留 Bitstream Vera / Arev 条款及完整 LICENSE、AUTHORS、README。衍生几何模板随资源包保留原版权和许可；项目代码的 AGPL 不替代字体许可。资源包包含 `font-bundle.json`、`SOURCE_LOCK.json`、`COVERAGE.json`、`NOTICE.md` 与原始许可文本。客户图纸与私有系统字体不进入公开包。

## English

Download **r3** core/extended resources from the [rc34 release](https://github.com/y26s4824k264/pdf2dxf-construction/releases/tag/v2.0.0rc34), verify checksums and pass one or both bundle manifests using the commands above. The ten pinned font faces and their licenses are unchanged. All 246,293 existing templates and 2,288,068 lookup keys preserve their geometry and labels. Schema v3 adds original-font em-space ink bounds and horizontal advance, with separate bounds for raw and filled representations.

The additional horizontal Han-row proof requires at least three distinct, uniquely labeled whole glyphs, one already uncontested candidate, consistent em scale/baseline/advance and contiguous DXF provenance. Exact mask/topology matching remains mandatory; the 0.01-em layout tolerance accounts for curve flattening. Whole-glyph aliases, crossing windows, letters/digits, arbitrary competing Han labels, independent small-text rows and discontinuous evidence remain unresolved. No OCR, semantic guessing or runtime PDF/font access is used.

All-ten-catalog tests now complete **84/84 short and 16/16 long** rows. All 100 original font PDFs were reconverted, restoring 3,630 characters. These known-font fixtures are not a universal accuracy benchmark. See [per-case evidence](OPEN_FONT_VALIDATION.json). Unicode coverage remains 102,998 assigned Han codepoints; IVS/IVD sequences and arbitrary font variants remain unsupported.

r3 requires rc34+. Legacy v1/v2 resources remain readable but cannot supply the new layout measurements. Rebuild from the original font or download r3 to enable this proof. Explicit builds verify pinned downloads and preserve attribution; conversion stays offline. Source Han/Plangothic retain OFL 1.1, Jigmo retains CC0 1.0 and DejaVu retains its original Bitstream Vera/Arev terms. The code's AGPL does not replace these licenses. Source fonts and private drawings are excluded from the wheel and source archive.
