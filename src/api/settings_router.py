"""Machine-global settings routes.

OpenAI credentials are stored only through the DPAPI-backed secure store.
LLM endpoint/model settings use the existing non-secret app_settings authority
and are applied to the immutable RuntimeConfigProvider on backend restart.
Delivery Root remains a non-secret dynamic machine setting.
"""

import sqlite3

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from .delivery_output import get_delivery_root, save_delivery_root
from .runtime_config import (
    LLM_PROVIDER_NAME,
    LlmOperationalSettingsError,
    read_llm_operational_settings,
    save_llm_operational_settings,
)
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
    provider: str
    openai_base_url: str | None
    llm_model: str
    is_configured: bool
    secret_status: str
    migration_required: bool = False


class LLMOperationalSettingsPayload(BaseModel):
    openai_base_url: str = ""
    llm_model: str = ""


class LLMOperationalSettingsResponse(BaseModel):
    provider: str
    openai_base_url: str | None
    llm_model: str
    restart_required: bool = True


class DeliveryRootPayload(BaseModel):
    delivery_root: str = ""


class DeliveryRootResponse(BaseModel):
    delivery_root: str
    is_configured: bool


@router.get(
    "/llm",
    response_model=LLMKeyResponse,
    summary="Get non-secret LLM configuration and API-key status",
)
def get_llm_key() -> LLMKeyResponse:
    """Return non-secret settings and secret status, never secret-derived data."""
    store = get_default_secret_store()
    state = inspect_openai_secret_state(store)
    try:
        operational = read_llm_operational_settings(store.db_path)
    except (LlmOperationalSettingsError, sqlite3.Error, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM_OPERATIONAL_SETTINGS_READ_FAILED",
        ) from exc
    return LLMKeyResponse(
        provider=LLM_PROVIDER_NAME,
        openai_base_url=operational.openai_base_url,
        llm_model=operational.llm_model,
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


@router.post(
    "/llm/config",
    response_model=LLMOperationalSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Save non-secret LLM provider configuration",
)
def save_llm_config(
    payload: LLMOperationalSettingsPayload,
) -> LLMOperationalSettingsResponse:
    """Persist validated endpoint/model settings for the next backend start."""
    try:
        operational = save_llm_operational_settings(
            get_default_secret_store().db_path,
            openai_base_url=payload.openai_base_url,
            llm_model=payload.llm_model,
        )
    except LlmOperationalSettingsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM_OPERATIONAL_SETTINGS_SAVE_FAILED",
        ) from exc
    return LLMOperationalSettingsResponse(
        provider=LLM_PROVIDER_NAME,
        openai_base_url=operational.openai_base_url,
        llm_model=operational.llm_model,
    )


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
