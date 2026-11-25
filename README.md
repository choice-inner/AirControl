# AirControl

基于 OpenCV 和 MediaPipe 的 Windows 单手手势鼠标。第一版默认使用 B 方案：捏合移动、张指点击、张掌拖拽、双指滚动。

## 日常使用

- **便携版：**打开 `dist/AirControl/Start AirControl.cmd`，或解压 `releases/` 中的 ZIP 后启动。保留整个便携版文件夹。
- **源码版：**双击根目录 `start_preview.cmd`，使用 `E:\conda_envs\AirControl` 环境。
- 启动默认预览；点击预览窗口、按 **C**，再保持中立姿势，显示 **CONTROL** 后开始真实控制。**F8** 暂停/恢复，**F9** 急停，**Esc** 退出。

完整手势、恢复方式和限制见 [使用说明](docs/USER_GUIDE.md)。

```powershell
& E:\conda_envs\AirControl\python.exe main.py
& E:\conda_envs\AirControl\python.exe main.py --control
```

## 目录结构

```text
AirControl/
├── main.py                  默认 B 方案启动入口
├── start_preview.cmd        使用指定 Conda 环境启动
├── aircontrol/              应用代码、手势算法、系统输入、阶段预览
├── tests/                   自动测试
├── docs/                    使用说明、环境说明、规划与开发记录
├── models/                  手部模型与来源说明
├── scripts/                 打包脚本
├── packaging/               PyInstaller 配置与打包依赖
├── legacy/                  不再使用的早期草稿
├── requirements.txt         运行依赖
├── requirements-lock.txt    开发环境依赖快照
├── environment.yml          Conda 环境定义
├── dist/AirControl/         可直接启动的便携版（构建生成）
├── releases/                ZIP 发布包、校验文件及历史包
└── build/                   打包中间文件（构建生成）
```

详细模块职责、阶段入口和整理记录见 [开发指南](docs/DEVELOPMENT.md)。阶段 2–8 的历史记录见 [开发阶段记录](docs/DEVELOPMENT_HISTORY.md)。

## 开发与验证

所有命令从项目根目录执行；环境准备见 [环境说明](docs/ENVIRONMENT_SETUP.md)。

```powershell
& E:\conda_envs\AirControl\python.exe -m unittest discover -q
& E:\conda_envs\AirControl\python.exe main.py --self-check
& E:\conda_envs\AirControl\python.exe -m aircontrol.stage8_ab_preview
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

阶段脚本已改为包内模块，请使用 `python -m aircontrol.<模块名>` 启动。默认入口仍可使用 `python main.py`，也支持 `python -m aircontrol`。自检不打开摄像头、不操作鼠标；打包过程会运行自动测试并验证 EXE 的模型加载与推理。

第一版已由用户实测确认当前效果基本理想；跨电脑兼容性、长期连续使用和误触率尚未量化验收。范围与后续事项见 [第一版规划](docs/FIRST_VERSION_PLAN.md)。
