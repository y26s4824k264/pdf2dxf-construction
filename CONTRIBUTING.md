# 参与开发

项目采用 [AGPL-3.0-only](LICENSE)。请仅提交你有权按该许可提供的代码、文档与测试数据，并保留必要的来源、版权和第三方许可声明。发布流程见 [发布检查](docs/RELEASE_CHECKLIST.md)。

## 本地验证

使用独立 Python 环境，安装 `python -m pip install '.[test]'`，执行 `python -m pytest -q`。
修复应附上最小可复现输入或程序生成的图形、预期行为和回归测试。不要提交客户图纸、专有字体、账号凭证或带个人路径的报告。

构建：`python -m build`。安装生成的 wheel 后运行 `python tools/test_installed_wheel.py`，验证实际从 `site-packages` 导入，避免源码目录遮蔽安装缺陷。`python -m twine check dist/*` 只检查分发元数据，不上传。

## 转换边界

- PDF 读取只负责输入验证和 PDF→DXF 转换。文字、尺寸、比例分析必须读取已保存的 DXF 图元。
- 原生文字可以写入 TEXT/MTEXT。轮廓匹配依靠可审核字形模板、拓扑与几何一致性；未知或冲突字形保留几何，不猜字，不隐式调用 OCR。
- 不通过列宽、常见层高或其他假定补造工程比例。声明比例与经过尺寸校验的比例必须分别报告。
- 改变输出规则时同时检查图片引用、TEXT、块变换、隐藏备份层、报告哈希、单位和确定性。
- 小改动保持单一主题；版本仅修改 `pdf2dxf_stable/version.py`，不要复制出新的 vXX 引擎入口。

## 缺陷报告

描述操作系统、Python 与包版本、完整命令、实际退出码和预期结果。报告应先脱敏；尽量用 `fitz`、`ezdxf` 或测试用 FontBuilder 生成可复现文件。
