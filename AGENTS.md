# AGENTS.md

> 本文件面向后续维护或继续开发该项目的 AI 编码助手。请在进行任何代码改动前先阅读本文件。

---

## 1. 项目背景与目标

**ubuntu-speak** 是一个面向 Ubuntu 桌面环境的语音输入法工具。

- **核心功能**：用户通过全局快捷键触发录音，松开快捷键后自动把语音上传到云端语音识别服务，识别结果写入系统剪贴板。
- **当前实现**：基于阿里云「百炼 / 灵积 (DashScope)」平台的 `qwen3-asr-flash` 语音识别模型（支持本地文件路径直接识别）。
- **最终交付形态**：打包成可在 Ubuntu 上安装的 `.deb` 软件包，安装后提供系统命令 `ubuntu-speak` 及桌面快捷启动/全局快捷键方案。
- **当前进度**：核心 Python 功能模块已完成；第一阶段状态反馈（系统托盘指示器 + 即时通知）已实现；第二阶段按住说话（evdev）已实现；`.deb` 已重新打包至 0.3.0-1。剩余缺口主要是用户文档与自动化测试。

---

## 2. 目录结构

```
ubuntu_speak/
├── pyproject.toml                  # Python 包元数据、依赖、构建配置（hatchling）
├── AGENTS.md                       # 本文件
├── README.md                       # 人类用户文档（待补充）
├── src/ubuntu_speak/               # Python 源码
│   ├── __init__.py                 # 包标识
│   ├── cli.py                      # 命令行入口、toggle/按住说话录音、daemon、配置交互
│   ├── asr.py                      # 调用阿里云百炼语音识别 API
│   ├── recorder.py                 # 系统音频录制（PipeWire / PulseAudio）
│   ├── clipboard.py                # 识别结果写入系统剪贴板
│   ├── notifier.py                 # 桌面通知
│   ├── config.py                   # 配置读取、保存、默认值
│   ├── state.py                    # 应用状态文件管理（indicator / daemon 共享）
│   ├── indicator.py                # 系统托盘指示器（GTK3 + AppIndicator）
│   ├── evdev_listener.py           # evdev 硬件热键监听（按住说话）
│   ├── shortcut_manager.py         # 桌面全局快捷键管理
│   └── settings_window.py          # GTK4 图形化配置窗口
├── debian/                         # Debian 打包文件
├── data/                           # 桌面资源：.desktop、图标、快捷键方案等
├── .venv/                          # Python 虚拟环境（本地开发使用）
└── ../releases/                    # 打包产物归档目录（.deb / .buildinfo / .changes）
```

---

## 3. 核心设计

### 3.1 工作流程

1. 用户按下全局快捷键 → 调用 `ubuntu-speak`（默认 toggle 模式）；或运行 `ubuntu-speak --listen-hotkey` 通过 evdev 监听硬件热键，按住录音、松开识别。
2. `cli.toggle_recording()` 检查是否有正在录音的 daemon：
   - 若有，发送 `SIGUSR1` 信号停止录音。
   - 若无，启动 `ubuntu-speak --daemon` 后台进程开始录音。
3. 状态文件 `~/.cache/ubuntu-speak/state.json` 会同步更新为 `recording` / `recognizing` / `success` / `error`。
4. `ubuntu-speak --indicator` 常驻系统托盘，根据状态文件切换图标与标签，并在状态变化时发送桌面通知。
5. daemon 录音结束后，调用 `asr.recognize()` 将音频通过 `file://` 本地路径传给百炼多模态对话接口进行识别。
6. 识别结果通过 `clipboard.copy_text()` 写入剪贴板。
7. 通过 `notifier.notify()` 发送桌面通知（作为 fallback）。

### 3.2 关键设计决策

