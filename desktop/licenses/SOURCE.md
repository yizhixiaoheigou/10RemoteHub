# 第三方许可、对应源码与修改版

主程序源代码采用仓库根目录 MIT；内置 codec 保持 LGPL-2.1-or-later，Apple 示例、Qt/PySide、libusb、FFmpeg 等保留各自许可。项目 MIT 不覆盖第三方代码。

发布包的 `licenses/components.json` 应列出实际版本、原始许可文件及 SHA-256、精确对应源码归档及 SHA-256、构建配置与改动。该清单由构建环境生成，不能用一个跨版本手写表代替。源码归档与二进制须一并交付；完整材料尚未验收的旧包不能据本说明宣称许可完整。

- Qt/PySide6 6.12.0 的绑定源码：[官方源码目录](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/)。Qt 本体、各模块第三方代码和 FFmpeg 是另外的源码，不包含在这份绑定源码中。
- FFmpeg 随 Qt Multimedia 的实际版本与配置须从目标二进制核对，保存对应源码、补丁及构建参数；[上游要求](https://ffmpeg.org/legal.html)。内置 Python codec 来自另一个固定版本，见随包 `codec-source/remotehub/codec/NOTICE.md`，不可混用版本。
- libusb 可能同时存在于 Python wheel 与原生 helper 中，两者分别核对版本、源码和动态链接位置。
- Python、NumPy、PyObjC、hidapi 等也需要其实际分发的版权与许可通知。

## 修改和重新构建

允许按适用 LGPL 条款修改这些组件、为调试修改而进行必要的逆向分析，并使用修改后的版本。Qt/PySide/shiboken/FFmpeg/libusb 以独立动态库分发；Python codec 的完整修改源码随包提供。

在源码 checkout 的项目隔离环境中安装匹配版本的依赖，用自己的兼容构建替换相应库后，按 [RELEASE.md](../RELEASE.md) 重新构建整个 App 与原生组件。Qt 的位置通常为 macOS App 的 `Contents/Frameworks/PySide6/Qt/` 或 Windows 的 `_internal/PySide6/`；实际位置以该包清单为准。不得替换后继续声称其为项目原始签名发布版。

macOS 采集器的 GUI 客户端、守护进程、worker 与 libusb 必须使用同一套**自己的证书签名身份**构建。`build_device_helper.py` 从签名 worker 提取证书指纹并编译进两端校验。只对 App 执行 `codesign --deep --sign -` 不能生成可用的修改版采集服务；临时签名包也不能接入原签名服务。自己构建后，通过系统标准安装器安装配套组件并重新授权辅助功能，不关闭 XPC 签名校验或系统保护。

分发修改版时还需设置自己的更新来源、更新公钥与代码签名证书校验值，防止它自动更新回原版。项目私钥不提供，也不是重建自己的版本所必需。系统安装、权限提示及真实设备验收需由操作者明确执行。

Windows 替换动态库后重新打包和验证；Zadig、VB-CABLE 由用户向其提供者获取，项目不再分发。内核驱动权限与本项目源码许可分别处理。

完整发布材料和 native 重建/替换流程仍需在各目标系统验收；文本与结构校验不替代该验收。[Qt LGPL 说明](https://www.qt.io/development/open-source-lgpl-obligations)。
