"""⑤ 对话 Agent + 多 Agent 评审链（M4）。

run_dialogue()：单轮对话。中文"大学职业规划顾问"人设，把学生画像与当前路线图
摘要放进上下文，输出 DialogueTurn——action 识别"改目标"类意图：
  - replan         换目标路线/岗位（就业↔考研、换方向），需要重新规划
  - adjust_hours   调整每周投入时长
  - clarify        关键信息不足，先追问
  - none           普通咨询/闲聊，不触发改动

review_roadmap()：多 Agent 评审链，三角色分工（各角色独立 system_prompt，
全部走 llm.ask_json：0 温度 + SQLite 缓存）：
  1. Planner  基于 skill_stats 找 roadmap 薄弱点，生成改进提案；
  2. 辩论循环 Critic 质疑 -> Planner 回应并修订提案；
  3. Reporter 汇总辩论结果，产出 ReviewReport。

轮数硬限制：辩论轮数由 for 循环上限 config.MAX_DEBATE_ROUNDS 写死在代码里
（06 手册§3：不靠提示词"劝"模型收敛）；Critic 主动认输（空质疑）可提前收束，
但永不超过上限。
"""

from pydantic import BaseModel, Field

from . import config, llm
from .schemas import DialogueTurn, Roadmap, ReviewReport, SkillStat, StudentProfile

# ---------------------------------------------------------------------------
# 内部中间契约：只在评审链各角色之间传递，不进 schemas.py 全局契约
# ---------------------------------------------------------------------------


class _DebateProposal(BaseModel):
    """Planner 的中间产物：薄弱点 + 改进提案。"""

    weaknesses: list[str] = Field(default_factory=list)
    proposal: str = ""


class _CriticChallenge(BaseModel):
    """Critic 的中间产物：对提案的质疑列表（空列表 = 认为提案无懈可击）。"""

    challenges: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 各角色 system_prompt（一角色一提示词，便于缓存键区分与单独调优）
# ---------------------------------------------------------------------------

_DIALOGUE_PROMPT = (
    "你是一名大学职业规划顾问，根据学生画像与当前路线图回应学生的每条消息。\n"
    "先判定学生这条消息的意图，再作答：\n"
    "- replan：学生想更换目标路线或岗位（如 就业↔考研、换技术方向），需要重新规划\n"
    "- adjust_hours：学生想调整每周可投入的小时数\n"
    "- clarify：缺少关键信息（如年级、目标岗位），需要先追问\n"
    "- none：普通咨询/闲聊，无需改动规划\n"
    "reply 面向学生、用中文、具体可执行；reason 用一句话说明判定依据。"
)

_PLANNER_PROMPT = (
    "你是 Planner（规划评审员）。基于岗位技能统计审查学生的路线图："
    "找出技能覆盖不足、时间安排失衡、里程碑不可检验等薄弱点，"
    "并给出具体、可执行的改进提案。面对质疑时逐条回应，修订提案；未被质疑的部分保持原样。"
)

_CRITIC_PROMPT = (
    "你是 Critic（批判评审员）。你的职责是质疑 Planner 的改进提案："
    "找逻辑漏洞、与技能统计不符、超出学生时间预算、里程碑不可检验等问题。"
    "只提质疑，不改写提案；若提案确实无懈可击，返回空的 challenges 列表。"
)

_REPORTER_PROMPT = (
    "你是 Reporter（汇总评审员）。阅读路线图、技能统计与辩论全程记录，"
    "汇总成最终评审报告：summary 概括整体结论；issues 逐条列出遗留问题"
    "（aspect 如 技能覆盖/时间安排/里程碑，severity 取 low/medium/high）；"
    "suggestions 给出吸收了辩论结论的行动建议。不要引入辩论中没有出现过的新主张。"
)


# ---------------------------------------------------------------------------
# 摘要工具：把契约对象压成稳定中文摘要（确定性文本 = 稳定缓存键）
# ---------------------------------------------------------------------------


def _profile_brief(p: StudentProfile) -> str:
    """画像压一行摘要。"""
    return (
        f"姓名: {p.name or '未填'}｜年级: {p.grade}｜目标岗位: {p.target_role}"
        f"｜路线: {p.path}｜每周可投入: {p.weekly_hours}h"
        f"｜已有基础: {'、'.join(p.skills) or '无'}｜备注: {p.notes or '无'}"
    )


def _roadmap_brief(r: Roadmap) -> str:
    """路线图压成多行摘要（每学期一行）。"""
    lines = [f"画像: {r.profile_summary}", f"风险: {'；'.join(r.risks) or '无'}"]
    for s in r.semesters:
        lines.append(
            f"- {s.term}｜主线: {s.focus}｜课程: {'、'.join(s.courses) or '无'}"
            f"｜行动: {'；'.join(s.actions) or '无'}"
            f"｜里程碑: {s.milestone or '无'}｜投入: {s.hours_per_week}h/周"
        )
    return "\n".join(lines)


