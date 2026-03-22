"""
素材服务适配器 — 抽象基类 + Pexels 实现

设计原则：与 llm_provider.py 保持一致的策略模式（Strategy Pattern）。
  上层节点（AssetSelectNode）只依赖 BaseAssetProvider 接口，
  未来切换到可灵 / Runway / Stability AI 等视频生成 API 只需新增子类，
  无需改动任何上层业务逻辑。

已实现适配器：
  PexelsProvider  — 调用 Pexels 免费视频搜索 API，下载符合要求的 .mp4 素材

环境变量：
  PEXELS_API_KEY  — 必填（在 pexels.com/api 免费申请）
"""

import hashlib
import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

# 隐藏 Windows 下 FFprobe 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.env_utils import get_ffmpeg_path


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class BaseAssetProvider(ABC):
    """
    所有素材服务适配器必须实现的接口。
    上层节点（如 AssetSelectNode）只依赖该抽象类，与具体素材源完全解耦。
    """

    @abstractmethod
    def get_video_clip(self, keyword: str, duration: int) -> str:
        """
        根据关键词检索并下载一段视频素材，返回本地文件路径。

        Args:
            keyword:  搜索关键词（来自 scene.visual_prompt）
            duration: 期望的视频时长（秒），用于筛选长度合适的素材

        Returns:
            已下载到本地的 .mp4 文件绝对路径

        Raises:
            RuntimeError: 当素材检索/下载失败时抛出
        """
        pass


# ---------------------------------------------------------------------------
# HTTP Session 工厂（含重试）
# ---------------------------------------------------------------------------

