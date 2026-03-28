"""
Data models mirroring Mihon's source-api contracts.
"""
from __future__ import annotations
from dataclasses import dataclass, field


# Manga status constants (mirrors Mihon SManga)
STATUS_UNKNOWN = 0
STATUS_ONGOING = 1
STATUS_COMPLETED = 2
STATUS_LICENSED = 3
STATUS_PUBLISHING_FINISHED = 4
STATUS_CANCELLED = 5
STATUS_ON_HIATUS = 6


@dataclass
class SManga:
    """Source manga model."""
    url: str
    title: str
    artist: str | None = None
    author: str | None = None
    description: str | None = None
    genre: str | None = None          # comma-separated tag list
    status: int = STATUS_UNKNOWN
    thumbnail_url: str | None = None
    initialized: bool = False

    def status_label(self) -> str:
        return {
            STATUS_ONGOING: "Ongoing",
            STATUS_COMPLETED: "Completed",
            STATUS_CANCELLED: "Cancelled",
            STATUS_ON_HIATUS: "Hiatus",
            STATUS_LICENSED: "Licensed",
            STATUS_PUBLISHING_FINISHED: "Finished",
        }.get(self.status, "Unknown")


@dataclass
class SChapter:
    """Source chapter model."""
    url: str
    name: str
    date_upload: int = 0          # epoch milliseconds
    chapter_number: float = -1.0
    scanlator: str | None = None


@dataclass
class Page:
    """Single manga page."""
    index: int
    url: str = ""
    image_url: str | None = None


@dataclass
class MangasPage:
    """A paginated list of manga."""
    mangas: list[SManga]
    has_next_page: bool


# ---------------------------------------------------------------------------
# Filter models
# ---------------------------------------------------------------------------

@dataclass
class Filter:
    """Base filter."""
    name: str


@dataclass
class TextFilter(Filter):
    state: str = ""


@dataclass
class SelectFilter(Filter):
    options: list[str] = field(default_factory=list)
    state: int = 0

    def selected(self) -> str:
        return self.options[self.state] if self.options else ""


@dataclass
class CheckBoxFilter(Filter):
    state: bool = False


@dataclass
class TriStateFilter(Filter):
    """0 = ignore, 1 = include, 2 = exclude."""
    state: int = 0


@dataclass
class SortFilter(Filter):
    options: list[str] = field(default_factory=list)
    state: int = 0
    ascending: bool = False


FilterList = list  # list[Filter]
