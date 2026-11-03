# rc40：原生文字映射、DXF 整数规范和大文件处理

## 修复 / Fixes

- 某些 CAD PDF 没有 ToUnicode 映射，MuPDF texttrace 返回 U+FFFD；旧回退会把字形编号当 Unicode。现在只在内嵌 TrueType 的 Unicode cmap 对实际 glyph ID 提供唯一标签、同名字体程序全部一致时恢复原生文字。来源记录字体程序集合摘要，保留原字符位置与绘制状态，不覆盖已有有效 Unicode。
- rawdict 回退关闭 `TEXT_CID_FOR_UNKNOWN_UNICODE`，不把 CID 或 GID 当作汉字。无法确认的原生字符明确报告 `NATIVE_UNICODE_UNRESOLVED`，不能标记为完整图形；纯轮廓文字仍由保存 DXF 的拓扑/几何模板识别，没有 OCR 或 AI 补字。
- 超过 32767 的来源编号和 PDF 对象编号使用 DXF group 1071，较小整数继续兼容 group 1070。保存后验证器新增有符号整数范围检查，避免 ASCII 能加载、二进制保存却溢出的非规范 XDATA。
- 同批发行包含维护仓库此前已提交的负虚线相位支持；保持完整绘制/间隔周期取模，不放宽非法虚线长度检查。
- 大 ASCII DXF 的确定性序列化只解析 HEADER/OBJECTS 元数据，其余数据按有界字节块复制。355.8 MB 实例从约 9.35 秒降至 3.58 秒，与旧实现输出 SHA-256 完全一致。只说明这一序列化步骤的性能，不代表整页转换提速倍数。

## 验证范围与剩余边界

新回归覆盖真实内嵌测试字体、缺失映射、同形多码点、同名字体冲突、有效 Unicode 不覆盖、原坐标保持、缓存入口、二进制 DXF 整数往返、大文件字节保持和截断文件原子失败。客户 PDF 和内嵌字体不进入源码、wheel 或公开字库。

本轮提供的六张结构 PDF 仅做轻量清点，选择基础、梁、楼梯三类代表页转换。每页标题栏有 210 处未解码字符（含空格），可用内嵌 cmap 核验恢复。楼梯页 106 条尺寸的 P95 误差为 0.1896%。梁页工程比例没有得到独立确认，继续保留纸面坐标。基础页在人工设置的 420 秒整页预算下超时，使用已保存产物续做校验；不将续验冒充公开 Converter 完整成功。

两张大页的中间 DXF 约 320–330 MB，默认 2560 MB 内存预算不足；抽测显式使用 8192 MB。复杂页可按实际资源配置 `--memory-limit-mb 8192 --timeout-seconds 900 --workers 1`，这不是放宽比例或几何质量门槛。

这批正文大多是纯轮廓；现有十套 r3 字库未锁定对应字体，不能声称已全部转为 TEXT。未确认内容保留原几何。继续补齐需原 CAD 使用的 SHX/TTF/OTF 字体或可验证模板，不能用词义、文件名或 OCR 猜字。未全量重跑历史 PDF 库，也不承诺任意字体、任意 PDF 均能恢复全部文字。

PyMuPDF 对未知 Unicode 和 glyph ID 的定义见其[官方文档](https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_texttrace)；rawdict 的 CID 回退说明见[文本提取文档](https://pymupdf.readthedocs.io/en/latest/app1.html)。

## English

Recover missing native PDF Unicode only from unique actual embedded TrueType glyph-ID/cmap evidence, requiring agreement across same-named faces. Preserve valid native Unicode and placement. Disable rawdict CID-as-Unicode fallback and reject incomplete native text as complete graphics. Outline recognition still consumes saved DXF geometry, without OCR or semantic completion.

Large source/object indices use signed 32-bit XDATA where necessary, with saved-output range validation. Bounded byte copying of nonmetadata sections accelerates deterministic serialization while matching the previous output byte for byte on a 355.8 MB drawing. This is not a whole-conversion speed claim.

Only three representative structural pages were converted. The stair page has 106 checked dimensions and a 0.1896% P95 relative error. Unconfirmed engineering scale stays explicit. The foundation attempt exceeded an explicitly chosen 420-second budget; verifying a saved artifact is not a completed public Converter run. Two large pages require more than the default 2.5 GB budget. Existing r3 catalogs do not identify the body-outline font in this batch: unmatched outlines remain geometry and require the original font or verified templates for further TEXT recovery. Private source PDFs and fonts are excluded from public distributions.
