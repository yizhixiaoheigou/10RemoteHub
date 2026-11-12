# Windows 安装与使用

完整接入遥控器需要用 **Zadig** 配置 USB 驱动；**VB-CABLE** 仅在使用遥控器麦克风时需要，使用电脑麦克风无需安装。它们不随本项目分发，需要向原提供者获取。应用本身解压运行。

> 发布包位于 [GitHub Releases](https://github.com/yizhixiaoheigou/10RemoteHub/releases)。先核对同一版本的 SHA256SUMS；源码环境与构建见 [RELEASE.md](RELEASE.md)。

> Windows x64 已实机验证。

## 一、准备两个组件

### 1. Zadig（给遥控器接口换驱动）

遥控器的接收器是复合 USB 设备，其中两个接口需要交给本项目独占，否则按键和声音拿不到完整数据。

1. 从 [zadig.akeo.ie](https://zadig.akeo.ie/) 下载 Zadig（本项目不附带；应用里「通用设置 → 前往下载 Zadig」就是打开这个页面）。
2. 插上遥控器接收器。
3. 打开 Zadig → 菜单 **Options → List All Devices** 打勾。
4. 下拉框里选 **`… (Interface 3)`**，驱动选 **WinUSB**，点 **Replace Driver**，等它完成。
5. 再选 **`… (Interface 4)`**，同样选 **WinUSB**，点 **Replace Driver**。

> 只绑这两个。Interface 1/2 会被应用顺带接管，失败会自动退回系统输入，不影响使用。

### 2. VB-CABLE（虚拟麦克风）

Windows 不能像 macOS 那样由应用自带虚拟麦克风（那需要微软签名的内核驱动），所以用免费的 VB-CABLE：

1. 从 [vb-audio.com/Cable](https://vb-audio.com/Cable/) 下载 `VBCABLE_Driver_Pack43.zip`（应用「语音设置 → 前往下载 VB-CABLE」就是打开这个页面）。
2. 解压，**右键 `VBCABLE_Setup_x64.exe` → 以管理员身份运行** → 点 **Install Driver**。
3. **重启电脑**。

装完后系统里会有：

- 播放端 `CABLE Input (VB-Audio Virtual Cable)`
- 录音端 `CABLE Output (VB-Audio Virtual Cable)`

## 二、安装应用

1. 下载发布页的 `10RemoteHub-<版本>-win-x64.zip`，解压到固定目录（例如 `D:\10RemoteHub`）。
2. 双击 `10RemoteHub.exe`。若 SmartScreen 拦截，先核对下载来源与该版本的 SHA-256；确认后按系统提供的选项继续。企业策略禁止运行时，联系管理员，不关闭系统防护。
3. 左侧应出现 `USB 0416:0602`；按遥控器任意键，右侧对应按键会高亮。

## 三、配置语音

1. 打开 **语音设置**：
   - 语音来源：**遥控器麦克风**
   - 麦克风连接方式：**录音时切换系统默认麦克风**（推荐）
   - 识别快捷键：设成识别软件里"按住说话"用的键
2. 打开 **通用设置**，确认「遥控器语音接口」显示 **已绑定**；未绑定时卡片里会直接写出 Zadig 的两步操作和下载按钮，不需要另找文档。

### 识别软件怎么设

| 识别软件 | 能否用本项目唤醒 | 说明 |
|---|---|---|
| **微信输入法** | ✅ | 识别快捷键设 `Alt`；麦克风选 **系统默认** |
| 豆包输入法 | ❌ | 会过滤所有程序模拟的按键，遥控器无法唤醒 |
| Windows 语音输入（Win+H） | 能唤出，但不识别本项目音频 | 不推荐 |

用「录音时切换系统默认麦克风」时，程序会在按住语音键期间把系统默认麦克风临时切到 `CABLE Output`，松手立刻恢复原设备。所以识别软件的麦克风选「系统默认」即可，不需要固定选虚拟设备。

如果你想手动指定，把连接方式改成「固定使用虚拟麦克风」，然后在识别软件里直接选 `CABLE Output (VB-Audio Virtual Cable)`。

## 四、已知限制

- **遥控器按键不会进入系统键盘**：本项目独占接收器，按键只在应用内触发动作。这是刻意的（避免按键同时被前台程序收到、产生重复触发）。
- **应用没运行时遥控器不产生任何按键**。
- 豆包输入法无法被唤醒（见上）。这是它的反注入策略，不是本项目的问题。
- 首次安装 Zadig 换驱动后，需要拔插一次接收器。

## 五、卸载

1. 应用菜单退出程序，删除解压目录。
2. 设备管理器 → 找到 `深圳讯飞互动… (Interface 3/4)` → 右键卸载设备 → 勾选「删除驱动程序」。
3. 拔插接收器，Windows 会自动恢复原驱动。
4. VB-CABLE 用安装目录里的 `VBCABLE_Setup_x64.exe`（管理员）选择移除，或从「应用和功能」卸载。

## 六、出问题看这里

- 日志：`%LOCALAPPDATA%\RemoteHub\logs\connection.log`
- 只读环境报告：`10RemoteHub.exe --diagnose report.json`
- 最小环境报告：`powershell -ExecutionPolicy Bypass -File scripts\collect_windows_logs.ps1`（在源码目录里用）。只收集系统版本、设备数量、驱动状态和应用哈希，不包含用户名、设备序列号、个人路径或原始日志；分享前仍应检查内容。该脚本已在 Windows 原生运行并复核导出内容。
- 更细的架构、协议与验收记录见 [Windows 端说明](docs/WINDOWS-TESTING.md)。
