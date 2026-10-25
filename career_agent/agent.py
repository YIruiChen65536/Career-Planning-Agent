"""⑤ 对话 Agent：工具调用驱动①~④，感知画像变化后重规划（M4）。

TODO(M4)：
- PAI Agent 注册①~④为工具；message_history 手动传入（store.py 取存）
- FastAPI /api/chat 消费本模块的流式输出
- 多 Agent 链：主 Agent + 2~3 专家并行 + 1 轮 review + 汇总，
  轮数上限读 config.MAX_DEBATE_ROUNDS
"""
