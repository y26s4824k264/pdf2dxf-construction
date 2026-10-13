# rc39：中英文混排字体修复 / Mixed-script style repair

rc38 的文字 STYLE 按来源字体与类别缓存，但按第一个字符决定使用中文还是西文字体。混排行先出现英文字母时，后续汉字也会引用 Arial。现在先检查来源字体的所有文字行，只要包含非西文字符就使用已有中文回退字体；纯西文保持既有字体。字符、基线、原始字距、XDATA 来源及工程比例判断不变。

十个新增回归通过真实通用内核、施工图内核与磁盘缓存管线重读保存 DXF，覆盖同一行混排、拆成两行、相反顺序及纯西文。修复前六个 Latin-first 用例失败，修复后与轮廓和绘制相关的 66 项检查通过。源码和安装包的完整单元回归由版本 CI 验证；不重跑历史 PDF 全集。

中文纯轮廓仍通过持久化 DXF 的拓扑、精确字形模板、字库锁定和重复一致性恢复为 TEXT。r3 字库与识别门槛未改变；不使用 OCR、AI、PDF 像素或词义补字。无法独立确认的字符保留原几何。DXF 字体引用不等于字体二进制，本包不分发系统字体，也不承诺任意源字体外观完全一致。

DrawingIR 的预览资源问题另在应用内修复：提供 ezdxf 尺寸 STYLE 所用的原版 OpenSansCondensed-Light，补齐 SimSun TTC 名称解析；不修改未知字体提示或给其他字体伪造别名。这些浏览器字体资源属于应用，而非本 Python wheel。

rc38 chose a fallback font from the first emitted character before caching a shared STYLE. rc39 inspects all runs of each source font first, preventing Latin-first content from assigning Arial to later Han characters. Latin-only styles, Unicode values, placement and provenance stay unchanged. Ten saved-DXF regressions cover both graphics kernels and the cached conversion pipeline. The existing offline DXF topology/template recognizer and r3 catalogs are unchanged. Unconfirmed glyphs remain geometry; no OCR or semantic completion is introduced. Font binaries and universal source-font fidelity are outside the Python package contract.
