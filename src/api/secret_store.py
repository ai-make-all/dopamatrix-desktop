"""Global DPAPI-backed secret storage for V1.5 machine credentials.

The store is deliberately small: recognized keys are fixed, ciphertext lives
only in the RuntimePaths global settings database, and callers receive stable
secret-safe failures.  Tenant databases and ORM metadata are not involved.
"""

from __future__ import annotations

import ctypes
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

from .runtime_paths import RuntimeMode, get_runtime_paths


OPENAI_API_KEY = "openai_api_key"
RESERVATION_ROLLOUT_ASSIGNMENT_SECRET = "reservation_rollout_assignment_secret"
PEXELS_API_KEY = "pexels_api_key"
TELEGRAM_BOT_TOKEN = "telegram_bot_token"
CF_API_TOKEN = "cf_api_token"

KNOWN_SECRET_KEYS = frozenset(
    {
        OPENAI_API_KEY,
        RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
        PEXELS_API_KEY,
        TELEGRAM_BOT_TOKEN,
        CF_API_TOKEN,
    }
)

DPAPI_CURRENT_USER_V1 = "dpapi-current-user-v1"
LEGACY_OPENAI_SETTING_KEY = "openai_api_key"


class SecretStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    ERROR = "ERROR"


class OpenAISecretMigrationResult(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    MIGRATED = "MIGRATED"
    SECURE_ONLY = "SECURE_ONLY"
    REDUNDANT_LEGACY_REMOVED = "REDUNDANT_LEGACY_REMOVED"
    MIGRATION_CONFLICT = "MIGRATION_CONFLICT"
    ERROR = "ERROR"


class SecretStoreError(RuntimeError):
    """Base class whose public text never contains secret-derived material."""


class SecretKeyUnrecognized(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_KEY_UNRECOGNIZED")


class SecretValueInvalid(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_VALUE_INVALID")


class SecretProtectorUnavailable(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_PROTECTOR_UNAVAILABLE")


class SecretEncryptionFailed(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_ENCRYPTION_FAILED")


class SecretDecryptionFailed(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_DECRYPTION_FAILED")


class SecretSchemeUnsupported(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_SCHEME_UNSUPPORTED")


class SecretValueCorrupt(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("SECRET_VALUE_CORRUPT")


class OpenAISecretMigrationConflict(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("OPENAI_SECRET_MIGRATION_CONFLICT")


class SecretProtector(Protocol):
    @property
    def scheme(self) -> str: ...

    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


class WindowsDpapiProtector:
    """Windows DPAPI CurrentUser protector with UI disabled.

    No optional entropy is used.  DPAPI already binds ciphertext to the
    current Windows user profile, and H2 has no independent handoff secret.
    """

    scheme = DPAPI_CURRENT_USER_V1
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SecretProtectorUnavailable()
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError as exc:  # pragma: no cover - broken Windows installation
            raise SecretProtectorUnavailable() from exc

        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_wchar_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def protect(self, plaintext: bytes) -> bytes:
        if not plaintext:
            raise SecretValueInvalid()
        input_value, keepalive = _input_blob(plaintext)
        output = _DataBlob()
        try:
            succeeded = self._crypt32.CryptProtectData(
                ctypes.byref(input_value),
                None,
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not succeeded:
                raise SecretEncryptionFailed()
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                self._kernel32.LocalFree(output.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext:
            raise SecretValueCorrupt()
        input_value, keepalive = _input_blob(ciphertext)
        output = _DataBlob()
        try:
            succeeded = self._crypt32.CryptUnprotectData(
                ctypes.byref(input_value),
                None,
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not succeeded:
                raise SecretDecryptionFailed()
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                self._kernel32.LocalFree(output.pbData)


class _UnavailableProtector:
    scheme = DPAPI_CURRENT_USER_V1

    def protect(self, plaintext: bytes) -> bytes:
        raise SecretProtectorUnavailable()

    def unprotect(self, ciphertext: bytes) -> bytes:
        raise SecretProtectorUnavailable()


def create_platform_secret_protector() -> SecretProtector:
    if sys.platform != "win32":
        return _UnavailableProtector()
    return WindowsDpapiProtector()


def _validate_key(key_name: str) -> None:
    if key_name not in KNOWN_SECRET_KEYS:
        raise SecretKeyUnrecognized()


def _create_secure_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS secure_settings ("
        "key_name TEXT PRIMARY KEY, "
        "encryption_scheme TEXT NOT NULL, "
        "ciphertext BLOB NOT NULL, "
        "updated_at TEXT NOT NULL"
        ");"
    )


def _create_app_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "key_name TEXT PRIMARY KEY, key_value TEXT"
        ");"
    )


class SecretStore:
    def __init__(
        self,
        db_path: str | os.PathLike[str] | Path,
        protector: SecretProtector,
    ) -> None:
        self._db_path = Path(db_path).expanduser().resolve(strict=False)
        self._protector = protector

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            _create_secure_settings_table(conn)

    def _decrypt_row(self, row: sqlite3.Row) -> str:
        if row["encryption_scheme"] != self._protector.scheme:
            raise SecretSchemeUnsupported()
        ciphertext = row["ciphertext"]
        if not isinstance(ciphertext, bytes):
            raise SecretValueCorrupt()
        try:
            plaintext = self._protector.unprotect(ciphertext)
            return plaintext.decode("utf-8", errors="strict")
        except SecretStoreError:
            raise
        except (UnicodeError, ValueError, TypeError) as exc:
            raise SecretValueCorrupt() from exc
        except Exception as exc:
            raise SecretDecryptionFailed() from exc

    def _read_row(
        self,
        conn: sqlite3.Connection,
        key_name: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT encryption_scheme, ciphertext FROM secure_settings "
            "WHERE key_name = ?;",
            (key_name,),
        ).fetchone()

    def _set_on_connection(
        self,
        conn: sqlite3.Connection,
        key_name: str,
        value: str,
    ) -> None:
        _validate_key(key_name)
        if not isinstance(value, str) or not value:
            raise SecretValueInvalid()
        try:
            ciphertext = self._protector.protect(value.encode("utf-8"))
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretEncryptionFailed() from exc
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise SecretEncryptionFailed()

        conn.execute(
            "INSERT OR REPLACE INTO secure_settings "
            "(key_name, encryption_scheme, ciphertext, updated_at) "
            "VALUES (?, ?, ?, ?);",
            (
                key_name,
                self._protector.scheme,
                sqlite3.Binary(ciphertext),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        persisted = self._read_row(conn, key_name)
        if persisted is None or self._decrypt_row(persisted) != value:
            raise SecretValueCorrupt()

    def set_secret(self, key_name: str, value: str) -> None:
        _validate_key(key_name)
        with closing(self._connect()) as conn, conn:
            _create_secure_settings_table(conn)
            self._set_on_connection(conn, key_name, value)

    def get_secret(self, key_name: str) -> str | None:
        _validate_key(key_name)
        try:
            with closing(self._connect()) as conn, conn:
                _create_secure_settings_table(conn)
                row = self._read_row(conn, key_name)
                return None if row is None else self._decrypt_row(row)
        except SecretStoreError:
            raise
        except sqlite3.Error as exc:
            raise SecretDecryptionFailed() from exc

    def delete_secret(self, key_name: str) -> None:
        _validate_key(key_name)
        with closing(self._connect()) as conn, conn:
            _create_secure_settings_table(conn)
            conn.execute("DELETE FROM secure_settings WHERE key_name = ?;", (key_name,))

    def get_status(self, key_name: str) -> SecretStatus:
        try:
            return (
                SecretStatus.PRESENT
                if self.get_secret(key_name) is not None
                else SecretStatus.ABSENT
            )
        except (SecretStoreError, sqlite3.Error, OSError):
            return SecretStatus.ERROR


def get_default_secret_store() -> SecretStore:
    return SecretStore(
        get_runtime_paths().settings_db_path,
        create_platform_secret_protector(),
    )


def _legacy_openai_value(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT key_value FROM app_settings WHERE key_name = ?;",
        (LEGACY_OPENAI_SETTING_KEY,),
    ).fetchone()
    if row is None or not row[0]:
        return None
    return str(row[0])


def migrate_legacy_openai_secret(store: SecretStore) -> OpenAISecretMigrationResult:
    """Migrate only the active RuntimePaths DB; never relocates legacy roots."""
    try:
        with closing(store._connect()) as conn, conn:
            _create_app_settings_table(conn)
            _create_secure_settings_table(conn)
            legacy_value = _legacy_openai_value(conn)
            secure_row = store._read_row(conn, OPENAI_API_KEY)

            if legacy_value is None and secure_row is None:
                return OpenAISecretMigrationResult.UNCONFIGURED

            if secure_row is not None:
                secure_value = store._decrypt_row(secure_row)
                if legacy_value is None:
                    return OpenAISecretMigrationResult.SECURE_ONLY
                if secure_value != legacy_value:
                    return OpenAISecretMigrationResult.MIGRATION_CONFLICT
                conn.execute(
                    "DELETE FROM app_settings WHERE key_name = ?;",
                    (LEGACY_OPENAI_SETTING_KEY,),
                )
                return OpenAISecretMigrationResult.REDUNDANT_LEGACY_REMOVED

            if legacy_value is None:  # defensive exhaustiveness
                return OpenAISecretMigrationResult.UNCONFIGURED
            store._set_on_connection(conn, OPENAI_API_KEY, legacy_value)
            conn.execute(
                "DELETE FROM app_settings WHERE key_name = ?;",
                (LEGACY_OPENAI_SETTING_KEY,),
            )
            return OpenAISecretMigrationResult.MIGRATED
    except (SecretStoreError, sqlite3.Error, OSError):
        return OpenAISecretMigrationResult.ERROR


@dataclass(frozen=True)
class OpenAISecretState:
    is_configured: bool
    secret_status: SecretStatus
    migration_required: bool


def inspect_openai_secret_state(store: SecretStore) -> OpenAISecretState:
    try:
        with closing(store._connect()) as conn, conn:
            _create_app_settings_table(conn)
            _create_secure_settings_table(conn)
            legacy_value = _legacy_openai_value(conn)
            secure_row = store._read_row(conn, OPENAI_API_KEY)
            if secure_row is None:
                return OpenAISecretState(
                    False,
                    SecretStatus.ERROR if legacy_value is not None else SecretStatus.ABSENT,
                    legacy_value is not None,
                )
            store._decrypt_row(secure_row)
            if legacy_value is not None:
                return OpenAISecretState(False, SecretStatus.ERROR, True)
            return OpenAISecretState(True, SecretStatus.PRESENT, False)
    except (SecretStoreError, sqlite3.Error, OSError):
        return OpenAISecretState(False, SecretStatus.ERROR, False)


def read_openai_secret_for_use(store: SecretStore) -> str | None:
    """Return secure OpenAI authority, rejecting all legacy split-brain states."""
    try:
        with closing(store._connect()) as conn, conn:
            _create_app_settings_table(conn)
            _create_secure_settings_table(conn)
            secure_row = store._read_row(conn, OPENAI_API_KEY)
            if secure_row is None:
                if _legacy_openai_value(conn) is not None:
                    raise OpenAISecretMigrationConflict()
                return None
            secure_value = store._decrypt_row(secure_row)
            if _legacy_openai_value(conn) is not None:
                raise OpenAISecretMigrationConflict()
            return secure_value
    except SecretStoreError:
        raise
    except sqlite3.Error as exc:
        raise SecretDecryptionFailed() from exc


def replace_openai_secret(store: SecretStore, value: str) -> None:
    """Explicit operator replacement resolves legacy conflict transactionally."""
    try:
        with closing(store._connect()) as conn, conn:
            _create_app_settings_table(conn)
            _create_secure_settings_table(conn)
            store._set_on_connection(conn, OPENAI_API_KEY, value)
            conn.execute(
                "DELETE FROM app_settings WHERE key_name = ?;",
                (LEGACY_OPENAI_SETTING_KEY,),
            )
    except SecretStoreError:
        raise
    except sqlite3.Error as exc:
        raise SecretEncryptionFailed() from exc


def initialize_secret_storage() -> OpenAISecretMigrationResult:
    """Startup hook: schema plus bounded OpenAI migration, never import-time."""
    try:
        store = get_default_secret_store()
        store.ensure_schema()
        return migrate_legacy_openai_secret(store)
    except (SecretStoreError, sqlite3.Error, OSError):
        return OpenAISecretMigrationResult.ERROR


def load_runtime_secret(
    key_name: str,
    *,
    development_environment_key: str | None = None,
    store: SecretStore | None = None,
) -> str | None:
    """Central credential source for optional integration consumers.

    Packaged and test modes never consult process environment. Source
    development retains an explicit environment adapter for optional services.
    """
    _validate_key(key_name)
    paths = get_runtime_paths()
    if paths.mode is RuntimeMode.SOURCE_DEVELOPMENT:
        return (
            os.environ.get(development_environment_key)
            if development_environment_key
            else None
        )
    active_store = store or get_default_secret_store()
    return active_store.get_secret(key_name)
