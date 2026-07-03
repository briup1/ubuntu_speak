"""evdev 键盘事件监听，实现按住说话 / 松开识别。

本模块直接读取 /dev/input/event* 设备，因此运行该监听进程的用户需要
对输入设备有读权限（通常需要加入 input 用户组，或配合 udev 规则）。
"""
from __future__ import annotations

import os
import select
import signal
import sys
import time
from typing import Callable

from .notifier import notify

try:
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover
    evdev = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]


PressCallback = Callable[[], None]
ReleaseCallback = Callable[[], None]


def _normalize_key_name(key_name: str) -> str:
    """把类似 'f12' / 'KEY_F12' 统一成 'KEY_F12'。"""
    key_name = key_name.strip().upper()
    if not key_name.startswith("KEY_"):
        key_name = f"KEY_{key_name}"
    return key_name


def find_key_code(key_name: str) -> int | None:
    """把 KEY_XXX 字符串转成 evdev code。"""
    if ecodes is None:
        return None
    key_name = _normalize_key_name(key_name)
    return getattr(ecodes, key_name, None)


def list_keyboard_devices() -> list[evdev.InputDevice]:
    """列出当前可访问的键盘类输入设备。"""
    if evdev is None:
        return []
    devices: list[evdev.InputDevice] = []
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
            caps = device.capabilities(verbose=False)
            if ecodes.EV_KEY in caps:
                devices.append(device)
        except (OSError, PermissionError):
            # 没有权限访问该设备，通常是还没加入 input 组
            continue
    return devices


def run_listener(
    key_name: str,
    on_press: PressCallback,
    on_release: ReleaseCallback,
    grab: bool = False,
) -> int:
    """阻塞式监听指定按键，按下时调用 on_press，松开时调用 on_release。

    返回 0 表示正常结束，非 0 表示出错。
    """
    if evdev is None:
        notify(
            "Ubuntu Speak",
            "未安装 python3-evdev，无法监听硬件热键",
            urgency="critical",
        )
        return 1

    key_code = find_key_code(key_name)
    if key_code is None:
        notify("Ubuntu Speak", f"未知的按键名称：{key_name}", urgency="critical")
        return 1

    devices = list_keyboard_devices()
    if not devices:
        notify(
            "Ubuntu Speak",
            "未找到可访问的键盘设备。请确认当前用户已在 input 组，或已配置 udev 规则。",
            urgency="critical",
        )
        return 1

    # 尝试独占抓取设备。grab=True 会阻止该设备的按键继续传给其他应用，
    # 适合搭配不常用的独立按键/脚踏开关；grab=False 则保留系统原有按键行为。
    if grab:
        for device in devices:
            try:
                device.grab()
            except Exception:
                pass

    pressed = False
    shutdown = False

    def _on_signal(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    notify(
        "Ubuntu Speak",
        f"开始监听 {key_name}，按住说话，松开识别",
        urgency="low",
    )

    while not shutdown:
        try:
            readable, _, _ = select.select(devices, [], [], 0.5)
            for device in readable:
                try:
                    for event in device.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        if event.code != key_code:
                            continue
                        # value: 0=松开, 1=按下, 2=重复
                        if event.value == 1 and not pressed:
                            pressed = True
                            on_press()
                        elif event.value == 0 and pressed:
                            pressed = False
                            on_release()
                except (OSError, PermissionError):
                    # 设备被移除或权限变更，忽略该设备本次事件
                    continue
        except Exception as e:
            notify("Ubuntu Speak", f"热键监听出错：{e}", urgency="critical")
            return 1

    # 清理
    for device in devices:
        try:
            if grab:
                device.ungrab()
            device.close()
        except Exception:
            pass

    return 0


def test_find_keyboards() -> None:
    """调试用：列出检测到的键盘设备和指定按键信息。"""
    if evdev is None:
        print("python3-evdev 未安装")
        return
    print("检测到的键盘设备：")
    for device in list_keyboard_devices():
        print(f"  {device.path}: {device.name}")
