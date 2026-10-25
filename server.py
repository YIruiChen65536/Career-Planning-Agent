"""FastAPI 入口：uvicorn server:app --reload。路由层只做协议转换，业务在 career_agent/。"""

from fastapi import FastAPI, HTTPException, Query

from career_agent import datasource, pipeline, store
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
    """①→④ 全链路：画像 -> 按 target_role 检索语料 -> 抽取/归并 -> 课程映射 -> 分学期路线图，落库后返回。"""
    postings = datasource.get_source().fetch(profile.target_role, 10)
    reqs_or_none, errors = await pipeline.extract_all(postings)
    reqs = [r for r in reqs_or_none if r is not None]
    if postings and not reqs:
        # 与 /api/analyze 同口径：语料在而一条都没抽出来 = LLM 缺配置/网关不可达，503 而非空路线图误导前端
        detail = errors[0][:200] if errors else "未知错误"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）")
    skills = pipeline.aggregate_skills(reqs)
    try:
        mappings = await pipeline.map_courses(skills)
        roadmap = await pipeline.make_roadmap(profile, skills, mappings)
    except HTTPException:
        raise
    except Exception as exc:  # ③④的 LLM 调用失败（配置缺失/网关不可达），沿用 analyze 的 503 口径
        detail = f"{type(exc).__name__}: {str(exc)[:150]}"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）") from exc
    store.save_profile(profile)
    store.save_roadmap(profile.name, roadmap)
    return roadmap


@app.get("/api/plan/{name}")
def get_plan(name: str) -> Roadmap:
    """取回已存路线图（该学生最近一次 POST /api/plan 的结果）。"""
    roadmap = store.get_roadmap(name)
    if roadmap is None:
        raise HTTPException(status_code=404, detail=f"学生 {name} 暂无已存路线图，请先 POST /api/plan 生成")
    return roadmap


@app.post("/api/chat")
async def chat(message: str) -> dict:
    """⑤：对话调整，SSE 流式（M4）。"""
    raise NotImplementedError("M4")
