"""GTK4 图形化配置窗口"""
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from .asr import recognize
from .clipboard import copy_text
from .config import config
from .notifier import notify
from .recorder import AudioRecorder
from .shortcut_manager import (
    DEFAULT_BINDING_HUMAN,
    install_shortcut,
    uninstall_shortcut,
)


try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gio, GLib
except ImportError as e:
    raise ImportError(
        "运行图形配置界面需要安装 python3-gi 与 gir1.2-gtk-4.0"
    ) from e


class SettingsWindow(Gtk.ApplicationWindow):
    """Ubuntu Speak 设置窗口"""

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="Ubuntu Speak 设置")
        self.set_default_size(480, 520)
        self.set_resizable(False)

        # 主容器
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        self.set_child(box)

        # 标题
        title = Gtk.Label()
        title.set_markup('<span size="x-large" weight="bold">Ubuntu Speak 设置</span>')
        title.set_halign(Gtk.Align.START)
        box.append(title)

        subtitle = Gtk.Label(label="配置语音识别 API、全局快捷键与 evdev 按住说话热键")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        # 表单网格
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(12)
        grid.set_column_homogeneous(False)
        box.append(grid)

        row = 0

        # API Key
        api_label = Gtk.Label(label="百炼 API Key:")
        api_label.set_halign(Gtk.Align.END)
        grid.attach(api_label, 0, row, 1, 1)

        self.api_entry = Gtk.Entry()
        self.api_entry.set_hexpand(True)
        self.api_entry.set_visibility(False)  # 密码模式
        self.api_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.api_entry.set_placeholder_text("sk-...")
        grid.attach(self.api_entry, 1, row, 1, 1)
        row += 1

        # API Key 提示
        api_hint = Gtk.Label(
            label="可从阿里云百炼控制台获取，保存后写入 ~/.config/ubuntu-speak/config.json"
        )
        api_hint.add_css_class("dim-label")
        api_hint.set_halign(Gtk.Align.START)
        api_hint.set_wrap(True)
        api_hint.set_xalign(0)
        grid.attach(api_hint, 1, row, 1, 1)
        row += 1

        # 模型
        model_label = Gtk.Label(label="识别模型:")
        model_label.set_halign(Gtk.Align.END)
        grid.attach(model_label, 0, row, 1, 1)

        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_hexpand(True)
        models = [
            "qwen3-asr-flash",
            "qwen2-audio-instruct",
        ]
        for m in models:
            self.model_combo.append(m, m)
        self.model_combo.set_active(0)
        grid.attach(self.model_combo, 1, row, 1, 1)
        row += 1

        # 语言偏好
        lang_label = Gtk.Label(label="语言偏好:")
        lang_label.set_halign(Gtk.Align.END)
        grid.attach(lang_label, 0, row, 1, 1)

        self.lang_entry = Gtk.Entry()
        self.lang_entry.set_hexpand(True)
        self.lang_entry.set_placeholder_text("zh、en、auto 等")
        grid.attach(self.lang_entry, 1, row, 1, 1)
        row += 1

        # 最大录音时长
        max_label = Gtk.Label(label="最大录音秒数:")
        max_label.set_halign(Gtk.Align.END)
        grid.attach(max_label, 0, row, 1, 1)

        self.max_spin = Gtk.SpinButton()
        self.max_spin.set_hexpand(True)
        self.max_spin.set_range(5, 300)
        self.max_spin.set_increments(5, 15)
        grid.attach(self.max_spin, 1, row, 1, 1)
        row += 1

        # evdev 热键
        evdev_key_label = Gtk.Label(label="evdev 热键:")
        evdev_key_label.set_halign(Gtk.Align.END)
        grid.attach(evdev_key_label, 0, row, 1, 1)

        self.evdev_key_entry = Gtk.Entry()
        self.evdev_key_entry.set_hexpand(True)
        self.evdev_key_entry.set_placeholder_text("例如 KEY_F12、KEY_F13")
        grid.attach(self.evdev_key_entry, 1, row, 1, 1)
        row += 1

        evdev_key_hint = Gtk.Label(
            label="--listen-hotkey 模式监听的按键。建议选用不常用的 KEY_F13-F24，避免与系统快捷键冲突。"
        )
        evdev_key_hint.add_css_class("dim-label")
        evdev_key_hint.set_halign(Gtk.Align.START)
        evdev_key_hint.set_wrap(True)
        evdev_key_hint.set_xalign(0)
        grid.attach(evdev_key_hint, 1, row, 1, 1)
        row += 1

        # evdev 独占抓取
        evdev_grab_label = Gtk.Label(label="独占设备:")
        evdev_grab_label.set_halign(Gtk.Align.END)
        grid.attach(evdev_grab_label, 0, row, 1, 1)

        self.evdev_grab_switch = Gtk.Switch()
        self.evdev_grab_switch.set_halign(Gtk.Align.START)
        grid.attach(self.evdev_grab_switch, 1, row, 1, 1)
        row += 1

        evdev_grab_hint = Gtk.Label(
            label="开启后 evdev 会独占抓取键盘设备，阻止该设备的按键继续传给系统。仅建议为独立按键/脚踏开关开启。"
        )
        evdev_grab_hint.add_css_class("dim-label")
        evdev_grab_hint.set_halign(Gtk.Align.START)
        evdev_grab_hint.set_wrap(True)
        evdev_grab_hint.set_xalign(0)
        grid.attach(evdev_grab_hint, 1, row, 1, 1)
        row += 1

        # 快捷键区域
        shortcut_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        shortcut_box.set_margin_top(8)
        box.append(shortcut_box)

        shortcut_title = Gtk.Label()
        shortcut_title.set_markup('<span weight="bold">全局快捷键</span>')
        shortcut_title.set_halign(Gtk.Align.START)
        shortcut_box.append(shortcut_title)

        self.shortcut_label = Gtk.Label(label=f"默认快捷键: {DEFAULT_BINDING_HUMAN}")
        self.shortcut_label.set_halign(Gtk.Align.START)
        shortcut_box.append(self.shortcut_label)

        shortcut_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        shortcut_btn_box.set_margin_top(4)
        shortcut_box.append(shortcut_btn_box)

        self.install_shortcut_btn = Gtk.Button(label="设置快捷键")
        self.install_shortcut_btn.connect("clicked", self.on_install_shortcut)
        shortcut_btn_box.append(self.install_shortcut_btn)

        self.remove_shortcut_btn = Gtk.Button(label="移除快捷键")
        self.remove_shortcut_btn.connect("clicked", self.on_remove_shortcut)
        shortcut_btn_box.append(self.remove_shortcut_btn)

        self.shortcut_status = Gtk.Label(label="")
        self.shortcut_status.set_halign(Gtk.Align.START)
        self.shortcut_status.set_wrap(True)
        self.shortcut_status.set_xalign(0)
        shortcut_box.append(self.shortcut_status)

        # 操作按钮区
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_box.set_halign(Gtk.Align.END)
        action_box.set_margin_top(16)
        box.append(action_box)

        self.test_btn = Gtk.Button(label="测试识别")
        self.test_btn.connect("clicked", self.on_test)
        action_box.append(self.test_btn)

        self.save_btn = Gtk.Button(label="保存")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self.on_save)
        action_box.append(self.save_btn)

        # 状态栏
        self.status_label = Gtk.Label(label="")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_wrap(True)
        self.status_label.set_xalign(0)
        self.status_label.add_css_class("dim-label")
        box.append(self.status_label)

        # 加载当前配置
        self.load_config()

    def load_config(self):
        """把当前配置填充到控件"""
        self.api_entry.set_text(config.api_key)

        model = config.model
        found = False
        for i, m in enumerate(["qwen3-asr-flash", "qwen2-audio-instruct"]):
            if m == model:
                self.model_combo.set_active(i)
                found = True
                break
        if not found:
            self.model_combo.append(model, model)
            self.model_combo.set_active_id(model)

        self.lang_entry.set_text(config.language_hints)
        self.max_spin.set_value(config.max_record_seconds)
        self.evdev_key_entry.set_text(config.evdev_key)
        self.evdev_grab_switch.set_active(config.evdev_grab)

        self._update_status("配置已加载")

    def _update_status(self, message: str):
        """更新状态栏"""
        self.status_label.set_text(message)

    def _show_message(self, title: str, message: str):
        """弹出提示对话框（GTK4 兼容实现）"""
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.set_default_size(360, -1)

        content = dialog.get_content_area()
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_spacing(12)

        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{title}</b>")
        title_label.set_halign(Gtk.Align.START)
        content.append(title_label)

        msg_label = Gtk.Label(label=message)
        msg_label.set_wrap(True)
        msg_label.set_halign(Gtk.Align.START)
        msg_label.set_xalign(0)
        content.append(msg_label)

        dialog.add_button("确定", Gtk.ResponseType.OK)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def on_install_shortcut(self, button):
        """安装全局快捷键"""
        success, message = install_shortcut()
        self.shortcut_status.set_text(message)
        if success:
            self.shortcut_status.add_css_class("success")
            notify("Ubuntu Speak", "全局快捷键已设置，建议重新登录生效")
        else:
            self.shortcut_status.add_css_class("error")

    def on_remove_shortcut(self, button):
        """移除全局快捷键"""
        success, message = uninstall_shortcut()
        self.shortcut_status.set_text(message)
        if success:
            self.shortcut_status.add_css_class("success")
        else:
            self.shortcut_status.add_css_class("error")

    def on_save(self, button):
        """保存配置"""
        config.api_key = self.api_entry.get_text().strip()
        config._data["model"] = self.model_combo.get_active_text()
        config._data["language_hints"] = self.lang_entry.get_text().strip()
        config._data["max_record_seconds"] = int(self.max_spin.get_value())
        config._data["evdev_key"] = self.evdev_key_entry.get_text().strip() or "KEY_F12"
        config._data["evdev_grab"] = bool(self.evdev_grab_switch.get_active())
        config.save()
        self._update_status("配置已保存")
        notify("Ubuntu Speak", "配置已保存")

    def on_test(self, button):
        """启动一次 3 秒测试录音并识别"""
        if not config.ensure_api_key():
            self._show_message("未配置 API Key", "请先填写并保存 API Key 后再测试。")
            return

        self._update_status("测试识别中，请说话...")
        self.test_btn.set_sensitive(False)
        thread = threading.Thread(target=self._do_test, daemon=True)
        thread.start()

    def _do_test(self):
        """在后台线程执行测试录音识别"""
        recorder = AudioRecorder()
        audio_path = None
        try:
            audio_path = recorder.start()
            notify("Ubuntu Speak", "正在测试录音，3 秒后自动停止...")
            time.sleep(3)
            recorder.stop()

            if not audio_path or not audio_path.exists():
                GLib.idle_add(self._test_done, False, "录音失败，未生成音频文件")
                return

            text = recognize(audio_path)
            if text:
                copy_text(text)
                GLib.idle_add(self._test_done, True, f"识别结果：{text}")
                notify("Ubuntu Speak", f"测试成功：{text[:80]}")
            else:
                GLib.idle_add(self._test_done, False, "未识别到内容，请检查麦克风或 API 配置")
        except Exception as e:
            GLib.idle_add(self._test_done, False, f"测试失败：{e}")
        finally:
            recorder.stop()
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass

    def _test_done(self, success: bool, message: str):
        """测试完成后回到主线程更新 UI"""
        self.test_btn.set_sensitive(True)
        self._update_status(message)
        if success:
            self._show_message("测试成功", message)
        else:
            self._show_message("测试失败", message)
        return False


class SettingsApp(Gtk.Application):
    """GTK 配置应用"""

    def __init__(self):
        super().__init__(
            application_id="com.github.ubuntu-speak",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self):
        win = SettingsWindow(self)
        win.present()


def run_settings():
    """启动配置窗口"""
    app = SettingsApp()
    # 不将 ubuntu-speak 的 CLI 参数传给 Gtk.Application，避免
    # GTK 把 --settings 等标志当成未知选项而报错。
    return app.run(None)


if __name__ == "__main__":
    sys.exit(run_settings())
