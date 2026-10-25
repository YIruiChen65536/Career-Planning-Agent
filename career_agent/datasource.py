"""岗位数据源统一接口（ADR-0002）。下游只认 list[JobPosting]，不关心数据从哪来。"""

import json
import re
from typing import Protocol

from . import config
from .schemas import JobPosting

# 单一来源在 config.DATA_DIR；此处保留模块属性供测试 monkeypatch（历史耦合点，勿删）
DATA_DIR = config.DATA_DIR


def _keyword_tokens(keyword: str) -> list[str]:
    """检索关键词按语言切段："Python后端" -> ["Python", "后端"]（空串 -> 空列表）。"""
    return re.findall(r"[A-Za-z0-9+#.]+|[\u4e00-\u9fff]+", keyword)


class PostingSource(Protocol):
    """所有数据源的统一接口。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]: ...


class JsonCorpusSource:
    """默认实现：读 data/postings/*.json（小组手动收集的真实 JD）。"""

    def fetch(self, keyword: str, limit: int = 50) -> list[JobPosting]:
        """按关键词检索语料：整串子串命中或全部 token（语言切段）同时命中。

        此前只做整串子串匹配，"Python后端" 这类细分岗位名只能命中 JD 原文里
        逐字出现该连写的少数几条（实测 3/54）；token 全命中是整串命中的超集，
        单词关键词（如"后端"）行为与旧逻辑完全一致。"""
        tokens = _keyword_tokens(keyword)
        postings: list[JobPosting] = []
        for path in sorted((DATA_DIR / "postings").glob("*.json")):
            for raw in json.loads(path.read_text(encoding="utf-8")):
                hay = f"{raw.get('title', '')}\n{raw.get('description', '')}"
                hit = all(t in hay for t in tokens) if tokens else True
                if hit:
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
