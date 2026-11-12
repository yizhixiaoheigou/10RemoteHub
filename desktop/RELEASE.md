# 可复现构建与发布验收

本次 macOS arm64 和 Windows x64 发布文件已通过构建、许可内容检查与解包启动。Mac 完成实际安装、卸载、旧版恢复与最终安装；Windows 在独立目录完成便携安装、旧版替换、回滚和卸载。实体按键/语音沿用此前实机结论，本轮按维护者决定不重复测试；边界见 README。旧包不能作为整改后的发布包。
源码发布与二进制发布分别验收；不要把本机 artifacts、虚拟环境、日志或历史实验一起上传。

## 环境

使用 Python 3.12（目前验证基线为 3.12.13）。PySide6 固定 6.12.0；该版本在 Python 3.10/3.11 有已报告的信号引用计数问题，见 [PYSIDE-3474](https://qt-project.atlassian.net/browse/PYSIDE-3474)。其官方 macOS wheel 标记为 macosx_14_0，当前依赖基线要求 macOS 14 或更新。由于没有 Intel Mac，本轮不安排 Intel 真机验收，文档明确保留未实测的兼容性限制；Rosetta 离屏结果不能代替 Intel 真机测试。

```sh
cd desktop
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2'
.venv/bin/python -m pip install --require-hashes -r requirements-macos-arm64.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/verify.py --output ../artifacts/verification.json
```

Windows 用 Python 3.12 的项目环境，执行 `scripts/build_windows.ps1 -LicenseSupplement <材料清单绝对路径>`。macOS 使用已存在的本机签名身份：

```sh
.venv/bin/python scripts/release_macos.py --codesign-identity '<本机签名身份>' --license-supplement '<材料清单绝对路径>'
```

当前 Apple Silicon 基线可先运行以下命令生成许可材料。脚本会下载约 600 MB 已固定 SHA-256 的上游源码、Python 发行版与构建材料，记录本机实际运行库并保留版权声明；后续复用核验通过的缓存。它要求已安装且版本匹配的 Homebrew libusb，不自动安装或变更共享环境。Mac 运行库为 Python 3.12.13，Windows 本轮原生构建使用 Python 3.12.10；不要混用两者的补充材料。

```sh
.venv/bin/python scripts/inventory_macos_runtime.py --output-dir ../artifacts/release-materials
.venv/bin/python scripts/prepare_macos_licenses.py --output-dir ../artifacts/release-materials
```

也可在 Mac 本机终端运行 `scripts/build_release_candidate.command`，依次执行材料准备、测试和签名构建。它优先使用 `.venv-mac`，其次 `.venv`；可用 `REMOTEHUB_PYTHON`、`REMOTEHUB_MATERIALS` 和 `CODESIGN_IDENTITY` 指定已有环境、材料缓存和签名身份。本机签名构建已通过；SSH 会话若无法使用钥匙串私钥，应在本机终端完成最终签名，不关闭签名检查或擅自放宽钥匙串权限。

这个公开入口运行自动测试、构建 App、DMG、ZIP，再从 ZIP 解包验证签名和离屏启动；写入新的 candidate 目录，不安装、不接管 USB、不发布。Windows 也必须通过内容与许可检查。源码 checkout 不依赖私有 artifacts/*.command。证书创建、钥匙串变更、安装和系统授权由维护者另行执行。

`requirements-release.txt` 是版本约束源；`requirements-macos-arm64.lock`、`requirements-macos-x86_64.lock` 与 `requirements-windows-x64.lock` 为 Python 3.12 的完整依赖 hash lock。Intel 和 Windows 使用对应 lock，先 `pip install --require-hashes -r <lock>`，再 `pip install --no-deps --no-build-isolation -e .` 安装本项目。Mac 两种架构均已解析并与目标环境核对；Windows lock 已通过 Windows x64 原生安装、测试与构建。每次构建另外保存 `pip inspect`、构建日志和实际包清单。

## 许可材料清单

`collect_licenses.py` 从安装包 RECORD 中收集 PEP 639 和传统许可文件，统一处理大小写及 `_`/`-`，排除与版权文件同名的程序模块。PyInstaller 分析结束后再次按实际文件所属发行包补充运行时依赖通知，随后才封签。Qt 归属文件保留相对目录和链接。缺少必需组件、许可、原生库或对应源码证据时终止构建；每次保留独立材料目录供检查。随包携带项目 MIT、Apple 示例许可、libusb、LGPL、GPL 与各依赖原始文本及 SHA-256 清单 `licenses/components.json`。

对 wheel 未附带的通知和原生库，需要 `--license-supplement` 指定 JSON 文件。顶层为 `{"components": [...]}`，每项：

- `name`：规范名称；Python 依赖如 `pyside6-essentials`、`pyobjc-core`，原生项必须有 `qt`、`ffmpeg`、`python`、`libusb`。macOS 另需 `libusb-helper`，分别记录 Python runtime 与原生采集组件使用的 libusb。
- `version`：实际发布版本；Python 补充材料必须与安装版本完全相同。
- `license_files`：相对该 JSON 的原始许可/版权通知文件路径，保留上游完整声明。
- `license_root`：可选的归属文件根目录；其内部路径在包内保留，用于 Qt 等相对链接。`runtime_provenance` 可记录 Python 发行版、补丁和构建脚本归档及其哈希。
- `source_url`、`source_sha256`：已下载核对过的**精确对应源码归档**地址和 SHA-256，不能只写项目主页。
- `build_notes`：源码版本、上游构建方式、配置参数、补丁、对应 wheel 和本项目重建命令；不能写“同上”代替证据。

Qt/PySide/shiboken、pynput、FFmpeg、libusb 强制要求对应源码记录。Qt 还要收集实际模块的第三方归属说明；NumPy 的内部 BLAS 等也应核对实际 wheel 的通知。原生库不能只用 pip 包名代替。FFmpeg 必须记录二进制导出的 configure 行，并确认未启用 `--enable-gpl` / `--enable-nonfree`；其 ABI 主版本不是完整源码版本。

已从官方源取得 PySide6 6.12.0 和 FFmpeg 9.0.1 原始归档，并在 `licenses/vendor/SOURCES.json` 记录 SHA-256、提取许可原文。

两平台已整理 11 个对应源码/构建脚本归档；Mac 原生补充材料为 12 项组件、247 份通知，最终包再按 PyInstaller 实际依赖补齐为 29 项、339 份通知。Python 独立发行版的第三方许可、构建补丁和精确发行包哈希已纳入材料；Windows 使用其实际 Python 安装的聚合许可。两平台成品的原生加载依赖没有指向本机开发环境，FFmpeg 均从成品库读出 LGPL 配置。字段/哈希校验只保证材料结构与一致性，不代表法律意见。对应源码归档与二进制一起提供，并在发布后核对公开下载地址可获取性。参考 [Qt LGPL 义务](https://www.qt.io/development/open-source-lgpl-obligations)、[FFmpeg 分发要求](https://ffmpeg.org/legal.html)。

## 包内容门禁与原生验收

`python scripts/release_policy.py <App目录或ZIP>` 拒绝 QtVirtualKeyboard、未审阅 Qt 模块、QtPdf、WebEngine 和历史闭源解码器；校验许可清单与文件哈希。QtGui 自定义 hook 从收集阶段去掉虚拟键盘/PDF 插件，最终门禁再次检查依赖是否带回它们。该内容门禁已在 macOS/Windows 新包中通过。

每个目标平台至少验证：干净环境安装/启动、27 个映射键、固定语音键、单击/双击/长按/重映射、断连释放、失败后重试、结束和退出后恢复默认输入、用户中途手动改输入时保留选择。管理员安装、证书/辅助功能与真机 USB 验收不由离屏测试替代。签名身份、系统修改、发布和上传分别需要实际授权。

## 源码公开边界

`scripts/export_source.py --output <新的目录>` 生成不含 .git 的候选快照，保留原仓库及历史。它按白名单导出桌面应用、原生组件、必要构建脚本和测试，用公开开发说明取代本机历史笔记，不导出私人诊断、历史照片、远程连接信息或闭源实验。仍须人工核对候选素材与版权来源后才可建公开远端。

保留原 Git 历史公开属于另一条路径：旧照片权利和历史个人环境信息尚未确定，不能只删除当前文件就认为历史安全。本脚本不重写历史、不初始化仓库、不推送。

导出时可加 `--archive <新的.tar.gz路径>`。压缩包只包含哈希清单中的文件，使用固定的顶层目录和规范化时间、属主信息，不携带本机文件路径、属主名称或扩展属性。不要直接压缩整个开发目录；其中的私有记录、旧日志与 Git 历史没有经过公开脱敏。

公开署名采用 `yizhixiaoheigou`。首次公开提交在独立快照仓库使用该昵称和 GitHub 账户提供的隐私邮箱（no-reply）；发布前核对作者及提交者字段，不继承原开发仓库的身份配置。源码归档本身不包含 `.git`，公开仓库从一次初始提交开始。

源码默认不配置更新地址，检查更新时会提示尚未配置且不发起网络请求。维护者在新发布渠道、清单签名与应用签名配套验证后，才通过 `REMOTEHUB_UPDATE_URL` 配置签名清单地址；仅更换 URL 不会自动更换签名信任配置。

## 二进制隐私与归档

源码无个人路径不代表冻结程序没有。Mac 构建会通过 `sanitize_sysconfig.py` 生成不含构建者个人目录的 sysconfig 数据，供 PyInstaller 使用，原 Python 环境不变。验收时还需打开冻结模块并检查字符串常量，不能只对压缩后的可执行文件做文本搜索。Windows ZIP 使用固定的 ZIP 合法时间与通用权限，不携带本机属主信息，也可处理源码快照的 1970 年时间戳。
