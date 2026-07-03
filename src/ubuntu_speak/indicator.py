"""系统托盘指示器

提供一个常驻 GNOME/KDE 面板的图标，实时显示 ubuntu-speak 的状态：
- 待机
- 录音中
- 识别中
- 完成
- 错误

优先使用 Ayatana AppIndicator（Ubuntu 24.04 默认），回退到传统 AppIndicator3。
"""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

try:
    import gi

    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    except ValueError:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3
    from gi.repository import GLib, Gtk
except ImportError as e:
    raise ImportError(
        "运行系统托盘指示器需要安装 python3-gi、gir1.2-gtk-3.0 与 "
        "gir1.2-ayatanaappindicator3-0.1（或 gir1.2-appindicator3-0.1）"
    ) from e

from .config import config
from .notifier import notify
from .state import AppState, StateManager


INDICATOR_PID_FILE = config.cache_dir / "indicator.pid"
HOTKEY_PID_FILE = config.cache_dir / "hotkey.pid"


def _write_indicator_pid():
    """写入 indicator 进程 PID"""
    try:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        INDICATOR_PID_FILE.write_text(str(os.getpid()))
    except Exception as e:
        print(f"[indicator] 写入 PID 失败: {e}")


def _clear_indicator_pid():
    """清除 indicator 进程 PID"""
    try:
        INDICATOR_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


