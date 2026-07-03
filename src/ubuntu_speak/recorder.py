"""音频录制模块"""
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import config


class AudioRecorder:
    """基于系统命令的音频录制器"""

    def __init__(self):
        self.process = None
        self.output_path = None
        self._stopped = False

    def _find_recorder(self) -> tuple[str, list[str]]:
        """查找可用的录音命令
        
        返回: (命令名, 基础参数列表)
        """
        sample_rate = config.sample_rate
        channels = config.channels

        # 优先使用 PipeWire 原生工具
        if shutil.which("pw-record"):
            cmd = [
                "pw-record",
                "--rate", str(sample_rate),
                "--channels", str(channels),
                "--format", "s16",
            ]
            return "pw-record", cmd

        # 退回到 PulseAudio 的 parec + sox/pacat
        if shutil.which("parec"):
            # parec 输出原始 PCM，需要 sox 转成 wav
            if shutil.which("sox"):
                return "parec+sox", ["parec", "-r", str(sample_rate), "--channels", str(channels), "--format", "s16le"]
            # 如果没有 sox，直接输出原始 PCM，后面转码
            return "parec", ["parec", "-r", str(sample_rate), "--channels", str(channels), "--format", "s16le"]

        raise RuntimeError("未找到可用的录音工具，请安装 pulseaudio-utils 或 pipewire")

    def start(self) -> Path:
        """开始录音，返回输出文件路径"""
        kind, base_cmd = self._find_recorder()
        suffix = ".wav" if kind != "parec" else ".raw"
        self.output_path = Path(tempfile.gettempdir()) / f"ubuntu-speak-{int(time.time())}{suffix}"

        if kind == "pw-record":
            cmd = base_cmd + [str(self.output_path)]
            self.process = subprocess.Popen(cmd)
        elif kind == "parec+sox":
            # parec | sox -t raw ... -t wav output.wav
            self._parec_proc = subprocess.Popen(
                base_cmd,
                stdout=subprocess.PIPE,
            )
            cmd = [
                "sox",
                "-t", "raw",
                "-r", str(config.sample_rate),
                "-e", "signed",
                "-b", "16",
                "-c", str(config.channels),
                "-",
                "-t", "wav",
                str(self.output_path),
            ]
            self.process = subprocess.Popen(
                cmd,
                stdin=self._parec_proc.stdout,
            )
            self._parec_proc.stdout.close()
        elif kind == "parec":
            cmd = base_cmd + [str(self.output_path)]
            self.process = subprocess.Popen(cmd)
        else:
            raise RuntimeError(f"不支持的录音方式: {kind}")

        return self.output_path

    def stop(self) -> Path | None:
        """停止录音并返回录制文件路径"""
        if self._stopped:
            return self.output_path
        self._stopped = True

        if self.process:
            try:
                self.process.send_signal(signal.SIGTERM)
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except ProcessLookupError:
                pass

        if hasattr(self, "_parec_proc") and self._parec_proc:
            try:
                self._parec_proc.send_signal(signal.SIGTERM)
                self._parec_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._parec_proc.kill()
                self._parec_proc.wait()
            except ProcessLookupError:
                pass

        return self.output_path

    def is_running(self) -> bool:
        """检查录音是否仍在进行"""
        if self.process is None:
            return False
        return self.process.poll() is None

    def terminate_after(self, seconds: float):
        """在指定秒数后自动停止"""
        def _timeout_handler(signum, frame):
            self.stop()
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(int(seconds))
