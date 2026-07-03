"""命令行入口"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .asr import recognize
from .clipboard import copy_text
from .config import config
from .notifier import notify
from .recorder import AudioRecorder
from .state import AppState, state_manager


def _maybe_run_settings():
    """尝试启动 GTK 配置窗口。失败时打印提示。"""
    try:
        from .settings_window import run_settings
        return run_settings()
    except ImportError as e:
        notify("Ubuntu Speak", f"无法启动配置界面：{e}")
        print(f"无法启动配置界面：{e}")
        print("请使用命令行：ubuntu-speak --configure")
        return 1


PID_FILE = config.cache_dir / "recording.pid"
HOTKEY_PID_FILE = config.cache_dir / "hotkey.pid"


def _is_process_alive(pid: int) -> bool:
    """检查进程是否存活"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_pid() -> int | None:
    """读取正在录音的进程 PID"""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _clear_pid():
    """清除 PID 文件"""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _write_pid(pid: int):
    """写入 PID 文件"""
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _read_indicator_pid() -> int | None:
    """读取 indicator 进程 PID"""
    # 延迟导入 indicator 模块，避免在 --settings 等需要 GTK4 的场景下
    # 提前加载 GTK3 命名空间。
    from .indicator import INDICATOR_PID_FILE

    if not INDICATOR_PID_FILE.exists():
        return None
    try:
        return int(INDICATOR_PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_indicator_alive() -> bool:
    """检查 indicator 是否正在运行"""
    pid = _read_indicator_pid()
    if not pid:
        return False
    return _is_process_alive(pid)


def _read_hotkey_pid() -> int | None:
    """读取 listen-hotkey 进程 PID"""
    if not HOTKEY_PID_FILE.exists():
        return None
    try:
        return int(HOTKEY_PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_hotkey_alive() -> bool:
    """检查 listen-hotkey 是否正在运行"""
    pid = _read_hotkey_pid()
    if not pid:
        return False
    return _is_process_alive(pid)


def _ensure_indicator_running():
    """确保系统托盘指示器正在运行，没有则后台启动。

    注意：indicator 是 GUI 进程，需要保留在当前 X11/Wayland 用户会话内，
    因此不使用 start_new_session=True，也不关闭所有文件描述符，避免丢失
    D-Bus / X11 / AppIndicator 所需的 fd。
    """
    if _is_indicator_alive():
        return
    try:
        cmd = [sys.executable, "-m", "ubuntu_speak.cli", "--indicator"]
        log_file = config.cache_dir / "indicator.log"
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "a")
        subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
            close_fds=False,
        )
        # 给 indicator 一点时间启动并写入 PID
        time.sleep(0.5)
    except Exception as e:
        print(f"启动托盘指示器失败: {e}")


def _notify_recording_started():
    notify("开始录音", "请说话，松开快捷键结束录音", urgency="low")


