"""百炼/灵积语音识别 API 客户端"""
import sys
from pathlib import Path

from .config import config


def _ensure_vendor_path():
    """将随包分发的 _vendor 目录加入 sys.path，确保系统级安装也能找到 dashscope。"""
    vendor_dir = Path(__file__).parent / "_vendor"
    if vendor_dir.is_dir() and str(vendor_dir) not in sys.path:
        # 插入到最前面，优先使用 vendor 版本；同时避免重复插入
        sys.path.insert(0, str(vendor_dir))


_ensure_vendor_path()


class ASRError(RuntimeError):
    """语音识别调用异常"""


def recognize(audio_path: Path) -> str:
    """识别本地音频文件，返回文本"""
    if not config.ensure_api_key():
        raise ASRError(
            "未配置 API Key。请在 ~/.config/ubuntu-speak/config.json 中设置 api_key，"
            "或设置环境变量 DASHSCOPE_API_KEY。"
        )

    audio_path = Path(audio_path).resolve()
    if not audio_path.exists():
        raise ASRError(f"音频文件不存在: {audio_path}")

    return _recognize_with_multimodal(audio_path)


def _recognize_with_multimodal(audio_path: Path) -> str:
    """使用 DashScope 多模态对话接口识别本地音频文件。

    当前默认模型 ``qwen3-asr-flash`` 支持直接传入本地文件绝对路径
    （``file://`` 格式），无需提前上传音频到公网可访问地址。
    """
    import dashscope
    from dashscope import MultiModalConversation

    dashscope.api_key = config.api_key

    # qwen3-asr-flash 要求使用 file:// 绝对路径
    file_url = f"file://{audio_path}"
    messages = [
        {"role": "user", "content": [{"audio": file_url}]}
    ]

    asr_options = {"enable_itn": False}
    if config.language_hints:
        # qwen3-asr-flash 使用 language 指定待识别语种
        asr_options["language"] = config.language_hints

    try:
        response = MultiModalConversation.call(
            model=config.model,
            messages=messages,
            result_format="message",
            asr_options=asr_options,
        )
    except Exception as e:
        raise ASRError(f"调用语音识别接口失败: {e}") from e

    if response.status_code != 200:
        raise ASRError(
            f"API 错误: {response.status_code} "
            f"{getattr(response, 'code', '')} {getattr(response, 'message', '')}".strip()
        )

    return _extract_text(response)


def _extract_text(response) -> str:
    """从多模态对话响应中提取识别文本"""
    try:
        choices = response.output.choices
        if choices and choices[0].message.content:
            parts = []
            for item in choices[0].message.content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(item["text"])
            text = "".join(parts).strip()
            if text:
                return text
    except AttributeError:
        pass

    # 兜底：尝试常见字段
    for attr in ("text", "content"):
        try:
            value = getattr(response.output, attr, None) or response.output.get(attr)
            if value:
                return str(value).strip()
        except Exception:
            pass

    return ""
