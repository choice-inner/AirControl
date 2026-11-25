# 开发指南

## 入口与模块

从项目根目录运行，解释器为 `E:\conda_envs\AirControl\python.exe`。源码使用标准 Python 包内相对导入，不需要修改 `PYTHONPATH`。

| 路径 | 用途 |
|---|---|
| `main.py` / `aircontrol/__main__.py` | 默认 B 方案入口，默认预览 |
| `aircontrol/aircontrol_app.py` | 启动参数、窗口、键盘交互和资源生命周期 |
| `aircontrol/hand_tracker.py` | MediaPipe 手部关键点检测 |
| `aircontrol/gesture_scheme_b.py` | B 方案手势与相对移动、点击、拖拽状态 |
| `aircontrol/stage8_b_control.py` | B 方案真实输入与安全状态 |
| `aircontrol/mouse_output.py`、`windows_wheel.py` | 鼠标输出接口与 Windows 滚轮 |
| `aircontrol/safety_monitor.py` | 全局快捷键与帧超时监控 |
| `aircontrol/config.py` | 公共配置；B 的部分参数仍位于 B 状态机中 |
| `aircontrol/gesture_detector.py`、`cursor_mapper.py`、`click_drag_controller.py` | A 方案与阶段预览使用的识别、映射和点击拖拽逻辑 |
| `aircontrol/scroll_controller.py` | 滚动状态机 |
| `aircontrol/self_check.py` | 无摄像头、无真实输入的模型自检 |

模块名中的 `stage` 保留开发过程的对应关系。正式 B 入口仍复用阶段 2/4/5/6 的画面、坐标和关键点辅助函数，因此这些文件属于运行依赖；本次只整理路径，不重新拆分其逻辑。

## 阶段入口

以下命令使用已激活的项目环境，支持各自的 `--help`：

| 命令 | 用途 |
|---|---|
| `python -m aircontrol.stage2_hand_preview` | 摄像头与手部关键点 |
| `python -m aircontrol.stage3_gesture_preview` | A 方案手势判断 |
| `python -m aircontrol.stage4_cursor_preview` | 坐标映射与平滑 |
| `python -m aircontrol.stage5_click_drag_preview` | A 方案点击拖拽预览 |
| `python -m aircontrol.stage6_scroll_preview` | 滚动预览 |
| `python -m aircontrol.stage7_mouse_control` | 保留的 A 方案真实控制入口，默认预览 |
| `python -m aircontrol.stage8_ab_preview` | A/B 对照，默认 A 预览 |
| `python -m aircontrol.stage8_ab_preview --scheme B --control` | B 真实控制对照，仍需中立确认 |

不要直接运行 `python aircontrol/stage*.py`；请使用 `-m` 以正确解析包内导入。`legacy/actions.py` 仅归档查阅，不参与当前入口与打包。

## 测试与打包

```powershell
& E:\conda_envs\AirControl\python.exe -m unittest discover -q
& E:\conda_envs\AirControl\python.exe -m unittest -v tests.test_gesture_scheme_b tests.test_stage8_b_control
& E:\conda_envs\AirControl\python.exe main.py --self-check
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

打包配置为 `packaging/AirControl.spec`，打包依赖为 `packaging/requirements-build.txt`。`scripts/package_release.py` 解析项目根路径，先测试后打包，复制使用说明和第三方许可，再从临时工作目录执行 EXE 自检；自检的 PATH 不包含 Conda 路径，通过后生成 ZIP 和 SHA256。

源码模型寻址为项目根目录的 `models/hand_landmarker.task`。目录便携包的对应位置为 `_internal/models/hand_landmarker.task`，不依赖启动时的工作目录。

`build/` 为可重新生成的打包中间文件；`dist/` 为当前便携版；`releases/` 为压缩包。它们不纳入 Git。整理前的第一版 ZIP 保留在 `releases/archive/before-directory-cleanup/`，新的构建仍输出到 `releases/`。

## 本次整理范围（2026-11-25）

将应用模块、测试、文档、打包脚本和历史草稿分别归档，更新 Python 导入、模型寻址、文档链接、测试命令与打包配置。保留 `main.py`、`start_preview.cmd` 和运行环境清单在根目录。手势参数与交互规则沿用当前第一版。

详细日志、量化使用测试、进一步集中配置和算法优化仍作为后续工作；本次不将这些事项作为整理前置条件。
