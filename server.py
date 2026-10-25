"""FastAPI 入口：uvicorn server:app --reload。路由层只做协议转换，业务在 career_agent/。"""

from fastapi import FastAPI

from career_agent import datasource, pipeline, store
from career_agent.schemas import ExtractedRequirements, Roadmap, SkillStat, StudentProfile

app = FastAPI(title="职规 Agent", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/analyze/{keyword}")
async def analyze(keyword: str, limit: int = 50) -> list[SkillStat]:
    """①+②：某岗位方向的技能频次表（M2）。"""
    postings = datasource.get_source().fetch(keyword, limit)
    reqs = [await pipeline.extract_requirements(p) for p in postings]
    return pipeline.aggregate_skills(reqs)


@app.post("/api/plan")
async def plan(profile: StudentProfile) -> Roadmap:
    """③+④：画像 -> 分学期路线图（M3）。"""
    raise NotImplementedError("M3")


@app.post("/api/chat")
async def chat(message: str) -> dict:
    """⑤：对话调整，SSE 流式（M4）。"""
    raise NotImplementedError("M4")
