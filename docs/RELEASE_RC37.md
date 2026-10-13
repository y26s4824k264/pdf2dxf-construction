# rc37：线帽、连接和图片附件 / Stroke styles and image attachments

支持 butt/round/square 线帽、miter/round/bevel 连接、miter limit 回退、闭合接缝、虚线相位及非等比描边空间。读取 MuPDF 的原始路径顺序，避免 rectangle/quad 优化重排虚线起点。未裁剪的原生中心线和三次曲线控制点保留为透明 DXF 几何；实际绘制边界独立保存为带 `PDF2DXF_STROKE` 标记的 HATCH。DrawingIR 识别使用中心线，跳过绘制包络，避免把笔画宽度认成额外墙线。

PNG 原始字节、SHA-256、大小和像素尺寸保存在 IMAGEDEF 扩展 XRECORD 中；IMAGEDEF 保留普通相对路径。转换临时目录清理后，规范化 DXF 和独立图框仍携带完整附件。`pdf2dxf_stable.image_resources` 提供校验、复制、还原与 ZIP 导出。标准 CAD 使用 ZIP 中的真实 DXF 和 `images/` 文件。自定义存储适配器须为修改后的 DXF 计算自身产物哈希；原转换报告继续描述原转换产物。

DrawingIR 的 `FRAME_PACKAGE` 使用现有鉴权下载接口 `/drawing-ir/frame-snapshots/{id}/artifacts/FRAME_PACKAGE`。SVG 和原生 CAD 画布按 IMAGE 的仿射基向量、像素裁剪和透明度显示 PNG；外部路径、网络地址、损坏或缺失附件不会被自动读取。图片文字仍是图片，不使用 OCR。

## 验证 / Verification

新增 24 项两套内核描边测试及 6 项资源测试，保存后重读 DXF，独立核对面积、miter limit、宽度裁剪、非等比变换、虚线接缝及 SPLINE。合成 PDF/DXF 独立渲染的二值绘制区域 IoU 为 0.9972；它不是文字识别率或工程精度指标。原生 CAD 最新构建的浏览器验证覆盖普通、旋转、斜切、镜像 PNG、多边形及反向裁剪；附件半透明像素、方向和跨图框持久化有定向回归。

仅抽测三页：建筑 25 条尺寸，P95 相对误差 0.1280%；结构 53 条尺寸，P95 0.1886%；带两张图片的给排水目录仍保持纸面坐标。同步检查规范化与独立图框的比例标记。数值记录见 [RC37_VALIDATION.json](RC37_VALIDATION.json)。最终跨平台源码和安装包检查见本版本提交的 [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)。不重跑历史全集；私有图纸和本机路径不进入发行包。

## 精度和边界 / Bounds

曲线描边包络及圆连接使用声明的离散误差，PDF 坐标中不超过 0.01 pt，存于 HATCH XDATA。曲线裁剪路径和已裁剪中心线仍沿用已有采样容差。超出顶点预算、退化变换或未确认状态明确失败。PDF hairline 的显示宽度仍取决于 CAD 设备；R12 继续是缺少现代透明度、HATCH 和 IMAGE 完整能力的兼容降级格式。未确认比例、未知字体及图片文字仍不作为已恢复的工程语义。

Per-path paint envelopes preserve caps, joins, miter limits, dash phase and affine stroke space. Native unclipped cubic controls survive for geometry evidence; envelope sampling carries an explicit error bound. Verified PNG bytes survive temporary-directory cleanup and frame imports. Ordinary CAD interchange uses a DXF plus real PNG sidecars from the exported ZIP; the extension record is an application storage transport. Curved clipping, hairlines and R12 retain their stated limits. Three representative pages were tested, without a full corpus rerun or universal-font accuracy claim.
