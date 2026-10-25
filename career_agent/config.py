"""全局配置：.env 读取。禁止在别处直接读环境变量。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # 项目根 .env

# 模型串，如 deepseek:deepseek-chat 或 zai:glm-4-flash；切换厂商只改 .env
MODEL: str = os.getenv("CAREER_MODEL", "deepseek:deepseek-chat")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "")

# 任意 OpenAI Chat Completions 兼容网关（本地测试网关/自建代理等），模型串用 openai:模型名
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

DB_PATH: Path = Path(os.getenv("DB_PATH", "db/career.db"))
DATA_DIR: Path = Path(__file__).parent.parent / "data"

# 多 Agent 链的硬上限（06 手册 §3：写死在代码里，不靠提示词收敛）
MAX_DEBATE_ROUNDS: int = 2
