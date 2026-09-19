"""
src/api/settings_router.py
———————————————————————————
BYOK（Bring Your Own Key）设置接口。

将用户通过前端配置的第三方 API Key 持久化到 SQLite app_settings 表，
避免任何敏感凭证出现在文件系统或环境变量中。

路由：
  GET  /api/v1/settings/llm  — 读取脱敏后的 LLM API Key（仅暴露首尾字符）
  POST /api/v1/settings/llm  — 写入 / 更新 LLM API Key

数据库：dopamatrix.db（全局共享，非租户隔离）
表结构：app_settings (key_name TEXT PRIMARY KEY, key_value TEXT)
"""

import sqlite3
from contextlib import contextmanager
from typing import Generator

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from .delivery_output import get_delivery_root, save_delivery_root
from .runtime_paths import get_runtime_paths
from src.services.llm_provider import invalidate_api_key_cache

router = APIRouter(prefix="/settings", tags=["Settings"])

# ── 键名常量 ─────────────────────────────────────────────────────────
_KEY_OPENAI = "openai_api_key"


# ================================================================== #
# 数据库连接管理                                                        #
# ================================================================== #

@contextmanager
def _settings_conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield 一个到全局 dopamatrix.db 的 sqlite3 连接。
    使用 contextmanager 确保连接在函数退出（含异常路径）时始终关闭。
    """
    conn = sqlite3.connect(get_runtime_paths().settings_db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 确保表存在（幂等，应用首次启动或升级均安全）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(key_name TEXT PRIMARY KEY, key_value TEXT);"
        )
        conn.commit()
        yield conn
    finally:
        conn.close()


# ================================================================== #
# 辅助工具                                                              #
# ================================================================== #

def _mask_key(key: str) -> str:
    """
    对 API Key 做脱敏掩码，只暴露首 5 位和末 4 位。
    示例：sk-abcdefg1234  →  sk-ab...1234
    """
    if len(key) <= 9:
        return "****"
    return key[:5] + "..." + key[-4:]


# ================================================================== #
# Pydantic Schema                                                      #
# ================================================================== #

class LLMKeyPayload(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("api_key 不能为空字符串。")
        return v


class LLMKeyResponse(BaseModel):
    api_key: str          # 脱敏后的值，或空字符串（表示未配置）
    is_configured: bool


class DeliveryRootPayload(BaseModel):
    delivery_root: str = ""


class DeliveryRootResponse(BaseModel):
    delivery_root: str
    is_configured: bool


# ================================================================== #
# 路由实现                                                              #
# ================================================================== #

@router.get(
    "/llm",
    response_model=LLMKeyResponse,
    summary="读取 LLM API Key（脱敏）",
)
def get_llm_key() -> LLMKeyResponse:
    """
    返回已存储的 LLM API Key 的脱敏版本（如 `sk-ab...1234`）。
    若尚未配置，返回 `api_key: ""` 且 `is_configured: false`。
    """
    try:
        with _settings_conn() as conn:
            row = conn.execute(
                "SELECT key_value FROM app_settings WHERE key_name = ?;",
                (_KEY_OPENAI,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取设置失败：{exc}",
        ) from exc

    if row is None or not row["key_value"]:
        return LLMKeyResponse(api_key="", is_configured=False)

    return LLMKeyResponse(api_key=_mask_key(row["key_value"]), is_configured=True)


@router.post(
    "/llm",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="保存 LLM API Key",
)
def save_llm_key(payload: LLMKeyPayload) -> dict:
    """
    将前端传入的 LLM API Key 以 `INSERT OR REPLACE` 写入 app_settings。
    不返回 Key 明文；写入成功返回 `{"status": "ok"}`。
    """
    try:
        with _settings_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key_name, key_value) VALUES (?, ?);",
                (_KEY_OPENAI, payload.api_key),
            )
            conn.commit()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存设置失败：{exc}",
        ) from exc

    # 精准清除 openai_api_key 的字典缓存，确保下次 LLM 请求重新加载最新值
    # 若未来支持多模型，各模型的 POST 路由只需传入对应的 setting_key 即可
    invalidate_api_key_cache(_KEY_OPENAI)

    return {"status": "ok"}


@router.get(
    "/delivery-root",
    response_model=DeliveryRootResponse,
    summary="Get the machine-global Delivery Root",
)
def read_delivery_root() -> DeliveryRootResponse:
    try:
        delivery_root = get_delivery_root()
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read Delivery Root",
        ) from exc
    return DeliveryRootResponse(
        delivery_root=delivery_root,
        is_configured=bool(delivery_root),
    )


@router.post(
    "/delivery-root",
    response_model=DeliveryRootResponse,
    status_code=status.HTTP_200_OK,
    summary="Save the machine-global Delivery Root",
)
def write_delivery_root(payload: DeliveryRootPayload) -> DeliveryRootResponse:
    try:
        delivery_root = save_delivery_root(payload.delivery_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save Delivery Root",
        ) from exc
    return DeliveryRootResponse(
        delivery_root=delivery_root,
        is_configured=bool(delivery_root),
    )
