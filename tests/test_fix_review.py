"""评审修复回归测试（缓存回放 + 纯函数，无网络也绿、秒级完成）。

覆盖两份结论的修复项：
  1. 年级规范化（high）：口语学年（大三/大3）-> 规范学期名；非法值 422；API 端到端
  2. 空名默认档名：name 留空 -> 未命名学生，plan/chat 全链路不再 404
  3. ⑤对话多轮 history：请求体带 history 且真正拼进 prompt（缓存键级验证）
  4. ②归并：同名跨类并成一行 + 确定性 SQL 别名
  5. ③映射单批容错；④考研版剔除秋招动作
  6. 数据源 token 检索、DATA_DIR 单源、TERMS 单源、store WAL 并发、ask_text_stream 已删
缓存键一律用 llm._cache_key 复算（prompt 复用 pipeline/agent 的组装函数）。
"""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import server
from career_agent import agent, config, datasource, llm, pipeline, store
from career_agent.datasource import JsonCorpusSource
from career_agent.schemas import (
    TERMS,
    UNNAMED_PROFILE_NAME,
    CourseMapping,
    DialogueTurn,
    ExtractedRequirements,
    JobPosting,
    Roadmap,
    SemesterPlan,
    SkillStat,
    StudentProfile,
)

_TERMS8 = list(TERMS)


# ---------------------------------------------------------------------------
# 素材：语料 / 画像 / 预填缓存（手法与 test_e2e.py 同源）
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
    data = {
        "backend-001": dict(hard_skills=["Python"], tools=["MySQL"]),
        "backend-002": dict(hard_skills=["Python"], tools=["Django"]),
    }
    return ExtractedRequirements(posting_id=posting_id, **data[posting_id])


def _install_corpus(tmp_path, monkeypatch) -> None:
    d = tmp_path / "data" / "postings"
    d.mkdir(parents=True)
    (d / "backend.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in _real_postings()]), encoding="utf-8",
    )
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", d.parent)


def _prefill_extract_cache() -> None:
    for p in _real_postings():
        key = llm._cache_key(
            pipeline.EXTRACT_AGENT_NAME, pipeline.EXTRACT_SYSTEM_PROMPT,
            pipeline._extract_user_prompt(p),
        )
        store.cache_put(key, _expected_extract(p.id).model_dump(mode="json"))


def _prefill_map_cache(skills) -> None:
    top = pipeline._top_skills(skills)
    for i in range(0, len(top), pipeline.MAP_BATCH_SIZE):
        batch = top[i : i + pipeline.MAP_BATCH_SIZE]
        key = llm._cache_key(
            pipeline.MAP_AGENT_NAME, pipeline.MAP_SYSTEM_PROMPT, pipeline._map_user_prompt(batch)
        )
        store.cache_put(key, {"mappings": [{"skill": s.skill} for s in batch]})


def _prefill_roadmap_cache(profile, skills, mappings, draft) -> None:
    key = llm._cache_key(
        pipeline.ROADMAP_AGENT_NAME, pipeline.ROADMAP_SYSTEM_PROMPT,
        pipeline._roadmap_user_prompt(profile, skills, mappings),
    )
    store.cache_put(key, draft)


def _break_llm_config(monkeypatch) -> None:
    """破坏 LLM 配置：任何缓存未命中都会走真调用路径抛配置错误，测试当场失败。"""
    monkeypatch.setattr(config, "MODEL", "openai:x")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")


