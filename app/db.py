"""SQLite 数据库连接与会话管理"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_PATH

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# SQLite WAL 模式，适合单用户低资源场景
engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    """SQLite 默认不启用外键约束，需手动开启"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    """ORM 模型基类"""


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：获取数据库会话"""
    with SessionLocal() as session:
        yield session


def _ensure_column(engine, table: str, column: str, ddl: str) -> None:
    """轻量迁移：为已有表补充新增列（SQLite ALTER TABLE，幂等）"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _recompute_canonical_keys() -> None:
    """重算所有料号与已匹配 BOM 项的等效键（幂等）。

    规范化规则升级（数值格式统一、封装归一化）后，让存量数据与
    新逻辑保持一致；启动时自动执行，数据量小开销可忽略。
    """
    from app.models import BOMItem, Part
    from app.parsers.part import part_canonical_key

    with SessionLocal() as session:
        changed = 0
        parts = session.execute(select(Part)).scalars().all()
        for p in parts:
            new_key = part_canonical_key(
                p.category.name,
                p.mpn,
                p.value,
                p.value_unit,
                p.package,
                p.tolerance,
                p.voltage,
                p.dielectric,
            )
            if new_key and new_key != p.canonical_key:
                p.canonical_key = new_key
                changed += 1
        # 已匹配 BOM 项同步为对应料号的 key
        items = session.execute(select(BOMItem).where(BOMItem.part_id.is_not(None))).scalars().all()
        for item in items:
            if item.part and item.canonical_key != item.part.canonical_key:
                item.canonical_key = item.part.canonical_key
                changed += 1
        if changed:
            session.commit()


def _ensure_unique_index(table: str, column: str) -> None:
    """为列建唯一索引（容错：存量已有重复值时跳过，仅对后续新数据生效）。"""
    index_name = f"uq_{table}_{column}"
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table}({column})"
            )
        except Exception:  # noqa: BLE001  存量重复 → 跳过，不阻塞启动
            pass


def init_db() -> None:
    """初始化数据库表结构（幂等）"""
    import app.models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    # 历史表补列迁移
    _ensure_column(engine, "parts", "lcsc_code", "VARCHAR(32)")
    _ensure_column(engine, "parts", "aliases", "TEXT")
    # lcsc_code 唯一索引（存量重复时自动跳过；新数据由应用层校验兜底）
    _ensure_unique_index("parts", "lcsc_code")
    # 规范化规则升级后重算存量等效键
    _recompute_canonical_keys()
