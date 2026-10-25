"""产品闭环旅程测试（真调用版）：像明天就要上台演示的团队一样走完整用户流程。

不是测代码，是测产品：每一步都是演示现场会真实发生的动作，latency 均为
真实服务器（uvicorn 真进程、127.0.0.1:8020 真端口）实测毫秒。

默认 skip，保证全量 pytest 无网络也绿。真跑方式（Git Bash，工作目录=项目根）：

    # 1) 起服务（必须项目根，data/ 与 db/ 相对路径才正确）：
    .venv/Scripts/python.exe -m uvicorn server:app --port 8020
    # 2) 跑旅程：
    CAREER_LIVE=1 .venv/Scripts/python.exe -m pytest tests/test_journey.py -q -s

旅程（按定义顺序执行，共享 STATE；LLM 允许真调用，单调用 2~60s 属预期）：
  1   /health 就绪探测
  2   GET  /api/analyze/后端?limit=8            ①② 首次计时 + 技能频次直觉检查
  3   POST /api/plan  大三·Python后端·就业 20h   ③④ 冷缓存计时 + 8学期/起点/时长/课程/动作检查
  4   POST /api/chat  “我决定改成考研了，路线怎么变？”  ⑤ SSE 帧格式 + replan 识别
  5   POST /api/plan  同画像改 path=考研         条件变更重排，与 3 对比差异
  5b  POST /api/plan  大三上（规范年级）          隔离验证“从当前学期起”契约
  6   缓存证明：重复步骤 2 与步骤 3 的同一请求     二跑应显著快于首跑
  7   打印 JOURNEY 摘要（step/latencyMs/ok/note）
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

# ---------------------------------------------------------------------------
# 开关与常量：CAREER_LIVE=1 才真跑；否则整文件 skip（无网络也绿）
# ---------------------------------------------------------------------------

LIVE = os.getenv("CAREER_LIVE") == "1"
BASE_URL = os.getenv("CAREER_BASE_URL", "http://127.0.0.1:8020")

pytestmark = pytest.mark.skipif(
    not LIVE, reason="旅程测试需真实服务器与真 LLM 调用：先起 uvicorn :8020 再设 CAREER_LIVE=1"
)

TERMS8 = ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下"]

# 任务指定的演示画像（grade 故意用用户口头常说的“大三”：契约层已做规范化，
# “大三”会被映射为“大三上”=第 5 学期，前 4 学期占位——本步同时端到端验证该规范化）
PROFILE_JOB = {
    "name": "林小满",
    "grade": "大三",
    "target_role": "Python后端",
    "path": "就业",
    "skills": ["Python", "SQL基础"],
    "weekly_hours": 20,
    "notes": "喜欢动手写代码，目标是大厂后端",
}
PROFILE_KAOYAN = {**PROFILE_JOB, "path": "考研"}
PROFILE_CANONICAL = {**PROFILE_JOB, "name": "李源", "grade": "大三上"}  # 对照组：规范年级输入

CHAT_MESSAGE = "我决定改成考研了，路线怎么变？"

# 培养方案 / 机会库（与产品同源文件、独立读取——黑盒校验不借用产品代码）
_DATA = Path(__file__).resolve().parent.parent / "data"
_CURRICULUM = json.loads((_DATA / "curriculum.json").read_text(encoding="utf-8"))
_OPPORTUNITIES = json.loads((_DATA / "opportunities.json").read_text(encoding="utf-8"))
COURSE_SEM = {c["name"]: c["semester"] for c in _CURRICULUM["courses"]}  # 课程 -> 培养方案学期(1..8)
LIB_NAMES = (
    [c["name"] for c in _OPPORTUNITIES["competitions"]]
    + [p["name"] for p in _OPPORTUNITIES["projects"]]
    + [r for it in _OPPORTUNITIES["internships"] for r in it["typical_roles"] + [it["stage"]]]
)

# 对口度软检查的关键词（Python 后端方向）
_TOPIC_KEYWORDS = (
    "python", "sql", "mysql", "redis", "web", "后端", "接口", "api", "数据库", "算法",
    "系统", "网络", "linux", "git", "django", "flask", "项目", "刷题", "部署", "docker",
)

JOURNEY: list[dict] = []  # (step, latencyMs, ok, note) 逐步记录
STATE: dict = {}  # 跨步骤共享：计时与路线图


def _record(step: str, latency_ms: int, ok: bool, note: str) -> None:
    JOURNEY.append({"step": step, "latencyMs": latency_ms, "ok": ok, "note": note})


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 响应体解析成 payload 列表：每个事件必须是单行 `data: {JSON}`。"""
    frames = []
    for event in text.split("\n\n"):
        if not event:
            continue
        assert event.startswith("data: "), f"SSE 事件格式错误: {event[:60]!r}"
        frames.append(json.loads(event[len("data: "):]))
    return frames