def _payload(**over) -> dict:
    base = {
        "name": "小陈", "grade": "大二上", "target_role": "后端开发工程师",
        "path": "就业", "skills": ["Python"], "weekly_hours": 15, "notes": "",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. 年级规范化（high）
# ---------------------------------------------------------------------------


def test_grade_normalization_year_to_first_semester():
    assert StudentProfile(**_payload(grade="大三")).grade == "大三上"
    assert StudentProfile(**_payload(grade="大3")).grade == "大三上"
    assert StudentProfile(**_payload(grade="大一")).grade == "大一上"
    assert StudentProfile(**_payload(grade="大三下")).grade == "大三下"  # 规范名原样


def test_grade_unrecognized_rejected_with_clear_message():
    with pytest.raises(ValidationError) as ei:
        StudentProfile(**_payload(grade="研一"))
    assert "无法识别" in str(ei.value) and "大三上" in str(ei.value)


def test_plan_api_grade_year_end_to_end_and_422(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    _break_llm_config(monkeypatch)
    _prefill_extract_cache()
    skills = pipeline.aggregate_skills([_expected_extract(p.id) for p in _real_postings()])
    _prefill_map_cache(skills)
    # ④缓存按“规范化后的 grade=大三上”预填：证明规范化发生在 prompt 组装之前
    profile = StudentProfile(**_payload(grade="大三上"))
    mappings = asyncio.run(pipeline.map_courses(skills))  # 缓存回放，与服务器一致的③产出
    _prefill_roadmap_cache(
        profile, skills, mappings,
        {"profile_summary": "x", "semesters": [
            {"term": "大三上", "focus": "补核心课", "actions": ["刷题"], "hours_per_week": 8}
        ], "risks": []},
    )

    with TestClient(server.app) as client:
        resp = client.post("/api/plan", json=_payload(grade="大三"))
        assert resp.status_code == 200, resp.text[:300]
        body = resp.json()
        assert [s["term"] for s in body["semesters"]] == _TERMS8
        # 前 4 学期必须占位（此前“大三”被静默按大一上排满 8 学期）
        assert all(not s["courses"] and not s["actions"] for s in body["semesters"][:4])
        assert "已修读" in body["semesters"][0]["focus"]
        assert body["semesters"][4]["actions"] == ["刷题"]  # 第 5 学期起才有实质内容
        # 非法年级：422 带明确提示，不再静默错排
        resp_bad = client.post("/api/plan", json=_payload(grade="研一"))
        assert resp_bad.status_code == 422
        assert "无法识别" in resp_bad.text
    assert store.get_profile("小陈").grade == "大三上"  # 规范化后落库


# ---------------------------------------------------------------------------
# 2. 空名默认档名（medium）
# ---------------------------------------------------------------------------


def test_unnamed_profile_gets_default_name():
    assert StudentProfile(**_payload(name="")).name == UNNAMED_PROFILE_NAME
    assert StudentProfile(**_payload(name="  ")).name == UNNAMED_PROFILE_NAME
    assert StudentProfile(**_payload(name=" 陈晓 ")).name == "陈晓"  # 顺带去首尾空格


def test_plan_then_chat_with_unnamed_profile_no_404(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _install_corpus(tmp_path, monkeypatch)
    _break_llm_config(monkeypatch)
    _prefill_extract_cache()
    skills = pipeline.aggregate_skills([_expected_extract(p.id) for p in _real_postings()])
    _prefill_map_cache(skills)
    mappings = asyncio.run(pipeline.map_courses(skills))
    profile = StudentProfile(**_payload(name=""))  # -> 未命名学生
    _prefill_roadmap_cache(
        profile, skills, mappings,
        {"profile_summary": "x", "semesters": [
            {"term": "大二上", "focus": "打基础", "actions": [], "hours_per_week": 5}
        ], "risks": []},
    )
    message = "我现在该主攻什么？"
    stored = StudentProfile(**_payload(name=UNNAMED_PROFILE_NAME))
    roadmap = asyncio.run(pipeline.make_roadmap(profile, skills, mappings))
    sp, up = agent._dialogue_prompts(stored, roadmap, message, [])
    turn = DialogueTurn(reply="先把 Python 与数据库打牢。", action="none", reason="普通咨询")
    store.cache_put(llm._cache_key("dialogue", sp, up), turn.model_dump(mode="json"))

    with TestClient(server.app) as client:
        resp = client.post("/api/plan", json=_payload(name=""))
        assert resp.status_code == 200, resp.text[:300]
        assert store.get_profile(UNNAMED_PROFILE_NAME) is not None
        # 前端 currentProfileName() 兜底值按默认档名寻址：此前恒 404 -> mock 降级
        chat = client.post("/api/chat", json={"profile_name": UNNAMED_PROFILE_NAME, "message": message})
        assert chat.status_code == 200
        assert chat.headers["content-type"].startswith("text/event-stream")
        frames = [json.loads(e[len("data: "):]) for e in chat.text.split("\n\n") if e]
        assert "".join(f["delta"] for f in frames[:-1]) == turn.reply
        assert frames[-1]["turn"]["reply"] == turn.reply


# ---------------------------------------------------------------------------
# 3. ⑤对话多轮 history（medium）
# ---------------------------------------------------------------------------


def test_chat_history_reaches_dialogue_prompt_cache_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _break_llm_config(monkeypatch)
    profile = StudentProfile(**_payload())
    store.save_profile(profile)
    roadmap = Roadmap(profile_summary="s", semesters=[SemesterPlan(term="大二上", focus="f", hours_per_week=1)])
    store.save_roadmap("小陈", roadmap)
    message = "那大二下具体做什么？"
    history = [
        {"role": "user", "content": "我大三了，路线怎么看？"},
        {"role": "assistant", "content": "先看主线与课程落位……"},
    ]
    turn = DialogueTurn(reply="大二下补数据库与项目实战。", action="none", reason="追问细节")
    # 只预填“带 history”的缓存：请求真的把 history 拼进 prompt 才会命中
    sp, up = agent._dialogue_prompts(profile, roadmap, message, history)
    store.cache_put(llm._cache_key("dialogue", sp, up), turn.model_dump(mode="json"))

    with TestClient(server.app) as client:
        ok = client.post("/api/chat", json={"profile_name": "小陈", "message": message, "history": history})
        assert ok.status_code == 200
        frames = [json.loads(e[len("data: "):]) for e in ok.text.split("\n\n") if e]
        assert "".join(f["delta"] for f in frames[:-1]) == turn.reply
        # 同消息不带 history：缓存键不同 -> miss -> 真调用路径 -> 配置错误 -> 503
        miss = client.post("/api/chat", json={"profile_name": "小陈", "message": message})
        assert miss.status_code == 503
        # history 超长（>32）：422 拒绝
        long_hist = [{"role": "user", "content": "q"}] * 33
        too_long = client.post(
            "/api/chat", json={"profile_name": "小陈", "message": message, "history": long_hist}
        )
        assert too_long.status_code == 422


# ---------------------------------------------------------------------------
# 4. ②归并：跨类同名 + 别名（medium）
# ---------------------------------------------------------------------------


def _req(pid, hard=(), tools=(), soft=()) -> ExtractedRequirements:
    return ExtractedRequirements(
        posting_id=pid, hard_skills=list(hard), tools=list(tools), soft_skills=list(soft)
    )


def test_aggregate_skills_same_name_across_categories_merged():
    stats = pipeline.aggregate_skills([
        _req("jd1", hard=["PostgreSQL", "SQL优化", "MySQL"], tools=["MySQL"]),
        _req("jd2", tools=["PostgreSQL", "复杂SQL"]),
        _req("jd3", hard=["Redis"], tools=["PostgreSQL"]),
    ])
    by_skill = {s.skill: s for s in stats}
    pg_rows = [s for s in stats if s.skill == "PostgreSQL"]
    assert len(pg_rows) == 1  # 此前按 (skill, category) 拆成 hard/tool 两行
    pg = by_skill["PostgreSQL"]
    assert pg.frequency == 3  # 提到该技能的 JD 数（3 条语料都提到）
    assert pg.category == "tool"  # 众数：tool 出现 2 次 > hard 1 次
    sql = by_skill["SQL"]
    assert sql.frequency == 2  # SQL优化(jd1) + 复杂SQL(jd2) 并入 SQL
    assert sql.aliases == ["SQL优化", "复杂SQL"]  # 被归并的原名留档（sorted：ASCII 首字母在前）
    mysql = by_skill["MySQL"]
    assert mysql.frequency == 1  # 同一 JD 内跨类出现只计 1 条
    assert mysql.category == "hard"  # 平票取技术属性更强的类


# ---------------------------------------------------------------------------
# 5. ③映射单批容错 + ④考研剔除秋招（medium/low）
# ---------------------------------------------------------------------------


def test_map_courses_single_batch_failure_degrades_not_explodes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    skills = [
        SkillStat(skill=f"s{i}", category="hard", frequency=1, is_core=True) for i in range(20)
    ]
    real_map_batch = pipeline._map_batch

    async def flaky_map_batch(batch):
        if batch[0].skill == "s8":  # 第 2 批（s8~s15）模拟网关错误
            raise RuntimeError("模拟网关 500")
        return await real_map_batch(batch)

    _prefill_map_cache(skills)  # 其余批走缓存回放
    monkeypatch.setattr(pipeline, "_map_batch", flaky_map_batch)
    mappings = asyncio.run(pipeline.map_courses(skills))  # 此前一批失败 -> 整链异常
    got = {m.skill for m in mappings}
    assert got == {f"s{i}" for i in range(8)} | {f"s{i}" for i in range(16, 20)}  # 剩余两批完好


def test_finalize_roadmap_kaoyan_drops_qiuzhao_actions():
    profile = StudentProfile(**_payload(path="考研", grade="大三上"))
    draft = pipeline._RoadmapDraft(
        profile_summary="x",
        semesters=[
            {"term": "大三上", "focus": "补基础", "actions": [
                "9-10 月抽空投递 3~5 家后端岗位秋招（简历用 Django 项目）",  # 评审实测残留的秋招动作
                "日常刷题保持手感",
            ], "hours_per_week": 6},
        ],
        risks=[],
    )
    roadmap = pipeline._finalize_roadmap(profile, draft, [])
    actions = [a for sp in roadmap.semesters for a in sp.actions]
    assert not any("秋招" in a for a in actions), f"考研版仍残留秋招动作: {actions}"
    assert not any("实习" in a for a in actions)
    assert any("日常刷题" in a for a in actions)  # 无关动作不受影响
    assert any("考研备考启动" in a for a in roadmap.semesters[5].actions)  # 确定性注入仍在


# ---------------------------------------------------------------------------
# 6. 数据源 / 单源 / store 并发 / 死代码清理
# ---------------------------------------------------------------------------


def _write_corpus(tmp_path, monkeypatch, rows) -> None:
    d = tmp_path / "postings"
    d.mkdir(parents=True)
    (d / "c.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", tmp_path)


def test_fetch_token_and_recalls_more_than_exact_substring(tmp_path, monkeypatch):
    _write_corpus(tmp_path, monkeypatch, [
        {"id": "a", "title": "Python后端开发工程师", "company": "X", "source": "t",
         "description": "负责服务端接口开发"},
        {"id": "b", "title": "Java后端工程师", "company": "Y", "source": "t",
         "description": "熟悉 Python 与 Django 者优先"},
        {"id": "c", "title": "前端工程师", "company": "Z", "source": "t",
         "description": "Vue/React 单页应用"},
    ])
    src = JsonCorpusSource()
    # 旧逻辑：整串"Python后端"只命中 a（3/54 的根源）；token AND 同时召回 b（Python 在 JD、后端在标题）
    assert {p.id for p in src.fetch("Python后端")} == {"a", "b"}
    # 单词关键词行为与旧逻辑一致：不误伤 c
    assert [p.id for p in src.fetch("前端")] == ["c"]
    assert len(src.fetch("")) == 3  # 空关键词=全量（与旧逻辑一致）


def test_single_source_constants():
    assert datasource.DATA_DIR == config.DATA_DIR  # DATA_DIR 单源在 config
    assert pipeline.TERMS is TERMS  # 学期名单源在 schemas（pipeline 仅引用）


def test_ask_text_stream_removed():
    # 06 手册 §3：绕过缓存的调用口子连同死代码一起删除
    assert not hasattr(llm, "ask_text_stream")


def test_store_concurrent_writes_no_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    store.cache_put("warm", {"n": 0})  # 先建库（顺带把 WAL 落到文件）

    def work(i: int) -> int:
        store.cache_put(f"k{i}", {"n": i})
        store.save_profile(StudentProfile(**_payload(name=f"p{i}")))
        return store.cache_get(f"k{i}")["n"]

    with ThreadPoolExecutor(max_workers=8) as ex:  # 8 线程并发读写：WAL 下不应再有 locked
        results = list(ex.map(work, range(40)))
    assert results == list(range(40))
    assert store.cache_get("k39") == {"n": 39}

    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"
