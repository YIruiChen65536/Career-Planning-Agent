"""M5 收尾联调 e2e：TestClient 全链路（缓存回放，无网络也绿、秒级完成）。

链路：/health -> /api/analyze（①②）-> /api/plan（①~④，恒 8 学期）-> /api/chat（⑤ SSE）。
LLM 结果全部预填缓存（键用 llm._cache_key 复算，prompt 复用 pipeline/agent 的组装函数），
并先破坏 LLM 配置——任何缓存未命中都会走真调用路径抛配置错误，让测试当场失败。
另覆盖 /api/chat 404/503 分支与前端静态挂载（"/" 不遮住 /api 与 /health）。
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from career_agent import agent, config, llm, pipeline, store
from career_agent.schemas import (
    DialogueTurn,
    ExtractedRequirements,
    JobPosting,
    Roadmap,
    StudentProfile,
)

_TERMS8 = ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下"]


# ---------------------------------------------------------------------------
# 真实语料（data/ 只读）：backend-01/02 各 1 条，title 含"后端开发工程师"
# ---------------------------------------------------------------------------


def _real_postings() -> list[JobPosting]:
    postings_dir = Path(config.DATA_DIR) / "postings"
    out: list[JobPosting] = []
    for fname in ("backend-01.json", "backend-02.json"):
        out.extend(
            JobPosting.model_validate(raw)
            for raw in json.loads((postings_dir / fname).read_text(encoding="utf-8"))
        )
    return out


def _expected_extract(posting_id: str) -> ExtractedRequirements:
    """与 test_plan.py 同源的期望抽取结果（人为约定，供缓存回放）。"""
    data = {
        "backend-001": dict(
            hard_skills=["Python", "数据结构与算法"], tools=["Flask", "MySQL"],
            soft_skills=["团队协作"], education="本科及以上", experience_years=1.0,
            project_requirements=[], extras=[],
        ),
        "backend-002": dict(
            hard_skills=["Python"], tools=["Django", "MySQL"],
            soft_skills=["沟通能力"], education="本科及以上", experience_years=None,
            project_requirements=[], extras=[],
        ),
    }
    return ExtractedRequirements(posting_id=posting_id, **data[posting_id])


def _profile() -> StudentProfile:
    return StudentProfile(
        name="小陈", grade="大二上", target_role="后端开发工程师", path="就业",
        skills=["Python", "MySQL"], weekly_hours=15,
    )


_DRAFT = {  # ④的 LLM 草稿（缓存回放用）：只给部分学期，8 学期结构由代码确定性补齐
    "profile_summary": "e2e·大二上·后端开发工程师·就业向，每周可投入 15h",
    "semesters": [
        {"term": "大二上", "focus": "Web 基础与刷题", "courses": [], "actions": ["LeetCode 刷题 100 题"],
         "milestone": "完成 100 题", "hours_per_week": 10},
        {"term": "大三上", "focus": "核心课深化", "courses": [], "actions": [], "milestone": "", "hours_per_week": 8},
    ],
    "risks": ["e2e 预填风险"],
}

_MESSAGE = "我想转考研，不找工作了，帮我调整路线"
_TURN = DialogueTurn(
    reply="好的，把路线从就业切到考研：先巩固数学与 408 相关课程，大三下启动系统复习，实习让位给备考。",
    action="replan",
    reason="学生明确表示从就业转向考研，需要重新规划",
)


# ---------------------------------------------------------------------------
# 预填缓存（键一律用 llm._cache_key 复算，不重写算法）
# ---------------------------------------------------------------------------


def _prefill_extract_cache(posting: JobPosting, expected: ExtractedRequirements) -> None:
    key = llm._cache_key(
        pipeline.EXTRACT_AGENT_NAME, pipeline.EXTRACT_SYSTEM_PROMPT,
        pipeline._extract_user_prompt(posting),
    )
    store.cache_put(key, expected.model_dump(mode="json"))


def _prefill_map_cache(skills) -> None:
    """按 pipeline 同款分批预填③缓存：e2e 只验协议链路，映射给最小合法值（全空列表）。"""
    for i in range(0, len(skills), pipeline.MAP_BATCH_SIZE):
        batch = skills[i : i + pipeline.MAP_BATCH_SIZE]
        key = llm._cache_key(
            pipeline.MAP_AGENT_NAME, pipeline.MAP_SYSTEM_PROMPT,
            pipeline._map_user_prompt(batch),
        )
        store.cache_put(
            key,
            {"mappings": [{"skill": s.skill} for s in batch]},  # 其余字段全走默认空值
        )


def _prefill_roadmap_cache(profile, skills, mappings) -> None:
    key = llm._cache_key(
        pipeline.ROADMAP_AGENT_NAME, pipeline.ROADMAP_SYSTEM_PROMPT,
        pipeline._roadmap_user_prompt(profile, skills, mappings),
    )
    store.cache_put(key, _DRAFT)


def _prefill_dialogue_cache(profile, roadmap) -> None:
    system_prompt, user_prompt = agent._dialogue_prompts(profile, roadmap, _MESSAGE, [])
    key = llm._cache_key("dialogue", system_prompt, user_prompt)
    store.cache_put(key, _TURN.model_dump(mode="json"))


def _break_llm_config(monkeypatch) -> None:
    """破坏 LLM 配置：先破坏再预填（缓存键含 MODEL，顺序与运行时一致），证明全程零真调用。"""
    monkeypatch.setattr(config, "MODEL", "openai:x")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")


def _install_corpus(tmp_path, monkeypatch) -> None:
    d = tmp_path / "data" / "postings"
    d.mkdir(parents=True)
    (d / "backend.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in _real_postings()]), encoding="utf-8",
    )
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", d.parent)


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 响应体解析成 payload 列表：每个事件必须是单行 `data: {JSON}`。"""
    frames = []
    for event in text.split("\n\n"):
        if not event:
            continue
        assert event.startswith("data: "), f"SSE 事件格式错误: {event[:60]!r}"
        frames.append(json.loads(event[len("data: "):]))
    return frames


