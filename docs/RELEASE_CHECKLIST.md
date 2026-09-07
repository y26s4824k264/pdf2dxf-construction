# 发布流程 / Release checklist

项目许可为 [AGPL-3.0-only](../LICENSE)。维护者于 2026-09-07 授权公开提供的源码、随包衍生模板及回归样本，记录见 [SOURCE_ORIGIN.json](../SOURCE_ORIGIN.json)。第三方来源与许可继续保留，参见 [NOTICE](../NOTICE)。

仓库：[y26s4824k264/pdf2dxf-construction](https://github.com/y26s4824k264/pdf2dxf-construction)。发布使用独立快照，包含本包的源码、测试、文档、必要模板与 CI；不携带宿主仓库及其 Git 历史。

## 构建与验证

```sh
python -m pip install '.[test]'
python -m pytest -q
python -m build
python -m twine check dist/*
python tools/check_distribution.py --public dist/*
```

安装刚构建的 wheel 后运行 `python tools/test_installed_wheel.py`，从临时目录验证 `site-packages` 导入，避免本地源码遮蔽安装缺陷。构建过程应包含从 sdist 重建 wheel。

`check_distribution.py --public` 检查必要模块、实际随包 LICENSE / NOTICE / 第三方说明、危险归档路径、内部资料、本机路径及维护者许可声明。元数据必须如实填写，检查工具不替代第三方权属核验。成功返回 0；声明仍待确认时返回 5；内容错误返回 2。

## 发布步骤

1. 检查当前变更，更新版本、CHANGELOG 和中英 README。确认新增代码和数据有权按所声明许可发布。
2. 运行测试、构建与公开分发内容检查；核对 wheel、源码包、来源清单和 SHA256。
3. 将独立源码推送到 GitHub，等待 `.github/workflows/ci.yml` 的目标提交检查。配置存在或曾经通过，不能代替当前提交的执行证据。
4. 为通过检查的提交创建版本标签和 GitHub Release，同时提供 wheel、源码包和 SHA256。rc 版本应标为 prerelease；失败或质量限制需写入发行说明。

独立快照可用 `python tools/prepare_public_release.py ../pdf2dxf-release` 导出；目标及 ZIP 已存在时拒绝覆盖。导出包含文件哈希，不复制原始图纸、截图、系统字体、外部字库、虚拟环境、内部验证日志或 Git 历史。白名单不是通用秘密扫描器，新增文件仍需审阅。

CI 固定 Action 提交，权限仅为读取仓库，无自动发布步骤。当前测试范围与真实图纸结果见 [验证记录](VALIDATION.md)。

## 结果解释

`ok`、`degraded`、`failed` 分别统计。`degraded` 可能有可读 DXF，但工程比例、视觉细节或兼容格式质量未全部通过。`convert` / `batch` 默认返回 5；显式允许质量降级时返回 2，失败仍为 5。参数错误也返回 2，须结合 stderr 和 JSON 判断。

`regress` 同时要求两次 DXF 字节一致且质量通过，不能用确定性代替工程质量。空清单或目录不是成功转换。

## English

Build and check both source and wheel distributions with the commands above. The public-content check requires real license notices inside each artifact, not just a license flag in local metadata. Publish only the standalone package snapshot, never the parent repository or private drawings/fonts/logs.

Push the source, wait for CI on the exact commit, and attach the wheel, source archive and SHA256 to a versioned GitHub Release. Mark rc versions as prereleases and retain quality limitations. The maintainer's authorization is recorded in SOURCE_ORIGIN.json; third-party licenses remain applicable.
