# AirControl 开发环境准备

## 固定环境

第一版开发使用 Windows 和以下 Conda 环境：

```text
E:\conda_envs\AirControl
```

当前已验证：

| 项目 | 版本或状态 |
|---|---|
| Python | 3.11.17 |
| OpenCV | 5.0.0，来自 `opencv-contrib-python==5.0.0.93` |
| MediaPipe | 1.1.1 |
| PyAutoGUI | 0.9.54 |
| 摄像头索引 0 | 可以打开 |

## 使用已有环境

在 PowerShell 中进入项目目录后，优先使用环境自身的 Python：

```powershell
conda activate E:\conda_envs\AirControl
python --version
python -m pip install -r requirements.txt
```

如果当前终端没有正确加载 `conda activate`，可以直接调用环境解释器：

```powershell
& E:\conda_envs\AirControl\python.exe --version
& E:\conda_envs\AirControl\python.exe -m pip install -r requirements.txt
```

项目依赖统一通过 `python -m pip` 安装，避免误用系统 Python 的 pip。

## 依赖文件

- `requirements.txt`：项目直接依赖，使用固定版本。
- `requirements-lock.txt`：当前环境完整依赖快照，用于复现已验证环境。
- `environment.yml`：Conda 环境的基础定义；由于项目依赖通过 pip 安装，更新现有路径环境时仍应执行 `python -m pip install -r requirements.txt`。

OpenCV 使用 `opencv-contrib-python`，因为 MediaPipe 依赖 OpenCV contrib 包。环境中不再同时安装 `opencv-python`，避免两个包共同提供 `cv2` 导致版本冲突。

当前 MediaPipe 版本使用 Tasks API：`mediapipe.tasks.python.vision.HandLandmarker`。它不提供旧版的 `mp.solutions.hands` 接口，因此正式实现阶段应按 Tasks API 编写，并准备对应的 Hand Landmarker `.task` 模型文件。模型文件不随 Python 依赖自动安装，放置位置和版本在阶段 2 开始前固定并记录。

阶段二所用模型已放在 `models/hand_landmarker.task`；来源、大小和 SHA256 见 [models/README.md](../models/README.md)。

## 环境验证

### 验证解释器和核心依赖

```powershell
& E:\conda_envs\AirControl\python.exe -c "import sys, cv2, mediapipe, pyautogui; print(sys.executable); print(cv2.__version__); print(mediapipe.__version__); print(pyautogui.__version__)"
```

预期输出应包含：

```text
E:\conda_envs\AirControl\python.exe
5.0.0
1.1.1
0.9.54
```

### 验证依赖一致性

```powershell
& E:\conda_envs\AirControl\python.exe -m pip check
```

预期输出：

```text
No broken requirements found.
```

### 验证 MediaPipe 手部追踪 API

```powershell
& E:\conda_envs\AirControl\python.exe -c "from mediapipe.tasks.python import vision; print('hand_landmarker=', hasattr(vision, 'HandLandmarker'))"
```

预期输出：

```text
hand_landmarker=True
```

该检查只验证 Python API 已安装，不代表模型文件已经准备好，也不代替摄像头阶段的实际识别测试。

### 验证摄像头

```powershell
& E:\conda_envs\AirControl\python.exe -c "import cv2; camera=cv2.VideoCapture(0); print('camera_opened=', camera.isOpened()); camera.release()"
```

`camera_opened=True` 只说明索引 0 的摄像头可以被打开；真正开发时仍需验证画面质量、分辨率和光照条件。

## 当前环境检查结果

2026-10-17 已完成：

- 指定路径环境存在。
- Python 解释器路径正确。
- OpenCV、MediaPipe、PyAutoGUI 可以导入。
- MediaPipe Tasks 的 `HandLandmarker` API 可以导入。
- 摄像头索引 0 可以打开。
- 阶段二预览入口为 `aircontrol/stage2_hand_preview.py`，只显示关键点，不操作鼠标。
- `requirements-lock.txt` 已记录当前完整依赖版本。

Conda 启动时可能显示 `anaconda-cloud-auth` 与 `typing_extensions` 相关的提示。这是基础 Conda 安装的插件提示，不属于 AirControl 项目依赖；当前环境的 Python、pip、核心库和摄像头探测均已正常工作。后续如需处理该提示，应单独维护基础 Conda 安装，不与项目依赖混合处理。
