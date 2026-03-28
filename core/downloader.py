"""
Chapter download manager.

Downloads are queued and processed sequentially.
Pages are cached in ~/.manhwa-reader/downloads/<manga_slug>/<chapter_slug>/.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable

import httpx

DATA_DIR = Path.home() / ".manhwa-reader"


class DownloadStatus(Enum):
    QUEUED = auto()
    DOWNLOADING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class DownloadJob:
    manga_url: str
    manga_title: str
    chapter_url: str
    chapter_name: str
    page_urls: list[str]
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: int = 0          # pages downloaded
    total: int = 0
    dest_dir: Path = field(default_factory=Path)
    error: str | None = None

    def progress_pct(self) -> float:
        return (self.progress / self.total * 100) if self.total else 0.0


def _slugify(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:80]


class Downloader:
    """Async chapter download manager."""

    def __init__(
        self,
        on_progress: Callable[[DownloadJob], None] | None = None,
    ) -> None:
        self._queue: asyncio.Queue[DownloadJob] = asyncio.Queue()
        self._jobs: list[DownloadJob] = []
        self._running = False
        self._on_progress = on_progress or (lambda _: None)

    # ------------------------------------------------------------------
    def enqueue(
        self,
        manga_url: str,
        manga_title: str,
        chapter_url: str,
        chapter_name: str,
        page_urls: list[str],
    ) -> DownloadJob:
        dest = (
            DATA_DIR
            / "downloads"
            / _slugify(manga_title)
            / _slugify(chapter_name)
        )
        dest.mkdir(parents=True, exist_ok=True)

        job = DownloadJob(
            manga_url=manga_url,
            manga_title=manga_title,
            chapter_url=chapter_url,
            chapter_name=chapter_name,
            page_urls=page_urls,
            total=len(page_urls),
            dest_dir=dest,
        )
        self._jobs.append(job)
        self._queue.put_nowait(job)
        return job

    def cancel(self, job: DownloadJob) -> None:
        if job.status == DownloadStatus.QUEUED:
            job.status = DownloadStatus.CANCELLED

    def all_jobs(self) -> list[DownloadJob]:
        return list(self._jobs)

    def clear_completed(self) -> None:
        self._jobs = [
            j for j in self._jobs
            if j.status not in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED)
        ]

    # ------------------------------------------------------------------
    def get_cached_path(self, manga_title: str, chapter_name: str, index: int, url: str) -> Path | None:
        """Return the local path of a cached page if it exists."""
        dest = (
            DATA_DIR
            / "downloads"
            / _slugify(manga_title)
            / _slugify(chapter_name)
        )
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        filename = f"{index:04d}{ext}"
        p = dest / filename
        return p if p.exists() else None

    # ------------------------------------------------------------------
    async def _download_job(self, job: DownloadJob) -> None:
        if job.status == DownloadStatus.CANCELLED:
            return

        job.status = DownloadStatus.DOWNLOADING
        self._on_progress(job)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                for i, url in enumerate(job.page_urls):
                    if job.status == DownloadStatus.CANCELLED:
                        return

                    ext = Path(url.split("?")[0]).suffix or ".jpg"
                    filename = f"{i:04d}{ext}"
                    dest_file = job.dest_dir / filename

                    if dest_file.exists():
                        job.progress = i + 1
                        self._on_progress(job)
                        continue

                    # Download with retry on 429
                    downloaded = False
                    for attempt in range(3):
                        resp = await client.get(url)
                        if resp.status_code == 429:
                            await asyncio.sleep(2.0 * (attempt + 1))
                            continue
                        resp.raise_for_status()
                        dest_file.write_bytes(resp.content)
                        downloaded = True
                        break
                    if not downloaded:
                        raise httpx.HTTPStatusError(
                            "Rate limited after 3 retries",
                            request=resp.request,
                            response=resp,
                        )

                    job.progress = i + 1
                    self._on_progress(job)

            job.status = DownloadStatus.COMPLETED
        except Exception as exc:
            job.status = DownloadStatus.FAILED
            job.error = str(exc)
        finally:
            self._on_progress(job)

    async def run(self) -> None:
        """Process the download queue indefinitely."""
        self._running = True
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._download_job(job)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._running = False
