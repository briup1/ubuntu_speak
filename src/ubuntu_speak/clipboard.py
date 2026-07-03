"""剪贴板工具"""
import os
import shutil
import subprocess


def copy_text(text: str) -> bool:
    """将文本复制到系统剪贴板"""
    if not text:
        return False

    # Wayland
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        try:
            proc = subprocess.Popen(
                ["wl-copy"],
                stdin=subprocess.PIPE,
                text=True,
            )
            proc.communicate(input=text, timeout=5)
            return proc.returncode == 0
        except Exception as e:
            print(f"[wl-copy 失败] {e}")

    # X11
    if shutil.which("xclip"):
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                text=True,
            )
            proc.communicate(input=text, timeout=5)
            return proc.returncode == 0
        except Exception as e:
            print(f"[xclip 失败] {e}")

    if shutil.which("xsel"):
        try:
            proc = subprocess.Popen(
                ["xsel", "-b", "-i"],
                stdin=subprocess.PIPE,
                text=True,
            )
            proc.communicate(input=text, timeout=5)
            return proc.returncode == 0
        except Exception as e:
            print(f"[xsel 失败] {e}")

    return False
