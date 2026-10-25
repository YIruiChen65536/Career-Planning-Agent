"""自检：契约与数据源在无 LLM 依赖下可用（06 手册§4：合并前提是 pytest 绿）。"""

import json

from career_agent.datasource import JsonCorpusSource, get_source
from career_agent.pipeline import aggregate_skills
from career_agent.schemas import ExtractedRequirements, JobPosting


def _req(pid: str, hard: list[str], tools: list[str] | None = None) -> ExtractedRequirements:
    return ExtractedRequirements(
        posting_id=pid, hard_skills=hard, tools=tools or [], soft_skills=[]
    )


def test_aggregate_skills_counts_and_core_flag():
    stats = aggregate_skills(
        [_req("a", ["Java", "MySQL"]), _req("b", ["Java"]), _req("c", ["Java"]), _req("d", ["Go"])]
    )
    java = next(s for s in stats if s.skill == "Java")
    assert java.frequency == 3 and java.is_core is True  # 3/4 >= 30%
    go = next(s for s in stats if s.skill == "Go")
    assert go.frequency == 1 and go.is_core is False


def test_json_corpus_source_reads_postings(tmp_path, monkeypatch):
    d = tmp_path / "postings"
    d.mkdir()
    (d / "backend.json").write_text(
        json.dumps([
            {"id": "1", "title": "Java后端", "company": "X", "source": "boss",
             "url": "https://example.com/1", "description": "会Java和Spring"}
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr("career_agent.datasource.DATA_DIR", tmp_path)
    src = JsonCorpusSource()
    got = src.fetch("Java")
    assert len(got) == 1 and isinstance(got[0], JobPosting) and got[0].url


def test_default_source_is_json_corpus():
    assert isinstance(get_source(), JsonCorpusSource)
