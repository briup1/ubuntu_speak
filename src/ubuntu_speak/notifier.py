"""桌面通知工具"""
import shutil
import subprocess


def notify(title: str, message: str, urgency: str = "normal"):
    """发送桌面通知"""
    if not shutil.which("notify-send"):
        print(f"[{title}] {message}")
        return

    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-a", "Ubuntu Speak", title, message],
            check=False,
            timeout=5,
        )
    except Exception as e:
        print(f"[通知失败] {e}")
        print(f"[{title}] {message}")
