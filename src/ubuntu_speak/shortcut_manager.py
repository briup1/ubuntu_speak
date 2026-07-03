"""桌面全局快捷键管理

Debian 包安装后无法以 root 身份修改当前登录用户的桌面快捷键设置，
因此快捷键注册逻辑作为普通用户运行时调用。配置界面会引导用户一键设置。

当前支持：
- GNOME / GNOME Flashback (gsettings)
- KDE Plasma (kwriteconfig5 / kconfig)
- 其他桌面环境返回手动设置说明
"""
import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path


class DesktopEnvironment(Enum):
    """检测到的桌面环境"""

    GNOME = "gnome"
    KDE = "kde"
    XFCE = "xfce"
    MATE = "mate"
    CINNAMON = "cinnamon"
    UNKNOWN = "unknown"


# 默认快捷键：右 Alt + 右 Ctrl + Space
DEFAULT_BINDING = "<Alt_R><Control_R>space"
DEFAULT_BINDING_HUMAN = "右 Alt + 右 Ctrl + Space"


def detect_desktop_environment() -> DesktopEnvironment:
    """检测当前桌面环境"""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()

    if "gnome" in desktop or "gnome" in session:
        return DesktopEnvironment.GNOME
    if "kde" in desktop or "plasma" in desktop or "kde" in session:
        return DesktopEnvironment.KDE
    if "xfce" in desktop or "xfce" in session:
        return DesktopEnvironment.XFCE
    if "mate" in desktop or "mate" in session:
        return DesktopEnvironment.MATE
    if "cinnamon" in desktop or "cinnamon" in session:
        return DesktopEnvironment.CINNAMON
    return DesktopEnvironment.UNKNOWN


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """便捷封装：运行外部命令"""
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        result = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(e))
        return result


def install_gnome_shortcut(
    binding: str = DEFAULT_BINDING,
    name: str = "Ubuntu Speak",
    command: str = "ubuntu-speak",
) -> tuple[bool, str]:
    """在 GNOME 中注册自定义媒体快捷键。

    返回 (是否成功, 提示信息)
    """
    if not shutil.which("gsettings"):
        return False, "未找到 gsettings，请安装 libglib2.0-bin"

    base_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    base_key = "org.gnome.settings-daemon.plugins.media-keys"
    custom_key = f"{base_key}.custom-keybinding"

    # 读取已有的自定义快捷键列表
    result = _run(["gsettings", "get", base_key, "custom-keybindings"])
    if result.returncode != 0:
        return False, f"读取现有快捷键失败: {result.stderr}"

    raw = result.stdout.strip()
    existing: list[str] = []
    if raw.startswith("[") and raw.endswith("]"):
        # 解析形如 ['...', '...'] 的字符串
        inner = raw[1:-1].strip()
        if inner:
            existing = [x.strip().strip("'") for x in inner.split(",")]

    # 查找是否已存在 ubuntu-speak 的快捷键
    our_index = None
    for i, path in enumerate(existing):
        cmd_result = _run(
            [
                "gsettings",
                "get",
                f"{custom_key}:{path}",
                "command",
            ]
        )
        if cmd_result.returncode == 0 and command in cmd_result.stdout:
            our_index = i
            break

    if our_index is None:
        # 分配一个新的索引，避免覆盖已有
        used_indices = set()
        for path in existing:
            parts = path.rstrip("/").split("/")
            if parts and parts[-1].startswith("custom"):
                try:
                    used_indices.add(int(parts[-1][6:]))
                except ValueError:
                    pass
        new_index = 0
        while new_index in used_indices:
            new_index += 1
        our_path = f"{base_path}/custom{new_index}/"
        existing.append(our_path)
    else:
        our_path = existing[our_index]

    # 设置列表
    list_value = "[" + ", ".join(f"'{p}'" for p in existing) + "]"
    r1 = _run(["gsettings", "set", base_key, "custom-keybindings", list_value], check=True)
    if r1.returncode != 0:
        return False, f"更新快捷键列表失败: {r1.stderr}"

    # 设置具体属性
    def set_prop(prop: str, value: str):
        return _run(
            [
                "gsettings",
                "set",
                f"{custom_key}:{our_path}",
                prop,
                value,
            ],
            check=True,
        )

    r2 = set_prop("name", f"'{name}'")
    r3 = set_prop("command", f"'{command}'")
    r4 = set_prop("binding", f"'{binding}'")

    errors = [r.stderr for r in (r2, r3, r4) if r.returncode != 0]
    if errors:
        return False, f"设置快捷键属性失败: {'; '.join(errors)}"

    return True, f"已设置 {name} 快捷键为 {binding}（GNOME 可能需要重新登录生效）"