- **前后端分离**：真正录音放在 daemon 进程，避免快捷键触发阻塞桌面。
- **状态共享**：通过 `state.json` 在 daemon、indicator 与 CLI 之间共享状态；indicator 轮询该文件并更新托盘图标。
- **系统依赖优先**：录音优先使用 `pw-record`（PipeWire），没有则回退 `parec + sox` 或纯 `parec`（PulseAudio）。
- **剪贴板兼容**：同时支持 Wayland（`wl-copy`）和 X11（`xclip` / `xsel`）。
- **云端识别**：当前仅支持阿里云百炼 DashScope API，模型默认 `qwen3-asr-flash`（通过 `dashscope.MultiModalConversation` 调用，音频以 `file://` 绝对路径传入）。
- **配置读取优先级**：环境变量 `DASHSCOPE_API_KEY` > `~/.config/ubuntu-speak/config.json`。

---

## 4. 开发环境

### 4.1 Python 版本

- 要求 Python `>=3.12`。
- 开发时使用项目根目录下的 `.venv` 虚拟环境。

### 4.2 安装依赖与本地运行

本项目已全面迁移到 [uv](https://docs.astral.sh/uv/) 工作流。uv 会自动读取 `pyproject.toml`，管理项目根目录下的 `.venv` 虚拟环境，并通过 `uv.lock` 锁定依赖版本。

```bash
cd ~/workdir/self_code/ubuntu_speak

# 根据 pyproject.toml 和 uv.lock 同步虚拟环境（首次或依赖变更后执行）
uv sync

# 运行项目命令（无需手动激活虚拟环境）
uv run ubuntu-speak --status
uv run ubuntu-speak --configure
uv run ubuntu-speak

# 单独安装/升级某个依赖
uv add <package>

# 移除依赖
uv remove <package>
```

**注意**：修改依赖后请提交 `uv.lock` 文件，确保所有协作者使用一致的依赖版本。

### 4.3 测试命令

添加测试后（例如 `tests/` 目录），使用 uv 运行：

```bash
# 运行全部测试
uv run pytest tests/

# 运行单个测试文件
uv run pytest tests/test_asr.py
```

### 4.4 构建命令

```bash
# 构建 wheel 包
uv build --wheel

# 构建源码包 + wheel
uv build

# Debian 打包（debian/ 补齐后）
# 注意：dpkg-buildpackage 默认会把 .deb / .buildinfo / .changes 输出到源码父目录。
# 为避免打包产物散落在项目同级目录，构建完成后必须统一移动到 releases/ 目录。
cd ~/workdir/self_code/ubuntu_speak
dpkg-buildpackage -us -uc -b
mv ../ubuntu-speak_*.deb ../ubuntu-speak_*.buildinfo ../ubuntu-speak_*.changes ../releases/
```

**打包产物目录约定**：所有 `.deb`、`.buildinfo`、`.changes` 文件必须归档到 `~/workdir/self_code/releases/`，禁止保留在项目根目录 `~/workdir/self_code/` 或源码目录 `ubuntu_speak/` 内。如果后续引入 Git，应在 `.gitignore` 中忽略这些打包产物。

**GitHub Releases 上传**：使用 `scripts/upload-release.sh` 手动上传，该脚本不会自动触发。运行前需要先配置 GitHub Token（详见脚本头部注释）。Token 文件路径已通过 `.gitignore` 排除，不会进入 Git 仓库。

### 4.5 运行时系统依赖

Ubuntu 桌面需安装以下工具之一：

Ubuntu 桌面需安装以下工具之一：

- PipeWire：`pipewire-bin`（提供 `pw-record`）
- 或 PulseAudio：`pulseaudio-utils` + `sox`

剪贴板工具：

- Wayland：`wl-clipboard`（提供 `wl-copy`）
- X11：`xclip` 或 `xsel`

通知：

- `libnotify-bin`（提供 `notify-send`）

托盘指示器：

- `gir1.2-gtk-3.0`
- `gir1.2-ayatanaappindicator3-0.1`（Ubuntu 24.04 默认）或 `gir1.2-appindicator3-0.1`

按住说话（evdev）：

- `python3-evdev`（提供 `evdev` 模块）
- 当前用户需要在 `input` 用户组（安装 `.deb` 时 `postinst` 会自动添加；修改后需注销重新登录生效）

本地开发（若通过 uv 安装 PyPI 版 `evdev`）：

- `python3-dev`（编译 `evdev` 扩展需要 `Python.h`）

### 4.6 目标运行环境（已验证）

通过 `env` 与 `loginctl`/`ps` 探查，当前用户实际运行的桌面环境如下：

| 项目 | 值 |
|---|---|
| 桌面环境 | `ubuntu:GNOME` |
| 会话类型 | `X11` |
| 显示服务器 | `Xorg` |
| `WAYLAND_DISPLAY` | 未设置 |
| `DISPLAY` | `:1` |

因此，后续优化应优先保证 **GNOME on X11** 的体验；同时保持对 Wayland 的兼容性（剪贴板、通知等已做兼容）。

---

## 5. 配置说明

配置文件位置：`~/.config/ubuntu-speak/config.json`

默认配置（见 `config.py`）：

```json
{
  "api_key": "",
  "model": "qwen3-asr-flash",
  "sample_rate": 16000,
  "channels": 1,
  "audio_format": "wav",
  "max_record_seconds": 60,
  "language_hints": "zh",
  "evdev_key": "KEY_F12",
  "evdev_grab": false
}
```

**注意**：不要把真实 API Key 写入代码或 Git。优先通过 `DASHSCOPE_API_KEY` 环境变量注入，或通过 `ubuntu-speak --configure` 交互式保存。

---

## 6. 编码规范

- **语言**：代码注释和文档优先使用中文。
- **格式化**：保持现有 4 空格缩进，不引入额外格式化工具（除非用户要求）。
- **类型注解**：适度使用 Python 类型注解（参考现有代码风格）。
- **错误处理**：对系统命令调用做异常捕获，失败时通过 `notify()` 或 `print()` 给出用户可见的提示。
- **最小改动**：修改现有逻辑时尽量保持接口不变；如需调整，同步更新调用方。
- **新文件位置**：Python 模块放在 `src/ubuntu_speak/`，桌面资源放在 `data/`，打包脚本放在 `debian/`。

---

## 7. 待办事项（已知缺口）

按优先级排列：

1. ~~Debian 打包（已重新构建至 0.3.0-1）：托盘图标、状态反馈、evdev 热键与 input 组权限均已处理。~~
2. ~~按住说话（第二阶段，已完成）：通过 `evdev` 监听键盘 press/release，实现按下录音、松开识别。~~
3. **用户文档**：补充 `README.md`，说明安装、配置 API Key、绑定快捷键、使用方法（含 toggle 模式与 `--listen-hotkey` 模式）。
4. **测试**：添加单元测试或至少一条端到端录音识别测试（需 mock API）。
5. **本地模型（可选）**：未来可考虑增加本地 ASR 模型支持（如 Whisper / SenseVoice 本地版），降低对云 API 的依赖。

---

## 8. 与用户沟通时的偏好

- 用户主要使用中文交流，回复需使用中文。
- 用户当前最关注：
  - 解决命令行 `ubuntu-speak` 无法运行的问题；
  - 完成 `.deb` 打包；
  - 对接阿里云百炼 API。
- 在动手前，如存在多个可行方案，可简要列出供用户选择，但默认推荐最简单可行的方案。

---

## 9. 常用命令速查

```bash
# 同步虚拟环境
uv sync

# 运行项目命令
uv run ubuntu-speak --status
uv run ubuntu-speak --configure
uv run ubuntu-speak

# 添加/移除依赖
uv add <package>
uv remove <package>

# 构建 wheel
uv build --wheel

# 运行测试
uv run pytest tests/

# 打包（debian/ 补齐后）
# 注意：dpkg-buildpackage 默认会把 .deb / .buildinfo / .changes 输出到源码父目录。
# 为避免打包产物散落在项目同级目录，构建完成后必须统一移动到 releases/ 目录。
cd ~/workdir/self_code/ubuntu_speak
dpkg-buildpackage -us -uc -b
mv ../ubuntu-speak_*.deb ../ubuntu-speak_*.buildinfo ../ubuntu-speak_*.changes ../releases/

# 手动上传到 GitHub Releases（需先配置 GITHUB_TOKEN）
./scripts/upload-release.sh
```
```
