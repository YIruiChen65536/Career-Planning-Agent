"""演示前缓存预热（真调用，结果落 SQLite 缓存——断网回放的根基）。

用法：.venv/Scripts/python.exe scripts/warm_cache.py
  1. 对 data/postings 全量 JD 跑①抽取（并发 4）；
  2. 对样例画像跑与 POST /api/plan 完全同参的链路（fetch(10)→①②③④），预热③④缓存；
  3. 立即重跑同一链路验证全缓存回放的耗时（应秒级）。
无 LLM 配置时打印中文提示并以 0 退出（预热是可选动作，不该当报错吓人）。
"""

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根入 sys.path，任意 cwd 可跑
if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台/管道默认 GBK，中文统计统一走 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from career_agent import config, datasource, llm, pipeline  # noqa: E402
from career_agent.schemas import JobPosting, StudentProfile  # noqa: E402

SAMPLE_PROFILE = StudentProfile(
    name="演示样例", grade="大二上", target_role="后端开发工程师", path="就业",
    skills=["Python", "MySQL"], weekly_hours=15,
)


def _cache_rows() -> int:
    """当前 llm_cache 条数（产品库 db/career.db，预热属产品行为，允许真写）。"""
    if not config.DB_PATH.exists():
        return 0
    with sqlite3.connect(config.DB_PATH) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0])


def _all_postings() -> list[JobPosting]:
    """data/postings 全量读取（不做关键词过滤：全量抽取是演示时任意关键词检索的超集）。"""
    postings: list[JobPosting] = []
    for path in sorted((config.DATA_DIR / "postings").glob("*.json")):
        postings.extend(
            JobPosting.model_validate(raw) for raw in json.loads(path.read_text(encoding="utf-8"))
        )
    return postings


async def _plan_chain(profile: StudentProfile) -> tuple[int, int, int, int, list[str]]:
    """与 POST /api/plan 完全同参的链路：同 fetch 条数/limit，保证演示时缓存键逐字命中。"""
    postings = datasource.get_source().fetch(profile.target_role, 10)
    reqs_or_none, errors = await pipeline.extract_all(postings)
    reqs = [r for r in reqs_or_none if r is not None]
    skills = pipeline.aggregate_skills(reqs)
    mappings = await pipeline.map_courses(skills)
    roadmap = await pipeline.make_roadmap(profile, skills, mappings)
    return len(postings), len(skills), len(mappings), len(roadmap.semesters), errors


async def main() -> int:
    # 配置预检：get_model 只构造不联网，缺 key/网关串格式错误在这里就地拦下
    try:
        llm.get_model()
    except Exception as exc:
        print(f"[跳过] LLM 未配置或配置不可用（{type(exc).__name__}: {exc}）")
        print("       请在 .env 填写 CAREER_MODEL 及对应 key/网关地址后重跑；本次未写入任何缓存。")
        return 0

    t_start = time.perf_counter()
    rows_before = _cache_rows()
    print(f"[配置] 模型 {config.MODEL}｜缓存库 {config.DB_PATH}（现有 {rows_before} 条）")

    # ① 全量抽取：data/postings 所有 JD，并发 4
    postings = _all_postings()
    print(f"[①抽取] data/postings 全量 {len(postings)} 条，并发 4（未命中才真调用，慢是预期）...")
    t = time.perf_counter()
    reqs, errors = await pipeline.extract_all(postings, concurrency=4)
    ok = sum(1 for r in reqs if r is not None)
    print(f"[①抽取] 完成：成功 {ok}/{len(postings)}，失败 {len(errors)}，耗时 {time.perf_counter() - t:.1f}s")
    for e in errors[:5]:
        print(f"        失败样例: {e[:160]}")

    # ③④ 样例画像规划链路（与 /api/plan 同参），跑两遍对比真调用 vs 缓存回放
    p = SAMPLE_PROFILE
    print(f"[③④规划] 样例画像 {p.name}（{p.grade}·{p.target_role}·{p.path}·每周 {p.weekly_hours}h）")
    t = time.perf_counter()
    n_post, n_skills, n_map, n_sem, errs = await _plan_chain(p)
    t_first = time.perf_counter() - t
    print(
        f"[③④规划] 首跑：语料 {n_post} 条 -> 技能 {n_skills} 个 -> 映射 {n_map} 条 -> "
        f"{n_sem} 学期路线图，耗时 {t_first:.1f}s（错误 {len(errs)}）"
    )

    t = time.perf_counter()
    await _plan_chain(p)
    t_replay = time.perf_counter() - t
    print(
        f"[③④规划] 二跑：全缓存回放耗时 {t_replay:.2f}s（首跑的 {t_replay / t_first * 100:.0f}%）"
        "——断网演示即此速度"
    )

    rows_after = _cache_rows()
    print(
        f"[统计] 缓存 {rows_before} -> {rows_after} 条（新增 {rows_after - rows_before}），"
        f"总耗时 {time.perf_counter() - t_start:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
