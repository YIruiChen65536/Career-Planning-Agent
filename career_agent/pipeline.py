"""流水线①~④：每函数一个 PAI Agent，输出即 schemas 契约（02-架构设计）。

纪律（06 手册§3）：temperature=0；调用必须过 store.py 缓存；
频次统计等确定性计算用 pandas，绝不交给 LLM。
"""

import asyncio
import functools
import json

import pandas as pd
from pydantic import BaseModel

from . import config, llm
from .datasource import get_source
from .schemas import (
    CourseMapping,
    ExtractedRequirements,
    JobPosting,
    Roadmap,
    SemesterPlan,
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


async def map_courses(skills: list[SkillStat]) -> list[CourseMapping]:
    """③ 映射：核心/高频技能分批并行问 LLM，课程/竞赛/项目/实习必须落在两个资产库内（代码确定性校验）。"""
    top = _top_skills(skills)
    if not top:
        return []
    batches = [top[i : i + MAP_BATCH_SIZE] for i in range(0, len(top), MAP_BATCH_SIZE)]
    results = await asyncio.gather(*(_map_batch(b) for b in batches))
    requested = {s.skill for s in top}
    merged: list[CourseMapping] = []
    for batch in results:
        for m in batch.mappings:
            if m.skill not in requested:  # 模型幻觉出的批外技能：直接丢弃
                continue
            merged.append(m)
    return _sanitize_mappings(merged)


# ---------------------------------------------------------------------------
# ③ 的资产底座、提示词与确定性校验
# ---------------------------------------------------------------------------

MAP_AGENT_NAME = "map_courses"  # 缓存键里的调用名；改提示词无需改它（键已含提示词全文）
MAP_TOP_N = 20  # 进入③的技能上限：is_core 优先 + frequency 降序（任务约定 20）
MAP_BATCH_SIZE = 8  # 每批映射的技能数上限：控制单次 prompt 体量与结构化输出风险（任务约定 ≤8）

MAP_SYSTEM_PROMPT = """你是计算机专业培养方案顾问：把岗位技能要求映射到培养方案课程与竞赛/项目/实习机会，只输出 JSON。

对输入的每个技能输出一条映射（键名必须完全一致）：
- skill: 原样返回输入给出的技能名
- courses: 【课程库】中与该技能相关的课程名列表，名称必须与库完全一致（一字不差）；库内无相关课程给 []
- competitions: 【竞赛库】中与该技能匹配的竞赛名列表，名称与库完全一致；无则 []
- projects: 【项目库】中匹配的项目名列表，名称与库完全一致；无则 []
- internships: 【实习档位】typical_roles 中匹配的岗位名列表，名称完全一致；无则 []
- gap_note: 培养方案覆盖不到的部分写具体自学路径（学什么方向、用什么资料、做什么练习、参加哪个竞赛/哪档实习）；完全覆盖给 ""

铁律：四类建议只能从下方库中逐字选取，禁止自创课程/竞赛/项目/岗位名——不在库内的建议会被系统直接剔除。宁可少给，不可编造。"""


class _BatchMappings(BaseModel):
    """③ 的 LLM 输出容器：ask_json 需要单个模型输出，列表包一层（内部契约，不进 schemas.py）。"""

    mappings: list[CourseMapping]


@functools.lru_cache(maxsize=1)
def _assets() -> tuple[dict, dict]:
    """读取 data/curriculum.json 与 opportunities.json（静态资产，小文件只读一次进内存）。"""
    curriculum = json.loads((config.DATA_DIR / "curriculum.json").read_text(encoding="utf-8"))
    opportunities = json.loads((config.DATA_DIR / "opportunities.json").read_text(encoding="utf-8"))
    return curriculum, opportunities


def _top_skills(skills: list[SkillStat]) -> list[SkillStat]:
    """③ 的入参筛选：is_core 优先、frequency 降序取前 MAP_TOP_N（确定性，控制 LLM 调用规模）。"""
    return sorted(skills, key=lambda s: (not s.is_core, -s.frequency))[:MAP_TOP_N]


def _map_user_prompt(batch: list[SkillStat]) -> str:
    """把一批技能 + 两个资产库拼成③的用户输入（进缓存键，格式改动=缓存全失效，慎改）。"""
    curriculum, opportunities = _assets()
    lines = ["【待映射技能】"]
    for s in batch:
        core = "核心" if s.is_core else "非核心"
        lines.append(f"- {s.skill}（{s.category}｜出现 {s.frequency} 条｜{core}）")
    # 库不大（课程 56 / 竞赛 16 / 项目 10 / 实习 4 档），全量紧凑附上：
    # 「完全一致」的硬校验要求模型看得到全部合法名，预筛反而制造信息缺口
    lines += ["", "【课程库】（courses 只能从这里选；格式 课程名（第X学期·类别｜覆盖技能））"]
    for c in curriculum["courses"]:
        cov = "、".join(c["skills_covered"]) or "—"
        lines.append(f"- {c['name']}（第{c['semester']}学期·{c['category']}｜覆盖: {cov}）")
    lines += ["", "【竞赛库】（competitions 只能从这里选）"]
    for c in opportunities["competitions"]:
        months = "/".join(str(m) for m in c["months"])
        lines.append(f"- {c['name']}（{c['level']}级｜常见月份 {months}｜关联技能: {'、'.join(c['skills'])}）")
    lines += ["", "【项目库】（projects 只能从这里选）"]
    for p in opportunities["projects"]:
        lines.append(f"- {p['name']}（约 {p['duration_weeks']} 周｜关联技能: {'、'.join(p['skills'])}）")
    lines += ["", "【实习档位】（internships 从各档 typical_roles 里选岗位名）"]
    for it in opportunities["internships"]:
        lines.append(f"- {it['stage']}：{'、'.join(it['typical_roles'])}")
    lines += ["", f"请给出以上 {len(batch)} 个技能的映射（mappings 列表，顺序与输入一致）。"]
    return "\n".join(lines)


async def _map_batch(batch: list[SkillStat]) -> _BatchMappings:
    """单批映射的 LLM 调用（走 ask_json 缓存）。"""
    return await llm.ask_json(
        agent_name=MAP_AGENT_NAME,
        system_prompt=MAP_SYSTEM_PROMPT,
        user_prompt=_map_user_prompt(batch),
        output_type=_BatchMappings,
    )


def _sanitize_mappings(raw: list[CourseMapping]) -> list[CourseMapping]:
    """确定性校验（不信任模型抄写）：四类建议名必须逐字在库内；不在的剔除并改写 gap_note 补自学路径。"""
    curriculum, opportunities = _assets()
    course_names = {c["name"] for c in curriculum["courses"]}
    comp_names = {c["name"] for c in opportunities["competitions"]}
    proj_names = {p["name"] for p in opportunities["projects"]}
    intern_names = (
        {role for it in opportunities["internships"] for role in it["typical_roles"]}
        | {it["stage"] for it in opportunities["internships"]}
    )

    def _keep(names: list[str], valid: set[str]) -> tuple[list[str], list[str]]:
        kept, dropped = [], []
        for n in names:
            (kept if n in valid else dropped).append(n)
        return kept, dropped

    # 同技能多条（跨批重复/模型分条）：合并去重（保序）
    by_skill: dict[str, CourseMapping] = {}
    for m in raw:
        base = by_skill.setdefault(m.skill, CourseMapping(skill=m.skill))
        for field in ("courses", "competitions", "projects", "internships"):
            cur = getattr(base, field)
            cur += [x for x in getattr(m, field) if x not in cur]
        if m.gap_note and m.gap_note not in base.gap_note:
            base.gap_note = f"{base.gap_note}；{m.gap_note}" if base.gap_note else m.gap_note

    result = []
    for m in by_skill.values():
        dropped: list[str] = []
        m.courses, d = _keep(m.courses, course_names)
        dropped += d
        m.competitions, d = _keep(m.competitions, comp_names)
        dropped += d
        m.projects, d = _keep(m.projects, proj_names)
        dropped += d
        m.internships, d = _keep(m.internships, intern_names)
        dropped += d
        if dropped:  # 剔除后把补齐路径写进 gap_note：给具体自学方向，而非留下一个悬空的课程名
            suffix = (
                f"『{'、'.join(dropped)}』不在培养方案/机会库内（已剔除），"
                "请按其官方文档/慕课自学，并用库内项目或竞赛练手补齐"
            )
            m.gap_note = f"{m.gap_note}；{suffix}" if m.gap_note else suffix
        result.append(m)
    return result


# ---------------------------------------------------------------------------
# ④ 规划（M3）：LLM 出草稿，代码做确定性修正
# ---------------------------------------------------------------------------

ROADMAP_AGENT_NAME = "make_roadmap"

ROADMAP_SYSTEM_PROMPT = """你是大学职业规划师：基于学生画像、岗位技能要求与课程映射，产出从当前学期到毕业的分学期路线图草稿，只输出 JSON。

输出（键名必须完全一致）：
- profile_summary: 一句话画像概括（年级/目标岗位/路线侧重/每周投入）
- semesters: 从当前学期到第 8 学期（大四下）的学期块列表，term 用规范名（大一上/大一下/大二上/大二下/大三上/大三下/大四上/大四下），每块含：
  - focus: 本学期主线，一句话
  - courses: 本学期要修/强化的课程名，只能从【可选课程】里选，名称完全一致
  - actions: 具体行动列表（竞赛按常见月份排入对应学期、项目/刷题/实习档位节点；写具体名称，如 蓝桥杯、Kaggle）
  - milestone: 学期末应达到的可检验状态
  - hours_per_week: 本学期全部课程外行动折算的每周小时数（不得超过给出的每周可投入上限）
- risks: 时间不够/先修缺失/窗口冲突等风险提示

路径侧重（必须体现）：path=就业 -> 保留实习节点，大四上排秋招投递；path=考研 -> 大三下起数学/专业课备考、大四上 12 月初试冲刺，实习让位给备考；path=未定 -> 兼顾并提示尽早定向。
当前学期之前的学期不要输出（由系统占位处理）。课程学期分布、时长上限等硬约束由系统最终校准，你负责主线、行动与里程碑的合理性。"""


class _RoadmapDraft(BaseModel):
    """④ 的 LLM 草稿：代码会做确定性修正（恒 8 学期/课程落位/时长钳制/path 特化），内部契约。"""

    profile_summary: str = ""
    semesters: list[SemesterPlan] = []
    risks: list[str] = []


_TERMS = ("大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下")
_GRADE_TO_SEM = {t: i + 1 for i, t in enumerate(_TERMS)}


def _roadmap_user_prompt(
    profile: StudentProfile, skills: list[SkillStat], mappings: list[CourseMapping]
) -> str:
    """把画像+技能+映射+资产日历拼成④的用户输入（进缓存键，格式改动=缓存全失效，慎改）。"""
    curriculum, opportunities = _assets()
    cur = _GRADE_TO_SEM.get(profile.grade, 1)  # 未知年级按大一上：保守地从第 1 学期排起
    cap = profile.weekly_hours * 6 // 5
    lines = [
        "【学生画像】",
        f"- 年级: {profile.grade}（当前第 {cur} 学期）",
        f"- 目标岗位: {profile.target_role}",
        f"- 路线: {profile.path}",
        f"- 每周课外可投入: {profile.weekly_hours}h（hours_per_week 不得超过 {cap}h）",
        f"- 已有基础: {'、'.join(profile.skills) or '无'}",
        f"- 备注: {profile.notes or '无'}",
        "",
        "【岗位技能要求】（核心优先）",
    ]
    lines += [
        f"- {s.skill}（{'核心' if s.is_core else '非核心'}｜出现 {s.frequency} 条）"
        for s in _top_skills(skills)
    ]
    lines += ["", "【课程映射（③产出）】"]
    for m in mappings:
        parts = []
        if m.courses:
            parts.append("课程: " + "、".join(m.courses))
        if m.competitions:
            parts.append("竞赛: " + "、".join(m.competitions))
        if m.projects:
            parts.append("项目: " + "、".join(m.projects))
        if m.internships:
            parts.append("实习: " + "、".join(m.internships))
        if m.gap_note:
            parts.append("gap: " + m.gap_note)
        lines.append(f"- {m.skill} -> " + ("；".join(parts) or "无对应资源"))
    lines += ["", f"【可选课程】（courses 只能从这里选；当前第 {cur} 学期，仅列当前及以后开课）"]
    for sem in range(cur, 9):
        names = "、".join(c["name"] for c in curriculum["courses"] if c["semester"] == sem)
        lines.append(f"- 第{sem}学期（{_TERMS[sem - 1]}）: {names or '无'}")
    lines += ["", "【竞赛日历】（名称｜常见月份）"]
    lines += [f"- {c['name']}｜{'/'.join(map(str, c['months']))} 月" for c in opportunities["competitions"]]
    lines += ["", "【实习档位】"]
    lines += [f"- {it['stage']}: {'、'.join(it['typical_roles'])}" for it in opportunities["internships"]]
    lines += [
        "",
        "（月份对照：秋季学期=9~次年1月，春季学期=2~8月；大三暑假档在第 6 学期后，秋招黄金窗口在第 7 学期 9-11 月）",
        f"请输出第 {cur} 学期（{_TERMS[cur - 1]}）至第 8 学期（大四下）的 semesters 草稿（term 用规范学期名）。",
    ]
    return "\n".join(lines)


async def make_roadmap(
    profile: StudentProfile, skills: list[SkillStat], mappings: list[CourseMapping]
) -> Roadmap:
    """④ 规划：LLM 生成草稿 -> 代码确定性校准（恒 8 学期/课程按培养方案落位/时长钳制/path 特化）。"""
    draft = await llm.ask_json(
        agent_name=ROADMAP_AGENT_NAME,
        system_prompt=ROADMAP_SYSTEM_PROMPT,
        user_prompt=_roadmap_user_prompt(profile, skills, mappings),
        output_type=_RoadmapDraft,
    )
    return _finalize_roadmap(profile, draft, mappings)


def _finalize_roadmap(
    profile: StudentProfile, draft: _RoadmapDraft, mappings: list[CourseMapping]
) -> Roadmap:
    """确定性修正 LLM 草稿：不信任模型的部分（学期数/课程落位/时长/路径侧重）全部由代码拍板。"""
    curriculum, _ = _assets()
    sem_of_course = {c["name"]: c["semester"] for c in curriculum["courses"]}
    order_in_curriculum = {c["name"]: i for i, c in enumerate(curriculum["courses"])}
    cur = _GRADE_TO_SEM.get(profile.grade, 1)
    # 1.2 倍上限用整数运算取整：15*1.2 在浮点下是 17.999...，int() 会误钳到 17
    cap = profile.weekly_hours * 6 // 5

    draft_by_sem: dict[int, SemesterPlan] = {}
    for sp in draft.semesters:
        sem = _GRADE_TO_SEM.get(sp.term)
        if sem is not None and sem >= cur:
            draft_by_sem.setdefault(sem, sp)

    # 课程落位：草稿与③映射提到的课程取并集，学期一律以培养方案的 semester 为准（不信 LLM 排的学期）
    wanted = {name for sp in draft_by_sem.values() for name in sp.courses}
    wanted |= {name for m in mappings for name in m.courses}
    courses_by_sem: dict[int, list[str]] = {sem: [] for sem in range(1, 9)}
    for name in wanted:
        sem = sem_of_course.get(name)
        if sem is None:  # 不在培养方案（③已钳过一轮，这里双保险）
            continue
        if sem < cur:  # 开课学期已过：不再可规划，舍弃（取舍见下方"过去学期"注释）
            continue
        courses_by_sem[sem].append(name)
    for sem in courses_by_sem:
        courses_by_sem[sem].sort(key=order_in_curriculum.__getitem__)

    risks = list(draft.risks)
    clamped = False
    semesters: list[SemesterPlan] = []
    for sem in range(1, 9):
        term = _TERMS[sem - 1]
        if sem < cur:
            # 取舍：当前学期之前的学期已成定局、不可规划，不排内容只做占位——
            # 但保持 8 学期完整结构，让路线图始终呈现完整的本科时间轴
            semesters.append(
                SemesterPlan(term=term, focus="已修读阶段（早于当前年级），不排规划", hours_per_week=0)
            )
            continue
        sp = draft_by_sem.get(sem)
        hours = min(max(sp.hours_per_week if sp else 0, 0), cap)  # 时长钳制：代码说了算，不靠模型自觉
        if sp and sp.hours_per_week > cap:
            clamped = True
        semesters.append(
            SemesterPlan(
                term=term,
                focus=sp.focus if sp and sp.focus else "完成培养方案课程与专项练习",
                courses=courses_by_sem[sem],
                actions=list(sp.actions) if sp else [],
                milestone=sp.milestone if sp else "",
                hours_per_week=hours,
            )
        )

    # path 特化：确定性注入（06 手册§3 精神——硬行为写死在代码里，不靠提示词"劝"模型）
    if profile.path == "考研":
        for sp in semesters:  # 实习让位：剔除草稿里的实习节点
            sp.actions = [a for a in sp.actions if "实习" not in a]
        for sem, action in (
            (6, "考研备考启动：数学一轮 + 408 统考专业课复习"),
            (7, "考研冲刺：近十年真题与模拟考（12 月初试）"),
            (8, "考研复试/调剂准备"),
        ):
            if sem >= cur:
                semesters[sem - 1].actions.append(action)
        risks.append("考研路线：实习节点已让位给备考，工程实践以课程配套项目为主")
    elif profile.path == "就业":
        if cur <= 7:
            semesters[6].actions.append("秋招投递与面试准备（9-11 月黄金窗口，简历/八股/项目复盘）")
    else:
        risks.append("路线未定（就业/考研）：建议最近一学期内定向，避免两头准备")
    if clamped:
        risks.append(f"有学期计划时长超出每周 {cap}h 上限，已按预算钳制")

    summary = draft.profile_summary or (
        f"{profile.grade}·{profile.target_role}·{profile.path}向，每周可投入 {profile.weekly_hours}h"
    )
    return Roadmap(profile_summary=summary, semesters=semesters, risks=risks)