class UbuntuSpeakIndicator:
    """Ubuntu Speak 系统托盘指示器"""

    # 状态 -> 图标名、显示标签、描述
    STATE_META = {
        AppState.IDLE: ("ubuntu-speak", "待机", "Ubuntu Speak：待机"),
        AppState.RECORDING: ("ubuntu-speak-recording", "录音中", "Ubuntu Speak：正在录音"),
        AppState.RECOGNIZING: ("ubuntu-speak-recognizing", "识别中", "Ubuntu Speak：语音识别中"),
        AppState.SUCCESS: ("ubuntu-speak-success", "完成", "Ubuntu Speak：识别完成"),
        AppState.ERROR: ("ubuntu-speak-error", "错误", "Ubuntu Speak：发生错误"),
    }

    # 需要复制到用户图标缓存目录的状态图标
    ICON_NAMES = [
        "ubuntu-speak",
        "ubuntu-speak-recording",
        "ubuntu-speak-recognizing",
        "ubuntu-speak-success",
        "ubuntu-speak-error",
    ]

    def __init__(self):
        self.state_manager = StateManager()
        self.current_state = AppState.IDLE
        self.last_message = ""
        self.last_mtime = 0.0

        # 确保状态图标可被 GTK 主题找到
        self._setup_icons_to_cache()

        # 创建一个隐藏窗口，让 GTK 主循环保持运行
        self._hidden_window = Gtk.Window()
        self._hidden_window.set_default_size(1, 1)
        self._hidden_window.set_decorated(False)
        self._hidden_window.set_skip_taskbar_hint(True)
        self._hidden_window.set_skip_pager_hint(True)
        self._hidden_window.set_keep_below(True)
        # 使用 CSS 实现完全透明，避免 set_opacity 弃用警告
        self._hidden_window.get_style_context().add_class("ubuntu-speak-hidden")
        css = Gtk.CssProvider()
        css.load_from_data(b".ubuntu-speak-hidden { background-color: transparent; opacity: 0; }")
        Gtk.StyleContext.add_provider_for_screen(
            self._hidden_window.get_screen(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._hidden_window.show()

        self.indicator = AppIndicator3.Indicator.new(
            "ubuntu-speak",
            "ubuntu-speak",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Ubuntu Speak")

        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        # 注册 POSIX 信号，确保 Ctrl+C 能退出 GTK 主循环
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """处理退出信号"""
        GLib.idle_add(self._quit)

    def _setup_icons_to_cache(self):
        """把状态图标安装到用户缓存目录，并加入 GTK 图标主题搜索路径"""
        icons_dir = config.cache_dir / "icons" / "hicolor" / "scalable" / "apps"
        icons_dir.mkdir(parents=True, exist_ok=True)

        # 源图标目录：优先使用源码 data/，否则假设已在系统主题中
        src_dir = None
        # 从本文件向上定位到项目 data/ 目录
        possible = Path(__file__).resolve().parent.parent.parent.parent / "data"
        if possible.is_dir() and (possible / "ubuntu-speak.svg").exists():
            src_dir = possible
        else:
            # 已安装场景：图标应在系统主题路径中，无需复制
            pass

        if src_dir:
            for name in self.ICON_NAMES:
                src = src_dir / f"{name}.svg"
                if src.exists():
                    dst = icons_dir / f"{name}.svg"
                    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                        shutil.copy2(src, dst)

        # 让 GTK 能搜索到缓存目录里的图标
        theme = Gtk.IconTheme.get_default()
        if theme and str(icons_dir.parent.parent.parent) not in theme.get_search_path():
            theme.append_search_path(str(icons_dir.parent.parent.parent))

    def _build_menu(self):
        """构建右键菜单"""
        # 当前状态标签（不可点击，用于显示文字状态）
        self.status_item = Gtk.MenuItem(label="Ubuntu Speak")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        self.sep1 = Gtk.SeparatorMenuItem()
        self.menu.append(self.sep1)

        # 开始录音
        self.record_item = Gtk.MenuItem(label="开始录音")
        self.record_item.connect("activate", self._on_start_recording)
        self.menu.append(self.record_item)

        # 停止录音
        self.stop_item = Gtk.MenuItem(label="停止并识别")
        self.stop_item.connect("activate", self._on_stop_recording)
        self.stop_item.set_sensitive(False)
        self.menu.append(self.stop_item)

        self.sep2 = Gtk.SeparatorMenuItem()
        self.menu.append(self.sep2)

        # 设置
        self.settings_item = Gtk.MenuItem(label="设置")
        self.settings_item.connect("activate", self._on_settings)
        self.menu.append(self.settings_item)

        # 退出
        self.quit_item = Gtk.MenuItem(label="退出")
        self.quit_item.connect("activate", self._on_quit)
        self.menu.append(self.quit_item)

        self.menu.show_all()

    def _on_start_recording(self, widget):
        """菜单：开始录音"""
        subprocess.Popen(
            ["ubuntu-speak"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _on_stop_recording(self, widget):
        """菜单：停止录音"""
        subprocess.Popen(
            ["ubuntu-speak"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _on_settings(self, widget):
        """菜单：打开设置窗口"""
        subprocess.Popen(
            [sys.executable, "-m", "ubuntu_speak.cli", "--settings"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _on_quit(self, widget):
        """菜单：退出"""
        # 如果按住说话进程在运行，先把它一起关掉
        try:
            if HOTKEY_PID_FILE.exists():
                pid = int(HOTKEY_PID_FILE.read_text().strip())
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, OSError):
            pass
        HOTKEY_PID_FILE.unlink(missing_ok=True)
        self._quit()

    def _quit(self):
        """退出主循环"""
        # 退出时把状态重置为 idle
        try:
            self.state_manager.set_state(AppState.IDLE)
        except Exception:
            pass
        _clear_indicator_pid()
        Gtk.main_quit()
        return False

    def _update_ui(self):
        """根据状态文件更新图标、标签和菜单"""
        state_data = self.state_manager.get_state()
        state_value = state_data.get("state", AppState.IDLE.value)
        message = state_data.get("message", "")

        try:
            new_state = AppState(state_value)
        except ValueError:
            new_state = AppState.IDLE

        if new_state == self.current_state and message == self.last_message:
            return True

        self.current_state = new_state
        self.last_message = message

        icon_name, label, desc = self.STATE_META.get(
            new_state, ("ubuntu-speak", "未知", "Ubuntu Speak")
        )

        # 更新图标与标签
        self.indicator.set_icon_full(icon_name, desc)
        self.indicator.set_label(label, "")
        self.indicator.set_title(desc)

        # 更新菜单状态文字
        display = f"Ubuntu Speak：{label}"
        if message:
            display += f"\n{message[:40]}"
        self.status_item.set_label(display)

        # 菜单项可用性
        is_recording = new_state == AppState.RECORDING
        self.record_item.set_sensitive(not is_recording)
        self.stop_item.set_sensitive(is_recording)

        # 状态变化时发送桌面通知（由 indicator 统一输出，避免 daemon 丢失 X11 授权）
        if new_state == AppState.RECORDING:
            notify("开始录音", message or "请说话，松开快捷键后识别", urgency="low")
        elif new_state == AppState.RECOGNIZING:
            notify("识别中", message or "正在调用百炼语音识别 API...", urgency="low")
        elif new_state == AppState.SUCCESS:
            notify("识别完成", message or "已复制到剪贴板", urgency="normal")
        elif new_state == AppState.ERROR:
            notify("Ubuntu Speak", message or "发生错误", urgency="critical")

        # 成功/错误状态保持几秒后自动回到 idle
        if new_state in (AppState.SUCCESS, AppState.ERROR):
            def reset_idle():
                self.state_manager.set_state(AppState.IDLE)
                self._update_ui()
                return False

            GLib.timeout_add_seconds(3, reset_idle)

        return True

    def _poll_state(self):
        """轮询状态文件"""
        try:
            if self.state_file.exists():
                mtime = self.state_file.stat().st_mtime
                if mtime != self.last_mtime:
                    self.last_mtime = mtime
                    self._update_ui()
        except Exception as e:
            print(f"[indicator] 轮询状态失败: {e}")
        return True

    def _start_polling(self):
        """启动状态轮询（200ms 一次）"""
        self.state_file = self.state_manager.state_file
        GLib.timeout_add(200, self._poll_state)
        # 立即更新一次
        self._update_ui()

    def run(self):
        """运行指示器主循环"""
        _write_indicator_pid()
        self._start_polling()
        # 注册 GLib 信号处理，确保 Ctrl+C / SIGTERM 能退出 GTK 主循环
        try:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._quit)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit)
        except AttributeError:
            pass

        Gtk.main()
        _clear_indicator_pid()


def run_indicator():
    """外部调用入口"""
    indicator = UbuntuSpeakIndicator()
    indicator.run()


if __name__ == "__main__":
    run_indicator()
