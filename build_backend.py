import os
import subprocess
import shutil
import platform
import stat
import tempfile
from pathlib import Path


class BuildSafetyError(RuntimeError):
    """The controlled build cannot establish a safe write boundary."""


def kill_backend_processes():
    """Disabled, including explicit calls; process ownership is not established."""
    raise BuildSafetyError("RE_SAFE_PROCESS_KILL_DISABLED: close owned processes externally")


def move_with_retry(src: str, dst: str, retries: int = 5, delay: float = 2.0):
    """Disabled: no legacy overwrite, source deletion, retry or automatic recovery."""
    raise BuildSafetyError("RE_SAFE_MOVE_DISABLED: shared sidecar publication requires approval")


def clean_build_cache():
    """Disabled: names and prefixes do not establish disposable ownership."""
    raise BuildSafetyError("RE_SAFE_CLEANUP_DISABLED: existing files must be preserved")


def prepare_release_data():
    """Disabled: building is never authority to reset runtime/customer data."""
    raise BuildSafetyError("RE_SAFE_RESET_DISABLED: runtime data is outside build scope")


def _plain_path(path: Path) -> Path:
    """Reject observed aliases/reparse points, including existing ancestors."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        info = part.lstat()  # Missing/inaccessible/unknown paths fail closed.
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BuildSafetyError(f"RE_SAFE_REPARSE_REJECTED: {part}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise BuildSafetyError(f"RE_SAFE_FILE_ALIAS_REJECTED: {part}")
    if os.path.normcase(str(path.resolve(strict=True))) != os.path.normcase(str(path)):
        raise BuildSafetyError(f"RE_SAFE_PATH_ALIAS_REJECTED: {path}")
    return path


def _object_id(path: Path) -> tuple[int, int]:
    info = _plain_path(path).stat()
    if not info.st_ino:
        raise BuildSafetyError(f"RE_SAFE_IDENTITY_UNAVAILABLE: {path}")
    return info.st_dev, info.st_ino


def get_sidecar_filename():
    """
    根据 Tauri Sidecar 命名规范确定目标文件名。
    规范格式：<name>-<target-triple>[.exe]
    """
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        if machine in ("amd64", "x86_64"):
            triple = "x86_64-pc-windows-msvc"
        elif machine in ("arm64", "aarch64"):
            triple = "aarch64-pc-windows-msvc"
        else:
            triple = f"{machine}-pc-windows-msvc"
        return f"backend-{triple}.exe"
    elif system == "Darwin":
        if machine in ("arm64", "aarch64"):
            triple = "aarch64-apple-darwin"
        else:
            triple = "x86_64-apple-darwin"
        return f"backend-{triple}"
    else:
        if machine in ("amd64", "x86_64"):
            triple = "x86_64-unknown-linux-gnu"
        elif machine in ("arm64", "aarch64"):
            triple = "aarch64-unknown-linux-gnu"
        else:
            triple = f"{machine}-unknown-linux-gnu"
        return f"backend-{triple}"


def get_pyinstaller_command() -> list[str]:
    """Return the single-binary backend build command.

    The console subsystem is required so a direct ``backend.exe operator``
    invocation inherits terminal stdout/stderr and exposes its exit status.
    Normal Tauri startup remains windowless because tauri-plugin-shell applies
    ``CREATE_NO_WINDOW`` when it spawns the same sidecar bytes on Windows.
    """
    return [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--name", "backend",
        "--add-data", "src/prompts:src/prompts",
        "main.py",
    ]


def build():
    """Build only in a fresh staging directory; never clean or publish shared bin.

    Staging is deliberately retained on success AND failure. Promotion/disposal
    requires a separate reviewed SOP. Path checks are not concurrent-writer locks
    or certification against a malicious same-user process replacing directories.
    """
    stage = None
    try:
        root = _plain_path(Path(__file__)).parent
        if _plain_path(Path.cwd()) != root:
            raise BuildSafetyError("RE_SAFE_CWD_MISMATCH: invoke from the script root")
        if not _plain_path(root / "main.py").is_file():
            raise BuildSafetyError("RE_SAFE_INPUT_INVALID: main.py")
        if not _plain_path(root / "src" / "prompts").is_dir():
            raise BuildSafetyError("RE_SAFE_INPUT_INVALID: src/prompts")

        # mkdtemp exclusively creates a NEW directory; never adopt an existing one.
        stage = Path(tempfile.mkdtemp(prefix=".re-safe-build-", dir=root))
        stage_id = _object_id(stage)
        if stage.parent != root or any(stage.iterdir()):
            raise BuildSafetyError("RE_SAFE_STAGE_INVALID: not a fresh child of build root")
        command = get_pyinstaller_command() + [
            "--workpath", str(stage / "build"),
            "--distpath", str(stage / "dist"),
            "--specpath", str(stage),
        ]
        subprocess.run(command, cwd=str(root), check=True)
        if _object_id(stage) != stage_id:
            raise BuildSafetyError("RE_SAFE_STAGE_CHANGED")

        src_name = "backend.exe" if platform.system() == "Windows" else "backend"
        source = _plain_path(stage / "dist" / src_name)
        source_id = _object_id(source)
        if not source.is_file() or source.stat().st_size <= 0:
            raise BuildSafetyError("RE_SAFE_ARTIFACT_INVALID: expected nonempty regular file")
        target = stage / get_sidecar_filename()
        with source.open("rb") as reader:
            opened = os.fstat(reader.fileno())
            if (opened.st_dev, opened.st_ino) != source_id:
                raise BuildSafetyError("RE_SAFE_ARTIFACT_CHANGED")
            # Exclusive creation: an existing file, alias or locked target is NOT replaced.
            with target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
                target_info = os.fstat(writer.fileno())
        if _object_id(stage) != stage_id or _object_id(target) != (
            target_info.st_dev, target_info.st_ino
        ):
            raise BuildSafetyError("RE_SAFE_PUBLICATION_CHANGED")
    except (OSError, subprocess.CalledProcessError, BuildSafetyError) as exc:
        raise BuildSafetyError(
            f"RE_SAFE_BUILD_REFUSED: {exc}; retained staging={stage}; no retry/cleanup"
        ) from exc

    print(f"Staged sidecar only: {target}")
    print("Shared bin was NOT updated. Promotion and cleanup require separate authorization.")


if __name__ == "__main__":
    build()
