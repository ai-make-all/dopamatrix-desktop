"""Non-authoritative, tenant-confined operator delivery output helpers."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .database import SETTINGS_DB_PATH, canonical_tenant_id

logger = logging.getLogger(__name__)

DELIVERY_ROOT_SETTING_KEY = "delivery_root"
_WINDOWS_RESERVED_SEGMENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class DeliveryPathError(ValueError):
    """A configured or derived delivery path violates the V1.5 contract."""


@dataclass(frozen=True)
class DeliveryPublicationResult:
    configured: bool
    destination: str | None
    copied_paths: tuple[str, ...] = ()
    failed_count: int = 0

    @property
    def succeeded(self) -> bool:
        return self.configured and self.failed_count == 0


def normalize_delivery_root(value: str | os.PathLike[str] | None) -> str:
    """Return a physical absolute path, or ``""`` for an unset root."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DeliveryPathError("DELIVERY_ROOT_MUST_BE_ABSOLUTE")
    return str(path.resolve(strict=False))


def _settings_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(SETTINGS_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE IF NOT EXISTS app_settings "
        "(key_name TEXT PRIMARY KEY, key_value TEXT);"
    )
    connection.commit()
    return connection


def get_delivery_root() -> str:
    """Load the machine-global Delivery Root from ``dopamatrix.db``."""
    connection = _settings_connection()
    try:
        row = connection.execute(
            "SELECT key_value FROM app_settings WHERE key_name = ?;",
            (DELIVERY_ROOT_SETTING_KEY,),
        ).fetchone()
    finally:
        connection.close()
    return normalize_delivery_root(row["key_value"] if row is not None else "")


def save_delivery_root(value: str | os.PathLike[str] | None) -> str:
    """Persist one normalized machine-global Delivery Root; blank unsets it."""
    normalized = normalize_delivery_root(value)
    connection = _settings_connection()
    try:
        if normalized:
            connection.execute(
                "INSERT OR REPLACE INTO app_settings (key_name, key_value) "
                "VALUES (?, ?);",
                (DELIVERY_ROOT_SETTING_KEY, normalized),
            )
        else:
            connection.execute(
                "DELETE FROM app_settings WHERE key_name = ?;",
                (DELIVERY_ROOT_SETTING_KEY,),
            )
        connection.commit()
    finally:
        connection.close()
    return normalized