def _run_recorder_daemon():
    """后台录音进程：收到停止信号后识别并复制到剪贴板"""
    recorder = AudioRecorder()
    stop_requested = False
    audio_path = None

    def _on_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        recorder.stop()

    signal.signal(signal.SIGUSR1, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    try:
        print(f"[daemon] HOME={os.environ.get('HOME', 'N/A')}", flush=True)
        print(f"[daemon] config_file={config.config_file}", flush=True)
        print(f"[daemon] api_key_exists={config.config_file.exists()}", flush=True)
        print(f"[daemon] api_key_configured={config.ensure_api_key()}", flush=True)
        print(f"[daemon] 启动录音", flush=True)
        audio_path = recorder.start()
        print(f"[daemon] 音频路径: {audio_path}", flush=True)
        _write_pid(os.getpid())
        state_manager.set_state(AppState.RECORDING, "请说话，松开快捷键后识别")
        _notify_recording_started()

        # 最长录音时间保护
        recorder.terminate_after(config.max_record_seconds)

        # 等待停止信号
        print(f"[daemon] 等待停止信号", flush=True)
        while not stop_requested and recorder.is_running():
            time.sleep(0.1)

        # 确保已停止
        print(f"[daemon] 停止录音", flush=True)
        recorder.stop()
        _clear_pid()
        state_manager.set_state(AppState.RECOGNIZING, "正在调用百炼语音识别 API...")

        print(f"[daemon] 检查音频文件: {audio_path} exists={audio_path.exists() if audio_path else 'N/A'}", flush=True)
        if not audio_path or not audio_path.exists():
            state_manager.set_state(AppState.ERROR, "未能生成音频文件")
            notify("录音失败", "未能生成音频文件", urgency="critical")
            return

        # 识别
        notify("识别中", "正在调用百炼语音识别 API...", urgency="low")
        text = recognize(audio_path)
        print(f"[daemon] 识别结果: {text}", flush=True)

        if text:
            if copy_text(text):
                state_manager.set_state(AppState.SUCCESS, f"已复制：{text[:40]}")
            else:
                state_manager.set_state(AppState.SUCCESS, f"结果：{text[:40]}（剪贴板失败）")
        else:
            state_manager.set_state(AppState.ERROR, "未能识别到语音内容")

    except Exception as e:
        _clear_pid()
        state_manager.set_state(AppState.ERROR, str(e))
        notify("出错了", str(e), urgency="critical")
        raise
    finally:
        # 调试模式：保留临时音频文件，方便检查录音质量
        # 如需恢复自动清理，取消下面注释并删除 pass
        # if audio_path and audio_path.exists():
        #     try:
        #         audio_path.unlink()
        #     except Exception:
        #         pass
        pass


def start_recording():
    """开始录音（若已在录音则忽略）"""
    _ensure_indicator_running()
    pid = _read_pid()
    if pid and _is_process_alive(pid):
        return

    state_manager.set_state(AppState.RECORDING, "请说话，松开快捷键后识别")
    _notify_recording_started()

    _clear_pid()
    cmd = [sys.executable, "-m", "ubuntu_speak.cli", "--daemon"]
    log_file = config.cache_dir / "daemon.log"
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    log_file_handle = open(log_file, "a")
    subprocess.Popen(
        cmd,
        stdout=log_file_handle,
        stderr=log_file_handle,
        start_new_session=True,
    )
    # 给 daemon 一点时间写入 PID 文件
    time.sleep(0.3)
    daemon_pid = _read_pid()
    if daemon_pid:
        print(f"已开始录音 (PID: {daemon_pid})")
    else:
        print("已开始录音")


def stop_recording():
    """停止当前录音（若未在录音则忽略）"""
    pid = _read_pid()
    if pid and _is_process_alive(pid):
        try:
            os.kill(pid, signal.SIGUSR1)
            state_manager.set_state(AppState.RECOGNIZING, "正在识别...")
            print(f"已发送停止信号到录音进程 {pid}")
        except Exception as e:
            print(f"停止录音失败: {e}")
            _clear_pid()


def toggle_recording():
    """切换录音状态（按下/松开共用同一快捷键时使用）"""
    pid = _read_pid()
    if pid and _is_process_alive(pid):
        stop_recording()
    else:
        start_recording()


def listen_hotkey():
    """通过 evdev 监听指定按键，按住开始录音、松开停止识别。

    该进程会常驻后台；再次启动时会检测是否已有实例在运行。
    """
    # 单实例保护
    existing_pid = _read_hotkey_pid()
    if existing_pid and _is_process_alive(existing_pid):
        notify(
            "Ubuntu Speak",
            "按住说话监听已在运行，请勿重复启动",
            urgency="low",
        )
        print(f"按住说话监听已在运行 (PID: {existing_pid})")
        return

    _ensure_indicator_running()
    from .evdev_listener import run_listener

    config.cache_dir.mkdir(parents=True, exist_ok=True)
    HOTKEY_PID_FILE.write_text(str(os.getpid()))

    key_name = config.evdev_key
    grab = config.evdev_grab
    try:
        sys.exit(run_listener(key_name, on_press=start_recording, on_release=stop_recording, grab=grab))
    finally:
        HOTKEY_PID_FILE.unlink(missing_ok=True)


def configure():
    """交互式配置 API Key"""
    print("配置 Ubuntu Speak")
    print(f"配置文件路径: {config.config_file}")
    current = config.api_key
    if current:
        masked = current[:4] + "*" * (len(current) - 8) + current[-4:] if len(current) > 8 else "***"
        print(f"当前 API Key: {masked}")
    else:
        print("当前未配置 API Key")

    new_key = input("请输入百炼/灵积 API Key (直接回车保持不变): ").strip()
    if new_key:
        config.api_key = new_key
        config.save()
        print("API Key 已保存")
    else:
        print("未更改")


def show_status():
    """显示当前状态"""
    pid = _read_pid()
    if pid and _is_process_alive(pid):
        print(f"正在录音中 (PID: {pid})")
    else:
        print("未在录音")
    print(f"配置文件: {config.config_file}")
    print(f"当前模型: {config.model}")
    print(f"API Key: {'已配置' if config.ensure_api_key() else '未配置'}")


def main():
    parser = argparse.ArgumentParser(description="Ubuntu 语音输入法")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="后台录音模式（内部使用）",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="命令行配置 API Key",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="打开图形化配置窗口",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看当前状态",
    )
    parser.add_argument(
        "--indicator",
        action="store_true",
        help="启动系统托盘指示器（后台常驻）",
    )
    parser.add_argument(
        "--listen-hotkey",
        action="store_true",
        help="通过 evdev 监听硬件热键，按住说话、松开识别",
    )
    args = parser.parse_args()

    if args.daemon:
        _run_recorder_daemon()
    elif args.configure:
        configure()
    elif args.settings:
        sys.exit(_maybe_run_settings())
    elif args.status:
        show_status()
    elif args.indicator:
        try:
            from .indicator import run_indicator
            run_indicator()
        except ImportError as e:
            notify("Ubuntu Speak", f"无法启动托盘指示器：{e}")
            print(f"无法启动托盘指示器：{e}")
            sys.exit(1)
    elif args.listen_hotkey:
        if not config.ensure_api_key():
            print("API Key 未配置，启动配置窗口...")
            sys.exit(_maybe_run_settings())
        listen_hotkey()
    else:
        # 没有显式参数时：如果没有 API Key，优先弹出配置窗口
        if not config.ensure_api_key():
            print("API Key 未配置，启动配置窗口...")
            sys.exit(_maybe_run_settings())
        toggle_recording()


if __name__ == "__main__":
    main()
