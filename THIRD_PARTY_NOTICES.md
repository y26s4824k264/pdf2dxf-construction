# 第三方来源与许可 / Third-party notices

项目采用 [AGPL-3.0-only](LICENSE)。维护者已于 2026-09-07 授权公开其提供的源码、随包衍生模板和回归样本，声明见 [SOURCE_ORIGIN.json](SOURCE_ORIGIN.json)。本文保留第三方来源与许可，不将第三方内容重新授权。

## 原始源码

本包由 `PDF2DXF_Construction_v2.0.0-rc4_pure_python_complete.zip` 整理而来；压缩包 SHA256 见 [SOURCE_ORIGIN.json](SOURCE_ORIGIN.json)。原归档未发现 LICENSE、COPYING 或 NOTICE 文件。本次公开依维护者的发布授权进行；原始权属没有经过独立核验，已有作者署名、来源与版权声明继续保留。

## PyMuPDF / MuPDF

运行时固定使用 PyMuPDF 1.26.4。上游提供 AGPL-3.0 与商业双许可；本项目选择 AGPL 开源发布路径，PyMuPDF / MuPDF 自身许可继续适用；本项目的授权不包含 Artifex 商业许可。[PyMuPDF 官方仓库](https://github.com/pymupdf/pymupdf)、[官方许可说明](https://pymupdf.readthedocs.io/en/latest/faq/index.html)。

## 其他依赖

直接运行依赖还包括 ezdxf、pydantic、NumPy、SciPy、Shapely、psutil、Pillow、PyYAML、opencv-python-headless 和 FontTools；测试/构建依赖见 `setup.py` 与 `pyproject.toml`。分发包不捆绑这些依赖的程序，但安装时会下载它们。发布时应保存最终依赖版本清单，并核对相应发行版及其二进制内含组件的许可证和 NOTICE。

可选 `render` extra 和测试环境安装 Matplotlib。无系统字体时，R12 的 MTEXT 拆分可使用它自带的字体度量，并明确报告外观近似；本项目 wheel 不包含这些字体程序。相关字体的授权及 NOTICE 由安装的 Matplotlib 发行版提供。

rc16 将 Pillow 最低版本提高到 12.3、FontTools 提高到 4.60.2，避免允许已知受影响的旧版本；当前包不调用 FontTools varLib 的 designspace CLI。上游说明：[Pillow 12.3.0](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html)、[FontTools GHSA-768j-98cg-p3fv](https://github.com/fonttools/fonttools/security/advisories/GHSA-768j-98cg-p3fv)。2026-09-07 的依赖审计范围和结果见 [验证记录](docs/VALIDATION.md)。依赖审计反映当日已知公告，不证明所有代码路径没有漏洞。

## 字形数据与回归样本

- `engineering_glyphs.json` 含 81 个尺寸数字及上下文字形模板，来源元数据包含 `superos.shx` 及来源 SHA256；本次公开的范围是维护者授权的随包几何模板，不包括源 SHX 字体程序。
- `chinese_glyph_templates.json` 含 101 个经过标签复核的几何模板。标签、来源 SHA256 和重复一致性证据随数据保留；原图及截图不随发布目录分发。维护者的发布授权包含这些随包衍生模板；来源证据不等同于独立权属核验。
- 两个 `tests/calibration/fixtures/*.json` 为从历史图纸问题提取的数值/局部轮廓回归数据；已移除本机路径，来源哈希保留，包含在维护者本次授权公开的回归样本范围内。
- `test_font_catalog.py` 在测试时生成简化的程序化字形，不依赖或分发系统中文字体。
- 外部 TTF/OTF/TTC/OTC 字体和 `.p2dfont` 不包含在本发布目录。由用户提供的字体生成字库不意味着可以公开再分发字库；需遵守对应字体授权。

参见 [模板来源](docs/TEMPLATE_PROVENANCE.md) 和 [发布检查](docs/RELEASE_CHECKLIST.md)。

## English summary

This project uses AGPL-3.0-only. The maintainer authorized publication of the supplied source, bundled derived glyph templates and regression fixtures on 2026-09-07. This records the maintainer's declaration; it is not independent verification of third-party ownership or permissions. Existing source hashes, authorship and copyright notices are preserved.

PyMuPDF 1.26.4 / MuPDF retain their AGPL/commercial licensing. This release uses the AGPL route and grants no Artifex commercial license. Other Python dependencies retain their respective licenses and notices; their programs are downloaded separately by the installer, not bundled in this project's wheel. Optional Matplotlib supplies its own fonts and notices for R12 text metrics.

The engineering template file records superos.shx provenance; the Chinese dictionary records source hashes and reviewed labels. The two calibration fixtures contain reduced numerical/outline regression data. The release includes the maintainer-authorized derived data, not the original SHX font program or customer PDFs. Test FontBuilder glyphs are generated programmatically. External OpenType fonts and generated .p2dfont catalogs are excluded; users must follow the licenses of the fonts they supply.
