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

import os
import threading

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

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
