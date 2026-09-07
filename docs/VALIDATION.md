# rc16 验证记录

版本：`2.0.0rc16`，日期：2026-09-07。以下区分实际执行、依赖解析和待运行的 CI。

## 自动回归与安装

| 环境 | 源码测试 | 安装包测试 |
| --- | --- | --- |
| macOS ARM64 / Python 3.10.20 | 222 通过 | 未单独执行 |
| macOS ARM64 / Python 3.12.13 | 222 通过 | 222 通过 |
| Linux ARM64 / Python 3.12，python:3.12-slim 容器 | 222 通过 | 222 通过 |
| Windows x64 / Python 3.10 | 依赖 wheel 下载通过 | 待 Windows 执行 |

安装包测试从临时目录中的 `site-packages` 导入，隔离源目录；macOS 最终 wheel 的 `pip check` 通过。Linux 使用安装到环境中的包，并覆盖无系统字体时 R12 MTEXT 的退化路径。Linux 测试后仅提高了依赖声明下限，实际安装的 Pillow 12.3、FontTools 4.64 与 OpenCV 5 已满足最终下限，运行时代码一致。5 条测试警告来自 PyMuPDF SWIG 的 DeprecationWarning。

新增回归覆盖预检资源失败及报告、伪装 PDF、密码错误、修复工具失败、进程树取消、批处理退出、输出锁超时与取消、字体 CLI 错误、无字体 R12 TEXT 位置，以及分发包内容和许可状态检查。原有几何、中文轮廓字库、比例、图片迁移和块变换测试继续运行。

最终源码包在独立构建环境中重建 wheel；wheel 与源码包的 `twine check` 和分发内容检查通过。不包含内部验证目录、原图、截图、系统字体、外部字库或本机用户名路径。GitHub 首次发布额外加入 2 项许可归档回归；最新公开提交的跨平台执行结果见 [CI](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)。本表记录的是发布前本地基线，不冒充 GitHub CI 结果。

## 依赖审计

使用 pip-audit 查询当日已知公告：实际 macOS Python 3.12 环境的 51 个第三方包（含测试、构建与 render 依赖）未发现已知漏洞；11 个直接运行依赖的最低允许发行版也未发现已知漏洞，均没有跳过条目。本地项目本身不属于 PyPI 公告查询范围。

原下限曾允许受影响的 Pillow、FontTools 版本，已提高至 Pillow 12.3、FontTools 4.60.2；当前转换器不调用已知 FontTools 公告所涉 varLib designspace CLI。最低版本审计未解析整套最低传递依赖组合，不能视为该组合的安装兼容性测试。审计结果不保证未来公告、底层二进制组件或所有调用路径安全。

## 实图范围

重新转换内部样本 22 份 PDF、22 页，启用内置中文字库、外部宋体样例 `.p2dfont`、`outline_chinese=required`、`scale_mode=declared`。完整 PDF、字体、截图与内部路径报告不随包分发。

22/22 生成 DXF，0 个转换失败；22 个结果仍为 `degraded`，批处理默认退出码 5。重开 DXF 审计错误/修复均为 0，全部输出 SHA256、恢复文本句柄和内容一致；独立重算保存后的尺寸验证，与转换报告相符。22 份报告新增的输入预检、源 SHA256 与页码证据也逐份核对。

内置模板恢复 238 条 TEXT、1035 个字符；外部宋体有 41 个孤立候选、0 个字体锁定、0 个外部字符写入。比例状态为 calibrated 9、declared_approximate 6、paper 6、unknown 1，geometry_valid 13/22。这些汇总与 rc15 相同；9 份已标定图纸的尺寸误差仍超过 0.2% 门槛，继续明确报告，不调宽阈值。参见 [机器可读摘要](validation.json)。

历史 rc11 曾对 4290 份去重 PDF、12577 页做基础转换验证。本轮只复测上述 22 份，不能把历史结果视为 rc16 的全语料中文、比例或安装验收。

## 公开发布说明

维护者已授权 AGPL-3.0-only 公开发布，来源声明保存在 SOURCE_ORIGIN.json；第三方权利与许可继续保留。分发包须通过 `check_distribution.py --public`，包括实际随包的 LICENSE / NOTICE / 第三方说明。GitHub CI 应按目标提交核对；已生成 DXF 仍不等于所有工程质量门槛通过。
