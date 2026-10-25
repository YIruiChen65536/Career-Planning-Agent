# ADR-0001 · 技术栈选定 FastAPI + PydanticAI

状态：生效（2026-10-26）

## 背景

课程项目需要 Web 化的对话式 Agent（结构化流水线 + SSE 流式 + 国产大模型 + SQLite + 可能的多 Agent 与 MCP 扩展），两周内由 5 人学生团队完成并现场演示。

## 备选

OpenAI Agents SDK、LangChain/LangGraph、PydanticAI、Claude Agent SDK、Dify（零代码）。完整加权评分见 `docs/research/对比-框架选型评分与详细对比.md`（9 维度加权：PydanticAI 82.4 / OAI SDK 80.2 / LangChain 70.6 / Claude SDK 64.6）。

## 决定

FastAPI（服务层）+ PydanticAI v2（Agent 运行时）+ DeepSeek/GLM（模型）+ SQLite + pandas。前端待 M5 决策（ADR-0003 届时补）。

## 理由

1. PydanticAI 与 OAI SDK 总分打平，但本项目的命脉是四步全结构化输出，PydanticAI 的"typed 输出 + 校验失败自动重试"是最强路径；
2. DeepSeek/智谱/Kimi 三家均为 PydanticAI 原生 provider，国产模型接入四家最顺；
3. 组里确认可接受英文官方文档 + 人工复核 AI 生成代码（这是此前 OAI 领先的主要项）；
4. 公共底座（数据源/契约/存储/统计）与框架解耦，保留约 1 天成本换框架的退路。

## 后果

- 只认 pydantic.dev 官方 v2 文档（v1 教程断层是已知坑，记入 05 文档）；
- 版本锁定 requirements.lock.txt，演示前冻结；
- 会话历史手动管理（message_history + store.py，约 20 行，自担）。
