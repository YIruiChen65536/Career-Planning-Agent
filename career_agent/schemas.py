"""全项目数据契约（权威定义）。改动本文件 = 全员周知 + 同步 02-架构设计。"""

from pydantic import BaseModel, Field


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
    grade: str = Field(description="如 大二上")
    target_role: str = Field(description="目标岗位，如 后端开发工程师")
    path: str = Field(default="就业", description="就业 | 考研 | 未定")
    skills: list[str] = Field(default_factory=list, description="已有技术基础")
    weekly_hours: int = Field(ge=0, description="每周课外可投入小时数")
    notes: str = ""
