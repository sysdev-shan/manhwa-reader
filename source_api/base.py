"""
Abstract source interface mirroring Mihon's source-api design.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from .models import SManga, SChapter, Page, MangasPage, FilterList


class Source(ABC):
    """Minimal source interface — every content source implements this."""

    @property
    @abstractmethod
    def id(self) -> int: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def lang(self) -> str:
        return ""

    @abstractmethod
    async def get_manga_details(self, manga: SManga) -> SManga:
        """Return a fully populated SManga for the given stub."""
        ...

    @abstractmethod
    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        """Return all available chapters, newest first."""
        ...

    @abstractmethod
    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        """Return the ordered page list for a chapter."""
        ...


class CatalogueSource(Source, ABC):
    """Source that also supports browsing/searching."""

    @property
    @abstractmethod
    def supports_latest(self) -> bool: ...

    @abstractmethod
    async def get_popular_manga(self, page: int) -> MangasPage: ...

    @abstractmethod
    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage: ...

    @abstractmethod
    async def get_latest_updates(self, page: int) -> MangasPage: ...

    @abstractmethod
    def get_filter_list(self) -> FilterList: ...


class HttpSource(CatalogueSource, ABC):
    """CatalogueSource that communicates over HTTP."""

    @property
    @abstractmethod
    def base_url(self) -> str: ...
