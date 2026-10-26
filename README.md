# 职规 Agent（AI 赋能职业成长）

> 从真实招聘数据出发，为计算机专业大学生生成"看得见"的四年成长路径。
> 课程项目 · 职业规划课 · 方向 A：岗位需求反推大学四年成长规划 Agent

输入你的画像（年级 / 技能 / 每周可投入时间 / 目标岗位），系统会：

1. **分析**：检索内置的真实 JD 语料，用 LLM 抽取技能要求并按频次统计；
2. **映射**：把高频技能对齐到培养方案课程、竞赛、项目、实习机会；
3. **规划**：生成从当前学期到毕业的八学期成长路线（每周时长会按你的空闲钳制）；
4. **对话**：右侧规划顾问随时提问——说一句"我想转考研"，路线按新目标重排；
5. **缓存回放**：所有 LLM 结果落 SQLite，演示断网也能秒级回放。

## 两种使用模式（无需 key 也能看效果）

| 模式 | 条件 | 效果 |
|---|---|---|
| **离线演示**（默认可玩） | 不填 key 直接启动 | 页面完整可操作：所有演示用的分析/规划/对话请求都已随仓库附带（`db/career.db` 缓存库），按剧本输入即秒回；超出的输入会提示先去配 key |
| **真实运行** | `.env` 填入自己的 key | 全流程真实 LLM 调用，任意画像/岗位/提问都可用（首次 10~30 秒，之后自动进缓存） |

> 判断当前模式：看控制台 `GET /health` 返回的 `llm_configured` 字段，或直接在页面发起请求看提示。
> 演示输入范围见 `scripts/demo_checklist.md` 第 3、5 步（冻结画像与两条对话消息）。

## 快速开始（Windows）

**双击 `启动.bat` 即可**：自动建虚拟环境 → 装依赖 → 首次运行会打开 `.env` 让你填 API key（**可以先跳过**，离线演示模式直接可用）→ 浏览器自动打开页面。

想真实运行时再去申请 API key（二选一，都行，几块钱免费额度就够跑）：

- [DeepSeek 开放平台](https://platform.deepseek.com/) → 充值 → 创建 `sk-` 开头的 key
- [智谱开放平台](https://open.bigmodel.cn/) → 实名后有免费额度 → 创建 key

## 快速开始（macOS / Linux / 手动）

```bash
git clone https://github.com/YIruiChen65536/Career-Planning-Agent.git
cd Career-Planning-Agent
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.lock.txt
cp .env.example .env    # 填入 API key（见上）
uvicorn server:app      # 打开 http://127.0.0.1:8000/
```

> 部署不求人：把本仓库地址直接丢给任意 AI 编程助手（ZCode / Codex / Claude Code…），它读根目录的 `AGENTS.md` 就知道怎么装、怎么跑、怎么修。

## 演示流程（约 5 分钟）

看 `scripts/demo_checklist.md`——含预热命令与逐页话术。核心提示：首次真调用需 10~30 秒，跑过一次 `scripts/warm_cache.py` 后全部秒回，断网可演示。

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows / macOS / Linux 均可 |
| Python | 3.11+（Windows 启动器会自动找 `py` 或 `python`） |
| 网络 | 仅安装依赖与首次 LLM 调用时需要；预热后断网可演示 |
| API key | DeepSeek 或智谱任一；也支持任意 OpenAI 兼容网关（`OPENAI_BASE_URL`） |

## 目录导览

```
career_agent/     核心包：schemas(契约) pipeline(四步流水线) agent(对话+多Agent评审)
                  llm(模型工厂+缓存入口) store(SQLite) datasource(数据源接口) config
server.py         FastAPI 入口：/api/analyze /api/plan /api/chat(SSE) + 静态挂载前端
frontend/         原生 HTML/CSS/JS 单页（无构建、无 CDN，断网自动降级演示模式）
data/             postings/(54条真实JD) curriculum.json(培养方案) opportunities.json(竞赛/项目/实习)
scripts/          warm_cache.py(演示预热) demo_checklist.md(演示剧本)
tests/            38 项离线测试 + CAREER_LIVE=1 门控的真实旅程测试
docs/             项目全部文档（见下）
```

## 文档索引（组员必读前 3 篇加粗）

| 文档 | 内容 | 何时看 |
|---|---|---|
| **[docs/01-项目定位.md](docs/01-项目定位.md)** | 解决什么问题、核心功能、成功标准 | **新组员入门 / 汇报前** |
| **[docs/02-架构设计.md](docs/02-架构设计.md)** | 技术栈、分层架构、模块职责、数据契约 | **写任何代码之前** |
| **[docs/06-开发规则手册.md](docs/06-开发规则手册.md)** | Git 工作流、LLM 纪律、测试、临时文件清理 | **每次提交前** |
| [docs/03-开发路线图.md](docs/03-开发路线图.md) | 里程碑 M0~M5、任务分解、验收标准 | 每次开工 / 组会 |
| [docs/04-进度状态.md](docs/04-进度状态.md) | 当前进度看板（持续更新） | 每天 |
| [docs/05-环境与依赖.md](docs/05-环境与依赖.md) | 环境搭建细节、常见坑 | 配环境时 |
| [docs/07-文档维护规则.md](docs/07-文档维护规则.md) | 每篇文档的负责人与更新时机 | 改文档时 |
| [AGENTS.md](AGENTS.md) | AI 编程助手专用约定（部署/开发给 agent 看） | 丢给 agent 时（会自动读） |
| [docs/decisions/](docs/decisions/) | 架构决策记录 ADR-0001~0003 | 想推翻某个决定时先读 |
| [docs/logs/](docs/logs/) | 每轮开发/测试/review 的过程记录（只增不改） | 出事回溯时查 |
| [docs/research/](docs/research/) | 选型调研过程存档（只读） | 想知道"为什么这么选" |

## 技术栈

Python 3.11+ · FastAPI + PydanticAI · DeepSeek/GLM 或任意 OpenAI 兼容网关（`.env` 一行切换）· SQLite（LLM 缓存/档案）· 原生手写前端单页

## 测试

```bash
.venv/Scripts/python.exe -m pytest -q     # 38 项，全离线，秒级
CAREER_LIVE=1 .venv/Scripts/python.exe -m pytest tests/test_journey.py -q   # 真实旅程（需服务运行中）
```

## License

[MIT](LICENSE)
