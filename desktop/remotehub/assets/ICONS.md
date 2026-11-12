# 10RemoteHub 图标

应用图标采用白色圆角底板、倾斜的黑色遥控器符号和蓝色点缀。配色为 #FFFFFF、#111116、#145BFF；底板之外透明。

- `app-icon.svg` 是可编辑的设计源文件，1024 × 1024。
- `app-icon.png` 是 SVG 的透明渲染结果，供应用窗口和源码启动使用。
- `desktop/scripts/build_icons.py` 使用 PySide6 QtSvg 渲染，再生成 ICNS 和多尺寸 ICO；每次构建同步 PNG。
- ICNS 尺寸为 16–1024 px，ICO 为 16–256 px。生成文件位于 `desktop/build/<platform>/icons/`。
- `tray-icon.png` 是黑色透明遥控器蒙版；macOS 将其作为模板图标，其他平台按系统明暗适配。

设计过程使用 AI 生成概念稿，再以 SVG 整理应用图标。状态栏图标保留其 AI 生成来源的 C2PA 元数据；其中的服务签名和生成时间不代表项目作者的身份或设备信息。项目原创图标按根目录 LICENSE 分发。

设计参考：[logo-design-skill](https://github.com/kaankiziltug/logo-design-skill) 的符号和小尺寸设计思路。公开材料不包含个人对话、方案选择记录或本机生成目录。