@pytest.fixture(scope="module")
def client():
    """真服务器真端口：读超时放宽到 240s（真 LLM 单调用可达 60s+，慢是预期不是失败）。"""
    with httpx.Client(
        base_url=BASE_URL, timeout=httpx.Timeout(connect=10, read=240, write=30, pool=240)
    ) as c:
        yield c


def _request(client: httpx.Client, method: str, path: str, *, json_body=None, params=None):
    """发请求并计时（毫秒）；偶发 500/传输错误重试一次——store 已改 WAL+连接显式关闭，
    "database is locked" 应不再出现，重试仅作兜底钉住回归（再出现即说明修复回退）。"""
    for attempt in (1, 2):
        t0 = time.perf_counter()
        try:
            resp = client.request(method, path, json=json_body, params=params)
        except httpx.TransportError:
            if attempt == 1:
                time.sleep(1.0)
                continue
            raise
        ms = round((time.perf_counter() - t0) * 1000)
        if resp.status_code == 500 and attempt == 1:
            _record(f"retry {method} {path}", ms, False, "偶发 500（疑似 database is locked），按约定重试一次")
            time.sleep(1.0)
            continue
        return resp, ms
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# 1 /health 就绪探测
# ---------------------------------------------------------------------------


def test_01_health_ready(client):
    waited = 0.0
    while waited < 40:
        try:
            resp = client.get("/health")
            if resp.status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.5)
        waited += 0.5
    t0 = time.perf_counter()
    resp = client.get("/health")
    ms = round((time.perf_counter() - t0) * 1000)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    _record("1 GET /health 就绪探测", ms, True, f"就绪等待 {waited:.0f}s 后单次探测耗时；body={{status:ok}}")


# ---------------------------------------------------------------------------
# 2 GET /api/analyze/后端（limit=8）：①抽取 + ②频次统计
# ---------------------------------------------------------------------------


def test_02_analyze_backend_first(client):
    resp, ms = _request(client, "GET", "/api/analyze/后端", params={"limit": 8})
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()

    assert len(body["postings"]) == 8, f"postings 数量应为 limit=8，实际 {len(body['postings'])}"
    assert body["errors"] == [], f"抽取错误: {body['errors'][:2]}"
    skills = body["skills"]
    assert skills, "技能频次表为空"

    by_skill = {s["skill"]: s for s in skills}
    py = by_skill.get("Python")
    assert py, "后端语料技能表里没有 Python"
    assert py["frequency"] >= 3, f"Python 频次直觉上应高频，实际 {py['frequency']}/8"
    assert py["is_core"] is True

    sql_like = [s for s in skills if "sql" in s["skill"].lower()]
    assert sql_like, "没有任何 SQL 系技能（SQL/MySQL…）"
    assert max(s["frequency"] for s in sql_like) >= 3, "SQL 系技能应高频"

    # is_core 与频次一致性（产品契约：出现率 >= 30% 判核心，pandas 确定性计算）
    for s in skills:
        assert s["is_core"] == (s["frequency"] / 8 >= 0.3), f"is_core 与频次不符: {s}"

    top5 = sorted(skills, key=lambda s: -s["frequency"])[:5]
    note = (
        "top技能: " + ", ".join(f"{s['skill']}×{s['frequency']}" for s in top5)
        + f"；Python {py['frequency']}/8 core；"
        + "SQL系 " + "/".join(f"{s['skill']}×{s['frequency']}" for s in sql_like)
        + f"；postings=8 errors=0（语料抽取已被预热脚本写入缓存，本步为缓存回放耗时）"
    )
    STATE["t_analyze_1st"] = ms
    _record("2 GET /api/analyze/后端 limit=8 首次", ms, True, note)


# ---------------------------------------------------------------------------
# 3 POST /api/plan：大三·Python后端·就业·每周20h（任务指定画像）
# ---------------------------------------------------------------------------


