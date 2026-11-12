# 10RemoteHub 前端逻辑定义

这份文档定义桌面端前端的分层、状态归属、数据流和不变量。视觉与交互状态见 [DESIGN.md](DESIGN.md)。

## 产品组成

1. 主程序：映射、动作执行、语音解码/处理、设置与状态。
2. 统一采集程序：一个设备会话同时提供按键报文与编码音频，不另设音频助手。
3. 可选虚拟麦克风：仅在使用遥控器麦克风时提供给外部识别软件。

Mac 的实现见 `native/device-helper/README.md`：XPC 服务和短生命周期 USB 子进程属于一个安装组件，不是两个用户入口。主程序用 `DeviceInput` 分发按键、用 `USBBridge` 订阅同一连接的音频；后者在 Mac 不再启动 sudo 终端或独立 USB worker。Windows 由 `windows_collector.py` 独占接收器的接口 1/2/3/4（WinUSB），读原始报文解析按键并处理语音会话，与 macOS 同一套 `HIDReports` 和固定键表；Raw Input 只在接口 4 未绑定时作为降级路径。Linux 的 evdev / X11 / PipeWire 实现已隔离到 `linux/`，不参与当前构建与发布。

## 分层

```text
ui/ (widgets)           只布局与呈现；把用户意图转成 controller 调用
  window.py   MainWindow：侧栏 + 页眉 + 页面栈 + 反馈条 + 托盘
  sidebar.py  导航、设备状态卡与重新检测、导入导出
  mapping.py  按键映射页：RemoteCanvas + Inspector
  inspector.py 选中键的动作编辑（草稿只存在这里）
  voice.py    语音来源、遥控器操作、识别软件、音频组件与检测
  general.py  登录启动、权限与统一采集组件
  widgets.py  label/button/row/Pill；快捷键录制换算
        │  调用方法                ▲  Qt 信号
        ▼                          │
controller.py  AppController(QObject)：全部应用状态与规则
        │
        ├─ store.py        ConfigStore：读 / 校验 / 迁移 / 原子保存（无 Qt）
        ├─ presentation.py 动作与快捷键的显示文字（纯函数）
        └─ 运行时服务：actions.KeyOutput/ActionRunner、audio.AudioBridge、
           session.VoiceSession、devices.DeviceInput、usb_bridge.USBBridge、
           inventory.USBMonitor、virtual_mic.VirtualMic
canvas.py  RemoteCanvas：照片、热区、引线、标签（也被 key_survey 复用）
theme.py   设计令牌、QSS 生成、apply_theme
```

规则：

- 控件不直接修改 `Profile` / `Button`，也不调用设备、USB、音频服务；一律经 `AppController`。
- `AppController` 不 import 任何控件类，不弹对话框。需要用户确认（USB 接管）或选择文件时，由页面负责，再把结果交给 controller。
- `store.py` 与 `presentation.py` 不依赖 Qt，可以单独测试。

## 状态归属

| 状态 | 所在 | 说明 |
|---|---|---|
| profiles、settings、load_error、legacy_backup | `ConfigStore` | 唯一持久化来源 |
| 当前配置 `index`、选中键 `selected_id` | `AppController` | `selected` 只返回可配置键，电源/TV 永远选不中 |
| `enabled`、`keys_ready`、`learning`、`pressed` | `AppController` | 设备与按键分发 |
| 测试倒计时 `test_timer` / `test_left` | `AppController` | 倒计时开始时锁定当时的动作 |
| 语音会话 owner、触发键、增益、输出 | `VoiceSession`（由 controller 写入） | |
| 动作草稿 `draft_kind`、`draft_app` | `Inspector` | 只在界面里；从不写入配置 |
| 页面索引、折叠区展开 | 控件自身 | 纯呈现 |

## 信号

| 信号 | 何时发出 | 订阅者 |
|---|---|---|
| `message(text, is_error)` | 任何反馈 | 反馈条 |
| `profiles_changed` | 配置列表或当前配置变化 | 侧栏、映射页、检查器 |
| `mapping_changed` | 选中、动作、名称、位置、照片变化 | 映射页（画布 + 计数）、检查器 |
| `device_changed` | 接收器状态 / 启用 / 就绪变化（含每 2 秒扫描） | 侧栏、检查器、语音页、托盘 |
| `learning_changed(bool)` | 进入 / 退出学习 | 页眉横幅、检查器 |
| `voice_changed` | 语音设置、输出列表、USB 链路、会话 owner 变化 | 语音页、主界面语音快捷设置 |
| `level(float)` | 音频电平 | 电平条 |
| `test_pending(int)` | 倒计时剩余秒数，0 为空闲 | 检查器「测试」按钮 |

