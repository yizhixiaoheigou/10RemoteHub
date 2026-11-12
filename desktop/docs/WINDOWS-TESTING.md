# Windows 端说明

本文记录 Windows 实现的结构、依赖、验收结果和已知限制。安装步骤见 [INSTALL-Windows.md](../INSTALL-Windows.md)。

## 1. 架构

Windows 与 macOS 采用同一个模型：**采集程序独占接收器，主程序只处理业务**。

```
遥控器
  │ 2.4G
接收器（USB 0416:0602）
  ├─ 接口 1 消费者控制 ─┐
  ├─ 接口 2 鼠标       ├─ windows_collector.py：WinUSB 独占，读原始 HID 报文
  ├─ 接口 3 厂商语音   │   用 HIDReports 解析成固定键表的 hid:* 标识
  └─ 接口 4 键盘      ─┘
        │
        ├─ 按键事件 → controller.on_key → 动作（快捷键 / 开应用 / 输入文本…）
        └─ 语音会话 → G.722.1 解码 → AudioBridge → CABLE Input → 识别软件
```

要点：

- **按键来源于原始报文，不是 Raw Input**。原因是 Windows 键盘驱动会把部分 HID 用法直接丢弃（例如遥控器 `#` 键的用法 `0xCC`），Raw Input 永远收不到；同时 Raw Input 无法抑制物理按键，会与前台程序重复触发。
- 接口 1/2/3/4 全部由 `remotehub/windows_collector.py` 独占；每个接口一个常驻读取线程，避免 HID 报文被后续报文覆盖。Raw Input 保留为降级路径：接口 4 未绑定时自动启用。
- 语音会话由接收器帧驱动：收到 `01 86` 开始，松手或音频停止 0.45 s 发送 `01 00` 结束；进程退出、重连前也一定先发停止，避免遥控器灯常亮。

### 语音协议（与 macOS 采集程序一致）

| 方向 | 端点 | 内容 |
|---|---|---|
| 读 | `0x84` 中断 IN | `01 86 …` 语音键帧；`01 81 …` 音频帧；`01 08 01 00` / `01 01 01 00` 握手；`01 ff` 停止确认 |
| 写 | `0x05` bulk OUT | `01 08 01 00` 就绪；`01 82 01 00` + `01 08 01 00` 开始；`01 01 01 00` 进入音频；`0a 54 45` 每秒保活；`01 00` 停止 |

音频帧固定 64 字节，第 6–45 字节为编码数据，第 46/50 字节起为双序号。主程序校验序号连续，偶发丢帧只重新对齐，连续 6 次才判定链路故障。

### 虚拟麦克风

Windows 的虚拟麦克风是内核音频驱动，必须微软签名，本项目不自带。方案是用免费的 **VB-CABLE**：

- 应用把声音播放到 `CABLE Input`；
- 识别软件从 `CABLE Output` 录音；
- 「录音时切换系统默认麦克风」模式下，应用通过 `IPolicyConfig` 在录音期间把系统默认麦克风（console / multimedia / communications 三个角色）切到 `CABLE Output`，松手恢复。

## 2. 依赖与绑定

| 组件 | 作用 | 是否随项目分发 |
|---|---|---|
| Zadig | 把接口 3、4 绑到 WinUSB（一次性） | 否，用户自行下载 |
| VB-CABLE | 虚拟声卡 | 否，用户自行安装 |
| libusb / pyusb | 访问 WinUSB 接口 | 是（Python 依赖） |
| PySide6 | 界面与音频 | 是 |

接口 4 未绑定时，应用仍可用：Raw Input 提供按键（`#` 键除外），语音接口 3 未绑定时语音不可用。

## 3. 验收记录

### 2026-11-09 端到端

验证环境：Windows x64，Python 3.12.10。

| 项目 | 结果 |
|---|---|
| 接口 1/2/3/4 独占 | ✅ 日志 `interface N claimed` |
| 按键（`#`、数字、方向、音量、返回） | ✅ `#` = `hid:7:204` |
| 语音键按下/松开 | ✅ 会话干净开始结束，遥控器灯正常 |
| 音频到虚拟麦克风 | ✅ 16 kHz 单声道回录峰值 RMS 0.30 |
| 微信输入法出字 | ✅ 端到端可用 |
| 自动化测试 | 376 passed / 2 skipped（macOS 环境） |

### 2026-11-08 首轮构建

- PyInstaller 原生打包成功，产物 `dist/windows/10RemoteHub-<版本>-win-x64.zip`；
- 修复：多处文件读取未指定 UTF-8（GBK 下崩溃）、构建脚本 pip 输出污染函数返回值、Windows 误显示 macOS「检查更新」；
- 该机直连 PyPI 的 TLS 被阻断，构建脚本自动回退清华镜像。

## 4. 已知限制

1. **豆包输入法无法唤醒**：它过滤所有程序模拟的按键。尝试过的绕过手段都失败——journal playback（`WH_JOURNALPLAYBACK`）被本机代码完整性策略以 `ERROR_ACCESS_DENIED` 拒绝；Interception 驱动安装后未能 attach 到键盘设备（`interception_wait` 返回 0），已卸载。微信输入法可用。
2. **Windows 语音输入（Win+H）**能唤醒但识别不到本项目音频。
3. 应用未运行时遥控器不产生按键；这是完整重映射的预期行为。
4. 托盘与登录自启动尚未实机验收。
5. VB-CABLE 重复安装会留下带 `2-` 前缀的实例，重启后可归一；使用时要选同一组的 Input/Output。

## 5. 排障

| 现象 | 检查 |
|---|---|
| 左侧不显示 `USB 0416:0602` | 接收器是否插好；`10RemoteHub.exe --diagnose` 的 `usb` 字段 |
| 按键全部无反应 | 通用设置「遥控器语音接口」是否已绑定；日志是否出现 `interface 4 claimed` |
| 语音键按下后灯常亮 | 日志是否出现 `request stop` 与 `in 01ff0000`；是否被强制结束进程 |
| 输入法有电平但不出字 | 识别快捷键是否与输入法一致（微信输入法为 `Alt`） |
| 输入法完全没有电平 | 麦克风连接方式选「录音时切换系统默认麦克风」并把输入法设为系统默认；或固定模式选 `CABLE Output` |

日志：`%LOCALAPPDATA%\RemoteHub\logs\connection.log`，只记录连接事件，不含音频与文字。

## 6. 构建与调试

```powershell
cd <项目>\desktop
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -LicenseSupplement <材料清单绝对路径>
```

脚本会依次创建 `.venv-win`、安装依赖、跑自动化检查、PyInstaller 打包、生成 zip 与 `SHA256SUMS`、写构建日志和只读诊断报告。国内网络直连 PyPI 失败时会自动回退清华镜像，也可以显式指定：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -LicenseSupplement <材料清单绝对路径> -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

PyInstaller 不能交叉编译，Windows 包必须在 Windows 上构建。
