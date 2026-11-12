# Mac / Windows 动作边界

2026-11-11 核对。区分“操作系统支持”与“本软件已提供独立动作”：未列入动作面板不代表系统没有该功能。

| 功能 | macOS | Windows | 当前软件处理 |
|---|---|---|---|
| 复制、粘贴、撤销、全选、保存 | Command 系列 | Ctrl 系列 | 常见动作按执行平台转换 |
| 应用切换 | Command+Tab | Alt+Tab | 分平台发送；Windows 不使用 Dock 检测/重试 |
| 窗口总览 | Mission Control | Win+Tab 任务视图 | 各用本机名称与行为 |
| 显示桌面 | 读取本机设置 | Win+D | Windows 固定组合，不读取 Mac 缓存 |
| 系统搜索 | Spotlight 本机配置 | Win+S | 同上 |
| 聚焦 Dock / 任务栏 | Dock 本机配置 | Win+T 任务栏 | 不解释为同一 UI |
| 截图 | 区域、全屏、剪贴板、截图录屏工具栏分别配置 | Win+Shift+S 打开选区 | Windows 本轮 7 键用截图选区；不发送 Shift+Command+4/5 |
| 隐藏应用 | Command+H 隐藏应用窗口 | Win+Down 是还原/最小化窗口 | Windows 文案明确不同，不叫隐藏整个应用 |
| 全屏 | Control+Command+F（应用支持时） | F11（应用支持时） | 不保证所有软件接受 |
| 退出当前应用 | 正常退出请求 / Command+Q | 没有与 Command+Q 完全等价的通用键；Alt+F4 关闭当前窗口 | 本轮 Windows 9 使用 quit_app，向当前应用同一进程窗口发送正常关闭请求，保留保存提示；托盘程序可能驻留，不强杀 |
| 上下翻页、方向、回车、返回、退格 | 对应按键 | 对应按键 | 键位相同 |
| 媒体控制 | 本机媒体事件 | Windows 媒体事件 | 控制当前媒体会话，不绑定特定播放器 |

## 系统快捷键读取

Mac 的 23 项命名系统动作在启动时读取本机配置，通用设置手动刷新。Windows 不显示该区，也不构造 SystemHotkeys 缓存。Windows 常见系统组合键按平台约定执行；第三方改键工具与应用内快捷键不是统一系统表，无法承诺自动识别，使用自定义组合键配置。

## Mac 专属概念与当前仅在 Mac 提供的入口

- Dock 显隐、Finder 搜索、Mac 菜单栏/状态菜单/浮动窗口焦点、当前应用窗口总览、Command+H：没有可直接照搬到 Windows 的统一同义行为。
- 同应用上一/下一窗口：Mac 的原生切换规则不等于 Windows 的 Alt+Tab，不机械替换。
- 左右桌面、输入源切换、全屏截图/剪贴板截图：两边系统都具备相关能力，但当前独立命名入口只接了 Mac；Windows 可通过“按键/组合键”设置，不应标成“Windows 不支持”。

## Windows 特有入口或应独立命名的功能

本次未擅自加入遥控器键位；可用自定义组合键：任务管理器 Ctrl+Shift+Esc、资源管理器 Win+E、运行 Win+R、快捷设置 Win+A、Windows 剪贴板历史 Win+V（需用户自行启用）、Windows 11 贴靠布局 Win+Z。Mac 不直接发送这些 Win 组合，也不将名字套到不同功能上。

Windows 左右虚拟桌面为 Win+Ctrl+Left/Right，输入源切换为 Win+Space；虽然本软件尚未提供对应的 Windows 独立常见动作，系统功能确实存在。

## 当前机器配置

- 1 Edge，2 开始菜单名为 ChatGPT 的已安装应用，3/4 留空，5 WorkBuddy，6 Windows 终端，0 Apple Music。
- 7 Windows 截图选区，8 Backspace，9 正常退出当前应用（上表限制）。其余方向、复制粘贴、翻页、任务视图、桌面、搜索、切歌等按 Mac 的功能布局配置。
- Windows 原有语音键、识别触发键、输出设备和增益保留；不复制 Mac 的音频设备 ID。

参考：[Microsoft 系统快捷键](https://support.microsoft.com/en-gb/accessibility/windows/keyboard-shortcuts-in-windows)、[Apple Mac 快捷键](https://support.apple.com/en-us/102650)。平台列表验证与真实实体按键测试分开记录。