def test_03_plan_job_first(client):
    resp, ms = _request(client, "POST", "/api/plan", json_body=PROFILE_JOB)
    assert resp.status_code == 200, resp.text[:300]
    roadmap = resp.json()
    STATE["t_plan_1st"] = ms
    STATE["roadmap_job"] = roadmap

    assert [sp["term"] for sp in roadmap["semesters"]] == TERMS8, "必须恒 8 学期"

    issues = []
    # (a) 从当前学期起：年级“大三”经契约规范化为第 5 学期（大三上），前 4 学期必须占位
    #     （修复回归钉：此前“大三”被静默按大一上排满 8 学期）
    early = [sp["term"] for sp in roadmap["semesters"][:4] if sp["courses"] or sp["actions"]]
    assert not early, f"年级“大三”未按第5学期排：前4学期被排入课程/行动 {early}"
    starts_ok = True

    # (b) 时长：单学期 hours_per_week 不得超过 20×1.2=24（代码钳制契约），同时记录合计
    cap = 24
    hours = [sp["hours_per_week"] for sp in roadmap["semesters"]]
    over = [sp["term"] for sp in roadmap["semesters"] if sp["hours_per_week"] > cap]
    assert not over, f"hours_per_week 超过 {cap}h 上限: {over}"

    # (c) 课程与培养方案一致：逐字在库内，且落在培养方案规定的学期（课程落位由代码拍板）
    for sp in roadmap["semesters"]:
        sem_idx = TERMS8.index(sp["term"]) + 1
        for c in sp["courses"]:
            assert c in COURSE_SEM, f"课程不在培养方案: {c}"
            assert COURSE_SEM[c] == sem_idx, f"课程学期错位: {c}（培养方案第{COURSE_SEM[c]}学期）被排进 {sp['term']}"

    # (d) 竞赛/实习动作真实可执行（软检查：动作中出现的专名应来自机会库）
    actions = [a for sp in roadmap["semesters"] for a in sp["actions"]]
    lib_mentions = [a for a in actions if any(n in a for n in LIB_NAMES)]
    if actions and len(lib_mentions) < 2:
        issues.append(f"动作中可对应到机会库专名的过少（{len(lib_mentions)}/{len(actions)}）")

    # (e) 内容对口（软检查：活跃学期应命中后端方向关键词）
    active = [sp for sp in roadmap["semesters"] if "已修读" not in sp["focus"]]
    on_topic = [
        sp
        for sp in active
        if any(k in (sp["focus"] + " ".join(sp["courses"]) + " ".join(sp["actions"])).lower() for k in _TOPIC_KEYWORDS)
    ]
    ratio = len(on_topic) / max(len(active), 1)
    if ratio < 0.6:
        issues.append(f"内容对口度偏低：{len(on_topic)}/{len(active)} 学期命中后端关键词")

    ok = not issues
    note = (
        f"8学期✓ 单学期时长≤{cap}h✓（8学期合计 {sum(hours)}h）课程在库且落位✓ "
        f"动作{len(actions)}条（机会库专名{len(lib_mentions)}处） 对口{len(on_topic)}/{len(active)} "
        + ("从当前学期起✓" if starts_ok else "从当前学期起✗（大三被当成大一上排满8学期）")
    )
    if issues:
        note += "；问题: " + "；".join(issues)
    _record("3 POST /api/plan 大三·Python后端·就业", ms, ok, note)


# ---------------------------------------------------------------------------
# 4 POST /api/chat：“我决定改成考研了，路线怎么变？”（SSE）
# ---------------------------------------------------------------------------


def test_04_chat_replan(client):
    resp, ms = _request(
        client, "POST", "/api/chat", json_body={"profile_name": PROFILE_JOB["name"], "message": CHAT_MESSAGE}
    )
    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers["content-type"].startswith("text/event-stream"), resp.headers["content-type"]

    frames = _parse_sse(resp.text)
    assert len(frames) >= 2, "SSE 至少应有增量帧 + 终帧"
    deltas = frames[:-1]
    assert all(set(f) == {"delta"} and isinstance(f["delta"], str) for f in deltas), "增量帧格式错误"
    turn = frames[-1]["turn"]
    assert set(frames[-1]) == {"turn"}, "终帧应为完整 DialogueTurn"
    assert "".join(f["delta"] for f in deltas) == turn["reply"], "增量帧拼接应还原完整回复"

    assert turn["action"] == "replan", f"改考研消息应识别为 replan，实际 {turn['action']}（{turn['reason']}）"
    assert "考研" in turn["reply"] and len(turn["reply"]) >= 30, "回复应有实质内容"

    _record(
        "4 POST /api/chat 改考研问路线", ms, True,
        f"action={turn['action']}（{turn['reason'][:40]}）；SSE {len(frames)} 帧，回复 {len(turn['reply'])} 字：{turn['reply'][:60]}…",
    )


# ---------------------------------------------------------------------------
# 5 POST /api/plan：同画像改 path=考研（条件变更重排）
# ---------------------------------------------------------------------------