# ---------------------------------------------------------------------------
# (a) 全链路：/health -> /api/analyze -> /api/plan -> /api/chat（SSE）
# ---------------------------------------------------------------------------


def test_e2e_full_chain_cache_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    _break_llm_config(monkeypatch)  # 全程"断网"：任何缓存未命中都会 503/报错，测试当场失败

    postings = _real_postings()
    for p in postings:
        _prefill_extract_cache(p, _expected_extract(p.id))
    skills = pipeline.aggregate_skills([_expected_extract(p.id) for p in postings])
    _prefill_map_cache(pipeline._top_skills(skills))
    mappings = asyncio.run(pipeline.map_courses(skills))  # 缓存回放，拿到与服务器一致的③产出
    profile = _profile()
    _prefill_roadmap_cache(profile, skills, mappings)
    roadmap = asyncio.run(pipeline.make_roadmap(profile, skills, mappings))  # 同上，④产出
    _prefill_dialogue_cache(profile, roadmap)

    with TestClient(server.app) as client:
        # 0. 健康检查
        assert client.get("/health").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}

        # 1. 岗位分析（①②）：语料 2 条全部命中抽取缓存，技能频次表非空
        resp = client.get("/api/analyze/后端开发工程师", params={"limit": 12})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["postings"]) == 2
        assert {p["id"] for p in body["postings"]} == {"backend-001", "backend-002"}
        assert body["skills"] and not body["errors"]
        python = next(s for s in body["skills"] if s["skill"] == "Python")
        assert python["frequency"] == 2 and python["is_core"] is True

        # 2. 规划（①~④）：200 且恒 8 学期，画像与路线图已落库
        resp = client.post("/api/plan", json=profile.model_dump(mode="json"))
        assert resp.status_code == 200
        plan = resp.json()
        assert [s["term"] for s in plan["semesters"]] == _TERMS8
        assert resp.json() == store.get_roadmap(profile.name).model_dump(mode="json")

        # 3. 对话（⑤）：SSE 媒体类型 + data: 帧格式（增量帧 + 终帧）
        resp = client.post(
            "/api/chat", json={"profile_name": profile.name, "message": _MESSAGE}
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = _parse_sse(resp.text)
        assert len(frames) >= 3  # 至少 2 个增量帧 + 1 个终帧（reply 远长于单帧 24 字符）
        deltas = frames[:-1]
        assert all(set(f) == {"delta"} and isinstance(f["delta"], str) for f in deltas)
        assert "".join(f["delta"] for f in deltas) == _TURN.reply  # 增量拼接还原全文
        assert frames[-1] == {"turn": _TURN.model_dump(mode="json")}  # 终帧带完整 DialogueTurn
        turn = DialogueTurn.model_validate(frames[-1]["turn"])
        assert turn.action == "replan"  # "我想转考研"识别为改目标


# ---------------------------------------------------------------------------
# (b) /api/chat 分支：404（无档案）与 503（LLM 不可用）
# ---------------------------------------------------------------------------


def test_chat_404_when_profile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    with TestClient(server.app) as client:
        resp = client.post("/api/chat", json={"profile_name": "查无此人", "message": "你好"})
    assert resp.status_code == 404
    assert "暂无档案" in resp.json()["detail"] and "查无此人" in resp.json()["detail"]


def test_chat_404_when_roadmap_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    store.save_profile(_profile())  # 有档案但从未生成路线图
    with TestClient(server.app) as client:
        resp = client.post("/api/chat", json={"profile_name": "小陈", "message": "你好"})
    assert resp.status_code == 404
    assert "暂无已存路线图" in resp.json()["detail"]


def test_chat_503_when_llm_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _break_llm_config(monkeypatch)  # 对话缓存未预填 -> 真调用路径抛配置错误 -> 503
    store.save_profile(_profile())
    store.save_roadmap("小陈", Roadmap(profile_summary="s", semesters=[]))
    with TestClient(server.app) as client:
        resp = client.post("/api/chat", json={"profile_name": "小陈", "message": "在吗"})
    assert resp.status_code == 503
    assert "LLM 不可用" in resp.json()["detail"] and ".env" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# (c) 前端静态挂载："/" 出 index.html，且不遮住 /api 与 /health
# ---------------------------------------------------------------------------


def test_frontend_mount_serves_index_without_shadowing_api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    frontend = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    if not frontend.exists():  # 挂载本身是条件性的：无 frontend/ 时跳过（纯 API 模式）
        pytest.skip("frontend/index.html 不存在，静态挂载未启用")
    with TestClient(server.app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "职规" in resp.text  # index.html 标题即服务出来的正文
        assert client.get("/health").status_code == 200  # 挂载不遮 API
        assert client.get("/api/plan/查无此人").status_code == 404  # 走路由而非静态 404 页
