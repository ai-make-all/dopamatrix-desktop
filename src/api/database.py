"""
src/api/database.py
———————————————————
SQLAlchemy 数据库配置层。
- 默认使用 SQLite（本地优先），DB 文件落在项目根目录。
- 通过 DATABASE_URL 环境变量可无缝切换至 PostgreSQL。
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ------------------------------------------------------------------ #
# 连接 URL — 优先读取环境变量，默认为本地 SQLite                         #
# ------------------------------------------------------------------ #
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./clipflow.db",
)

# SQLite 专属: check_same_thread=False 允许 FastAPI 在多线程中复用连接
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,          # 生产环境关闭 SQL 回显；调试时改为 True
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的统一基类。"""
    pass


# ------------------------------------------------------------------ #
# FastAPI 依赖注入 — 获取数据库会话                                      #
# ------------------------------------------------------------------ #
def get_db():
    """
    Yield 一个 DB Session，请求结束后自动关闭。
    用法：在路由函数中 `db: Session = Depends(get_db)`
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