def _skill_stats_brief(stats: list[SkillStat]) -> str:
    """技能统计压成多行摘要（数据面：LLM 只做解读，不做计算）。"""
    if not stats:
        return "（暂无技能统计数据）"
    return "\n".join(
        f"- {s.skill}（{s.category}）出现 {s.frequency} 条｜{'核心要求' if s.is_core else '非核心'}"
        for s in stats
    )


def _dialogue_prompts(
    profile: StudentProfile, roadmap: Roadmap, message: str, history: list[dict]
) -> tuple[str, str]:
    """组装 run_dialogue 的 (system_prompt, user_prompt)；测试用它复算缓存键。"""
    history_text = "\n".join(
        f"{'学生' if h.get('role') == 'user' else '顾问'}: {h.get('content', '')}"
        for h in history
    ) or "（无历史）"
    user_prompt = (
        f"【学生画像】\n{_profile_brief(profile)}\n\n"
        f"【当前路线图】\n{_roadmap_brief(roadmap)}\n\n"
        f"【对话历史】\n{history_text}\n\n"
        f"【学生这条消息】\n{message}"
    )
    return _DIALOGUE_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


async def run_dialogue(
    profile: StudentProfile, roadmap: Roadmap, message: str, history: list[dict]
) -> DialogueTurn:
    """单轮对话：画像+路线图+历史+新消息 -> 回复与意图动作（走 llm.ask_json，带缓存）。"""
    system_prompt, user_prompt = _dialogue_prompts(profile, roadmap, message, history)
    return await llm.ask_json("dialogue", system_prompt, user_prompt, DialogueTurn)


def _proposal_text(p: _DebateProposal) -> str:
    """提案压成稳定文本，供 Critic/Reporter 阅读。"""
    return f"薄弱点: {'；'.join(p.weaknesses) or '无'}\n提案: {p.proposal or '无'}"


async def review_roadmap(roadmap: Roadmap, skill_stats: list[SkillStat]) -> ReviewReport:
    """评审链：Planner 提案 -> Critic/Planner 辩论（for 循环硬限 ≤config.MAX_DEBATE_ROUNDS 轮）-> Reporter 汇总。"""
    context = (
        f"【待评审路线图】\n{_roadmap_brief(roadmap)}\n\n"
        f"【岗位技能统计】\n{_skill_stats_brief(skill_stats)}"
    )

    # ① Planner 初评：基于 skill_stats 找薄弱点、给改进提案
    proposal = await llm.ask_json(
        "review_planner",
        _PLANNER_PROMPT,
        f"{context}\n\n请指出这条路线图的薄弱点，并给出改进提案。",
        _DebateProposal,
    )

    # ② 辩论循环：上限写死在 for（06 手册§3），不靠提示词收敛
    debate_log: list[str] = []
    for round_no in range(1, config.MAX_DEBATE_ROUNDS + 1):
        challenge = await llm.ask_json(
            "review_critic",
            _CRITIC_PROMPT,
            f"{context}\n\n【Planner 当前提案】\n{_proposal_text(proposal)}\n\n"
            f"第 {round_no} 轮：请质疑上述提案。",
            _CriticChallenge,
        )
        if not challenge.challenges:  # Critic 认输则提前收束（上限仍由 for 保证）
            debate_log.append(f"第{round_no}轮 Critic 无异议，辩论提前结束")
            break
        debate_log.append(f"第{round_no}轮 Critic 质疑: {'；'.join(challenge.challenges)}")
        proposal = await llm.ask_json(
            "review_planner",
            _PLANNER_PROMPT,
            f"{context}\n\n【当前提案】\n{_proposal_text(proposal)}\n\n"
            f"【Critic 第 {round_no} 轮质疑】\n"
            + "\n".join(f"- {c}" for c in challenge.challenges)
            + "\n\n请逐条回应质疑，并给出修订后的完整提案。",
            _DebateProposal,
        )
        debate_log.append(f"第{round_no}轮 Planner 修订: {proposal.proposal}")

    # ③ Reporter 汇总成最终 ReviewReport
    debate_text = "\n".join(debate_log) or "（未进入辩论）"
    return await llm.ask_json(
        "review_reporter",
        _REPORTER_PROMPT,
        f"{context}\n\n【辩论后的最终提案】\n{_proposal_text(proposal)}\n\n"
        f"【辩论记录】\n{debate_text}",
        ReviewReport,
    )
