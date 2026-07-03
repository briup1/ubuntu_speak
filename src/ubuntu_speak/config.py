"""配置管理"""
import json
import os
from pathlib import Path


class Config:
    """应用配置"""

    DEFAULT_CONFIG = {
        "api_key": "",
        "model": "qwen3-asr-flash",
        "sample_rate": 16000,
        "channels": 1,
        "audio_format": "wav",
        "max_record_seconds": 300,
        "language_hints": "zh",
        "evdev_key": "KEY_RIGHTALT",
        "evdev_grab": False,
    }

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "ubuntu-speak"
        self.config_file = self.config_dir / "config.json"
        self.cache_dir = Path.home() / ".cache" / "ubuntu-speak"
        self._data = dict(self.DEFAULT_CONFIG)
        self.load()

    def load(self):
        """从文件加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data.update(loaded)
            except Exception as e:
                print(f"[警告] 读取配置文件失败: {e}")
        # 环境变量优先级最高
        env_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if env_key:
            self._data["api_key"] = env_key
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save(self):
        """保存配置到文件"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @property
    def api_key(self) -> str:
        return self._data.get("api_key", "")

    @api_key.setter
    def api_key(self, value: str):
        self._data["api_key"] = value

    @property
    def model(self) -> str:
        return self._data.get("model", "qwen3-asr-flash")

    @property
    def sample_rate(self) -> int:
        return int(self._data.get("sample_rate", 16000))

    @property
    def channels(self) -> int:
        return int(self._data.get("channels", 1))

    @property
    def audio_format(self) -> str:
        return self._data.get("audio_format", "wav")

    @property
    def max_record_seconds(self) -> int:
        return int(self._data.get("max_record_seconds", 60))

    @property
    def language_hints(self) -> str:
        return self._data.get("language_hints", "zh")

    @property
    def evdev_key(self) -> str:
        return self._data.get("evdev_key", "KEY_F12")

    @property
    def evdev_grab(self) -> bool:
        return bool(self._data.get("evdev_grab", False))

    def ensure_api_key(self) -> bool:
        """检查 API key 是否已设置"""
        return bool(self.api_key and self.api_key.strip())


# 全局配置实例
config = Config()
