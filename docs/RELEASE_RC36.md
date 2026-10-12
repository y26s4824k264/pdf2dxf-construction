# rc36：裁剪边界修复 / Clipping fixes

本轮补齐四个已复现的问题：部分裁剪圆点导致转换失败；圆点中心线在框内时跳过裁剪而越界；空裁剪或相交结果为空时错误放行图元；交集含有效面积与零面积接触部分时丢弃有效区域。

Round and tangent-oriented square dash caps now intersect polygon clip regions. Circle/line intersections are solved analytically and saved as native HATCH arc/line edges, including holes and disconnected regions. Empty clip scopes remain empty and the parent scope is correctly restored afterwards. See the [ezdxf boundary-path contract](https://ezdxf.readthedocs.io/en/stable/dxfentities/hatch.html) for native arc and hole representation.

## 验证 / Verification

- rc35 的失败复现：新增测试最初 8 失败、2 通过；修复后 40 项绘制回归全部通过。连同填充修复、媒体、公开接口和坐标契约，共 118 项相关检查通过。
- 实际保存 DXF 后重新读取，核对圆弧类型、独立解析面积、闭合边界、孔洞、分离区域、空裁剪及作用域恢复。PDF 原图与 DXF 的独立渲染已对照；合成样例二值绘制区域 IoU 为 0.9833，包含渲染器边缘采样差异，不是文字识别率或工程精度指标。
- 两张代表工程图重新通过公开 Converter API 转换，规范化和独立图框 DXF 均保留比例确认状态。建筑页检查 25 条尺寸，P95 相对误差 0.1280%；结构页检查 53 条尺寸，P95 相对误差 0.1886%。与 rc35 一致，均通过 0.2% 门槛，DXF 审计错误/修复数均为零。
- 不重跑历史全集、不增加字体识别率声明；r3 字库及其许可证不变。四组跨平台源码和安装包结果以本版本提交的 [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml) 为准，发布前检查全部成功。

Two representative engineering pages were reconverted, with 25/53 measured dimensions and unchanged P95 errors of 0.1280%/0.1886%. Coordinate guards were checked again after normalization and frame extraction. The historical corpus was not rerun. Public numeric evidence is in [RC36_VALIDATION.json](RC36_VALIDATION.json); private drawings and their geometry are excluded from releases.

## 仍有边界 / Remaining boundaries

- 圆点本身保留原生圆弧。曲线形状的裁剪路径仍沿用现有裁剪路径采样容差；无法确认闭合拓扑的退化边界明确报 `PDF_DASH_DOT_CLIP_TOPOLOGY_UNCONFIRMED`，不猜测补边。
- 一般描边仍使用 DXF 线宽，不能把本轮圆点修复视为所有 PDF 线帽、连接样式和曲线裁剪都已完全等价。
- 独立包保留 IMAGE 附件。DrawingIR 当前只存储 DXF 字节，仍拒绝含外部图片附件的导入；完整支持需要贯通附件持久化、独立图框与预览资源引用。
- R12 无现代透明度；未确认比例和未识别轮廓继续明确保留限制。

Exact circle-cap arcs do not make every PDF graphics operation lossless: curved clip paths retain their existing sampling tolerance, general strokes retain DXF lineweight semantics, and ambiguous degenerate boundary topology fails explicitly. DrawingIR's image-sidecar storage limitation remains explicit; the standalone package still preserves those assets.