def _make_session(retries: int = 3, backoff_factor: float = 0.8) -> requests.Session:
    """
    创建一个带自动重试的 requests.Session。

    重试策略：
      - 重试次数：3（可配置）
      - 退避系数：0.8（0.8s → 1.6s → 3.2s）
      - 触发重试的状态码：429（限速）、500、502、503、504
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# Pexels Provider 实现
# ---------------------------------------------------------------------------

class PexelsProvider(BaseAssetProvider):
    """
    基于 Pexels Video Search API 的素材适配器。

    API 文档：https://www.pexels.com/api/documentation/#videos-search

    工作流程：
      1. 用 visual_prompt 作为关键词调用搜索接口
      2. 筛选第一个横屏（landscape / width > height）HD 或 SD 文件
      3. 流式下载到 output/clips/<关键词哈希>.mp4 并返回本地路径

    关键配置（均从环境变量读取）：
      PEXELS_API_KEY   — 必填，API 密钥
      PEXELS_PER_PAGE  — 选填，单次搜索返回数量，默认 5
    """

    _SEARCH_URL = "https://api.pexels.com/videos/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: str = "output/clips",
        per_page: int = 5,
        timeout: int = 30,
    ):
        """
        Args:
            api_key:    Pexels API Key，默认从 PEXELS_API_KEY 环境变量读取
            output_dir: 下载目录，默认 output/clips
            per_page:   单次搜索返回结果数量（1~80），默认 5
            timeout:    HTTP 请求超时（秒），默认 30
        """
        self._api_key = api_key or os.getenv("PEXELS_API_KEY", "")
        if not self._api_key:
            raise RuntimeError(
                "[PexelsProvider] PEXELS_API_KEY is not set. "
                "Please add it to your .env file or environment variables."
            )

        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._per_page = min(max(per_page, 1), 80)
        self._timeout = timeout
        self._session = _make_session()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_video_clip(self, keyword: str, duration: int) -> str:
        """
        检索并下载一段视频素材。

        搜索策略（降级）：
          1. 使用完整 keyword 搜索
          2. 若结果为空，截取前两个词再搜索
          3. 若仍为空，抛出 RuntimeError

        Args:
            keyword:  搜索关键词
            duration: 期望时长（秒），优先选择时长 ≥ duration 的素材；
                      若无则选第一个可用素材

        Returns:
            本地 .mp4 文件路径（字符串）
        """
        # 尝试完整关键词
        video_url = self._search_video(keyword, duration)

        if not video_url:
            # 降级：截取前两词
            short_keyword = " ".join(keyword.split()[:2])
            if short_keyword and short_keyword != keyword:
                print(
                    f"[PexelsProvider] No results for '{keyword}', "
                    f"retrying with '{short_keyword}'..."
                )
                video_url = self._search_video(short_keyword, duration)

        if not video_url:
            raise RuntimeError(
                f"[PexelsProvider] No suitable video found for keyword: '{keyword}'"
            )

        return self._download_video(video_url, keyword)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _search_video(self, keyword: str, duration: int) -> Optional[str]:
        """
        调用 Pexels Video Search API，返回最优视频文件的下载 URL。
        返回 None 表示未找到合适素材。
        """
        headers = {"Authorization": self._api_key}
        params = {
            "query": keyword,
            "orientation": "landscape",
            "size": "medium",
            "per_page": self._per_page,
        }

        try:
            resp = self._session.get(
                self._SEARCH_URL,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"[PexelsProvider] Search API request failed for '{keyword}': {exc}"
            ) from exc

        data = resp.json()
        videos = data.get("videos", [])

        if not videos:
            return None

        # 优先选择时长 >= duration 的视频；否则取第一个
        preferred = [v for v in videos if int(v.get("duration", 0)) >= duration]
        chosen = preferred[0] if preferred else videos[0]

        return self._extract_download_url(chosen)

    def _extract_download_url(self, video: dict) -> Optional[str]:
        """
        从 Pexels video 对象中提取最优 .mp4 下载链接。

        优先顺序：HD > SD（质量由高到低）
        仅选择横屏（width > height）的文件。
        """
        files = video.get("video_files", [])

        # 按质量排序（HD 优先）
        hd_files = [
            f for f in files
            if f.get("quality") in ("hd", "sd")
            and f.get("width", 0) > f.get("height", 0)
            and f.get("link", "").endswith(".mp4")
        ]

        if not hd_files:
            # 退而求其次：只要是横屏 mp4
            hd_files = [
                f for f in files
                if f.get("width", 0) > f.get("height", 0)
            ]

        if not hd_files:
            hd_files = files  # 最后兜底：取任意文件

        if not hd_files:
            return None

        # quality 排序：hd > sd > 其他
        quality_order = {"hd": 0, "sd": 1}
        hd_files.sort(key=lambda f: quality_order.get(f.get("quality", ""), 99))

        return hd_files[0].get("link")

    def _download_video(self, url: str, keyword: str) -> str:
        """
        流式下载视频文件，保存到 output/clips/ 目录。

        文件名：基于 keyword + URL 的 MD5 哈希，避免重复下载。
        如果文件已存在，直接返回缓存路径（节省带宽）。

        Returns:
            本地文件路径字符串
        """
        # 生成确定性文件名
        hash_key = hashlib.md5(f"{keyword}:{url}".encode()).hexdigest()[:12]
        safe_keyword = "".join(c if c.isalnum() or c in "-_" else "_" for c in keyword[:30])
        filename = f"{safe_keyword}_{hash_key}.mp4"
        local_path = self._output_dir / filename

        # 缓存命中：直接返回
        if local_path.exists() and local_path.stat().st_size > 0:
            print(f"[PexelsProvider] Cache hit: {local_path}")
            return str(local_path)

        print(f"[PexelsProvider] Downloading: {url}")
        print(f"[PexelsProvider] -> {local_path}")

        try:
            resp = self._session.get(url, stream=True, timeout=self._timeout)
            resp.raise_for_status()

            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 512):  # 512 KB chunks
                    if chunk:
                        f.write(chunk)

        except requests.RequestException as exc:
            # 下载失败：清理残留文件
            if local_path.exists():
                local_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"[PexelsProvider] Download failed for '{url}': {exc}"
            ) from exc

        print(f"[PexelsProvider] Downloaded: {local_path} ({local_path.stat().st_size / 1024:.1f} KB)")
        return str(local_path)


# ---------------------------------------------------------------------------
# LocalMatrixProvider — 本地素材矩阵抽卡器
# ---------------------------------------------------------------------------

class LocalMatrixProvider:
    """
    本地视频素材矩阵提供者。

    从指定的本地目录中扫描 .mp4 文件，根据目标时长（target_duration）
    随机有放回地抽取素材，直到累计时长满足要求，返回文件路径列表。

    适用场景：
      - 矩阵批量生产（无需联网 API）
      - B/S Local First 架构下的本地素材优先策略

    构造参数：
        pool_dir:     本地素材目录，默认 "assets/matrix_pool/x_main"
        ffprobe_bin:  ffprobe 可执行文件路径，默认由 get_ffmpeg_path() 自动嗅探（生产/开发环境自适应）
        fallback_dur: 当 ffprobe 探测失败时使用的保底时长（秒），默认 5.0

    使用方法::

        provider = LocalMatrixProvider()
        clips = provider.get_clips_for_duration(target_duration=15.0)
        # → ["assets/matrix_pool/x_main/clip_a.mp4", "assets/matrix_pool/x_main/clip_b.mp4", ...]

        logo = provider.get_overlay_logo()
        # → "assets/matrix_pool/y_overlay/logos/logo_1_blue.png"  (随机选取，可为 None)

        sticker = provider.get_overlay_sticker()
        # → "assets/matrix_pool/y_overlay/stickers/sticker_2_orange.png"
    """

    def __init__(
        self,
        pool_dir: str = "assets/matrix_pool/x_main",
        ffprobe_bin: Optional[str] = None,
        fallback_dur: float = 5.0,
    ):
        self._pool_dir = Path(pool_dir)
        self._ffprobe_bin = ffprobe_bin or get_ffmpeg_path("ffprobe.exe")
        self._fallback_dur = fallback_dur
        # 文件时长缓存（避免对同一文件重复调用 ffprobe）
        self._duration_cache: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_clips_for_duration(self, target_duration: float) -> list[str]:
        """
        随机抽取本地素材，直到累计时长 >= target_duration。

        抽取策略：
          - 随机有放回（同一文件可被多次选中）
          - 每次迭代从整个素材池随机选一个文件
          - 累计时长超出目标后立即停止并返回

        Args:
            target_duration: 目标累计时长（秒）

        Returns:
            本地 .mp4 文件路径字符串列表（可包含重复路径）

        Raises:
            RuntimeError: 素材目录不存在或目录内无 .mp4 文件时抛出
        """
        import random

        if not self._pool_dir.exists():
            raise RuntimeError(
                f"[LocalMatrixProvider] Pool directory not found: '{self._pool_dir}'. "
                "Please create the directory and add .mp4 files."
            )

        mp4_files = sorted(self._pool_dir.glob("*.mp4"))
        if not mp4_files:
            raise RuntimeError(
                f"[LocalMatrixProvider] No .mp4 files found in '{self._pool_dir}'. "
                "Please add video files to the matrix pool."
            )

        print(
            f"[LocalMatrixProvider] Pool: {len(mp4_files)} file(s) in '{self._pool_dir}'. "
            f"Target duration: {target_duration:.1f}s"
        )

        selected: list[str] = []
        accumulated = 0.0
        max_iterations = 200  # 防止极端情况下的无限循环安全阀

        for _ in range(max_iterations):
            if accumulated >= target_duration:
                break

            chosen = random.choice(mp4_files)
            clip_path = str(chosen)
            dur = self._probe_duration(clip_path)
            selected.append(clip_path)
            accumulated += dur
            print(
                f"[LocalMatrixProvider]   + {chosen.name} ({dur:.1f}s) "
                f"→ accumulated {accumulated:.1f}s / {target_duration:.1f}s"
            )

        print(
            f"[LocalMatrixProvider] Done: {len(selected)} clip(s) selected, "
            f"total ~{accumulated:.1f}s (target {target_duration:.1f}s)."
        )
        return selected

    def get_overlay_logo(
        self,
        logos_subdir: str = "y_overlay/logos",
    ) -> Optional[str]:
        """
        从 {pool_dir.parent}/y_overlay/logos/ 随机选取一张 PNG，作为品牌 Logo。

        Args:
            logos_subdir: 相对于 pool_dir 父目录的子路径，默认 "y_overlay/logos"

        Returns:
            PNG 文件的绝对路径字符串；目录不存在或为空时返回 None。
        """
        logos_dir = self._pool_dir.parent / logos_subdir
        return self._pick_random_png(logos_dir)

    def get_overlay_sticker(
        self,
        stickers_subdir: str = "y_overlay/stickers",
    ) -> Optional[str]:
        """
        从 {pool_dir.parent}/y_overlay/stickers/ 随机选取一张 PNG，作为促销贴纸。

        Args:
            stickers_subdir: 相对于 pool_dir 父目录的子路径，默认 "y_overlay/stickers"

        Returns:
            PNG 文件的绝对路径字符串；目录不存在或为空时返回 None。
        """
        stickers_dir = self._pool_dir.parent / stickers_subdir
        return self._pick_random_png(stickers_dir)

    def _pick_random_png(self, subdir: Path) -> Optional[str]:
        """
        从指定目录随机选取一张 .png 文件。

        优雅降级策略：
          - 目录不存在 → 打印警告，返回 None
          - 目录为空（无 .png）→ 打印警告，返回 None
          - 否则：随机选取并返回绝对路径字符串
        """
        import random

        if not subdir.exists():
            print(
                f"[LocalMatrixProvider] Warning: overlay directory not found: '{subdir}'. "
                "Skipping overlay asset."
            )
            return None

        png_files = sorted(subdir.glob("*.png"))
        if not png_files:
            print(
                f"[LocalMatrixProvider] Warning: no .png files in '{subdir}'. "
                "Skipping overlay asset."
            )
            return None

        chosen = random.choice(png_files)
        print(f"[LocalMatrixProvider] Y-overlay selected: {chosen.name} from '{subdir.name}/'")
        return str(chosen)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _probe_duration(self, file_path: str) -> float:
        """
        用 ffprobe 探测视频文件时长；结果缓存以避免重复调用。
        探测失败时返回 fallback_dur（保底时长）。
        """
        if file_path in self._duration_cache:
            return self._duration_cache[file_path]

        try:
            result = subprocess.run(
                [
                    self._ffprobe_bin,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=_WIN_NO_WINDOW,
            )
            dur = float(result.stdout.strip())
        except Exception as exc:
            print(
                f"[LocalMatrixProvider] Warning: ffprobe failed for '{file_path}' ({exc}). "
                f"Using fallback duration {self._fallback_dur}s."
            )
            dur = self._fallback_dur

        self._duration_cache[file_path] = dur
        return dur
