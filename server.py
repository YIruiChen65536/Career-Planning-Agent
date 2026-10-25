"""FastAPI 入口：uvicorn server:app --reload。路由层只做协议转换，业务在 career_agent/。"""

from fastapi import FastAPI, HTTPException, Query

from career_agent import datasource, pipeline
from career_agent.schemas import Roadmap, StudentProfile

app = FastAPI(title="职规 Agent", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/analyze/{keyword}")
async def analyze(keyword: str, limit: int = Query(default=10, ge=1, le=50)) -> dict:
    """①+②：某岗位方向的 JD 列表 + 技能频次表（LLM 配置缺失/网关不可达时 503）。"""
    postings = datasource.get_source().fetch(keyword, limit)
    reqs_or_none, errors = await pipeline.extract_all(postings)
    reqs = [r for r in reqs_or_none if r is not None]
    if postings and not reqs:
        # 一条都没抽出来且带错误：基本等于 LLM 缺配置或网关不可达，按 503 透出而非空结果误导前端
        detail = errors[0][:200] if errors else "未知错误"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）")
    skills = pipeline.aggregate_skills(reqs)
    return {
        "postings": [p.model_dump(mode="json") for p in postings],
        "skills": [s.model_dump(mode="json") for s in skills],
        "errors": errors,
    }


@app.post("/api/plan")
async def plan(profile: StudentProfile) -> Roadmap:
    """③+④：画像 -> 分学期路线图（M3）。"""
    raise NotImplementedError("M3")


@app.post("/api/chat")
async def chat(message: str) -> dict:
    """⑤：对话调整，SSE 流式（M4）。"""
    raise NotImplementedError("M4")
