# AGENTS.md — AI 编程助手项目约定

> 本文件给 AI 编程助手（ZCode / Codex / Claude Code 等）看：工具会自动读取本文件作为项目上下文。
> 人类组员请看 README.md 和 docs/。

## 这个项目是什么

课程项目：岗位需求反推大学四年成长规划 Agent。FastAPI + PydanticAI 后端，原生 HTML/CSS/JS 前端，SQLite 存储。当前状态见 `docs/04-进度状态.md`（M0~M5 全部完成）。

## 部署（最常见的任务）

```bash
# 1. 虚拟环境（已存在 .venv 就跳过）
python -m venv .venv
# Windows Git Bash:
source .venv/Scripts/activate
# macOS/Linux:
source .venv/bin/activate

# 2. 依赖（以 requirements.lock.txt 为准，版本已锁定）
pip install -r requirements.lock.txt

# 3. 配置：复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY 或 ZAI_API_KEY
#    （模型串 CAREER_MODEL 默认 deepseek:deepseek-chat；也支持 zai:* 和 openai:* 兼容网关）
#    ⚠️ 部署完成后必须提醒用户：本仓库不附带任何 API key，也没有义务提供——
#    用户需自行前往 DeepSeek 开放平台（platform.deepseek.com，充值创建 sk- key）
#    或智谱开放平台（open.bigmodel.cn，有免费额度）创建 key 填入 .env。
#    但不填 key 也能玩：仓库附带演示缓存 db/career.db，无 key 时页面走内置演示数据
#    （后端 503 会返回引导文案，/health 的 llm_configured 字段可判断当前模式）。

# 4. 启动
python -m uvicorn server:app --port 8000    # 打开 http://127.0.0.1:8000/

# 5. 验证
python -m pytest -q                          # 应 38 passed, 8 skipped
curl http://127.0.0.1:8000/health            # 应 200
```

Windows 用户优先建议直接运行 `启动.bat`。

## 硬规则（违反 = 返工）

1. **LLM 纪律**：所有模型调用只准走 `career_agent/llm.py` 的 `ask_json`（temperature=0 在 `build_agent` 统一，禁止绕过）；所有结构化调用必须过 SQLite 缓存；辩论轮数上限写死在 `config.MAX_DEBATE_ROUNDS`，禁止靠提示词收敛。
2. **API key**：只放 `.env`（已被 .gitignore 排除，永不提交）；`store.py` 禁止存明文 key。
3. **测试**：单测必须离线绿（预填缓存回放：用 `llm._cache_key` 算键 + `store.cache_put` 写入期望结果，或 monkeypatch `llm.build_agent`）；涉及数据库的测试必须 monkeypatch `career_agent.config.DB_PATH` 到 tmp_path。
4. **数据纪律**：`data/postings/` 每条 JD 必带真实 url；入库前抹掉 HR 个人信息；禁止为演示观感编造/修改语料。
5. **临时文件**：每轮工作结束删掉自己产生的临时文件（脚本/截图/草稿/临时 db），不留到下轮。
6. **记录留档**：每轮开发/测试/review 当天在 `docs/logs/` 追加一条记录（模板见 `docs/logs/README.md`，≤20 行，只增不改）。没有记录 = 这轮工作没发生。
7. **文档同步**：改代码同一次提交里更新 `docs/04-进度状态.md`；改架构先读 `docs/decisions/`，推翻决策要写新 ADR 取代旧的。

## 架构速查（详情 docs/02-架构设计.md）

- 分层：`server.py`(端点) → `pipeline.py`(①抽取②归并③映射④规划纯函数) → `llm.py`(唯一模型入口) / `datasource.py`(数据源协议) → `store.py`(SQLite)
- 契约：`career_agent/schemas.py` 是唯一数据契约，server 返回与前端消费都以此为准
- 禁止：`server.py` 写业务逻辑；`llm.py` 之外创建模型对象；前端引入 npm/CDN

## 常见坑

- pydantic-ai 已锁 2.61：DeepSeek 无专属 Model 类，走 `OpenAIChatModel + DeepSeekProvider`；网上 v1 教程大多过时
- Windows 激活 venv 是 `.venv\Scripts\activate`（Git Bash 用 source）
- `store._conn()` 是 contextmanager（WAL 模式），用 `with store._conn() as c:`，不要按旧代码当连接对象用
- 全量 pytest 里 8 个 skip 是 `tests/test_journey.py`（`CAREER_LIVE=1` 才跑真实旅程），不是坏测试
- 写 .bat 时：if 块内 echo 文本不得含裸括号 `(...)`（cmd 会提前闭合块），换行必须 CRLF，中文先 `chcp 65001` 或干脆全 ASCII——本项目 `启动.bat` 是现成范例