刷新方式：订阅者收到信号后从 controller 读取当前状态并整体重绘自己（`refresh()`），不做增量补丁。正在输入的字段（有焦点的名称框、快捷键框）在刷新时保留用户文字。

## 主要流程

**专用语音键**：`photo_template.is_voice_button()` 按适配型号与固定 ID / HID 触发码判断。默认、载入和导入时归一为 `Action("voice")`；旧配置首次保存前备份。控制器拒绝清除或重映射，实体事件分发再次强制语音角色，避免仅靠隐藏 UI 约束。选中仍保留画布高亮，检查器替换为 `VoiceKeyEditor`，普通动作计数排除它。

**分配动作**：点画布 → `MappingPage.select_key` 检查未保存文本 → `controller.select(id)` → `mapping_changed` → 画布与检查器刷新。点动作类型：无参数类型直接 `assign`；有参数类型进入草稿，录好 / 选好后 `assign`；`text` 动作有独立多行草稿，点击「保存文本」才提交，离开前可保存、放弃或取消。`assign` 先 `Action.validate()`，失败只报错不改配置；成功即 `store.save()`，记录一次可撤销的旧动作并发出“已保存”；保存失败回滚原动作，编辑不进入运行态。

**自动接入按键映射**：普通启动开始 USB 扫描 → `ensure_mapping()` 对可用接收器尝试一次 → `set_enabled(True)` 检查最新检测结果 → `DeviceInput.start` → `ready(generation)` 标记就绪。`device.failed` 保留原始错误，不把原始 USB 采集错误归因于输入监控权限；随后 `stopped` 不覆盖已有原因。`StatusView` 附带诊断和设置入口标记，USB 未发现 / 检测错误优先于旧监听错误。普通接入失败不随每次扫描重试；重新检测或拔插后才重试。瞬时读取错误由底层在原进程内限频重挂，避免反复 detach/reopen；采集仍退出时应用只自动重连一次，不覆盖已有的语音提示。safe 模式禁止自动接入。Mac 与 Windows 都是按键与语音共享同一个独占采集会话，不重复接管同一接口。

**实体按键**：`DeviceInput.key` / `USBBridge.key` → `on_key(trigger, down)`：学习中只绑定不执行，且刚学的键松开不触发；否则找到同 trigger 的可配置键，先发 `physical_key` 供首跑验证。没有双击/长按配置时仍即时执行单击；方向快捷键、滚动、翻页和音量增减允许真实重复报文连发，其他动作过滤重复。`gestures.KeyGesture` 以 280 ms 双击窗口和 550 ms 长按阈值分发三套动作，修改配置、断连和退出会取消计时器。新手引导只在最后一页监听数字 1，不恢复固定型号的通用测试入口。

**保持输入与应用切换**：`holds.InputHolds` 按所有者记录修饰键并设置超时；`KeyOutput.chord` 只释放本次临时按键，保留仍被持有的修饰键，合成修饰键按当时仍按下的集合发送。`AppSwitcher` 复用这层状态实现完整应用切换：首次 Command 后 80ms、普通合成键 25ms、连续选择、停顿 1 秒确认、Option 恢复最小化窗口、Escape 取消。仅当本次确实按下 Option 时才由本次释放，语音持有 Alt 时拒绝启动。切换器还读取 Dock 窗口数识别外部关闭，避免错误地向前台补 Escape；断连、切配置和退出统一清理。

**通用型号内部测试（固定遥控器不展示）**：`schedule_test()` 锁定当前动作，每秒发 `test_pending(n)`，归零执行一次；`cancel_test()` 立即取消。语音动作不可测试。

**USB 语音**：Mac 的采集连接与虚拟麦克风就绪、来源为遥控器时，自动准备音频，无第二次设备接管或授权。按语音键向同一 XPC 会话发送开始/停止指令；编码帧在 GUI 中校验双序号并进入内置 `codec.g7221.Decoder`，每 40 字节产生 640 字节 PCM。每次录音 reset；停止时等待采集尾包与音频输出排空，再释放识别键。切换电脑麦克风只停止音频订阅，不停止按键采集。Windows 的声音播放到 VB-CABLE 的 `CABLE Input`，由识别软件从 `CABLE Output` 读取；Linux 采集已隔离。

