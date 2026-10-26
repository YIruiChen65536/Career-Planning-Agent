"""FastAPI 入口：uvicorn server:app --reload。路由层只做协议转换，业务在 career_agent/。"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from career_agent import agent, datasource, pipeline, store
from career_agent.schemas import Roadmap, StudentProfile

app = FastAPI(title="职规 Agent", version="0.1.0")

_NO_KEY_HINT = (
    "未配置 LLM API key：本仓库不附带 key，请自行到 DeepSeek 开放平台（platform.deepseek.com）"
    "或智谱开放平台（open.bigmodel.cn）创建并填入 .env；填好前页面会自动使用内置演示数据。"
)


def _llm_configured() -> bool:
    """只判断配置存在性（读 env 不发网络请求），用于无 key 时给用户明确引导而非含糊 503。"""
    from career_agent import config

    if config.MODEL.startswith("zai:"):
        return bool(config.ZAI_API_KEY)
    if config.MODEL.startswith("deepseek:"):
        return bool(config.DEEPSEEK_API_KEY)
    if config.MODEL.startswith("openai:"):
        return bool(config.OPENAI_BASE_URL and config.OPENAI_API_KEY)
    return False


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_configured": _llm_configured()}


@app.get("/api/analyze/{keyword}")
async def analyze(keyword: str, limit: int = Query(default=10, ge=1, le=50)) -> dict:
    """①+②：某岗位方向的 JD 列表 + 技能频次表（LLM 配置缺失/网关不可达时 503）。"""
    # 文件 IO（读语料 JSON）走线程池：async 端点内联同步 IO 会阻塞 event loop
    postings = await asyncio.to_thread(datasource.get_source().fetch, keyword, limit)
    reqs_or_none, errors = await pipeline.extract_all(postings)
    reqs = [r for r in reqs_or_none if r is not None]
    if postings and not reqs:
        # 一条都没抽出来且带错误：无 key 给明确引导（引导用演示模式），有 key 才是 503 真故障
        if not _llm_configured():
            raise HTTPException(status_code=503, detail=_NO_KEY_HINT)
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
    postings = await asyncio.to_thread(datasource.get_source().fetch, profile.target_role, 10)
    reqs_or_none, errors = await pipeline.extract_all(postings)
    reqs = [r for r in reqs_or_none if r is not None]
    if postings and not reqs:
        # 与 /api/analyze 同口径：无 key 给引导，有 key 才 503
        if not _llm_configured():
            raise HTTPException(status_code=503, detail=_NO_KEY_HINT)
        detail = errors[0][:200] if errors else "未知错误"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）")
    skills = pipeline.aggregate_skills(reqs)
    try:
        mappings = await pipeline.map_courses(skills)
        roadmap = await pipeline.make_roadmap(profile, skills, mappings)
    except HTTPException:
        raise
    except Exception as exc:  # ③④的 LLM 调用失败（配置缺失/网关不可达），沿用 analyze 的 503 口径
        if not _llm_configured():
            raise HTTPException(status_code=503, detail=_NO_KEY_HINT) from exc
        detail = f"{type(exc).__name__}: {str(exc)[:150]}"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）") from exc
    # sqlite 写同样走线程池：不阻塞 event loop（/api/chat 的 SSE 回放与其并发时尤其重要）
    await asyncio.to_thread(store.save_profile, profile)
    await asyncio.to_thread(store.save_roadmap, profile.name, roadmap)
    return roadmap


@app.get("/api/plan/{name}")
def get_plan(name: str) -> Roadmap:
    """取回已存路线图（该学生最近一次 POST /api/plan 的结果）。"""
    roadmap = store.get_roadmap(name)
    if roadmap is None:
        raise HTTPException(status_code=404, detail=f"学生 {name} 暂无已存路线图，请先 POST /api/plan 生成")
    return roadmap


class ChatMessage(BaseModel):
    """⑤ 的单条历史消息（前端回传多轮上下文，角色限定学生/顾问两侧）。"""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """⑤ 的请求体：按档案名寻址学生（画像与路线图已随 POST /api/plan 落库）。

    history 为近期对话上下文（[{role, content}]，不含本轮 message）——服务端
    此前写死 history=[]，第二轮提问完全失忆；不传则视为全新对话（向后兼容）。"""

    profile_name: str
    message: str
    history: list[ChatMessage] = Field(default_factory=list, max_length=32)


_CHAT_DELTA_CHARS = 24  # 每帧增量字符数：run_dialogue 是结构化整段产出（带缓存），此处只做分帧流式回放


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """⑤：对话调整——画像 + 已存路线做上下文，run_dialogue 出 DialogueTurn，SSE 流式回放。"""
    profile = await asyncio.to_thread(store.get_profile, req.profile_name)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"学生 {req.profile_name} 暂无档案，请先在首页表单提交画像（POST /api/plan）",
        )
    roadmap = await asyncio.to_thread(store.get_roadmap, req.profile_name)
    if roadmap is None:
        raise HTTPException(
            status_code=404, detail=f"学生 {req.profile_name} 暂无已存路线图，请先 POST /api/plan 生成"
        )
    try:
        turn = await agent.run_dialogue(
            profile, roadmap, req.message, history=[m.model_dump() for m in req.history]
        )
    except Exception as exc:  # LLM 配置缺失/网关不可达，与 /api/analyze 同口径
        if not _llm_configured():
            raise HTTPException(status_code=503, detail=_NO_KEY_HINT) from exc
        detail = f"{type(exc).__name__}: {str(exc)[:150]}"
        raise HTTPException(status_code=503, detail=f"LLM 不可用：请检查 .env 配置（{detail}）") from exc

    async def _sse() -> AsyncIterator[str]:
        for i in range(0, len(turn.reply), _CHAT_DELTA_CHARS):
            chunk = json.dumps({"delta": turn.reply[i : i + _CHAT_DELTA_CHARS]}, ensure_ascii=False)
            yield f"data: {chunk}\n\n"
        yield f"data: {json.dumps({'turn': turn.model_dump(mode='json')}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


# 前端静态挂载：必须放在所有路由注册之后——FastAPI 按注册顺序匹配，先注册的 /api/* 与
# /health 优先命中，此处兜底 "/" 才不会遮住它们；frontend/ 不存在时整个挂载跳过（纯 API 模式）
_frontend_dir = Path(__file__).parent / "frontend"
if (_frontend_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
