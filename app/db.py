"""SQLite 数据库连接与会话管理"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
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


def init_db() -> None:
    """初始化数据库表结构（幂等）"""
    import app.models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    # 历史表补列迁移
    _ensure_column(engine, "parts", "lcsc_code", "VARCHAR(32)")
