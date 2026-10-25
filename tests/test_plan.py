"""M3 规划链路测试：真实语料 + 预填缓存回放（LLM 纪律：无网络也绿、秒级完成）。

链路：data/postings 真实 JD（backend-001/002）-> ①extract（预填缓存）
-> ②aggregate（确定性）-> ③map_courses（预填缓存 + 库内校验断言）
-> ④make_roadmap（预填缓存 + 钳制/落位断言）-> /api/plan 200/503 + GET 取回。
缓存键一律用 llm._cache_key 复算（prompt 复用 pipeline 的组装函数），不重写算法。
"""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

import server
from career_agent import config, llm, pipeline, store
from career_agent.schemas import (
    CourseMapping,
    ExtractedRequirements,
    JobPosting,
    Roadmap,
    SemesterPlan,
    SkillStat,
    StudentProfile,
)

# ---------------------------------------------------------------------------
# 真实语料与资产库（data/ 只读）
# ---------------------------------------------------------------------------


def _real_postings() -> list[JobPosting]:
    """从 data/postings 取 2 条真实 JD（title 均含"后端开发工程师"，可被 target_role 检索到）。"""
    postings_dir = Path(config.DATA_DIR) / "postings"
    out: list[JobPosting] = []
    for fname in ("backend-01.json", "backend-02.json"):
        out.extend(
            JobPosting.model_validate(raw)
            for raw in json.loads((postings_dir / fname).read_text(encoding="utf-8"))
        )
    return out


def _curriculum_names() -> set[str]:
    data = json.loads((Path(config.DATA_DIR) / "curriculum.json").read_text(encoding="utf-8"))
    return {c["name"] for c in data["courses"]}


def _opportunity_names() -> tuple[set[str], set[str], set[str]]:
    """返回 (竞赛名, 项目名, 实习岗位名∪档位名) 三个合法集合。"""
    data = json.loads((Path(config.DATA_DIR) / "opportunities.json").read_text(encoding="utf-8"))
    comps = {c["name"] for c in data["competitions"]}
    projs = {p["name"] for p in data["projects"]}
    interns = (
        {role for it in data["internships"] for role in it["typical_roles"]}
        | {it["stage"] for it in data["internships"]}
    )
    return comps, projs, interns


def _lib_competition(substr: str) -> str:
    data = json.loads((Path(config.DATA_DIR) / "opportunities.json").read_text(encoding="utf-8"))
    return next(c["name"] for c in data["competitions"] if substr in c["name"])


def _lib_project(substr: str) -> str:
    data = json.loads((Path(config.DATA_DIR) / "opportunities.json").read_text(encoding="utf-8"))
    return next(p["name"] for p in data["projects"] if substr in p["name"])


def _lib_role(substr: str) -> str:
    data = json.loads((Path(config.DATA_DIR) / "opportunities.json").read_text(encoding="utf-8"))
    return next(r for it in data["internships"] for r in it["typical_roles"] if substr in r)


# ---------------------------------------------------------------------------
# 预填缓存：①抽取 ③映射 ④规划的期望输出（人为约定，名称全部取自库文件本身）
# ---------------------------------------------------------------------------


def _expected_extract(posting_id: str) -> ExtractedRequirements:
    data = {
        "backend-001": dict(
            hard_skills=["Python", "数据结构与算法"], tools=["Flask", "MySQL"],
            soft_skills=["团队协作"], education="本科及以上", experience_years=1.0,
            project_requirements=[], extras=["有 AI Agent 开发经验优先"],
        ),
        "backend-002": dict(
            hard_skills=["Python"], tools=["Django", "MySQL"],
            soft_skills=["沟通能力"], education="本科及以上", experience_years=None,
            project_requirements=[], extras=[],
        ),
    }
    return ExtractedRequirements(posting_id=posting_id, **data[posting_id])


def _canned_mapping(skill: str) -> dict:
    """每个技能的"LLM 输出"：合法名从库文件现取（杜绝抄写误差）；Flask/Django 故意越界测剔除。"""
    canned = {
        "MySQL": dict(
            courses=["数据库系统"], competitions=[_lib_competition("计算机设计大赛")],
            projects=[_lib_project("电商后端")], internships=[_lib_role("Web后端实习生")],
            gap_note="Redis 等缓存中间件培养方案未覆盖，需自学",
        ),
        "Python": dict(
            courses=["机器学习", "数据挖掘"], competitions=[_lib_competition("Kaggle")],
            projects=[_lib_project("推荐系统复现")], internships=[_lib_role("算法实习生")],
            gap_note="Flask/Django 等 Web 框架按官方文档自学",
        ),
        "Django": dict(  # 部分越界：一条合法 + 一条自创
            courses=["Web开发技术", "Django Web 开发实战"], competitions=[],
            projects=[], internships=[], gap_note="",
        ),
        "Flask": dict(  # 全部越界：四类建议均不在库内
            courses=["量子编程导论"], competitions=["自创杯大赛"],
            projects=["元宇宙社交平台"], internships=["火箭总装实习生"], gap_note="",
        ),
        "团队协作": dict(
            courses=[], competitions=[_lib_competition("挑战杯")], projects=[],
            internships=[], gap_note="借助小组作业与社团活动锻炼",
        ),
        "数据结构与算法": dict(
            courses=["数据结构", "算法设计与分析"], competitions=[_lib_competition("蓝桥杯")],
            projects=[], internships=[], gap_note="",
        ),
        "沟通能力": dict(
            courses=[], competitions=[], projects=[], internships=[_lib_role("IT支持助理")],
            gap_note="",
        ),
    }
    return {"skill": skill, **canned[skill]}


