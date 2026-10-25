"""岗位数据源统一接口（ADR-0002）。下游只认 list[JobPosting]，不关心数据从哪来。"""

import json
from pathlib import Path
from typing import Protocol

from .schemas import JobPosting

DATA_DIR = Path(__file__).parent.parent / "data"


class PostingSource(Protocol):
    """所有数据源的统一接口。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]: ...


class JsonCorpusSource:
    """默认实现：读 data/postings/*.json（小组手动收集的真实 JD）。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]:
        postings: list[JobPosting] = []
        for path in sorted((DATA_DIR / "postings").glob("*.json")):
            for raw in json.loads(path.read_text(encoding="utf-8")):
                if keyword in raw.get("title", "") or keyword in raw.get("description", ""):
                    postings.append(JobPosting.model_validate(raw))
                    if len(postings) >= limit:
                        return postings
        return postings


class CrawlerSource:
    """占位：确定目标网站后用 requests 脚本实现同一接口（ADR-0002）。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]:
        raise NotImplementedError("爬虫数据源待接入，流水线无需任何改动")


class ApiSource:
    """占位：接入外部招聘数据库/ API 时实现同一接口。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]:
        raise NotImplementedError("外部 API 数据源待接入")


def get_source() -> PostingSource:
    """换数据源只改这一行。"""
    return JsonCorpusSource()
