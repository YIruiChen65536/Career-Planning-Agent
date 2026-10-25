"""M4 自检：对话 Agent 与多 Agent 评审链（06 手册§4）。

全部离线：run_dialogue 走预填缓存回放（键用 llm._cache_key 计算），
review_roadmap 走 monkeypatch 的假 build_agent——无网络、无 key、秒级完成。
"""

import asyncio
from types import SimpleNamespace

from career_agent import agent, config, llm, store
from career_agent.schemas import (
    DialogueTurn,
    Roadmap,
    SemesterPlan,
    SkillStat,
    StudentProfile,
)


def _profile() -> StudentProfile:
    return StudentProfile(
        name="小陈", grade="大二上", target_role="后端开发工程师",
        path="就业", skills=["Python", "MySQL"], weekly_hours=15,
    )


def _roadmap() -> Roadmap:
    return Roadmap(
        profile_summary="大二后端就业向，每周 15h",
        semesters=[
            SemesterPlan(
                term="大二下", focus="Java 基础与数据库",
                courses=["数据库原理"], actions=["LeetCode 100 题"],
                milestone="能独立写 CRUD", hours_per_week=10,
            )
        ],
        risks=["每周投入偏紧"],
    )


def _stats() -> list[SkillStat]:
    return [
        SkillStat(skill="Java", category="hard", frequency=8, is_core=True),
        SkillStat(skill="Spring", category="tool", frequency=5, is_core=True),
        SkillStat(skill="Redis", category="hard", frequency=2, is_core=False),
    ]


# ---------------------------------------------------------------------------
# (a) 预填缓存回放 run_dialogue：命中缓存则 build_agent 根本不该被碰到
# ---------------------------------------------------------------------------


def test_run_dialogue_replays_from_prefilled_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("career_agent.config.DB_PATH", tmp_path / "test.db")

    def _boom(*args, **kwargs):
        raise AssertionError("缓存命中时不应真调用 build_agent（必须无网络也能过）")

    monkeypatch.setattr(llm, "build_agent", _boom)

    profile, roadmap = _profile(), _roadmap()
    message = "我想转考研，不找工作了"
    history = [{"role": "user", "content": "帮我规划下学期"}, {"role": "assistant", "content": "好的"}]

    # 键直接用 llm._cache_key 计算，prompts 复用 run_dialogue 同一组装函数
    system_prompt, user_prompt = agent._dialogue_prompts(profile, roadmap, message, history)
    key = llm._cache_key("dialogue", system_prompt, user_prompt)
    cached = DialogueTurn(
        reply="可以，我们把路线改成考研向，重新规划数学与专业课复习。",
        action="replan",
        reason="学生明确表示从就业转向考研",
    )
    store.cache_put(key, cached.model_dump(mode="json"))

    turn = asyncio.run(agent.run_dialogue(profile, roadmap, message, history))

    assert isinstance(turn, DialogueTurn)
    assert turn.action == "replan"          # 识别出"改目标"意图
    assert turn.reply == cached.reply
    assert turn.reason == cached.reason


# ---------------------------------------------------------------------------
# (b) 假 build_agent 计数：辩论轮数不得超过 config.MAX_DEBATE_ROUNDS
# ---------------------------------------------------------------------------

# 按输出类型名给假 LLM 的 canned 返回（结构与 schemas/内部契约一致）
_CANNED = {
    "DialogueTurn": {"reply": "好的", "action": "none", "reason": "测试"},
    "_DebateProposal": {"weaknesses": ["Redis 覆盖不足"], "proposal": "大二下补 Redis 入门"},
    "_CriticChallenge": {"challenges": ["每周小时数不够支撑新增内容"]},
    "ReviewReport": {
        "summary": "路线图基本可行，需微调",
        "issues": [{"aspect": "技能覆盖", "description": "Redis 非核心但常见", "severity": "low"}],
        "suggestions": ["维持现有主线，补充 Redis 自学"],
    },
}


class _FakeAgent:
    """替身：run() 直接返回 output_type 的 canned 实例，不碰网络。"""

    def __init__(self, output_type):
        self._output = output_type.model_validate(_CANNED[output_type.__name__])

    async def run(self, user_prompt):
        return SimpleNamespace(output=self._output)


def _install_fake_llm(monkeypatch) -> list[tuple[str, type]]:
    calls: list[tuple[str, type]] = []

    def fake_build_agent(system_prompt: str = "", output_type=None):
        calls.append((system_prompt, output_type))
        return _FakeAgent(output_type)

    monkeypatch.setattr(llm, "build_agent", fake_build_agent)
    return calls


def test_review_roadmap_debate_rounds_capped_at_config(tmp_path, monkeypatch):
    monkeypatch.setattr("career_agent.config.DB_PATH", tmp_path / "test.db")
    calls = _install_fake_llm(monkeypatch)

    report = asyncio.run(agent.review_roadmap(_roadmap(), _stats()))

    assert isinstance(report.summary, str) and report.summary
    assert report.issues[0].severity == "low" and report.issues[0].aspect == "技能覆盖"
    assert report.suggestions == ["维持现有主线，补充 Redis 自学"]

    # 辩论轮数 = Critic 被调用的次数，硬性不超过 config.MAX_DEBATE_ROUNDS
    critic_calls = [sp for sp, _ in calls if sp == agent._CRITIC_PROMPT]
    assert len(critic_calls) <= config.MAX_DEBATE_ROUNDS
    # 结构自检：Planner 初评 1 次 + 每轮(质疑 1 + 回应 1) + Reporter 汇总 1 次
    assert len(calls) == 2 + 2 * config.MAX_DEBATE_ROUNDS


def test_review_roadmap_round_cap_follows_shrunk_config(tmp_path, monkeypatch):
    """把上限改小到 1，调用数随之收敛——证明轮数由代码常量控制，不是提示词。"""
    monkeypatch.setattr("career_agent.config.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "MAX_DEBATE_ROUNDS", 1)
    calls = _install_fake_llm(monkeypatch)

    asyncio.run(agent.review_roadmap(_roadmap(), _stats()))

    critic_calls = [sp for sp, _ in calls if sp == agent._CRITIC_PROMPT]
    assert len(critic_calls) == 1 == config.MAX_DEBATE_ROUNDS
    assert len(calls) == 4  # 初评 + 1 轮×2 + 汇总