_DRAFT_JOB = {  # ④就业版草稿：hours=99 超标、课程落位故意排错学期、只排到大三上（测补齐）
    "profile_summary": "大二上·后端开发工程师·就业向，每周可投入 15h",
    "semesters": [
        {"term": "大二上", "focus": "Python 进阶与数据结构打底",
         "courses": ["数据结构", "数据库系统"], "actions": ["LeetCode 刷题 100 题"],
         "milestone": "能独立实现链表/树/图常见结构", "hours_per_week": 99},
        {"term": "大二下", "focus": "Web 开发入门",
         "courses": ["操作系统"], "actions": ["完成个人博客/作品集网站并上线部署"],
         "milestone": "", "hours_per_week": 12},
        {"term": "大三上", "focus": "核心课深化与竞赛",
         "courses": [], "actions": ["参加蓝桥杯（4/6 月）"], "milestone": "", "hours_per_week": 10},
    ],
    "risks": ["核心课集中在高年级，大二课时偏紧"],
}

_DRAFT_GRAD = {  # ④考研版草稿：含实习节点，测"实习让位 + 备考注入"
    "profile_summary": "大二上·后端开发工程师·考研向",
    "semesters": [
        {"term": "大二上", "focus": "数学与程序基础", "courses": ["数据结构"],
         "actions": ["巩固 C/C++ 语法"], "milestone": "", "hours_per_week": 8},
        {"term": "大三下", "focus": "复习启动与暑期规划", "courses": [],
         "actions": ["大三暑假：投后端开发实习生"], "milestone": "", "hours_per_week": 15},
    ],
    "risks": [],
}


def _prefill_extract_cache(posting: JobPosting, expected: ExtractedRequirements) -> None:
    key = llm._cache_key(
        pipeline.EXTRACT_AGENT_NAME, pipeline.EXTRACT_SYSTEM_PROMPT,
        pipeline._extract_user_prompt(posting),
    )
    store.cache_put(key, expected.model_dump(mode="json"))


def _prefill_map_cache(skills: list[SkillStat]) -> None:
    """按 pipeline 同款分批逻辑预填③缓存：每批 canned 与批内技能一一对应。"""
    top = pipeline._top_skills(skills)
    for i in range(0, len(top), pipeline.MAP_BATCH_SIZE):
        batch = top[i : i + pipeline.MAP_BATCH_SIZE]
        key = llm._cache_key(
            pipeline.MAP_AGENT_NAME, pipeline.MAP_SYSTEM_PROMPT,
            pipeline._map_user_prompt(batch),
        )
        store.cache_put(key, {"mappings": [_canned_mapping(s.skill) for s in batch]})


def _prefill_roadmap_cache(
    profile: StudentProfile, skills: list[SkillStat], mappings: list[CourseMapping], draft: dict
) -> None:
    key = llm._cache_key(
        pipeline.ROADMAP_AGENT_NAME, pipeline.ROADMAP_SYSTEM_PROMPT,
        pipeline._roadmap_user_prompt(profile, skills, mappings),
    )
    store.cache_put(key, draft)


def _break_llm_config(monkeypatch) -> None:
    """破坏 LLM 配置：缓存未命中走真调用路径时 get_model 直接抛配置错误。"""
    monkeypatch.setattr(config, "MODEL", "openai:x")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")


def _profile(path: str = "就业", name: str = "小陈") -> StudentProfile:
    return StudentProfile(
        name=name, grade="大二上", target_role="后端开发工程师", path=path,
        skills=["Python", "MySQL"], weekly_hours=15,
    )


def _install_corpus(tmp_path, monkeypatch) -> None:
    """临时语料目录：真实 backend 语料 2 条（/api/plan 用 target_role 检索）。"""
    d = tmp_path / "data" / "postings"
    d.mkdir(parents=True)
    (d / "backend.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in _real_postings()]), encoding="utf-8",
    )
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", d.parent)


