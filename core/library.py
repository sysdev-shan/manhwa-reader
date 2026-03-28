"""
Library management — saved titles organised in categories.
Persisted at ~/.manhwa-reader/library.json.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

DATA_DIR = Path.home() / ".manhwa-reader"
LIBRARY_FILE = DATA_DIR / "library.json"

DEFAULT_CATEGORIES = ["Default", "Favorites", "Reading", "Completed", "On Hold"]


class Library:
    """
    Schema::

        {
          "categories": ["Default", ...],
          "entries": {
            "<manga_url>": {
              "title": str,
              "author": str | null,
              "thumbnail_url": str | null,
              "status": int,
              "genre": str | null,
              "categories": ["Default"],
              "added_at": float,
              "unread_count": int
            }
          }
        }
    """

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._categories: list[str] = list(DEFAULT_CATEGORIES)
        self._entries: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if LIBRARY_FILE.exists():
            try:
                raw = json.loads(LIBRARY_FILE.read_text())
                self._categories = raw.get("categories", list(DEFAULT_CATEGORIES))
                self._entries = raw.get("entries", {})
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        LIBRARY_FILE.write_text(
            json.dumps(
                {"categories": self._categories, "entries": self._entries},
                indent=2,
            )
        )

    # ------------------------------------------------------------------
    # Manga operations
    # ------------------------------------------------------------------
    def add(self, manga, category: str = "Default") -> None:
        """Add or update a manga entry."""
        from source_api.models import SManga
        if not isinstance(manga, SManga):
            raise TypeError("Expected SManga")

        existing = self._entries.get(manga.url, {})
        cats: list[str] = existing.get("categories", [])
        if category not in cats:
            cats.append(category)

        self._entries[manga.url] = {
            "title": manga.title,
            "author": manga.author,
            "thumbnail_url": manga.thumbnail_url,
            "status": manga.status,
            "genre": manga.genre,
            "categories": cats,
            "added_at": existing.get("added_at", time.time()),
            "unread_count": existing.get("unread_count", 0),
        }
        self._save()

    def remove(self, manga_url: str) -> None:
        self._entries.pop(manga_url, None)
        self._save()

    def contains(self, manga_url: str) -> bool:
        return manga_url in self._entries

    def get(self, manga_url: str) -> dict | None:
        return self._entries.get(manga_url)

    def all(self, category: str | None = None) -> list[dict]:
        items = [{"manga_url": k, **v} for k, v in self._entries.items()]
        if category:
            items = [i for i in items if category in i.get("categories", [])]
        items.sort(key=lambda x: x.get("added_at", 0), reverse=True)
        return items

    # ------------------------------------------------------------------
    # Category operations
    # ------------------------------------------------------------------
    @property
    def categories(self) -> list[str]:
        return list(self._categories)

    def add_category(self, name: str) -> None:
        if name not in self._categories:
            self._categories.append(name)
            self._save()

    def remove_category(self, name: str) -> None:
        if name in DEFAULT_CATEGORIES:
            return  # Cannot remove default categories
        self._categories = [c for c in self._categories if c != name]
        for entry in self._entries.values():
            entry["categories"] = [
                c for c in entry.get("categories", []) if c != name
            ]
        self._save()

    def set_category(self, manga_url: str, category: str) -> None:
        if manga_url in self._entries and category in self._categories:
            self._entries[manga_url]["categories"] = [category]
            self._save()

    # ------------------------------------------------------------------
    # Unread count
    # ------------------------------------------------------------------
    def set_unread(self, manga_url: str, count: int) -> None:
        if manga_url in self._entries:
            self._entries[manga_url]["unread_count"] = max(0, count)
            self._save()
