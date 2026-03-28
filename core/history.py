"""
Reading history — tracks which chapter a user last read per manga.
Persisted at ~/.manhwa-reader/history.json.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

DATA_DIR = Path.home() / ".manhwa-reader"
HISTORY_FILE = DATA_DIR / "history.json"


class History:
    """
    Schema::

        {
          "<manga_url>": {
            "title": str,
            "thumbnail_url": str | null,
            "last_chapter_url": str,
            "last_chapter_name": str,
            "last_page": int,
            "timestamp": float   # unix epoch
          }
        }
    """

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if HISTORY_FILE.exists():
            try:
                self._data = json.loads(HISTORY_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        HISTORY_FILE.write_text(json.dumps(self._data, indent=2))

    # ------------------------------------------------------------------
    def record(
        self,
        manga_url: str,
        title: str,
        thumbnail_url: str | None,
        chapter_url: str,
        chapter_name: str,
        page: int = 0,
    ) -> None:
        self._data[manga_url] = {
            "title": title,
            "thumbnail_url": thumbnail_url,
            "last_chapter_url": chapter_url,
            "last_chapter_name": chapter_name,
            "last_page": page,
            "timestamp": time.time(),
        }
        self._save()

    def get(self, manga_url: str) -> dict | None:
        return self._data.get(manga_url)

    def get_last_page(self, chapter_url: str) -> int:
        """Return the last-read page index for a chapter (0 if unknown)."""
        for entry in self._data.values():
            if entry.get("last_chapter_url") == chapter_url:
                return entry.get("last_page", 0)
        return 0

    def recent(self, limit: int = 50) -> list[dict]:
        """Return entries sorted newest-first."""
        items = [
            {"manga_url": k, **v} for k, v in self._data.items()
        ]
        items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return items[:limit]

    def clear(self) -> None:
        self._data = {}
        self._save()

    def remove(self, manga_url: str) -> None:
        self._data.pop(manga_url, None)
        self._save()