def _chain_skills() -> list[SkillStat]:
    """②的真实输出：真实语料 + 预填抽取结果的聚合（确定性，不走 LLM）。"""
    return pipeline.aggregate_skills([_expected_extract(p.id) for p in _real_postings()])


# ---------------------------------------------------------------------------
# (a) 纯函数：技能筛选与分批（无 LLM）
# ---------------------------------------------------------------------------


def test_top_skills_core_first_frequency_desc_capped_at_20():
    stats = [
        SkillStat(skill="a", category="hard", frequency=1, is_core=True),
        SkillStat(skill="b", category="hard", frequency=5, is_core=True),
        SkillStat(skill="c", category="hard", frequency=9, is_core=True),
    ]
    stats += [
        SkillStat(skill=f"s{i}", category="hard", frequency=30 - i, is_core=False)
        for i in range(25)
    ]
    top = pipeline._top_skills(skills=stats)
    assert len(top) == pipeline.MAP_TOP_N == 20  # 上限 20
    assert [s.skill for s in top[:3]] == ["c", "b", "a"]  # core 优先，组内频次降序
    assert all(s.is_core for s in top[:3]) and not any(s.is_core for s in top[3:])
    batches = [top[i : i + pipeline.MAP_BATCH_SIZE] for i in range(0, len(top), pipeline.MAP_BATCH_SIZE)]
    assert [len(b) for b in batches] == [8, 8, 4]  # 每批 ≤8，20 个技能分 3 批


# ---------------------------------------------------------------------------
# (b) ③ map_courses：缓存回放 + 确定性校验
# ---------------------------------------------------------------------------


def test_map_courses_replay_and_library_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    skills = _chain_skills()
    _prefill_map_cache(skills)

    mappings = asyncio.run(pipeline.map_courses(skills))

    course_names = _curriculum_names()
    comps, projs, interns = _opportunity_names()
    assert {m.skill for m in mappings} == {s.skill for s in skills}  # 技能一个不丢
    for m in mappings:  # 四类建议全部逐字在库内
        assert set(m.courses) <= course_names
        assert set(m.competitions) <= comps
        assert set(m.projects) <= projs
        assert set(m.internships) <= interns

    flask_m = next(m for m in mappings if m.skill == "Flask")  # 全越界：剔除并改写 gap_note
    assert flask_m.courses == [] and flask_m.competitions == []
    assert flask_m.projects == [] and flask_m.internships == []
    assert "量子编程导论" in flask_m.gap_note and "自学" in flask_m.gap_note
    django_m = next(m for m in mappings if m.skill == "Django")  # 部分越界：留合法剔自创
    assert django_m.courses == ["Web开发技术"]
    assert "Django Web 开发实战" in django_m.gap_note
    python_m = next(m for m in mappings if m.skill == "Python")
    assert python_m.courses == ["机器学习", "数据挖掘"]


# ---------------------------------------------------------------------------
# (c) ④ make_roadmap：缓存回放 + 确定性修正
# ---------------------------------------------------------------------------


def _run_roadmap(path: str, draft: dict, tmp_path, monkeypatch) -> Roadmap:
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    skills = _chain_skills()
    _prefill_map_cache(skills)
    mappings = asyncio.run(pipeline.map_courses(skills))
    profile = _profile(path=path)
    _prefill_roadmap_cache(profile, skills, mappings, draft)
    return asyncio.run(pipeline.make_roadmap(profile, skills, mappings))


def test_make_roadmap_job_path_structure_and_clamp(tmp_path, monkeypatch):
    roadmap = _run_roadmap("就业", _DRAFT_JOB, tmp_path, monkeypatch)

    terms = [s.term for s in roadmap.semesters]
    assert len(terms) == 8  # 恒 8 学期
    assert terms == ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下"]

    cap = 15 * 6 // 5  # weekly_hours=15 的 1.2 倍（整数运算，与实现一致）
    course_names = _curriculum_names()
    assert all(s.hours_per_week <= cap for s in roadmap.semesters)  # 时长钳制
    assert all(set(s.courses) <= course_names for s in roadmap.semesters)  # 课程全部在库

    sem1 = roadmap.semesters[0]  # 大一上/大一下在"大二上"之前：不排内容只占位
    assert sem1.courses == [] and sem1.actions == [] and sem1.hours_per_week == 0
    assert "不排规划" in sem1.focus

    sem3 = roadmap.semesters[2]  # 大二上（当前）：草稿 99h 钳到 18；错排课程被挪走
    assert sem3.hours_per_week == cap
    assert "数据结构" in sem3.courses and "数据库系统" not in sem3.courses
    assert any("LeetCode" in a for a in sem3.actions)

    sem5 = roadmap.semesters[4]  # 大三上：错排的数据库系统(库 semester=5)/操作系统(=5)落位到此
    assert {"数据库系统", "操作系统", "算法设计与分析"} <= set(sem5.courses)
    sem6 = roadmap.semesters[5]  # 大三下：③映射带入的机器学习(6)/数据挖掘(6)
    assert {"机器学习", "数据挖掘"} <= set(sem6.courses)

    sem7 = roadmap.semesters[6]  # 大四上：就业路线注入秋招
    assert any("秋招" in a for a in sem7.actions)
    assert any("钳制" in r for r in roadmap.risks)  # 超时被钳有留痕


