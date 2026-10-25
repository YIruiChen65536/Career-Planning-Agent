"""SQLite：学生档案 / 历史方案 / LLM 结果缓存（演示断网回放的根基）。

LLM 缓存（cache_key/cache_get/cache_put）+ 档案与历史方案存取（M3）。
roadmaps 表按 profile_id 关联 profiles，对外接口一律用 name 寻址。
"""

import hashlib
import json
import sqlite3

from . import config
from .schemas import Roadmap, StudentProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    output TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, data TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS roadmaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL, data TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _conn() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15)  # timeout：多进程共写（演示+验收并行）时等待锁而非立刻报错
    conn.executescript(_SCHEMA)
    return conn


def cache_key(call: str, payload) -> str:
    raw = json.dumps({"call": call, "payload": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_get(key: str):
    with _conn() as conn:
        row = conn.execute("SELECT output FROM llm_cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(key: str, output) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache(key, output) VALUES(?, ?)",
            (key, json.dumps(output, ensure_ascii=False)),
        )


def save_profile(profile: StudentProfile) -> int:
    """档案 upsert：按 name 查重，存在则更新 data，否则插入；返回档案行 id。"""
    data = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)
    with _conn() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE name=?", (profile.name,)).fetchone()
        if row:  # upsert：同名档案更新而非再插一行（updated_at 手动刷新，列默认值只在 INSERT 生效）
            conn.execute(
                "UPDATE profiles SET data=?, updated_at=datetime('now') WHERE id=?",
                (data, row[0]),
            )
            return row[0]
        cur = conn.execute("INSERT INTO profiles(name, data) VALUES(?, ?)", (profile.name, data))
        return int(cur.lastrowid)


def get_profile(name: str) -> StudentProfile | None:
    """按 name 取最新档案（理论上 name 唯一，ORDER BY 兜底取最新）；无则 None。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT data FROM profiles WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
    return StudentProfile.model_validate(json.loads(row[0])) if row else None


def save_roadmap(name: str, roadmap: Roadmap) -> int:
    """给学生追加一份历史路线图（按 name 关联档案，档案须先 save_profile）；返回路线图行 id。"""
    data = json.dumps(roadmap.model_dump(mode="json"), ensure_ascii=False)
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM profiles WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        if not row:
            raise KeyError(f"学生 {name!r} 无档案，请先 save_profile 建立档案")
        cur = conn.execute("INSERT INTO roadmaps(profile_id, data) VALUES(?, ?)", (row[0], data))
        return int(cur.lastrowid)


def get_roadmap(name: str) -> Roadmap | None:
    """取该学生最近一次保存的路线图；无档案或无路线图则 None。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT r.data FROM roadmaps r JOIN profiles p ON r.profile_id = p.id "
            "WHERE p.name=? ORDER BY r.id DESC LIMIT 1",
            (name,),
        ).fetchone()
    return Roadmap.model_validate(json.loads(row[0])) if row else None