**授权与音频准备**：启动只读检查采集组件安装/签名，不自动打开安装器或权限页；用户主动安装/更新后重新检测。原始 USB 采集不走 GUI IOHID，因此不再以输入监控作为启动门槛；辅助功能仍负责按键和窗口操作。虚拟麦克风仅按需安装，`QMediaDevices.audioOutputsChanged` 刷新后只选择本项目设备，缺失不改用扬声器。Mac 同时检查已安装的驱动文件；2 秒只读轮询仅在安装状态改变时刷新，退出时停止定时器，避免安装完成但音频设备尚未出现时仍提示安装。已安装但系统未枚举时提供「完成设置」入口；手动重新检测会显示当前状态。音频 0.1.1 仅发布输入/输出流，不发布示例音量/静音/数据源控制。独立安装包为带提示的 distribution，完整安装包复用其 payload；postinstall 在系统卷上先校验签名、再重新加载 coreaudiod，并用随包 universal probe 最多 15 次检查固定 UID、双向声道与无多余数据源（每次查询 3 秒超时），失败明确报错，离线卷安装不影响运行中的音频服务。构建与隔离测试不执行这些系统操作。

**系统设置伴随面板**：`open_permission()` 成功后发出 `permission_opened(name)`，通用设置创建/复用 `PermissionOverlay`（独立非模态 Tool 窗口，主窗口隐藏时也可由状态栏入口唤起）。`permissions.settings_window()` 通过系统设置 bundle ID 找 PID，只读 `CGWindowListCopyWindowInfo` 的必要元数据来定位；不截屏、不读取标题、不用需要先授权的 AX 自动化。250 ms 跟随窗口，1.5 s 只读检查权限；切到其他应用隐藏，拖拽期间暂停跟随/收起，授权完成或关闭时停止计时。找不到系统窗口最多等待 10 秒，之后保留通用设置的定位替代入口。定位参考 [Apple 必要窗口元数据](https://developer.apple.com/documentation/coregraphics/required-window-list-keys)，后台 Tool 显示与不激活使用 [Qt 窗口属性](https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum)。

**语音设置**：`voice_source` 缺省为 `disabled`，按实体语音键仅提示未启用，不启动录音、发送唤起键或自动连接音频；明确选择 remote/trigger 后才分别使用遥控器音频或仅触发外部识别。两处唤起键使用 `VoiceKeyRecorder` 捕获单个按键和弦（允许单独修饰键），完成释放后校验并保存，不接受文本或输入法提交。遥控器手势与外部快捷键方式分别配置。字段变化 → `update_voice(**changes)`：会话进行中拒绝；合并后 `validate_settings` 失败则拒绝并让字段回到原值；成功即写入 `VoiceSession` 与配置。

## 不变量（有测试覆盖）

- 编辑、选键、预览不执行动作，不启用设备（`test_photo_mapping`、`test_fixed_keys`）。
- 电源 / TV 不能选中、配置或执行旧动作（`test_fixed_keys`）。
- 原配置读取失败时绝不覆盖原文件（`test_ui`、`test_failure_paths`）；迁移前的原文在首次保存时另存备份（`test_inventory`、`test_fixed_keys`）。
- 学习到的键松开不触发动作（`test_failure_paths`）。
- 拔出接收器会停止监听并取消启用；换同型号设备无需绑定（`test_inventory`）。
- USB 接管前的所有检查先于确认框（`test_controller`）。
- 快捷键按物理键保存：macOS 上录 ⌘C 存为 `cmd+c`（`test_ui`）。
- 配置文件格式不变：`{"version": 1, "profiles": [...], "settings": {...}}`（`test_controller`）。

## 扩展方式

- **新动作类型**：`model.KINDS` 与 `Action.validate` → `actions.ActionRunner.run` → `presentation.KIND_TITLES/KIND_HINTS` → 有参数时在 `inspector.PAGES` 加页并实现提交；所有入口由 `presentation.palette()` 平铺；常见操作在 `common_actions` 注册。
- **新页面**：在 `ui/` 新建 QWidget 子类，提供 `title`、`subtitle`，订阅需要的 controller 信号，在 `MainWindow.pages` 里登记。
- **新颜色或尺寸**：先加到 `theme.TOKENS` / `SPACE` / `RADIUS`，再在 QSS 里用 `@NAME@` 引用。
- **新适配型号**：键表进 `assets/`，`photo_template.is_fixed_model` 与 `inventory.SUPPORTED` 同步；固定型号隐藏学习、测试、位置、照片编辑入口。

## 测试

- `tests/test_controller.py`：不建窗口，直接驱动 controller。
- 其余 UI 测试用 `MainWindow(tmp_path, safe=True)`：不启动 USB 扫描、不建托盘、不修改系统设置或发送实际按键；动作执行通过 monkeypatch `controller.runner.run` 观察。
- 运行：`QT_QPA_PLATFORM=offscreen python -m pytest -q`；整套验收：`python scripts/verify.py`。

**预设文本动作**：`Action(kind="text", text=...)`，默认空字段保持旧配置可读；验证 1–10000 字符并拒绝 NUL/非法控制码及孤立代理项。`ActionRunner` 仅在 down 调用 `KeyOutput.input_text`，沿用控制器的按住去重。Qt 剪贴板保存纯文本，输出一个平台粘贴组合键，不添加 Enter，不经过 shell；界面提示剪贴板会更新。文本输入不会开启 USB、录音或额外服务。

**Qt 音频状态兼容**：使用 QtAudio.Error/State（不是旧 QAudio 枚举）；PySide6 6.12 的同名 NoError 可能来自不同枚举类，不相等。stateChanged 连接无参数 @Slot 并查询 sink.state()，规避遗留 QAudio::State 信号参数转换；同步启动信号由 start 返回后统一处理，stop 前保留错误码，避免重入删除 sink 或把 NoError 当失败。2026-11-05 静音实机探针通过，真实 USB/识别链另行验收。


**审计修复的输入与动作边界**：`input_codes.py` 把 Windows 标准扫描码归一为 HID trigger（Linux 的 MSC_SCAN 归一化随实现隔离在 `linux/`）；`windows_hid.py` 通过 HidP API 按实际预解析描述符处理 consumer 报告，保留 Report ID 与设备隔离。真实 Windows 特殊 # 键输入仍待确认，不猜测扫描码。`HIDReports` 对没有按键字段的报告直接忽略；适配器对坏按键包计数/跳过，传输故障和坏音频仍失败。真实采集描述符保存在测试 fixture 中，不需要额外 CC 越界例外。

**响应与心跳**：`launch.py` 用 QProcess 执行桌面 opener，最多 8 个并发、15 秒超时、错误输出保留上限 4 KB，完成后删除进程对象；退出只停止自己启动的 opener。控制器统一消费 LaunchRequest，保留真实启动失败反馈。XPC 客户端的 2 秒心跳由原生 GCD 队列运行，停止/失败时取消，不依赖 GUI 主线程或 GIL。服务端租约与有界队列仍防止失联/积压无限占用；长时间冻结导致音频队列满仍是明确错误，不无限缓存。

**持久化失败**：导入先保存再切换配置；名称、位置、增删键、照片与动作编辑在保存失败后恢复原内存状态。损坏的现有配置不会被自动覆盖；显示可读错误，不暴露 JSON 字段名/解析栈。键名的便携格式验证与本机可发送性验证分开，Mac 不支持 F21–F24 时在分配/录制阶段拒绝，不破坏其他平台导入配置。

**Mac 默认输入临时切换**：`mac_input.py` 用独立串行线程调用 CoreAudio，设备 UID 保存/解析、`dIn ` 属性通知及读回确认都不阻塞 GUI。`VoiceSession` 为 USB 会话增加准备与恢复阶段，准备时有界缓存 PCM，确认切换后才启动音频并发送识别快捷键；结束识别后恢复，恢复期间禁止新会话。取消中的迟到通知不启动录音，手动更改默认输入后让出控制权。电脑麦克风、文件回放与 safe 模式不修改系统默认输入；不操作默认输出。不新增原生助手或第三方依赖。

连接方式由配置 `input_routing`（`automatic` / `fixed`，缺省 automatic）控制，`VoiceSession.switch_input` 只在 USB 会话开始时读取。固定模式完全跳过默认输入租约。语音页按来源显示连接方式及对应说明，主界面语音键摘要同步；非 Mac 平台不提供未实现的自动切换选项。设置保存失败回滚内存和 UI，录音及恢复阶段禁止修改。
