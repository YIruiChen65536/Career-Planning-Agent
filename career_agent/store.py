"""SQLite：学生档案 / 历史方案 / LLM 结果缓存（演示断网回放的根基）。

M1 任务：先实现 LLM 缓存（按调用名+输入的哈希存取 JSON）；
M3 任务：档案与历史方案的存取。
"""

import hashlib
import json
import sqlite3

from . import config

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
