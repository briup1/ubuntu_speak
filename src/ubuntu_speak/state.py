"""应用状态管理

用于在主进程、录音 daemon 与系统托盘指示器之间共享当前状态。
状态写入 ~/.cache/ubuntu-speak/state.json，indicator 通过轮询或监听该文件更新图标。
"""
import json
import time
from enum import Enum
from pathlib import Path

from .config import config


class AppState(str, Enum):
    """应用状态枚举"""

    IDLE = "idle"
    RECORDING = "recording"
    RECOGNIZING = "recognizing"
    SUCCESS = "success"
    ERROR = "error"


class StateManager:
    """简单的文件-based 状态管理器"""

    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file or (config.cache_dir / "state.json")
        config.cache_dir.mkdir(parents=True, exist_ok=True)

    def set_state(self, state: AppState, message: str = ""):
        """设置当前状态"""
        data = {
            "state": state.value,
            "message": message,
            "updated_at": time.time(),
        }
        try:
            # 先写入临时文件再重命名，避免 indicator 读取到不完整内容
            tmp_file = self.state_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp_file.replace(self.state_file)
        except Exception as e:
            print(f"[状态写入失败] {e}")

    def get_state(self) -> dict:
        """读取当前状态"""
        if not self.state_file.exists():
            return {"state": AppState.IDLE.value, "message": "", "updated_at": 0}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"state": AppState.IDLE.value, "message": "", "updated_at": 0}


# 全局状态管理实例
state_manager = StateManager()