def uninstall_gnome_shortcut(command: str = "ubuntu-speak") -> tuple[bool, str]:
    """从 GNOME 中移除 ubuntu-speak 快捷键"""
    if not shutil.which("gsettings"):
        return False, "未找到 gsettings"

    base_key = "org.gnome.settings-daemon.plugins.media-keys"
    custom_key = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"

    result = _run(["gsettings", "get", base_key, "custom-keybindings"])
    if result.returncode != 0:
        return False, f"读取快捷键失败: {result.stderr}"

    raw = result.stdout.strip()
    existing: list[str] = []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if inner:
            existing = [x.strip().strip("'") for x in inner.split(",")]

    to_remove = []
    for path in existing:
        cmd_result = _run(["gsettings", "get", f"{custom_key}:{path}", "command"])
        if cmd_result.returncode == 0 and command in cmd_result.stdout:
            to_remove.append(path)

    if not to_remove:
        return True, "未找到已设置的 Ubuntu Speak 快捷键"

    new_list = [p for p in existing if p not in to_remove]
    list_value = "[" + ", ".join(f"'{p}'" for p in new_list) + "]"
    r1 = _run(["gsettings", "set", base_key, "custom-keybindings", list_value], check=True)
    if r1.returncode != 0:
        return False, f"移除快捷键失败: {r1.stderr}"

    return True, "已移除 Ubuntu Speak 全局快捷键"


def install_kde_shortcut(
    binding: str = DEFAULT_BINDING,
    name: str = "Ubuntu Speak",
    command: str = "ubuntu-speak",
) -> tuple[bool, str]:
    """在 KDE Plasma 中注册自定义快捷键。

    当前通过写入 kglobalshortcutsrc 实现。KDE 快捷键格式与 GTK 不同，
    这里先做基础支持，将 Ctrl+Super+Space 尽量转换。
    """
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    shortcut_file = config_home / "kglobalshortcutsrc"

    # KDE 中 Super 是 Meta；保留左右修饰键后缀（如 Alt_R、Control_R）
    kde_binding = binding.replace("<Super>", "Meta+").replace("<Control_R>", "Ctrl_R+").replace("<Control_L>", "Ctrl_L+").replace("<Control>", "Ctrl+").replace("<Alt_R>", "Alt_R+").replace("<Alt_L>", "Alt_L+").replace("<Alt>", "Alt+").replace("<Shift_R>", "Shift_R+").replace("<Shift_L>", "Shift_L+").replace("<Shift>", "Shift+")
    kde_binding = kde_binding.replace("space", "Space")

    entry = f"{command},{kde_binding},{name},Services"

    lines: list[str] = []
    if shortcut_file.exists():
        lines = shortcut_file.read_text(encoding="utf-8").splitlines()

    section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "[kwin]":
            section_idx = i
            break

    if section_idx is None:
        lines.append("[kwin]")
        section_idx = len(lines) - 1

    # 查找或插入
    key = f"_k_friendly_name={name}"
    inserted = False
    for i in range(section_idx + 1, len(lines)):
        if lines[i].startswith("["):
            break
        if lines[i].startswith(f"{name}=") or lines[i].startswith(f"{command}="):
            lines[i] = f"{name}={entry}"
            inserted = True
            break

    if not inserted:
        lines.insert(section_idx + 1, f"{name}={entry}")

    shortcut_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, f"已写入 KDE 快捷键配置，请注销后重新登录生效（绑定: {kde_binding}）"


def install_shortcut(
    binding: str = DEFAULT_BINDING,
    name: str = "Ubuntu Speak",
    command: str = "ubuntu-speak",
) -> tuple[bool, str]:
    """根据检测到的桌面环境安装全局快捷键"""
    de = detect_desktop_environment()
    if de == DesktopEnvironment.GNOME:
        return install_gnome_shortcut(binding, name, command)
    if de == DesktopEnvironment.KDE:
        return install_kde_shortcut(binding, name, command)
    if de in (DesktopEnvironment.XFCE, DesktopEnvironment.MATE, DesktopEnvironment.CINNAMON):
        return False, f"{de.value} 桌面环境暂不支持自动设置，请手动在键盘快捷键中绑定命令：{command}"
    return False, "未能识别桌面环境，请手动设置快捷键"


def uninstall_shortcut(command: str = "ubuntu-speak") -> tuple[bool, str]:
    """根据检测到的桌面环境卸载全局快捷键"""
    de = detect_desktop_environment()
    if de == DesktopEnvironment.GNOME:
        return uninstall_gnome_shortcut(command)
    return False, "当前桌面环境暂不支持自动移除快捷键，请在系统设置中手动删除"


def manual_shortcut_help() -> str:
    """返回手动设置快捷键的说明"""
    return (
        "请打开“系统设置 → 键盘 → 自定义快捷键”，\n"
        f"添加命令：ubuntu-speak\n"
        f"绑定快捷键：{DEFAULT_BINDING_HUMAN}"
    )