def test_make_roadmap_grad_path_swaps_internship_for_exam(tmp_path, monkeypatch):
    roadmap = _run_roadmap("考研", _DRAFT_GRAD, tmp_path, monkeypatch)

    assert len(roadmap.semesters) == 8
    assert not any("实习" in a for s in roadmap.semesters for a in s.actions)  # 实习让位
    assert any("考研备考启动" in a for a in roadmap.semesters[5].actions)  # 大三下
    assert any("考研冲刺" in a for a in roadmap.semesters[6].actions)  # 大四上（12 月初试）
    assert any("复试" in a for a in roadmap.semesters[7].actions)  # 大四下
    assert any("让位" in r or "备考" in r for r in roadmap.risks)


# ---------------------------------------------------------------------------
# (d) store：档案与路线图存取（DB 一律指向 tmp_path）
# ---------------------------------------------------------------------------


def test_store_profile_and_roadmap_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    p = _profile(name="小赵")
    pid = store.save_profile(p)
    assert store.get_profile("小赵") == p
    assert store.get_profile("查无此人") is None

    p.notes = "想冲大厂"
    assert store.save_profile(p) == pid  # upsert：同名更新同一行
    assert len(list(_rows(tmp_path))) == 1
    assert store.get_profile("小赵").notes == "想冲大厂"

    r = Roadmap(
        profile_summary="x",
        semesters=[SemesterPlan(term="大二上", focus="f", hours_per_week=3)],
    )
    store.save_roadmap("小赵", r)
    assert store.get_roadmap("小赵") == r
    store.save_roadmap("小赵", Roadmap(profile_summary="x2", semesters=[]))
    assert store.get_roadmap("小赵").profile_summary == "x2"  # 取最新一份
    assert store.get_roadmap("查无此人") is None

    try:  # 无档案不允许直接存路线图
        store.save_roadmap("查无此人", r)
        raised = False
    except KeyError:
        raised = True
    assert raised


def _rows(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        yield from conn.execute("SELECT id FROM profiles")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# (e) /api/plan：TestClient + 缓存回放（200 / 503 / GET 取回）
# ---------------------------------------------------------------------------


def test_plan_endpoint_200_full_chain_and_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    for p in _real_postings():
        _prefill_extract_cache(p, _expected_extract(p.id))
    skills = _chain_skills()
    _prefill_map_cache(skills)
    mappings = asyncio.run(pipeline.map_courses(skills))
    profile = _profile()
    _prefill_roadmap_cache(profile, skills, mappings, _DRAFT_JOB)

    with TestClient(server.app) as client:
        resp = client.post("/api/plan", json=profile.model_dump(mode="json"))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["semesters"]) == 8  # 学期数=8
    assert all(s["hours_per_week"] <= 15 * 6 // 5 for s in body["semesters"])  # hours 钳制
    assert all(set(s["courses"]) <= _curriculum_names() for s in body["semesters"])  # 课程全在库

    with TestClient(server.app) as client:  # 已存路线取回：一致；查无此人是 404
        got = client.get(f"/api/plan/{profile.name}")
        assert got.status_code == 200 and got.json() == body
        assert client.get("/api/plan/查无此人").status_code == 404


def test_plan_endpoint_503_when_extract_llm_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    _break_llm_config(monkeypatch)  # 缓存键含 MODEL：先破坏再（不）预填，顺序与运行时一致
    with TestClient(server.app) as client:
        resp = client.post("/api/plan", json=_profile().model_dump(mode="json"))
    assert resp.status_code == 503
    assert "LLM 不可用" in resp.json()["detail"] and ".env" in resp.json()["detail"]


def test_plan_endpoint_503_when_mapping_llm_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    _break_llm_config(monkeypatch)  # ①命中缓存，③未预填走真调用路径 -> 配置错误 -> 503
    for p in _real_postings():
        _prefill_extract_cache(p, _expected_extract(p.id))
    with TestClient(server.app) as client:
        resp = client.post("/api/plan", json=_profile().model_dump(mode="json"))
    assert resp.status_code == 503
    assert "LLM 不可用" in resp.json()["detail"]