def _validate_segment(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise DeliveryPathError(f"{label}_INVALID")
    if any(character in value for character in ("/", "\\", ":")):
        raise DeliveryPathError(f"{label}_INVALID")
    if Path(value).name != value:
        raise DeliveryPathError(f"{label}_INVALID")
    if value.upper() in _WINDOWS_RESERVED_SEGMENTS:
        raise DeliveryPathError(f"{label}_WINDOWS_RESERVED")
    return value


def _validated_tenant(canonical_tenant: str) -> str:
    tenant = _validate_segment(canonical_tenant, label="DELIVERY_TENANT")
    if canonical_tenant_id(tenant) != tenant:
        raise DeliveryPathError("DELIVERY_TENANT_NOT_CANONICAL")
    return tenant


def _confined(root: Path, target: Path) -> Path:
    canonical_root = root.resolve(strict=False)
    canonical_target = target.resolve(strict=False)
    try:
        canonical_target.relative_to(canonical_root)
    except ValueError as exc:
        raise DeliveryPathError("DELIVERY_PATH_ESCAPES_ROOT") from exc
    return canonical_target


def derive_tenant_delivery_root(
    delivery_root: str | os.PathLike[str],
    canonical_tenant: str,
) -> Path:
    root_text = normalize_delivery_root(delivery_root)
    if not root_text:
        raise DeliveryPathError("DELIVERY_ROOT_UNCONFIGURED")
    root = Path(root_text)
    tenant = _validated_tenant(canonical_tenant)
    return _confined(root, root / "tenants" / tenant / "projects" / "_default")


def derive_render_delivery_dir(
    delivery_root: str | os.PathLike[str],
    canonical_tenant: str,
    task_id: str,
    render_date: date | str,
) -> Path:
    task_segment = _validate_segment(task_id, label="DELIVERY_TASK")
    if isinstance(render_date, date):
        date_segment = render_date.isoformat()
    else:
        try:
            date_segment = date.fromisoformat(str(render_date)).isoformat()
        except ValueError as exc:
            raise DeliveryPathError("DELIVERY_DATE_INVALID") from exc
    tenant_root = derive_tenant_delivery_root(delivery_root, canonical_tenant)
    return _confined(
        Path(normalize_delivery_root(delivery_root)),
        tenant_root / "renders" / date_segment / task_segment,
    )


def derive_export_delivery_dir(
    delivery_root: str | os.PathLike[str],
    canonical_tenant: str,
) -> Path:
    tenant_root = derive_tenant_delivery_root(delivery_root, canonical_tenant)
    return _confined(
        Path(normalize_delivery_root(delivery_root)),
        tenant_root / "exports",
    )


def _warn_delivery_copy(*, task_id: str, category: str, error: str) -> None:
    try:
        logger.warning(
            "[DELIVERY_COPY_FAILED] task_id=%s category=%s error=%s",
            task_id[:64],
            category[:64],
            error[:64],
        )
    except Exception:
        pass


def _candidate_sources(
    assets: Iterable[Mapping[str, Any]],
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for asset in assets:
        final_path = asset.get("file_path") or asset.get("path")
        if final_path:
            final = Path(str(final_path))
            if final.name.startswith("final_") and final.suffix.lower() == ".mp4":
                key = os.path.normcase(os.path.abspath(str(final)))
                if key not in seen:
                    seen.add(key)
                    candidates.append(final)
        cover_path = asset.get("cover_path")
        if cover_path:
            cover = Path(str(cover_path))
            if cover.name.startswith("cover_") and cover.suffix.lower() in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }:
                key = os.path.normcase(os.path.abspath(str(cover)))
                if key not in seen:
                    seen.add(key)
                    candidates.append(cover)
    return tuple(candidates)


def publish_render_delivery_assets(
    *,
    canonical_tenant: str,
    task_id: str,
    assets: Iterable[Mapping[str, Any]],
    render_date: date | None = None,
) -> DeliveryPublicationResult:
    """Best-effort copy finals/covers after authoritative history commit.

    This function deliberately catches all ordinary failures. Delivery is a
    convenience copy and must never alter catalog, Reservation, or task truth.
    """
    try:
        delivery_root = get_delivery_root()
        if not delivery_root:
            return DeliveryPublicationResult(configured=False, destination=None)
        destination = derive_render_delivery_dir(
            delivery_root,
            canonical_tenant,
            task_id,
            render_date or datetime.now(timezone.utc).date(),
        )
        destination.mkdir(parents=True, exist_ok=True)
        sources = _candidate_sources(assets)
    except Exception as exc:
        _warn_delivery_copy(
            task_id=task_id,
            category="setup",
            error=type(exc).__name__,
        )
        return DeliveryPublicationResult(
            configured=True,
            destination=None,
            failed_count=1,
        )

    copied: list[str] = []
    failed_count = 0
    for source in sources:
        try:
            if not source.is_file():
                raise FileNotFoundError(source.name)
            target = _confined(
                Path(delivery_root),
                destination / source.name,
            )
            shutil.copy2(source, target)
            copied.append(str(target))
        except Exception as exc:
            failed_count += 1
            _warn_delivery_copy(
                task_id=task_id,
                category="asset",
                error=type(exc).__name__,
            )

    return DeliveryPublicationResult(
        configured=True,
        destination=str(destination),
        copied_paths=tuple(copied),
        failed_count=failed_count,
    )
