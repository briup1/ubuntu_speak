# ubuntu_speak

Ubuntu 桌面语音输入法。按住全局快捷键录音，松开自动识别语音并写入系统剪贴板。

当前基于阿里云[百炼 / 灵积（DashScope）](https://dashscope.aliyun.com/)语音识别模型 `qwen3-asr-flash`。

---

## 功能特性

- **语音转文字**：录音后自动上传云端识别，结果写入剪贴板。
- **两种录音模式**：
  - **Toggle 模式**：按一次快捷键开始录音，再按一次结束并识别。
  - **按住说话**：通过 `evdev` 监听硬件热键，按住录音、松开识别。
- **系统托盘指示器**：实时显示录音 / 识别 / 成功 / 错误状态。
- **桌面通知**：识别完成或出错时弹出通知。
- **兼容 Wayland / X11**：剪贴板自动适配 `wl-copy` 或 `xclip` / `xsel`。

---

## 安装

### 方式一：从 GitHub Releases 下载 `.deb`（推荐）

1. 打开 [Releases 页面](https://github.com/briup1/ubuntu_speak/releases)。
2. 下载最新的 `ubuntu-speak_x.y.z-N_all.deb`。
3. 安装：

   ```bash
   sudo dpkg -i ubuntu-speak_0.3.6-1_all.deb
   sudo apt-get install -f
   ```

4. 注销并重新登录，使 `input` 用户组权限生效（evdev 热键需要）。

### 方式二：从源码构建

```bash
# 克隆仓库
git clone git@github.com:briup1/ubuntu_speak.git
cd ubuntu_speak

# 同步依赖（需要安装 uv）
uv sync

# 本地运行
uv run ubuntu-speak --status

# 构建 .deb
dpkg-buildpackage -us -uc -b
mv ../ubuntu-speak_*.deb ../ubuntu-speak_*.buildinfo ../ubuntu-speak_*.changes ../releases/
```

---

## 配置 API Key

本项目需要阿里云 DashScope API Key 才能调用语音识别服务。

### 获取 API Key

1. 登录 [DashScope 控制台](https://dashscope.aliyun.com/)。
2. 进入「API-KEY 管理」。
3. 创建并复制 API Key（以 `sk-` 开头）。

### 配置方式（二选一）

**方式一：环境变量（临时，适合开发调试）**

```bash
export DASHSCOPE_API_KEY="sk-xxxxxxxxxxxx"
```

**方式二：交互式保存（推荐，长期使用）**

```bash
ubuntu-speak --configure
```

按提示输入 API Key，程序会将其保存到 `~/.config/ubuntu-speak/config.json`。

> ⚠️ **注意**：不要把真实 API Key 写入代码、Git 仓库或任何会被公开的文件。

---

## 使用方法

### 1. 启动系统托盘指示器

```bash
ubuntu-speak --indicator
```

建议将其加入开机启动程序。

### 2. Toggle 模式录音

默认触发命令：

```bash
ubuntu-speak
```

第一次调用开始录音，第二次调用结束录音并开始识别。

### 3. 按住说话模式（evdev 热键）

```bash
ubuntu-speak --listen-hotkey
```

按住配置的热键录音，松开自动识别。

默认热键为 `KEY_RIGHTALT`，可在配置中修改。

### 4. 查看当前状态

```bash
ubuntu-speak --status
```

### 5. 图形化配置窗口

```bash
ubuntu-speak --settings
```

---

## 系统依赖

录音：

- PipeWire：`pipewire-bin`（提供 `pw-record`）
- 或 PulseAudio：`pulseaudio-utils` + `sox`

剪贴板：

- Wayland：`wl-clipboard`
- X11：`xclip` 或 `xsel`

通知：

- `libnotify-bin`

托盘指示器：

- `gir1.2-gtk-3.0`
- `gir1.2-ayatanaappindicator3-0.1` 或 `gir1.2-appindicator3-0.1`

按住说话：

- `python3-evdev`
- 当前用户需要在 `input` 用户组（安装 `.deb` 时自动添加，需注销重登生效）

---

## 项目结构

```
ubuntu_speak/
├── src/ubuntu_speak/    # Python 源码
├── debian/              # Debian 打包文件
├── data/                # 桌面资源（图标、.desktop 等）
├── scripts/             # 辅助脚本（如上传 Release）
├── pyproject.toml       # Python 包配置
├── uv.lock              # 依赖锁定文件
├── AGENTS.md            # 面向 AI 协作者的开发说明
└── README.md            # 本文件
```

---

## 常见问题

### 快捷键没有反应

- 确认已配置 API Key：`ubuntu-speak --status`
- 确认托盘指示器已启动：`ubuntu-speak --indicator`
- 使用 evdev 模式时，确认已注销并重新登录以应用 `input` 组权限。

### 录音失败

- 检查系统是否安装了 `pw-record` 或 `parec`。
- 检查麦克风是否被其他应用占用。

### 识别成功但剪贴板没有内容

- Wayland 用户安装 `wl-clipboard`。
- X11 用户安装 `xclip` 或 `xsel`。

### 通知没有弹出

- 安装 `libnotify-bin`。
- 检查当前桌面环境是否支持桌面通知。

---

## 开发与构建

```bash
# 同步依赖
uv sync

# 运行测试
uv run pytest tests/

# 构建 wheel
uv build --wheel

# 构建 Debian 包
dpkg-buildpackage -us -uc -b
mv ../ubuntu-speak_*.deb ../ubuntu-speak_*.buildinfo ../ubuntu-speak_*.changes ../releases/
```

---

## 许可证

MIT License

---

## 相关链接

- 项目主页：https://github.com/briup1/ubuntu_speak
- Release 下载：https://github.com/briup1/ubuntu_speak/releases
- DashScope 控制台：https://dashscope.aliyun.com/
