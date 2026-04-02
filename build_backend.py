import glob
import os
import sqlite3
import subprocess
import shutil
import platform
import time


def kill_backend_processes():
    """
    在 Windows 上强制终止所有正在运行的 backend.exe / app.exe 进程。
    目的：释放对旧 sidecar 二进制文件的文件锁，使后续的 move 操作得以成功。
    非 Windows 平台跳过此步骤。
    """
    if platform.system() != "Windows":
        return

    targets = ["backend.exe", "app.exe"]
    for name in targets:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True,
            text=True,
        )
        if "SUCCESS" in result.stdout or "成功" in result.stdout:
            print(f"  已终止进程：{name}")
        # 进程不存在时 taskkill 返回错误，属正常情况，不报告


def move_with_retry(src: str, dst: str, retries: int = 5, delay: float = 2.0):
    """
    带重试的文件移动。
    Windows Defender 扫描新生成的 EXE 时会短暂锁定文件；
    重试最多 `retries` 次，每次等待 `delay` 秒。
    """
    # 若目标文件已存在且被锁，先尝试删除
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except PermissionError:
            pass  # 下面的重试会再次尝试覆盖

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            shutil.copy2(src, dst)
            os.remove(src)
            return
        except PermissionError as exc:
            last_exc = exc
            print(f"  文件仍被占用，{delay:.0f} 秒后重试（{attempt}/{retries}）...")
            time.sleep(delay)

    raise PermissionError(
        f"移动 {src} -> {dst} 失败（已重试 {retries} 次）：{last_exc}\n"
        "请确保 ClipFlow 应用已完全关闭后重试。"
    ) from last_exc


def clean_build_cache():
    """
    清理 PyInstaller 产物与根目录 *.spec，并仅删除 sidecar 目录中以 backend- 为前缀的旧二进制。
    不触碰 web_ui/src-tauri/bin/ 下的 ffmpeg.exe、ffprobe.exe。
    """
    root = os.path.dirname(os.path.abspath(__file__))

    def _safe_rmtree(path: str):
        if not os.path.isdir(path):
            return
        try:
            shutil.rmtree(path)
        except Exception as exc:
            print(f"  ⚠️  警告：无法删除目录 {path}：{exc}")

    def _safe_remove_file(path: str):
        try:
            os.remove(path)
        except Exception as exc:
            print(f"  ⚠️  警告：无法删除文件 {path}：{exc}")

    _safe_rmtree(os.path.join(root, "build"))
    _safe_rmtree(os.path.join(root, "dist"))

    for spec in glob.glob(os.path.join(root, "*.spec")):
        if os.path.isfile(spec):
            _safe_remove_file(spec)

    bin_dir = os.path.join(root, "web_ui", "src-tauri", "bin")
    if os.path.isdir(bin_dir):
        # 仅匹配 backend- 前缀；不会匹配 ffmpeg.exe / ffprobe.exe
        for sidecar in glob.glob(os.path.join(bin_dir, "backend-*")):
            if os.path.isfile(sidecar):
                _safe_remove_file(sidecar)


def prepare_release_data():
    """
    出厂前清理：清空 output 下的产物，并重置 clipflow.db 中的任务历史与素材疲劳计数。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(root, "output")

    try:
        if os.path.isdir(output_dir):
            for name in os.listdir(output_dir):
                path = os.path.join(output_dir, name)
                try:
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                except Exception as exc:
                    print(f"  ⚠️  警告：无法删除 {path}：{exc}")
        else:
            os.makedirs(output_dir, exist_ok=True)
    except Exception as exc:
        print(f"  ⚠️  警告：清理或创建 output 目录失败：{exc}")

    db_path = os.path.join(root, "clipflow.db")
    if not os.path.exists(db_path):
        print(f"  ⚠️  警告：未找到数据库 {db_path}，跳过数据库出厂重置。")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        if "task_history" in tables:
            cursor.execute("DELETE FROM task_history;")
        if "local_assets_inventory" in tables:
            cursor.execute("UPDATE local_assets_inventory SET usage_count = 0;")

        conn.commit()
    except Exception as exc:
        print(f"  ⚠️  警告：数据库出厂重置失败：{exc}")
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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


def build():
    # ── Step 0: 释放文件锁（关闭正在运行的旧版本） ──────────────────────────
    print("==> [0/4] 终止正在运行的 ClipFlow 进程（释放文件锁）...")
    kill_backend_processes()
    # 稍等片刻，让 Windows 完成句柄回收
    time.sleep(1)

    print("==> [0.2/4] 精准清理旧的打包缓存(build, dist, .spec, 旧 sidecar)...")
    clean_build_cache()

    print("==> [0.3/4] 执行出厂重置 (清空 output 视频与重置数据库)...")
    prepare_release_data()

    print("==> [1/4] 运行 PyInstaller 打包后端...")
    subprocess.run(
        [
            "pyinstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",   # 防止 Windows 上弹出黑色 CMD 窗口
            "--name", "backend",
            "main.py",
        ],
        check=True,
    )

    src_name = "backend.exe" if platform.system() == "Windows" else "backend"
    src_path = os.path.join("dist", src_name)

    if not os.path.exists(src_path):
        raise FileNotFoundError(
            f"PyInstaller 产物未找到：{src_path}，请检查打包日志。"
        )

    dest_dir = os.path.join("web_ui", "src-tauri", "bin")
    dest_name = get_sidecar_filename()
    dest_path = os.path.join(dest_dir, dest_name)

    print(f"==> [2/4] 确保目标目录存在：{dest_dir}")
    os.makedirs(dest_dir, exist_ok=True)

    print(f"==> [3/4] 移动并重命名：{src_path} -> {dest_path}")
    # 使用带重试的移动，应对 Windows Defender 扫描新 EXE 时的短暂文件锁
    move_with_retry(src_path, dest_path)

    print(f"==> [4/4] 完成！")
    print(f"  Sidecar 二进制：{dest_path}")
    print(f"\n下一步：cd web_ui && npm run tauri build  （打包完整安装包）")


if __name__ == "__main__":
    build()
