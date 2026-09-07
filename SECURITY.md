# 安全报告 / Security reporting

请通过 [GitHub 私密漏洞报告](https://github.com/y26s4824k264/pdf2dxf-construction/security/advisories/new) 提交安全问题。普通缺陷可使用 Issues；不要在公开 issue 中上传客户图纸、项目名、凭证或本机路径。项目目前不承诺响应时限。

本包调用 PyMuPDF、FontTools、NumPy 等解析器。进程资源采样限制不是安全沙箱，也不保证恶意文件的操作系统隔离。处理不受信任上传文件时，部署方应提供独立的低权限执行环境和输入访问边界。

字库校验包含文件集合、尺寸、哈希、数组类型、长度和字形拓扑。SHA256 能发现损坏与不一致，不能证明作者身份或字形标签真实。建议使用最小的程序生成样本复现问题。

Please use [GitHub private vulnerability reporting](https://github.com/y26s4824k264/pdf2dxf-construction/security/advisories/new) for security issues. Use Issues for ordinary bugs, but never post customer drawings, credentials or personal filesystem paths publicly. No response-time guarantee is currently offered.

Resource sampling is not a security sandbox. Deployments accepting untrusted files should use an isolated, low-privilege environment. Catalog hashes detect inconsistencies; they do not authenticate authors or glyph labels. Prefer a minimal, programmatically generated reproducer.
