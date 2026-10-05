"""Backend-authoritative Philippine Seed tenant session validation."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware

from .runtime_paths import RuntimeMode, get_runtime_paths
from .tenant_policy import TenantPolicyError, require_provisioned_tenant


router = APIRouter(prefix="/tenant", tags=["Tenant Session"])


class TenantHeaderAuthorityMiddleware(BaseHTTPMiddleware):
    """Reject forged tenant headers before route code can access storage."""

    def __init__(self, app, *, paths) -> None:
        super().__init__(app)
        self._paths = paths

    async def dispatch(self, request, call_next):
        raw_tenant_id = request.headers.get("X-Local-User")
        if raw_tenant_id is not None and self._paths.mode is not RuntimeMode.TEST:
            try:
                require_provisioned_tenant(raw_tenant_id, self._paths)
            except TenantPolicyError as exc:
                return JSONResponse(
                    status_code=exc.http_status,
                    content={"detail": exc.code},
                )
        return await call_next(request)


class TenantSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str


class TenantSessionResponse(BaseModel):
    tenant_id: str
    authorized: bool
    provisioned: bool
    usable: bool


@router.post("/session/validate", response_model=TenantSessionResponse)
def validate_tenant_session(payload: TenantSessionRequest) -> TenantSessionResponse:
    identity = require_provisioned_tenant(payload.tenant_id, get_runtime_paths())
    return TenantSessionResponse(
        tenant_id=identity.canonical_id,
        authorized=True,
        provisioned=True,
        usable=True,
    )