def test_05_replan_kaoyan(client):
    resp, ms = _request(client, "POST", "/api/plan", json_body=PROFILE_KAOYAN)
    assert resp.status_code == 200, resp.text[:300]
    ky = resp.json()
    assert [sp["term"] for sp in ky["semesters"]] == TERMS8

    job = STATE["roadmap_job"]
    acts_job = {a for sp in job["semesters"] for a in sp["actions"]}
    acts_ky = {a for sp in ky["semesters"] for a in sp["actions"]}

    # 考研备考动作必须出现（代码确定性注入，不依赖 LLM 自觉）
    joined = "；".join(acts_ky)
    assert "考研备考启动" in joined, "考研版应出现“考研备考启动”动作"
    assert "初试" in joined, "考研版应有 12 月初试冲刺相关动作"
    # 实习让位：考研版不得再含“实习”动作
    intern_left = [a for a in acts_ky if "实习" in a]
    assert not intern_left, f"考研版仍残留实习动作: {intern_left}"

    removed = acts_job - acts_ky
    added = acts_ky - acts_job
    intern_removed = sorted(a for a in removed if "实习" in a)
    # 秋招让位（修复回归钉：path=考研 的确定性特化剔除含“秋招”的动作）
    qiucao_left = [a for a in acts_ky if "秋招" in a]
    assert not qiucao_left, f"考研版仍残留秋招动作: {qiucao_left}"
    qiucao_gone = True

    issues = []
    if not intern_removed:
        issues.append("就业版路线图本就不含实习动作——“实习让位”在两版对比中不可见")

    ok = not issues and len(removed) >= 2 and len(added) >= 2
    note = (
        f"动作差异：就业版独有 {len(removed)} 条、考研版新增 {len(added)} 条。"
        f"让位的实习动作: {'；'.join(intern_removed)[:80] or '无'}。"
        f"新增样例: {'；'.join(sorted(added))[:110]}。"
        f"考研注入(备考启动/初试/复试)✓ 秋招让位{'✓' if qiucao_gone else '✗'}"
    )
    if issues:
        note += "；问题: " + "；".join(issues)
    _record("5 POST /api/plan 同画像改考研重排", ms, ok, note)


# ---------------------------------------------------------------------------
# 5b 对照组：规范年级“大三上”应从第 5 学期起排（隔离定位 3 的问题归属）
# ---------------------------------------------------------------------------


def test_05b_plan_canonical_grade(client):
    resp, ms = _request(client, "POST", "/api/plan", json_body=PROFILE_CANONICAL)
    assert resp.status_code == 200, resp.text[:300]
    sem = resp.json()["semesters"]
    assert [sp["term"] for sp in sem] == TERMS8

    assert all(
        "已修读" in sp["focus"] and not sp["courses"] and not sp["actions"] and sp["hours_per_week"] == 0
        for sp in sem[:4]
    ), "大三上之前（第1~4学期）应为‘已修读阶段’占位"
    active = sem[4:]
    with_content = [sp for sp in active if sp["courses"] or sp["actions"]]
    assert len(with_content) >= 3, f"第5学期起应有实质内容，仅 {len(with_content)} 个学期有排程"

    _record(
        "5b POST /api/plan 大三上(规范)·就业 对照", ms, True,
        f"前4学期占位✓ 第5学期起 {len(with_content)}/4 个学期有排程——"
        "对照说明步骤3的起点问题只发生在“大三”这类非规范年级输入上",
    )


# ---------------------------------------------------------------------------
# 6 缓存证明：重复步骤 2 与步骤 3 的同一请求，计时对比
# ---------------------------------------------------------------------------


def test_06_cache_proof(client):
    resp_a, ms_a2 = _request(client, "GET", "/api/analyze/后端", params={"limit": 8})
    assert resp_a.status_code == 200
    resp_p, ms_p2 = _request(client, "POST", "/api/plan", json_body=PROFILE_JOB)
    assert resp_p.status_code == 200
    assert [sp["term"] for sp in resp_p.json()["semesters"]] == TERMS8

    t_p1 = STATE.get("t_plan_1st", 0)
    assert ms_p2 < max(8000, t_p1), (
        f"plan 二跑 {ms_p2}ms 未显著低于首跑 {t_p1}ms——缓存命中失效，演示防翻车机制不成立"
    )
    t_a1 = STATE.get("t_analyze_1st", 0)
    drop_p = (1 - ms_p2 / t_p1) * 100 if t_p1 else 0
    ok = ms_p2 < t_p1
    note = (
        f"plan: 首跑 {t_p1}ms → 二跑 {ms_p2}ms（降 {drop_p:.0f}%，首跑含④路线图真调用、二跑全缓存回放）；"
        f"analyze: 首跑 {t_a1}ms → 二跑 {ms_a2}ms（该请求语料抽取已被演示预热脚本提前写缓存，"
        "两跑均命中、无冷热差——冷热差以 plan 对照为准）"
    )
    _record("6 缓存证明：重复步骤2/3同请求", ms_p2, ok, note)


# ---------------------------------------------------------------------------
# 7 打印旅程摘要（-s 可见；供验收记录直接引用）
# ---------------------------------------------------------------------------


def test_07_print_journey():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n===== JOURNEY 摘要（step / latencyMs / ok / note）=====")
    print(json.dumps(JOURNEY, ensure_ascii=False, indent=2))
    print("===== END JOURNEY =====")
    assert len(JOURNEY) >= 7, "旅程应至少记录 7 步"
