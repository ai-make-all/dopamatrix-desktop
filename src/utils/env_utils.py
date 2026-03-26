"""
环境感知工具 — FFmpeg/FFprobe 路径嗅探器 + .env 加载器

解决 PyInstaller 单体打包后找不到 ffmpeg.exe 以及 .env 不随安装包分发的问题。

在 Tauri Sidecar 架构中：
  - ffmpeg.exe / ffprobe.exe 可能与 backend.exe 处于同级目录，
    也可能因 tauri.conf.json 的资源打包规则被放入同级的 bin/ 子目录。
  - .env 文件不在 PyInstaller bundle 内，需要放置在安装目录下；
    load_env() 会明确以 sys.executable 所在目录为基础查找，而非依赖 CWD。

使用方式：
    from src.utils.env_utils import get_ffmpeg_path, load_env

    load_env()                              # 最早调用一次即可，线程安全
    ffmpeg_bin  = get_ffmpeg_path("ffmpeg.exe")
    ffprobe_bin = get_ffmpeg_path("ffprobe.exe")
"""

import os
import sys
from pathlib import Path


def load_env() -> None:
    """
    加载 .env 文件到 os.environ。

    查找顺序：
      生产环境（PyInstaller frozen）：
        1. <sys.executable 所在目录>/.env   （安装目录，例：C:\\ClipFlow\\.env）
        2. 若不存在，调用无参 load_dotenv() 按 CWD → 祖先目录继续向上搜索

      开发环境：
        直接调用无参 load_dotenv()，按 python-dotenv 默认逻辑（CWD 向上搜索）

    调用时机：
      在 main.py 的模块级代码最早处调用一次。
      使用 ThreadPoolExecutor 时，所有工作线程共享同一 os.environ，
      无需在每个 worker 函数中重复调用。
    """
    from dotenv import load_dotenv

    if getattr(sys, "frozen", False):
        # 生产模式：优先从 exe 所在目录加载
        exe_dir_env = Path(sys.executable).parent / ".env"
        if exe_dir_env.exists():
            load_dotenv(dotenv_path=exe_dir_env, override=False)
            return
        # 兜底：继续按默认路径向上搜索（覆盖行为关闭，不覆盖已有系统变量）
        load_dotenv(override=False)
    else:
        # 开发模式：默认从 CWD / 项目根目录加载
        load_dotenv(override=False)


def get_ffmpeg_path(executable_name: str = "ffmpeg.exe") -> str:
    """
    根据运行环境智能返回 FFmpeg 系列可执行文件的路径。

    逻辑：
      - 生产环境 (PyInstaller frozen)：
          sys.executable 指向打包后的 backend.exe，base_dir 为其所在目录。
          采用多级路径猜测，按顺序查找：

          猜测 1：<base_dir>/<executable_name>
              ffmpeg.exe 与 backend.exe 处于同级目录时命中。
              例：C:/Users/.../app/ffmpeg.exe

          猜测 2：<base_dir>/bin/<executable_name>
              tauri.conf.json 将资源强制打入 bin/ 子目录时命中。
              例：C:/Users/.../app/bin/ffmpeg.exe

          兜底：若以上路径均不存在，返回猜测 1 的路径，
              让后续 subprocess 调用抛出带有明确路径的 FileNotFoundError，
              方便日志排查。

      - 开发环境：
          优先在项目根目录（与 main.py 同级）查找物理可执行文件。
          例：<project_root>/ffmpeg.exe → 返回绝对路径

          兜底：若根目录无物理文件，返回去掉 .exe 后缀的命令名，依赖系统 PATH 解析。
          例：ffmpeg / ffprobe

    Args:
        executable_name: 可执行文件名，含扩展名，如 "ffmpeg.exe" 或 "ffprobe.exe"。

    Returns:
        可直接传入 subprocess 命令列表第一个元素的字符串路径。
    """
    is_prod = getattr(sys, "frozen", False)
    if is_prod:
        base_dir = os.path.dirname(sys.executable)

        # 猜测 1：与 backend.exe 同级
        candidate_same_level = os.path.join(base_dir, executable_name)
        if os.path.exists(candidate_same_level):
            return candidate_same_level

        # 猜测 2：Tauri resources 强制放入的 bin/ 子目录
        candidate_bin_subdir = os.path.join(base_dir, "bin", executable_name)
        if os.path.exists(candidate_bin_subdir):
            return candidate_bin_subdir

        # 兜底：返回猜测 1 路径，让 subprocess 报出明确的 FileNotFoundError
        return candidate_same_level

    # 开发环境：优先在项目根目录（main.py 所在位置）查找物理可执行文件
    # parents[0] = src/utils/  parents[1] = src/  parents[2] = 项目根目录
    project_root = Path(__file__).resolve().parents[2]
    candidate_dev = project_root / executable_name          # 保留 .exe 后缀
    if candidate_dev.exists():
        return str(candidate_dev)

    # 终极兜底：根目录也找不到物理文件时，才降级依赖系统 PATH
    return executable_name.replace(".exe", "")
