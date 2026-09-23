"""Tenant-scoped V1 backup, verification, and isolated restore tooling.

The bundle is deliberately a directory so operators can inspect and copy it
with ordinary filesystem tools.  The tenant database is captured with the
SQLite online backup API.  Rendered assets are enumerated only from the
TaskHistory catalog in that database snapshot; the output directory is never
scanned for authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from src.version import APPLICATION_VERSION


BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATABASE_BACKUP_PATH = "tenant.db"
ASSET_BACKUP_DIRECTORY = "assets"
_COPY_ATTEMPTS = 2
_COPY_CHUNK_SIZE = 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class BackupRestoreError(RuntimeError):
    """Base class carrying a stable, non-sensitive operator error code."""

    code = "BACKUP_RESTORE_FAILED"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class BackupSourceNotFoundError(BackupRestoreError):
    code = "TENANT_DATABASE_NOT_FOUND"


class BackupDestinationExistsError(BackupRestoreError):
    code = "BACKUP_DESTINATION_ALREADY_EXISTS"


class RestoreDestinationExistsError(BackupRestoreError):
    code = "RESTORE_STAGING_DESTINATION_ALREADY_EXISTS"


class BackupPathSafetyError(BackupRestoreError):
    code = "BACKUP_PATH_SAFETY_VIOLATION"


class IncompleteBackupError(BackupRestoreError):
    code = "INCOMPLETE_BACKUP"


class BackupIntegrityError(BackupRestoreError):
    code = "BACKUP_INTEGRITY_INVALID"


class BackupFormatError(BackupRestoreError):
    code = "BACKUP_MANIFEST_INVALID"


@dataclass(frozen=True)
class BackupResult:
    bundle_path: Path
    canonical_tenant_id: str
    asset_count: int
    counts: dict[str, int]


@dataclass(frozen=True)
class RestoreResult:
    staging_root: Path
    canonical_tenant_id: str
    asset_count: int
    counts: dict[str, int]


@dataclass(frozen=True)
class _AssetSource:
    source_path: Path
    relative_asset_path: PurePosixPath
    logical_reference: str
    reference_kind: str
    catalog_shape: str
    catalog_locators: tuple[str, ...] = ()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_integrity(path: Path) -> tuple[int, str]:
    if not path.is_file():
        raise BackupIntegrityError()
    return path.stat().st_size, _sha256_file(path)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_manifest_relative_path(value: Any, *, prefix: str | None = None) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BackupPathSafetyError()
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise BackupPathSafetyError()
    if prefix is not None and (not path.parts or path.parts[0] != prefix):
        raise BackupPathSafetyError()
    return path


def _safe_bundle_member(bundle_root: Path, relative_path: PurePosixPath) -> Path:
    root = bundle_root.resolve()
    candidate = root.joinpath(*relative_path.parts).resolve()
    if not _is_within(candidate, root):
        raise BackupPathSafetyError()
    return candidate


def _tenant_database_path(project_root: Path, tenant_id: str) -> tuple[str, Path]:
    canonical = _canonical_tenant_id(tenant_id)
    root = project_root.resolve()
    return canonical, root / "data" / f"dopamatrix_{canonical}.db"


def _canonical_tenant_id(tenant_id: str | None) -> str:
    """Mirror the legacy physical-name sanitizer without importing database.py.

    The backup verifier is a standalone bundle operation.  Importing the
    application database module would bind a global Engine to RuntimePaths and
    can initialize runtime directories before verification starts.
    """
    raw_tenant_id = tenant_id or "default"
    safe_tenant_id = "".join(
        character
        for character in raw_tenant_id
        if character.isalnum() or character in ("_", "-")
    )
    return os.path.normcase(safe_tenant_id or "default")


def _sqlite_read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _sqlite_immutable_read_only_uri(path: Path) -> str:
    """Open a completed bundle snapshot without creating SQLite sidecars."""
    return f"{path.resolve().as_uri()}?mode=ro&immutable=1"


def _sqlite_online_backup(source_path: Path, destination_path: Path) -> None:
    """Create a standalone SQLite-consistent snapshot using dedicated handles."""
    source = sqlite3.connect(_sqlite_read_only_uri(source_path), uri=True, timeout=30)
    destination = sqlite3.connect(destination_path, timeout=30)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(destination, pages=64, sleep=0.01)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise BackupIntegrityError()
    finally:
        destination.close()
        source.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _snapshot_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = _table_names(connection)
    requested = {
        "task_history": "task_history",
        "video_tasks": "video_tasks",
        "fingerprint_identities": "fingerprint_identities",
        "fingerprint_occurrences": "fingerprint_occurrences",
        "reservation_run_diagnostics": "reservation_run_diagnostics",
        "reservation_rollout_breakers": "reservation_rollout_breakers",
    }
    return {
        label: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        if table in tables
        else 0
        for label, table in requested.items()
    }


def _decode_output_assets(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise IncompleteBackupError() from exc
    if not isinstance(value, list):
        raise IncompleteBackupError()
    return value


def _resolve_catalog_asset(
    reference: str,
    *,
    project_root: Path,
    asset_root: Path,
    catalog_shape: str,
) -> _AssetSource:
    if not isinstance(reference, str) or not reference.strip() or "\x00" in reference:
        raise IncompleteBackupError()

    raw_path = Path(reference)
    windows_path = PureWindowsPath(reference)
    reference_is_absolute = raw_path.is_absolute() or windows_path.is_absolute()
    if windows_path.drive and not windows_path.is_absolute():
        raise BackupPathSafetyError()
    if reference_is_absolute:
        resolved = raw_path.resolve()
        reference_kind = "legacy_absolute_within_asset_root"
    else:
        resolved = (project_root / raw_path).resolve()
        reference_kind = "project_relative"

    resolved_asset_root = asset_root.resolve()
    if not _is_within(resolved, resolved_asset_root) or resolved == resolved_asset_root:
        raise BackupPathSafetyError()
    if not resolved.is_file():
        raise IncompleteBackupError()

    relative_asset = PurePosixPath(resolved.relative_to(resolved_asset_root).as_posix())
    logical_reference = PurePosixPath(
        Path(asset_root.name).joinpath(*relative_asset.parts).as_posix()
    ).as_posix()
    return _AssetSource(
        source_path=resolved,
        relative_asset_path=relative_asset,
        logical_reference=logical_reference,
        reference_kind=reference_kind,
        catalog_shape=catalog_shape,
    )


def _enumerate_authoritative_assets(
    snapshot_path: Path,
    *,
    project_root: Path,
    asset_root: Path,
) -> list[_AssetSource]:
    connection = sqlite3.connect(
        _sqlite_immutable_read_only_uri(snapshot_path), uri=True
    )
    try:
        if "task_history" not in _table_names(connection):
            return []
        rows = connection.execute(
            "SELECT id, output_assets FROM task_history ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    assets_by_relative_path: dict[PurePosixPath, _AssetSource] = {}
    for history_id, encoded_assets in rows:
        for asset_index, item in enumerate(_decode_output_assets(encoded_assets)):
            if not isinstance(item, dict):
                raise IncompleteBackupError()
            if item.get("file_path"):
                reference = item["file_path"]
                shape = "DSL"
            elif item.get("path"):
                reference = item["path"]
                shape = "LEGACY_MATRIX"
            else:
                raise IncompleteBackupError()
            asset = _resolve_catalog_asset(
                reference,
                project_root=project_root,
                asset_root=asset_root,
                catalog_shape=shape,
            )
            locator = f"task_history:{history_id}:{asset_index}"
            asset = _AssetSource(
                source_path=asset.source_path,
                relative_asset_path=asset.relative_asset_path,
                logical_reference=asset.logical_reference,
                reference_kind=asset.reference_kind,
                catalog_shape=asset.catalog_shape,
                catalog_locators=(locator,),
            )
            existing = assets_by_relative_path.get(asset.relative_asset_path)
            if existing is not None and existing.source_path != asset.source_path:
                raise BackupPathSafetyError()
            if existing is None:
                assets_by_relative_path[asset.relative_asset_path] = asset
            else:
                assets_by_relative_path[asset.relative_asset_path] = _AssetSource(
                    source_path=existing.source_path,
                    relative_asset_path=existing.relative_asset_path,
                    logical_reference=existing.logical_reference,
                    reference_kind=existing.reference_kind,
                    catalog_shape=existing.catalog_shape,
                    catalog_locators=existing.catalog_locators + (locator,),
                )
    return [assets_by_relative_path[key] for key in sorted(assets_by_relative_path, key=str)]


def _stat_signature(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino)


def _copy_file_bytes(source: Path, destination: Path) -> tuple[int, str]:
    """Copy one full file while hashing the exact bytes read from the source."""
    digest = hashlib.sha256()
    byte_count = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        for chunk in iter(lambda: source_handle.read(_COPY_CHUNK_SIZE), b""):
            destination_handle.write(chunk)
            digest.update(chunk)
            byte_count += len(chunk)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    return byte_count, digest.hexdigest()


def _copy_asset_consistently(source: Path, destination: Path) -> tuple[int, str]:
    for attempt in range(_COPY_ATTEMPTS):
        try:
            before = _stat_signature(source)
            byte_count, copied_digest = _copy_file_bytes(source, destination)
            after = _stat_signature(source)
            destination_size, destination_digest = _file_integrity(destination)
        except (FileNotFoundError, OSError) as exc:
            if attempt + 1 == _COPY_ATTEMPTS:
                raise IncompleteBackupError() from exc
            destination.unlink(missing_ok=True)
            continue

        if (
            before == after
            and byte_count == before[0]
            and destination_size == byte_count
            and destination_digest == copied_digest
        ):
            return destination_size, destination_digest
        destination.unlink(missing_ok=True)
    raise IncompleteBackupError()


def _write_manifest(staging_root: Path, manifest: dict[str, Any]) -> None:
    temporary = staging_root / f".{MANIFEST_NAME}.tmp"
    final = staging_root / MANIFEST_NAME
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, final)


def _snapshot_catalog_and_counts(snapshot_path: Path) -> dict[str, int]:
    try:
        connection = sqlite3.connect(
            _sqlite_immutable_read_only_uri(snapshot_path), uri=True
        )
        try:
            return _snapshot_counts(connection)
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupIntegrityError() from exc


def create_backup_bundle(
    *,
    tenant_id: str,
    destination: str | Path,
    project_root: str | Path = ".",
) -> BackupResult:
    """Create and verify one atomic tenant backup directory."""
    root = Path(project_root).resolve()
    canonical, source_database = _tenant_database_path(root, tenant_id)
    if not source_database.is_file():
        raise BackupSourceNotFoundError()

    final_root = Path(destination).resolve(strict=False)
    if os.path.lexists(final_root):
        raise BackupDestinationExistsError()
    final_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = final_root.parent / f".{final_root.name}.staging-{uuid.uuid4().hex}"
    staging_root.mkdir()

    try:
        snapshot_path = staging_root / DATABASE_BACKUP_PATH
        _sqlite_online_backup(source_database, snapshot_path)
        counts = _snapshot_catalog_and_counts(snapshot_path)
        asset_sources = _enumerate_authoritative_assets(
            snapshot_path,
            project_root=root,
            asset_root=root / "output",
        )

        asset_entries: list[dict[str, Any]] = []
        for source in asset_sources:
            relative_backup = PurePosixPath(ASSET_BACKUP_DIRECTORY).joinpath(
                source.relative_asset_path
            )
            destination_asset = staging_root.joinpath(*relative_backup.parts)
            size, digest = _copy_asset_consistently(source.source_path, destination_asset)
            asset_entries.append(
                {
                    "backup_path": relative_backup.as_posix(),
                    "asset_relative_path": source.relative_asset_path.as_posix(),
                    "logical_reference": source.logical_reference,
                    "reference_kind": source.reference_kind,
                    "catalog_shape": source.catalog_shape,
                    "catalog_locators": list(source.catalog_locators),
                    "byte_size": size,
                    "sha256": digest,
                }
            )

        database_size, database_digest = _file_integrity(snapshot_path)
        manifest: dict[str, Any] = {
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "application_version": APPLICATION_VERSION,
            "canonical_tenant_id": canonical,
            "created_at_utc": _utc_now_text(),
            "database": {
                "path": DATABASE_BACKUP_PATH,
                "byte_size": database_size,
                "sha256": database_digest,
            },
            "asset_count": len(asset_entries),
            "assets": asset_entries,
            "counts": counts,
        }
        _write_manifest(staging_root, manifest)
        verify_backup_bundle(staging_root)
        _publish_staging_directory(staging_root, final_root)
        return BackupResult(final_root, canonical, len(asset_entries), counts)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _require_int(value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BackupFormatError()
    return value


def _require_sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise BackupFormatError()
    return value


def _read_manifest(bundle_root: Path) -> dict[str, Any]:
    root = bundle_root.resolve()
    manifest_path = _safe_bundle_member(root, PurePosixPath(MANIFEST_NAME))
    if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise BackupFormatError()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupFormatError() from exc
    if not isinstance(manifest, dict):
        raise BackupFormatError()
    return manifest


def _publish_staging_directory(staging_root: Path, final_root: Path) -> None:
    """Publish without replacing a destination won by a competing process.

    DopaMatrix V1.5 is a Windows product.  ``os.rename`` on Windows fails when
    the destination exists, unlike ``os.replace`` which deliberately replaces
    an existing entry.  The immediate lexists check also catches broken links
    and gives a stable conflict before the rename call.
    """
    if os.path.lexists(final_root):
        raise BackupDestinationExistsError()
    try:
        os.rename(staging_root, final_root)
    except OSError:
        if os.path.lexists(final_root):
            raise BackupDestinationExistsError() from None
        raise


def _snapshot_catalog_contract(database_path: Path) -> dict[str, str]:
    """Return every authoritative TaskHistory asset locator and its shape."""
    try:
        connection = sqlite3.connect(
            _sqlite_immutable_read_only_uri(database_path), uri=True
        )
        try:
            if "task_history" not in _table_names(connection):
                return {}
            rows = connection.execute(
                "SELECT id, output_assets FROM task_history ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupIntegrityError() from exc

    contract: dict[str, str] = {}
    for history_id, encoded_assets in rows:
        for asset_index, item in enumerate(_decode_output_assets(encoded_assets)):
            if not isinstance(item, dict):
                raise BackupFormatError()
            if item.get("file_path"):
                shape = "DSL"
            elif item.get("path"):
                shape = "LEGACY_MATRIX"
            else:
                raise BackupFormatError()
            contract[f"task_history:{history_id}:{asset_index}"] = shape
    return contract


def verify_backup_bundle(bundle: str | Path) -> dict[str, Any]:
    """Verify manifest structure, safe paths, hashes, presence, and SQLite integrity."""
    bundle_root = Path(bundle).resolve()
    if not bundle_root.is_dir():
        raise BackupFormatError()
    manifest = _read_manifest(bundle_root)
    if manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
        raise BackupFormatError()
    application_version = manifest.get("application_version")
    if (
        not isinstance(application_version, str)
        or not application_version
        or len(application_version) > 64
        or any(character.isspace() for character in application_version)
    ):
        raise BackupFormatError()

    tenant = manifest.get("canonical_tenant_id")
    if not isinstance(tenant, str) or not tenant or _canonical_tenant_id(tenant) != tenant:
        raise BackupFormatError()
    created = manifest.get("created_at_utc")
    if not isinstance(created, str) or not created.endswith("Z"):
        raise BackupFormatError()

    database = manifest.get("database")
    if not isinstance(database, dict) or database.get("path") != DATABASE_BACKUP_PATH:
        raise BackupFormatError()
    database_relative = _safe_manifest_relative_path(database["path"])
    database_path = _safe_bundle_member(bundle_root, database_relative)
    expected_database_size = _require_int(database.get("byte_size"))
    expected_database_digest = _require_sha256(database.get("sha256"))
    actual_database_size, actual_database_digest = _file_integrity(database_path)
    if (
        actual_database_size != expected_database_size
        or actual_database_digest != expected_database_digest
    ):
        raise BackupIntegrityError()

    assets = manifest.get("assets")
    asset_count = _require_int(manifest.get("asset_count"))
    if not isinstance(assets, list) or asset_count != len(assets):
        raise BackupFormatError()
    seen_backup_paths: set[str] = set()
    seen_asset_paths: set[str] = set()
    manifest_catalog_contract: dict[str, str] = {}
    for entry in assets:
        if not isinstance(entry, dict):
            raise BackupFormatError()
        backup_relative = _safe_manifest_relative_path(
            entry.get("backup_path"), prefix=ASSET_BACKUP_DIRECTORY
        )
        asset_relative = _safe_manifest_relative_path(entry.get("asset_relative_path"))
        if backup_relative.parts[1:] != asset_relative.parts:
            raise BackupPathSafetyError()
        if (
            backup_relative.as_posix() in seen_backup_paths
            or asset_relative.as_posix() in seen_asset_paths
        ):
            raise BackupFormatError()
        seen_backup_paths.add(backup_relative.as_posix())
        seen_asset_paths.add(asset_relative.as_posix())
        if entry.get("reference_kind") not in (
            "project_relative",
            "legacy_absolute_within_asset_root",
        ):
            raise BackupFormatError()
        if entry.get("catalog_shape") not in ("DSL", "LEGACY_MATRIX"):
            raise BackupFormatError()
        locators = entry.get("catalog_locators")
        if not isinstance(locators, list) or not locators:
            raise BackupFormatError()
        for locator in locators:
            if (
                not isinstance(locator, str)
                or re.fullmatch(r"task_history:[1-9][0-9]*:[0-9]+", locator) is None
                or locator in manifest_catalog_contract
            ):
                raise BackupFormatError()
            manifest_catalog_contract[locator] = entry["catalog_shape"]
        logical = _safe_manifest_relative_path(entry.get("logical_reference"))
        if not logical.parts or logical.parts[0] != "output":
            raise BackupPathSafetyError()
        expected_size = _require_int(entry.get("byte_size"))
        expected_digest = _require_sha256(entry.get("sha256"))
        asset_path = _safe_bundle_member(bundle_root, backup_relative)
        actual_size, actual_digest = _file_integrity(asset_path)
        if actual_size != expected_size or actual_digest != expected_digest:
            raise BackupIntegrityError()

    if manifest_catalog_contract != _snapshot_catalog_contract(database_path):
        raise BackupIntegrityError()

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise BackupFormatError()
    for value in counts.values():
        _require_int(value)
    if dict(counts) != _snapshot_catalog_and_counts(database_path):
        raise BackupIntegrityError()

    connection = sqlite3.connect(
        _sqlite_immutable_read_only_uri(database_path), uri=True
    )
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise BackupIntegrityError()
    except sqlite3.DatabaseError as exc:
        raise BackupIntegrityError() from exc
    finally:
        connection.close()
    return manifest


def _validate_restored_database(database_path: Path) -> None:
    from sqlalchemy import create_engine

    from .database import initialize_application_schema
    from .fingerprint_ledger import ensure_fingerprint_ledger_schema

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        initialize_application_schema(engine)
        ensure_fingerprint_ledger_schema(engine)
        with engine.connect() as connection:
            if connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
                raise BackupIntegrityError()
    finally:
        engine.dispose()


def restore_backup_to_staging(
    *,
    bundle: str | Path,
    staging_root: str | Path,
) -> RestoreResult:
    """Restore only into a new isolated root; an existing destination is never overwritten."""
    bundle_root = Path(bundle).resolve()
    # Resolve existing parent aliases while permitting the requested staging
    # leaf (and any other trailing components) not to exist yet.  Every later
    # destination operation must use this same physical target.
    final_root = Path(staging_root).resolve(strict=False)
    if final_root.exists():
        raise RestoreDestinationExistsError()
    if _is_within(final_root, bundle_root) or _is_within(bundle_root, final_root):
        raise BackupPathSafetyError()
    manifest = verify_backup_bundle(bundle_root)

    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = final_root.parent / f".{final_root.name}.restore-{uuid.uuid4().hex}"
    temporary_root.mkdir()
    try:
        tenant = manifest["canonical_tenant_id"]
        source_database = _safe_bundle_member(
            bundle_root, PurePosixPath(DATABASE_BACKUP_PATH)
        )
        restored_database = temporary_root / "data" / f"dopamatrix_{tenant}.db"
        restored_database.parent.mkdir(parents=True)
        shutil.copyfile(source_database, restored_database)
        restored_size, restored_digest = _file_integrity(restored_database)
        if (
            restored_size != manifest["database"]["byte_size"]
            or restored_digest != manifest["database"]["sha256"]
        ):
            raise BackupIntegrityError()

        for entry in manifest["assets"]:
            source_relative = _safe_manifest_relative_path(
                entry["backup_path"], prefix=ASSET_BACKUP_DIRECTORY
            )
            target_relative = _safe_manifest_relative_path(entry["asset_relative_path"])
            source_asset = _safe_bundle_member(bundle_root, source_relative)
            target_asset = temporary_root / "output" / Path(*target_relative.parts)
            target_asset.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_asset, target_asset)
            target_size, target_digest = _file_integrity(target_asset)
            if target_size != entry["byte_size"] or target_digest != entry["sha256"]:
                raise BackupIntegrityError()

        _validate_restored_database(restored_database)
        os.replace(temporary_root, final_root)
        return RestoreResult(
            final_root,
            tenant,
            manifest["asset_count"],
            dict(manifest["counts"]),
        )
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.api.backup_restore",
        description="DopaMatrix tenant backup/verify/isolated-restore operator tool",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create an atomic tenant backup bundle")
    backup.add_argument("--tenant", required=True)
    backup.add_argument("--destination", required=True)
    backup.add_argument("--project-root", default=".")

    verify = commands.add_parser("verify", help="verify a backup without restoring it")
    verify.add_argument("--bundle", required=True)

    restore = commands.add_parser(
        "restore-to-staging",
        help="restore into a new isolated staging root",
    )
    restore.add_argument("--bundle", required=True)
    restore.add_argument("--staging-root", required=True)
    return parser


def _print_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "backup":
            result = create_backup_bundle(
                tenant_id=args.tenant,
                destination=args.destination,
                project_root=args.project_root,
            )
            _print_result(
                {
                    "status": "VALID",
                    "bundle": str(result.bundle_path),
                    "canonical_tenant_id": result.canonical_tenant_id,
                    "asset_count": result.asset_count,
                    "counts": result.counts,
                }
            )
        elif args.command == "verify":
            manifest = verify_backup_bundle(args.bundle)
            _print_result(
                {
                    "status": "VALID",
                    "canonical_tenant_id": manifest["canonical_tenant_id"],
                    "asset_count": manifest["asset_count"],
                    "counts": manifest["counts"],
                }
            )
        else:
            result = restore_backup_to_staging(
                bundle=args.bundle,
                staging_root=args.staging_root,
            )
            _print_result(
                {
                    "status": "VALID_STAGING_RESTORE",
                    "staging_root": str(result.staging_root),
                    "canonical_tenant_id": result.canonical_tenant_id,
                    "asset_count": result.asset_count,
                    "counts": result.counts,
                }
            )
        return 0
    except BackupRestoreError as exc:
        print(exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
