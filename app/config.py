"""BOMatch 应用配置"""

import os
import secrets
from pathlib import Path

# 项目根目录与本地数据目录（数据库、密钥等，已被 .gitignore 忽略）
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 允许通过环境变量覆盖数据库路径（测试用），默认 data/bomatch.db
DATABASE_PATH = Path(os.environ.get("BOMATCH_DB_PATH", str(DATA_DIR / "bomatch.db")))

SECRET_KEY_PATH = DATA_DIR / "secret_key"


def _load_or_create_secret() -> str:
    """优先取环境变量 BOMATCH_SECRET_KEY，否则从本地密钥文件加载/生成"""
    env_key = os.environ.get("BOMATCH_SECRET_KEY")
    if env_key:
        return env_key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key, encoding="utf-8")
    return key


SECRET_KEY = _load_or_create_secret()

# 生产环境（Caddy HTTPS 反代）建议设置 BOMATCH_COOKIE_SECURE=1
COOKIE_SECURE = os.environ.get("BOMATCH_COOKIE_SECURE", "0") == "1"
