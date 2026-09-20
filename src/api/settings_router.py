"""Machine-global settings routes.

OpenAI credentials are stored only through the DPAPI-backed secure store.
Delivery Root remains a non-secret dynamic machine setting.
"""

import sqlite3

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from .delivery_output import get_delivery_root, save_delivery_root
from .secret_store import (
    SecretStoreError,
    get_default_secret_store,
    inspect_openai_secret_state,
    replace_openai_secret,
)
from src.services.llm_provider import invalidate_api_key_cache


router = APIRouter(prefix="/settings", tags=["Settings"])
_KEY_OPENAI = "openai_api_key"


class LLMKeyPayload(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("api_key must not be empty")
        return value


class LLMKeyResponse(BaseModel):
    is_configured: bool
    secret_status: str
    migration_required: bool = False


class DeliveryRootPayload(BaseModel):
    delivery_root: str = ""


class DeliveryRootResponse(BaseModel):
    delivery_root: str
    is_configured: bool


@router.get(
    "/llm",
    response_model=LLMKeyResponse,
    summary="Get LLM API-key configuration status",
)
def get_llm_key() -> LLMKeyResponse:
    """Return presence/error state only; never secret-derived metadata."""
    state = inspect_openai_secret_state(get_default_secret_store())
    return LLMKeyResponse(
        is_configured=state.is_configured,
        secret_status=state.secret_status.value,
        migration_required=state.migration_required,
    )


@router.post(
    "/llm",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Save LLM API Key securely",
)
def save_llm_key(payload: LLMKeyPayload) -> dict:
    """Replace secure authority and remove legacy plaintext transactionally."""
    try:
        replace_openai_secret(get_default_secret_store(), payload.api_key)
    except (SecretStoreError, sqlite3.Error, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM_SECRET_SAVE_FAILED",
        ) from exc

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
