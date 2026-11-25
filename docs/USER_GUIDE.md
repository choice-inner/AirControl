# AirControl v0.1.0 使用说明

Windows 单手手势鼠标原型，默认 B 方案。支持移动、左键单击、拖拽和页面滚动。

## 便携版启动

1. 解压 `AirControl-v0.1.0-windows-x64.zip`，保留整个 `AirControl` 文件夹。
2. 双击 `Start AirControl.cmd`（或 `AirControl.exe`）。无需安装 Conda 或 Python；运行不需要联网下载模型。
3. 默认只预览。点击摄像头预览窗口使其获得焦点，按 **C** 开启真实控制。
4. 四指自然弯曲，拇指与食指分开，不要捏合，也不要张掌。保持到状态显示 **CONTROL**，再开始操作。

这是“中立姿势”：只用于恢复确认，不会点击。拇指紧贴食指的握拳可能会被识别成捏合；以画面的 `Gesture: NONE`、`Candidate: NONE` 为准，连续 3 帧后恢复控制。

程序会同时打开终端和摄像头预览窗口。不要只复制 EXE；`_internal` 中包含模型、Python 运行时和动态库。

## B 方案手势

| 操作 | 手势与行为 |
|---|---|
| 移动 | 拇指尖与食指尖靠近，稳定识别为 `PINCH_AIM` 后移动手；光标按拇指尖的相对位移移动 |
| 重新摆手 | 收起手指成为中立姿势，调整手的位置后再捏合，重新建立相对移动基准 |
| 左键单击 | 先捏合瞄准，随后拇指与食指大幅张开（类似“八”），其余手指收起；稳定确认后点击一次。点击确认时不再将光标移向张开的拇指 |
| 拖拽 | 先把光标移到目标，张开手掌并张开拇指，识别为 `DRAG_OPEN` 后按住左键；移动手时跟随拇指尖。离开张掌姿势并稳定确认后释放 |
| 滚动 | 食指、中指伸直并靠拢，其余手指收起，上下移动两指；光标应预先放在要滚动的窗口上 |
| 停止本次移动 | 回到中立姿势；手离开画面也会停止输入并释放拖拽 |

移动/点击与拖拽/滚动互斥。当前不支持独立右键、专用双击手势、缩放或多屏控制。

## 快捷键

| 按键 | 功能 | 生效范围 |
|---|---|---|
| C | 从预览或暂停开启控制，再保持中立姿势 | 预览窗口有焦点时 |
| P | 暂停/恢复，恢复后先保持中立姿势 | 预览窗口有焦点时 |
| F8 | 暂停/恢复；首次预览请使用 C 开启 | 全局 |
| E / F9 | 锁定急停并释放左键；需重启程序才能再次控制 | E 需窗口焦点，F9 全局 |
| Q / Esc | 释放左键并退出 | Q 需窗口焦点，Esc 全局 |

将物理鼠标推到主屏角落也可触发 PyAutoGUI 的 Fail-Safe。

## 看懂状态与“无响应”

虚拟光标可在预览或暂停期间继续变化；**它能动不等于真实鼠标正在输出**，请同时查看 `Mode` 和 `Input`。

| 显示 | 含义与处理 |
|---|---|
| PREVIEW | 只预览，按 C 后保持中立姿势 |
| CONTROL | 已允许真实输入；`MOVE_SENT` / `CLICK_SENT` / `WHEEL_SENT` 表示调用了对应输入接口 |
| WAIT FOR NEUTRAL | 等待中立姿势；四指弯曲、拇指与食指分开，等待 `NONE` 连续确认 |
| WAIT FOR NEUTRAL / FRAME_TIMEOUT | 超过 0.75 秒没有新帧，已释放拖拽并清空旧动作；画面恢复且保持中立后自动继续，无需按 F8 |
| PAUSED | 手动暂停，按 F8 或窗口内 P/C 恢复，再保持中立 |
| EMERGENCY STOP | 急停锁定，退出后重启 |
| AIM_FROZEN / Aim locked: True | 正在离开捏合，暂时固定瞄准位置以确认点击；恢复捏合候选会解除 |

如果 `CONTROL` 且持续显示 `MOVE_SENT`，但真实鼠标仍不响应，请保留终端信息，并确认目标是否为管理员权限程序。发送接口被调用并不能证明目标窗口接收了输入。

## 摄像头、自检与源码启动

在便携版文件夹打开 PowerShell：

```powershell
.\AirControl.exe --help
.\AirControl.exe --camera 1
.\AirControl.exe --self-check
.\AirControl.exe --control
```

`--camera 1` 切换摄像头，默认索引为 0。`--self-check` 加载随包模型并执行空白图推理，不打开摄像头、不输出鼠标事件；它不能验证实际摄像头、手势手感和桌面输入。`--control` 启动后仍需中立确认。

源码版在项目目录双击 `start_preview.cmd`，或运行：

```powershell
& E:\conda_envs\AirControl\python.exe main.py
& E:\conda_envs\AirControl\python.exe main.py --control
```

源码版保留 A 方案：`aircontrol/stage7_mouse_control.py`；A/B 对照：`aircontrol/stage8_ab_preview.py`。便携 EXE 只提供默认 B 使用入口。

目录整理后，阶段预览从项目根目录以模块方式启动，例如：

```powershell
& E:\conda_envs\AirControl\python.exe -m aircontrol.stage8_ab_preview
```

请使用 `-m aircontrol.<模块名>`，不要直接运行包内的 `.py` 文件；日常默认入口 `main.py` 和 `start_preview.cmd` 仍在根目录。

## 已知限制

- 第一版面向 Windows x64、主屏、单只手；尚未完成跨电脑兼容性、长时间连续使用与点击命中率的量化验收。
- 遮挡、弱光、运动模糊或手超出画面仍可能使手势中断。丢手会释放拖拽，重新控制前需要中立确认。
- 当前普通权限输入不保证能控制管理员窗口、UAC 安全桌面或限制模拟输入的应用。
- 退出后 MediaPipe 资源清理可能有延迟；先让程序完成退出。
- 终端可能显示 MediaPipe 的 XNNPACK、feedback manager、NORM_RECT 提示；如出现 Traceback 或自检失败，应保留完整错误。
- 这是当前环境构建的原型便携包，未做数字签名；不能视为已覆盖所有 Windows 版本。

## 重新打包

在准备好运行依赖的开发环境中：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

脚本会安装固定版本打包工具、运行自动测试、按 `packaging/AirControl.spec` 生成目录包，并在另一个工作目录运行 EXE 的离线自检；全部通过后才生成 `releases/AirControl-v0.1.0-windows-x64.zip` 和 SHA256 文件。打包时可用 `-Python <解释器路径>` 替换默认 Conda 解释器。

源码依赖见 `requirements.txt`，当前环境快照见 `requirements-lock.txt`，打包工具见 `packaging/requirements-build.txt`。第三方文件来源与许可文本随包保存在 `THIRD_PARTY_NOTICES.txt`、`third_party_licenses/`；模型来源见 `_internal/models/README.md`。
