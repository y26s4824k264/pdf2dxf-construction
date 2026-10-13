# rc38：完整转换入口的描边缓存修复 / Cached stroke-state repair

项目实际画布检查发现，rc37 的直接几何内核能生成线帽和连接包络，但完整 Converter 使用磁盘 DrawingSpool 缓存，迭代时重新反序列化字典。描边捕获只修改了其中一次迭代的记录，后续几何发射读取不到状态，因而退回原中心线显示。原 rc37 包不覆盖，使用 rc38 修复。

缓存现在将描边状态与原始路径顺序写入替换 spool，再供后续读取；不把全页绘图列表载入内存。失败时关闭替换文件并保留旧缓存，路径、裁剪和绘制顺序不变。图片附件与工程比例准入契约沿用 rc37。

回归将 12 项描边用例同时跑过真实缓存管线，另从公开 Converter API 调用受监督的子进程并重读 DXF，按独立圆头面积校验包络。修复前三种线帽在缓存管线中均失败；修复后 81 项描边和契约检查通过。最终源码和安装包跨平台结果以 [本版本 CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) 为准。仅代表页验证，未重跑历史 PDF 全集。

The disk spool yields fresh dictionaries on every pass. rc37 enriched one pass, so the full conversion pipeline lost the captured stroke state before emission despite direct-kernel tests passing. rc38 persists enrichment in a replacement spool and retains bounded page-memory behavior. Cached-pipeline regressions cover all cap/join/dash/clip cases; a public Converter regression verifies saved round-cap paint against elementary geometry. Image transport, unconfirmed engineering scale, curve-sampling bounds, hairlines and R12 retain their stated limits.
