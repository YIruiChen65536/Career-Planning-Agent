"""流水线①~④：每函数一个 PAI Agent，输出即 schemas 契约（02-架构设计）。

纪律（06 手册§3）：temperature=0；调用必须过 store.py 缓存；
频次统计等确定性计算用 pandas，绝不交给 LLM。
"""

import asyncio

import pandas as pd

from . import llm
from .datasource import get_source
from .schemas import (
    CourseMapping,
    ExtractedRequirements,
    JobPosting,
    Roadmap,
    SkillStat,
    StudentProfile,
)

CORE_FREQUENCY_RATIO = 0.3  # 出现率 ≥30% 判为核心要求（可调，改这里并通知全组）


EXTRACT_AGENT_NAME = "extract_requirements"  # 缓存键里的调用名；改提示词无需改它（键已含提示词全文）

EXTRACT_SYSTEM_PROMPT = """你是岗位 JD 解析专家：把一条招聘 JD 解析成结构化任职要求，只输出 JSON。

输出字段（键名必须完全一致）：
- posting_id: 原样返回输入给出的岗位ID
- hard_skills: 专业硬技能列表，如 ["Java", "数据结构", "机器学习"]（语言、算法、领域知识归这里）
- tools: 框架/工具链/平台列表，如 ["Spring", "Git", "Docker", "MySQL"]
- soft_skills: 软技能列表，如 ["沟通能力", "团队协作"]
- education: 学历要求，如 "本科及以上"；未提及给 ""
- experience_years: 经验年限数字，"3年以上"→3；"应届/经验不限"或未提及给 null
- project_requirements: 项目/经历要求列表，如 ["有高并发系统开发经验"]
- extras: 加分项原文摘要列表

技能名归一化：同一技能只保留最常用规范名，如 "Python开发/Python编程"→"Python"、"Java开发"→"Java"、"Vue.js"→"Vue"；别名与规范名不得同时输出。

铁律：只抽取 JD 中明确出现的要求；未提及的字段一律留空（空列表/空字符串/null），严禁按常识补齐。"""


def _extract_user_prompt(posting: JobPosting) -> str:
    """把一条 JobPosting 拼成抽取 Agent 的用户输入（进缓存键，格式改动=缓存全失效，慎改）。"""
    return (
        f"岗位ID：{posting.id}\n"
        f"职位：{posting.title}\n"
        f"公司：{posting.company}\n"
        f"来源：{posting.source}\n\n"
        f"JD原文：\n{posting.description}"
    )


async def extract_requirements(posting: JobPosting) -> ExtractedRequirements:
    """① 抽取：一条 JD -> 结构化要求（ask_json 结构化输出 + SQLite 缓存回放）。"""
    req = await llm.ask_json(
        agent_name=EXTRACT_AGENT_NAME,
        system_prompt=EXTRACT_SYSTEM_PROMPT,
        user_prompt=_extract_user_prompt(posting),
        output_type=ExtractedRequirements,
    )
    req.posting_id = posting.id  # ID 是确定性字段，不信任模型抄写，直接覆盖
    return req


async def extract_all(
    postings: list[JobPosting], concurrency: int = 4
) -> tuple[list[ExtractedRequirements | None], list[str]]:
    """① 并行批量抽取：信号量限并发，结果与输入同序；单条失败对应位置置 None 并收集错误，不炸整体。"""
    sem = asyncio.Semaphore(concurrency)

    async def _one(p: JobPosting) -> ExtractedRequirements:
        async with sem:
            return await extract_requirements(p)

    done = await asyncio.gather(*(_one(p) for p in postings), return_exceptions=True)
    reqs: list[ExtractedRequirements | None] = []
    errors: list[str] = []
    for posting, result in zip(postings, done):
        if isinstance(result, BaseException):
            reqs.append(None)
            errors.append(f"{posting.id}: {type(result).__name__}: {result}")
        else:
            reqs.append(result)
    return reqs, errors


def aggregate_skills(reqs: list[ExtractedRequirements]) -> list[SkillStat]:
    """② 归并：语义合并交给 LLM（TODO(M1)，含别名表），频次与核心判定在本函数用 pandas 完成。"""
    df = pd.DataFrame(
        [(r.posting_id, s, "hard") for r in reqs for s in r.hard_skills]
        + [(r.posting_id, s, "tool") for r in reqs for s in r.tools]
        + [(r.posting_id, s, "soft") for r in reqs for s in r.soft_skills],
        columns=["posting_id", "skill", "category"],
    )
    if df.empty:
        return []
    total = df["posting_id"].nunique()
    stats = (
        df.groupby(["skill", "category"])["posting_id"].nunique().reset_index(name="n")
    )
    return [
        SkillStat(
            skill=row.skill,
            category=row.category,
            frequency=int(row.n),
            is_core=bool(row.n / total >= CORE_FREQUENCY_RATIO),
            aliases=[],
        )
        for row in stats.itertuples(index=False)
    ]


async def map_courses(skills: list[SkillStat], profile: StudentProfile) -> list[CourseMapping]:
    """③ 映射：能力 -> 课程/竞赛/项目/实习（依据 data/curriculum.json + opportunities.json）。TODO(M3)。"""
    raise NotImplementedError("M3")


async def make_roadmap(profile: StudentProfile, skills: list[SkillStat], mappings: list[CourseMapping]) -> Roadmap:
    """④ 规划：画像 + 技能要求 + 映射 -> 分学期路线图。TODO(M3)。"""
    raise NotImplementedError("M3")
