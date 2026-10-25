"""全项目数据契约（权威定义）。改动本文件 = 全员周知 + 同步 02-架构设计。"""

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

# 规范学期名（单一定义，pipeline 的 ④ 规划按它定位当前学期）
TERMS: tuple[str, ...] = (
    "大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下",
)

# 姓名留空时的默认档案名；前端 currentProfileName() 的兜底值必须与此逐字一致，
# 否则"未填姓名"用户的 ⑤ 对话会按错误档案名寻址而恒 404
UNNAMED_PROFILE_NAME = "未命名学生"


class JobPosting(BaseModel):
    """一条原始招聘信息——所有数据源统一产出的最小单位。"""

    id: str
    title: str
    company: str
    source: str = Field(description="来源平台或文件名")
    url: str | None = Field(default=None, description="原文链接，证据留存")
    description: str = Field(description="JD 原文")


class ExtractedRequirements(BaseModel):
    """流水线①的输出：一条 JD -> 结构化要求。"""

    posting_id: str
    hard_skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list, description="框架/工具链，如 Spring、Git")
    soft_skills: list[str] = Field(default_factory=list)
    education: str = Field(default="", description="如 本科及以上")
    experience_years: float | None = None
    project_requirements: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list, description="加分项原文摘要")


class SkillStat(BaseModel):
    """流水线②归并后的单行统计。"""

    skill: str = Field(description="归并后的规范名，如 Python")
    category: str = Field(description="hard | tool | soft")
    frequency: int = Field(ge=1, description="在该岗位方向语料中的出现条数（pandas 计数，不经 LLM）")
    is_core: bool = Field(description="出现率是否达到核心阈值")
    aliases: list[str] = Field(default_factory=list, description="被归并的原名，如 Python开发")


class CourseMapping(BaseModel):
    """流水线③的输出：能力 -> 课程/竞赛/项目/实习。"""

    skill: str
    courses: list[str] = Field(default_factory=list, description="培养方案内课程名")
    competitions: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    gap_note: str = Field(default="", description="课程覆盖不到时的自学路径建议")


class SemesterPlan(BaseModel):
    """④规划输出的单个学期块。"""

    term: str = Field(description="如 大二下")
    focus: str = Field(description="本学期主线，一句话")
    courses: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list, description="项目/竞赛/刷题等具体行动")
    milestone: str = Field(default="", description="学期末应达到的可检验状态")
    hours_per_week: int = Field(default=0)


class Roadmap(BaseModel):
    """流水线④的最终输出。"""

    profile_summary: str
    semesters: list[SemesterPlan]
    risks: list[str] = Field(default_factory=list, description="时间不够/先修缺失等提示")


class StudentProfile(BaseModel):
    """学生画像：③④⑤ 的共同输入，落 SQLite 档案。"""

    name: str = ""
    grade: str = Field(description="如 大二上；接受口语学年写法（大三 -> 大三上）")
    target_role: str = Field(description="目标岗位，如 后端开发工程师")
    path: str = Field(default="就业", description="就业 | 考研 | 未定")
    skills: list[str] = Field(default_factory=list, description="已有技术基础")
    weekly_hours: int = Field(ge=0, description="每周课外可投入小时数")
    notes: str = ""

    _GRADE_YEAR: ClassVar[dict[str, int]] = {"一": 1, "1": 1, "二": 2, "2": 2, "三": 3, "3": 3, "四": 4, "4": 4}

    @field_validator("grade")
    @classmethod
    def _normalize_grade(cls, v: str) -> str:
        """年级规范化：口语学年（"大三"/"大3"）映射到该学年上学期；无法识别直接校验失败。

        以前未知年级在 pipeline 里被静默按"大一上"排满 8 学期且无任何提示（评审 high），
        现在把好入口：要么规范成合法学期名，要么 422 明确告知合法写法。"""
        g = v.strip()
        if g in TERMS:
            return g
        m = re.fullmatch(r"大([一二三四1-4])上?", g)
        if m:  # 只写学年 → 保守取上学期：从该学年起排，不吞掉下半年时间轴
            return TERMS[(cls._GRADE_YEAR[m.group(1)] - 1) * 2]
        raise ValueError(
            f"年级 {v!r} 无法识别：请用规范学期名（{' / '.join(TERMS)}）或学年写法（如 大三，将按 大三上 处理）"
        )

    @field_validator("name")
    @classmethod
    def _default_name(cls, v: str) -> str:
        """姓名留空 → 默认档案名：空串建档会让 ⑤ 对话按空名寻址恒 404（评审 medium）。"""
        return v.strip() or UNNAMED_PROFILE_NAME


class DialogueTurn(BaseModel):
    """⑤ 对话 Agent 的单轮输出：回复 + 意图识别出的动作（M4）。"""

    reply: str = Field(description="给学生的中文回复")
    action: Literal["none", "replan", "adjust_hours", "clarify"] = Field(
        description="none=普通对话 | replan=改目标(就业↔考研/换岗位) | adjust_hours=调时长 | clarify=信息不足需追问"
    )
    reason: str = Field(description="一句话说明为何判定为该 action")


class Issue(BaseModel):
    """评审链发现的单个问题。"""

    aspect: str = Field(description="问题方面，如 技能覆盖/时间安排/里程碑")
    description: str = Field(description="问题描述")
    severity: Literal["low", "medium", "high"] = Field(description="严重程度")


class ReviewReport(BaseModel):
    """⑤ 多 Agent 评审链的最终产出。"""

    summary: str = Field(description="整体结论")
    issues: list[Issue] = Field(default_factory=list, description="遗留问题清单")
    suggestions: list[str] = Field(default_factory=list, description="行动建议")
