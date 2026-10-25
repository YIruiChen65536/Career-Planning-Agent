"""流水线①~④：每函数一个 PAI Agent，输出即 schemas 契约（02-架构设计）。

纪律（06 手册§3）：temperature=0；调用必须过 store.py 缓存；
频次统计等确定性计算用 pandas，绝不交给 LLM。
"""

import pandas as pd

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


async def extract_requirements(posting: JobPosting) -> ExtractedRequirements:
    """① 抽取：一条 JD -> 结构化要求。TODO(M1)：PAI Agent + output_type=ExtractedRequirements。"""
    raise NotImplementedError("M1")


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
