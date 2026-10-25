"""模型工厂：PydanticAI 的 provider/模型在此一处创建（02-架构设计§模块职责）。

M1 任务：按 pydantic.dev 官方 v2 文档接入 DeepSeekProvider / ZaiProvider，
返回可被 pipeline/agent 共用的模型实例。注意网上教程多为 v1 写法。
"""

from . import config


def get_model():  # pragma: no cover - M1 实现
    """按 config.MODEL 返回 PAI 模型实例。

    TODO(M1): 按 PydanticAI v2 文档实现：
      - "deepseek:*" -> DeepSeekProvider(api_key=config.DEEPSEEK_API_KEY)
      - "zai:*"      -> ZaiProvider(api_key=config.ZAI_API_KEY)
    """
    raise NotImplementedError("M1: 接入 PydanticAI v2 provider")
