# 职规 Agent（AI 赋能职业成长）

> 从真实招聘数据出发，为计算机专业大学生生成"看得见"的四年成长路径。
> 课程项目 · 职业规划课 · 方向 A：岗位需求反推大学四年成长规划 Agent

## 快速开始

```bash
# Git Bash（推荐）
cd /d/Project/职规Agent
/d/Professional_soft/anaconda3/python.exe -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env        # 填入 API key
uvicorn server:app --reload # 启动后访问 http://127.0.0.1:8000/docs
```

## 文档索引

| 文档 | 内容 | 何时看 |
|---|---|---|
| [docs/01-项目定位.md](docs/01-项目定位.md) | 解决什么问题、核心功能、成功标准 | 新组员入门 / 汇报前 |
| [docs/02-架构设计.md](docs/02-架构设计.md) | 技术栈、分层架构、模块职责、数据契约 | 写任何代码之前 |
| [docs/03-开发路线图.md](docs/03-开发路线图.md) | 里程碑 M0~M5、任务分解、验收标准 | 每次开工 / 组会 |
| [docs/04-进度状态.md](docs/04-进度状态.md) | 当前进度看板（**持续更新**） | 每天 |
| [docs/05-环境与依赖.md](docs/05-环境与依赖.md) | 环境搭建、依赖、API key、启动命令、常见坑 | 配环境 / 装依赖时 |
| [docs/06-开发规则手册.md](docs/06-开发规则手册.md) | Git 工作流、提交规范、LLM 纪律、测试、临时文件清理 | **每次提交前** |
| [docs/07-文档维护规则.md](docs/07-文档维护规则.md) | 每篇文档的负责人与更新时机 | 改文档时 |
| [docs/decisions/](docs/decisions/) | 架构决策记录（ADR） | 想推翻某个决定时先读 |
| [docs/logs/](docs/logs/) | 每轮开发/测试/review 的过程记录（只增不改） | 每轮工作结束时写；出事回溯时查 |
| [docs/research/](docs/research/) | 选型调研过程存档（只读，不再维护） | 想知道"为什么这么选"时 |

## 当前状态（同步自 04-进度状态）

- M0 仓库与文档系统：✅ 已完成
- 下一步：M1 最小闭环（一条 JD → 结构化 JSON）

## 技术栈一句话

Python 3.11+ · FastAPI + PydanticAI · DeepSeek/GLM（OpenAI 兼容国产 API）· SQLite · 前端待定（简版网页）
