"""内置基础数据（首次运行时写入）"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Category

DEFAULT_CATEGORIES = [
    "电阻",
    "电容",
    "电感",
    "二极管",
    "三极管",
    "IC",
    "连接器",
    "其他",
]


def seed_categories() -> None:
    """写入内置类别（幂等）"""
    with SessionLocal() as session:
        existing = set(session.execute(select(Category.name)).scalars())
        for index, name in enumerate(DEFAULT_CATEGORIES):
            if name not in existing:
                session.add(Category(name=name, sort_order=index))
        session.commit()
