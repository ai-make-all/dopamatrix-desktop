"""
src/api/database.py
———————————————————
SQLAlchemy 数据库配置层 — 多租户动态物理隔离架构。

每个租户（由请求头 X-Local-User 标识）拥有独立的 SQLite 文件：
  data/dopamatrix_<tenant_id>.db

Engine 实例按租户缓存，避免重复创建；线程锁保证并发安全。

此外，提供全局共享数据库 clipflow.db 的路径常量，供 app_settings
等跨租户表使用（通过原生 sqlite3 直连，不经过 ORM 层）。
"""

import json
import logging
import os
import sqlite3
import threading

from fastapi import Request
from sqlalchemy import create_engine, event, inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# 全局 SQLite WAL 模式拦截器                                            #
# 绑定在 Engine 类级别，所有动态创建的租户 Engine 均自动继承此配置。       #
# ------------------------------------------------------------------ #
@event.listens_for(Engine, "connect")
def _set_sqlite_wal_pragma(dbapi_connection, connection_record):
    """对每条新建的 SQLite 连接启用 WAL 模式及性能优化 PRAGMA。"""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-10000")
    cursor.close()

# ------------------------------------------------------------------ #
# 确保数据存放目录存在                                                   #
# ------------------------------------------------------------------ #
os.makedirs("data", exist_ok=True)

# ------------------------------------------------------------------ #
# 全局共享数据库（app_settings 等非租户数据存储于此）                     #
# main.py 中 `from src.api.database import engine, Base` 依赖此变量。  #
# ------------------------------------------------------------------ #
SETTINGS_DB_PATH = "clipflow.db"

# 全局默认 Engine（向后兼容，供 main.py 的 Base.metadata.create_all 使用）
engine = create_engine(
    f"sqlite:///./{SETTINGS_DB_PATH}",
    connect_args={"check_same_thread": False},
)


class Base(DeclarativeBase):
    """所有 ORM 模型的统一基类。"""
    pass


# ------------------------------------------------------------------ #
# Schema 自愈引擎                                                       #
# ------------------------------------------------------------------ #
def _sqlite_ddl_type(column) -> str:
    """将 SQLAlchemy 列类型映射为 SQLite DDL 类型字符串。"""
    from sqlalchemy import JSON, String, Text, Integer, Float, Boolean, DateTime
    type_map = [
        (JSON,     "TEXT"),
        (Boolean,  "INTEGER"),
        (Integer,  "INTEGER"),
        (Float,    "REAL"),
        (DateTime, "DATETIME"),
        (String,   "TEXT"),
        (Text,     "TEXT"),
    ]
    for sa_type, ddl_type in type_map:
        if isinstance(column.type, sa_type):
            return ddl_type
    return "TEXT"


def _sqlite_ddl_default(column) -> str | None:
    """提取列的 Python 侧默认值并序列化为 SQLite DEFAULT 子句字面量。"""
    if column.default is None:
        return None
    arg = column.default.arg
    value = arg() if callable(arg) else arg
    if isinstance(value, (list, dict)):
        return f"'{json.dumps(value, ensure_ascii=False)}'"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if value is None:
        return "NULL"
    return str(value)


def evolve_schema(engine) -> None:
    """
    自愈式 Schema 迁移：对比模型定义与物理表结构，自动 ALTER TABLE 补齐缺失列。

    - 只追加列，不删除 / 修改已有列（幂等、安全）。
    - 针对 SQLite 将 JSON 类型映射为 TEXT，并正确序列化默认值。
    - 迁移失败时仅记录错误日志，不抛出异常，确保主程序正常启动。
    """
    try:
        inspector = sa_inspect(engine)
        existing_tables = set(inspector.get_table_names())

        from .models import Base as ModelBase

        with engine.begin() as conn:
            for table_name, table in ModelBase.metadata.tables.items():
                if table_name not in existing_tables:
                    continue  # 全新表由 create_all 负责建立

                existing_cols = {
                    col["name"] for col in inspector.get_columns(table_name)
                }

                for column in table.columns:
                    if column.name in existing_cols:
                        continue

                    ddl_type    = _sqlite_ddl_type(column)
                    ddl_default = _sqlite_ddl_default(column)
                    ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {ddl_type}'
                    if ddl_default is not None:
                        ddl += f" DEFAULT {ddl_default}"

                    conn.execute(text(ddl))
                    logger.info(
                        "[evolve_schema] 已为表 '%s' 补齐列 '%s' (%s, DEFAULT %s)",
                        table_name, column.name, ddl_type, ddl_default,
                    )

    except Exception:
        logger.error(
            "[evolve_schema] Schema 自愈失败，跳过迁移，主程序不受影响。",
            exc_info=True,
        )


# ------------------------------------------------------------------ #
# 多租户 Engine 缓存                                                    #
# ------------------------------------------------------------------ #
_tenant_engines: dict = {}
_engine_lock = threading.Lock()


def get_tenant_engine(tenant_id: str):
    """根据 tenant_id 动态获取或创建专属数据库 Engine。"""
    tenant_id = tenant_id or "default"
    # 防止目录穿越攻击：只保留字母数字、下划线、连字符
    safe_tenant_id = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-"))
    if not safe_tenant_id:
        safe_tenant_id = "default"

    with _engine_lock:
        if safe_tenant_id not in _tenant_engines:
            db_path = f"sqlite:///./data/dopamatrix_{safe_tenant_id}.db"
            engine = create_engine(db_path, connect_args={"check_same_thread": False})

            # 延迟导入 Base 避免循环依赖，并为新租户自动建表
            from .models import Base as ModelBase
            ModelBase.metadata.create_all(bind=engine)
            evolve_schema(engine)  # 自愈迁移：补齐老库中缺失的新增列

            _tenant_engines[safe_tenant_id] = engine

        return _tenant_engines[safe_tenant_id]


# ------------------------------------------------------------------ #
# FastAPI 依赖注入 — 拦截请求头，分发专属 Session                        #
# ------------------------------------------------------------------ #
def get_db(request: Request):
    """
    Yield 一个与当前租户绑定的 DB Session，请求结束后自动关闭。
    用法：在路由函数中 `db: Session = Depends(get_db)`
    """
    tenant_id = request.headers.get("X-Local-User", "default")
    engine = get_tenant_engine(tenant_id)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
