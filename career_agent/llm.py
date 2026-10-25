"""模型工厂 + LLM 调用统一入口（02-架构设计：全项目唯一创建模型对象的地方）。

- get_model()        按 config.MODEL（"provider:model" 串，.env 切换）创建 PAI 模型
- build_agent()      统一 temperature=0、retries=1（06 手册 §3 纪律）
- ask_json()         结构化输出 + SQLite 缓存（演示可离线回放）
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent

from . import config, store

T = TypeVar("T", bound=BaseModel)

_T0 = {"temperature": 0}  # 所有调用 0 温度，禁改（06 手册 §3）


def get_model():
    """按 config.MODEL（如 "zai:glm-4.6" / "deepseek:deepseek-chat"）返回模型实例。"""
    provider, _, model_name = config.MODEL.partition(":")
    if not model_name:
        raise ValueError(f"config.MODEL 需为 'provider:model' 格式，当前: {config.MODEL!r}")
    if provider == "deepseek":
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY：请在 .env 填写（参考 .env.example）")
        # 2.61 无 DeepSeekModel：DeepSeek 走 OpenAI 兼容协议
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.deepseek import DeepSeekProvider

        return OpenAIChatModel(model_name, provider=DeepSeekProvider(api_key=config.DEEPSEEK_API_KEY))
    if provider == "zai":
        if not config.ZAI_API_KEY:
            raise RuntimeError("缺少 ZAI_API_KEY：请在 .env 填写（参考 .env.example）")
        from pydantic_ai.models.zai import ZaiModel
        from pydantic_ai.providers.zai import ZaiProvider

        return ZaiModel(model_name, provider=ZaiProvider(api_key=config.ZAI_API_KEY))
    if provider == "openai":
        if not (config.OPENAI_BASE_URL and config.OPENAI_API_KEY):
            raise RuntimeError("缺少 OPENAI_BASE_URL / OPENAI_API_KEY：请在 .env 填写（参考 .env.example）")
        # 任意 OpenAI Chat Completions 兼容网关（本地测试网关/自建代理）
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=config.OPENAI_BASE_URL, api_key=config.OPENAI_API_KEY))
    raise ValueError(f"未知 provider: {provider!r}（支持 zai / deepseek / openai）")


def build_agent(system_prompt: str = "", output_type=None) -> Agent:
    """全项目统一的 Agent 构造入口：0 温度、结构化重试 1 次。禁止绕过此处直接 new Agent。"""
    return Agent(
        get_model(),
        output_type=output_type,
        system_prompt=system_prompt,
        retries=1,
        model_settings=_T0,
    )


def _cache_key(agent_name: str, system_prompt: str, user_prompt: str) -> str:
    payload = json.dumps(
        {"model": config.MODEL, "agent": agent_name, "system": system_prompt, "user": user_prompt},
        ensure_ascii=False,
        sort_keys=True,
    )
    return store.cache_key(call="llm", payload=payload)


async def ask_json(agent_name: str, system_prompt: str, user_prompt: str, output_type: type[T]) -> T:
    """结构化问答（带 SQLite 缓存）：命中缓存直接回放，未命中才真调用并落缓存。

    这是全项目唯一的 LLM 调用形态：纯文本流式入口（旧 ask_text_stream）已删除——
    它绕过缓存（06 手册 §3 禁令）且无任何调用方；对话流式观感由 server 分帧回放实现。"""
    key = _cache_key(agent_name, system_prompt, user_prompt)
    hit = store.cache_get(key)
    if hit is not None:
        return output_type.model_validate(hit)
    agent = build_agent(system_prompt=system_prompt, output_type=output_type)
    result = await agent.run(user_prompt)
    store.cache_put(key, result.output.model_dump(mode="json"))
    return result.output
