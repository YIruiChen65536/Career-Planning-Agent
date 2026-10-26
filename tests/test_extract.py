"""M1 抽取链路测试：全部走缓存回放/异常注入，无网络也绿、秒级完成（LLM 纪律）。"""

import asyncio
import json

from fastapi.testclient import TestClient

import server
from career_agent import config, llm, pipeline, store
from career_agent.schemas import ExtractedRequirements, JobPosting


def _posting(pid: str, title: str, description: str) -> JobPosting:
    return JobPosting(
        id=pid, title=title, company="某科技公司", source="test",
        url=f"https://example.com/{pid}", description=description,
    )


def _expected(pid: str) -> ExtractedRequirements:
    """与 _CORPUS 中 pid 对应的期望抽取结果（人为约定，仅用于缓存回放断言）。"""
    data = {
        "api-1": dict(
            hard_skills=["Python"], tools=["FastAPI", "MySQL"], soft_skills=[],
            education="本科及以上", experience_years=3.0,
            project_requirements=["有高并发项目经验"], extras=["高并发项目经验优先"],
        ),
        "api-2": dict(
            hard_skills=["Python"], tools=["Django", "Git"], soft_skills=["沟通能力"],
            education="", experience_years=None, project_requirements=[], extras=[],
        ),
    }
    return ExtractedRequirements(posting_id=pid, **data[pid])


def _corpus() -> list[JobPosting]:
    return [
        _posting("api-1", "Python后端开发工程师",
                 "熟悉 Python、FastAPI、MySQL；本科及以上；3年以上开发经验；有高并发项目经验优先。"),
        _posting("api-2", "Python 后端",
                 "熟悉 Python、Django，会用 Git，具备良好的沟通能力。"),
    ]


def _prefill_cache(posting: JobPosting, expected: ExtractedRequirements) -> None:
    """用 llm._cache_key 算键并预填缓存，让 extract_requirements 离线回放（不真调 LLM）。"""
    key = llm._cache_key(
        pipeline.EXTRACT_AGENT_NAME,
        pipeline.EXTRACT_SYSTEM_PROMPT,
        pipeline._extract_user_prompt(posting),
    )
    store.cache_put(key, expected.model_dump(mode="json"))


def _break_llm_config(monkeypatch) -> None:
    """把 LLM 配置破坏掉：缓存未命中走真调用路径时，get_model 直接抛配置错误。"""
    monkeypatch.setattr(config, "MODEL", "openai:x")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")


def _make_corpus_dir(tmp_path):
    """在临时目录造一份 data/postings 语料，供 /api/analyze 读取。"""
    data_dir = tmp_path / "data"
    (data_dir / "postings").mkdir(parents=True)
    (data_dir / "postings" / "backend.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in _corpus()]), encoding="utf-8",
    )
    return data_dir


# ---------- (a) extract_requirements：缓存回放 ----------


def test_extract_requirements_cache_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    posting = _corpus()[0]
    expected = _expected("api-1")
    _prefill_cache(posting, expected)
    got = asyncio.run(pipeline.extract_requirements(posting))
    assert got == expected
    assert got.posting_id == posting.id  # ID 确定性覆盖，不信任模型抄写


def test_extract_all_partial_failure_returns_none_and_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _break_llm_config(monkeypatch)  # 先破坏配置再预填：缓存键含 MODEL，顺序必须一致
    p1, p2 = _corpus()
    _prefill_cache(p1, _expected("api-1"))  # p1 命缓存；p2 未预填 -> 真调用路径抛配置错误
    reqs, errors = asyncio.run(pipeline.extract_all([p1, p2], concurrency=2))
    assert reqs[0] == _expected("api-1")
    assert reqs[1] is None
    assert len(errors) == 1 and errors[0].startswith("api-2")


def test_extract_all_all_fail_still_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    _break_llm_config(monkeypatch)
    reqs, errors = asyncio.run(pipeline.extract_all(_corpus(), concurrency=4))
    assert reqs == [None, None] and len(errors) == 2  # 不炸整体，错误逐条收集


# ---------- (b) /api/analyze：TestClient + 缓存回放 ----------


def test_analyze_endpoint_200_with_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", _make_corpus_dir(tmp_path))
    for p in _corpus():
        _prefill_cache(p, _expected(p.id))
    with TestClient(server.app) as client:
        resp = client.get("/api/analyze/Python", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["postings"]) == 2
    assert {p["id"] for p in body["postings"]} == {"api-1", "api-2"}
    skills = body["skills"]
    assert skills, "技能频次表不应为空"
    for s in skills:
        assert {"skill", "category", "frequency", "is_core"} <= set(s)
    python = next(s for s in skills if s["skill"] == "Python")
    assert python["frequency"] == 2 and python["is_core"] is True  # 2/2 >= 30%


def test_analyze_endpoint_503_when_llm_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", _make_corpus_dir(tmp_path))
    _break_llm_config(monkeypatch)  # 不预填缓存：全部走真调用路径 -> 配置错误
    with TestClient(server.app) as client:
        resp = client.get("/api/analyze/Python")
    assert resp.status_code == 503
    assert resp.json()["detail"].endswith(".env 配置（未知错误）") or "未配置 LLM API key" in resp.json()["detail"]


def test_analyze_endpoint_limit_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", _make_corpus_dir(tmp_path))
    with TestClient(server.app) as client:
        assert client.get("/api/analyze/Python", params={"limit": 100}).status_code == 422
        assert client.get("/api/analyze/Python", params={"limit": 0}).status_code == 422
