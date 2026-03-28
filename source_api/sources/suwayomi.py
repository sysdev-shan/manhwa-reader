"""
Suwayomi-Server source adapter.

Suwayomi-Server is a Java server that hosts Keiyoushi/Mihon extensions and
exposes a REST API, giving this app access to all installed manga sources.

Quick Setup
-----------
1. Download and run Suwayomi-Server:
   https://github.com/Suwayomi/Suwayomi-Server/releases/latest
2. Open the web UI at http://localhost:4567
3. Go to Extensions → Browse → install the Keiyoushi extension repo
4. Install desired extensions (e.g. Asura Scans, Flame Comics, Webtoon…)
5. In this app's Settings, confirm the Server URL (default: http://localhost:4567)

API endpoints used
------------------
GET  /api/v1/source/list
GET  /api/v1/source/{sourceId}/popular/{page}
GET  /api/v1/source/{sourceId}/latest/{page}
POST /api/v1/source/{sourceId}/search
GET  /api/v1/manga/{mangaId}/full/
GET  /api/v1/manga/{mangaId}/chapters
GET  /api/v1/manga/{mangaId}/chapter/{chapterIndex}/
GET  /api/v1/manga/{mangaId}/chapter/{chapterIndex}/page/{pageIndex}
"""
from __future__ import annotations

from typing import Any

import httpx

from ..base import CatalogueSource
from ..models import (
    FilterList,
    MangasPage,
    Page,
    SChapter,
    SManga,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_LICENSED,
    STATUS_ON_HIATUS,
    STATUS_ONGOING,
    STATUS_PUBLISHING_FINISHED,
)

_STATUS_MAP: dict[str, int] = {
    "ONGOING": STATUS_ONGOING,
    "COMPLETED": STATUS_COMPLETED,
    "CANCELLED": STATUS_CANCELLED,
    "HIATUS": STATUS_ON_HIATUS,
    "LICENSED": STATUS_LICENSED,
    "PUBLISHING_FINISHED": STATUS_PUBLISHING_FINISHED,
}


class SuwayomiSource(CatalogueSource):
    """
    Source adapter for Suwayomi-Server.

    Exposes every Keiyoushi extension installed on the connected server as a
    CatalogueSource.  Call ``list_sources()`` to enumerate available sources,
    then ``activate_source(source_id)`` to select one before browsing.

    Attributes
    ----------
    base_url  : URL of the running Suwayomi-Server instance.
    source_id : ID of the currently active source (empty string = none selected).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4567",
        source_id: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._source_id = source_id
        self._source_meta: dict = {}

    # ------------------------------------------------------------------
    # CatalogueSource identity
    # ------------------------------------------------------------------
    @property
    def id(self) -> int:
        return abs(hash(f"suwayomi:{self._source_id}")) & 0x7FFF_FFFF_FFFF_FFFF

    @property
    def name(self) -> str:
        return (
            self._source_meta.get("displayName")
            or self._source_meta.get("name")
            or "Suwayomi"
        )

    @property
    def lang(self) -> str:
        return self._source_meta.get("lang", "en")

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def supports_latest(self) -> bool:
        return bool(self._source_meta.get("supportsLatest", True))

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------
    @property
    def source_id(self) -> str:
        return self._source_id

    @source_id.setter
    def source_id(self, value: str) -> None:
        self._source_id = value

    async def list_sources(self) -> list[dict]:
        """Return all sources installed on the Suwayomi server."""
        result = await self._get("/api/v1/source/list")
        return result if isinstance(result, list) else []

    async def activate_source(self, source_id: str) -> None:
        """Set the active source and load its metadata from the server."""
        sources = await self.list_sources()
        meta = next(
            (s for s in sources if str(s.get("id", "")) == str(source_id)),
            {},
        )
        self._source_meta = meta
        self._source_id = source_id

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _resolve_thumb(self, thumb: str | None) -> str | None:
        if not thumb:
            return None
        if thumb.startswith(("http://", "https://")):
            return thumb
        return f"{self._base_url}{thumb}"

    def _manga_from_entry(self, entry: dict) -> SManga:
        genre_raw = entry.get("genre", [])
        if isinstance(genre_raw, list):
            genre: str | None = ", ".join(filter(None, genre_raw)) or None
        else:
            genre = genre_raw or None

        status = _STATUS_MAP.get(str(entry.get("status", "")).upper(), 0)

        return SManga(
            url=str(entry.get("id", "")),
            title=entry.get("title") or "Unknown",
            author=entry.get("author") or None,
            artist=entry.get("artist") or None,
            description=entry.get("description") or None,
            genre=genre,
            status=status,
            thumbnail_url=self._resolve_thumb(entry.get("thumbnailUrl")),
            initialized=bool(entry.get("initialized", False)),
        )

    # ------------------------------------------------------------------
    # Internal guard
    # ------------------------------------------------------------------
    def _require_source(self) -> None:
        if not self._source_id:
            raise RuntimeError(
                "No source selected.\n"
                "Open Browse and use [Change Source] to pick a source."
            )

    # ------------------------------------------------------------------
    # CatalogueSource: manga lists
    # ------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        self._require_source()
        data = await self._get(
            f"/api/v1/source/{self._source_id}/popular/{page}"
        )
        mangas = [self._manga_from_entry(e) for e in data.get("mangaList", [])]
        return MangasPage(mangas=mangas, has_next_page=bool(data.get("hasNextPage")))

    async def get_latest_updates(self, page: int) -> MangasPage:
        self._require_source()
        data = await self._get(
            f"/api/v1/source/{self._source_id}/latest/{page}"
        )
        mangas = [self._manga_from_entry(e) for e in data.get("mangaList", [])]
        return MangasPage(mangas=mangas, has_next_page=bool(data.get("hasNextPage")))

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        self._require_source()
        data = await self._post(
            f"/api/v1/source/{self._source_id}/search",
            {"searchTerm": query, "pageNum": page, "filters": []},
        )
        mangas = [self._manga_from_entry(e) for e in data.get("mangaList", [])]
        return MangasPage(mangas=mangas, has_next_page=bool(data.get("hasNextPage")))

    def get_filter_list(self) -> FilterList:
        return []

    # ------------------------------------------------------------------
    # Source: detail / chapters / pages
    # ------------------------------------------------------------------
    async def get_manga_details(self, manga: SManga) -> SManga:
        manga_id = manga.url
        try:
            data = await self._get(f"/api/v1/manga/{manga_id}/full/")
        except Exception:
            data = await self._get(f"/api/v1/manga/{manga_id}/")
        return self._manga_from_entry(data)

    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        manga_id = manga.url
        data = await self._get(f"/api/v1/manga/{manga_id}/chapters")
        entries = data if isinstance(data, list) else []
        chapters: list[SChapter] = []
        for entry in entries:
            chapters.append(
                SChapter(
                    # Encode "manga_id/chapter_index" so get_page_list can parse it
                    url=f"{manga_id}/{entry.get('index', 0)}",
                    name=entry.get("name") or "",
                    date_upload=int(entry.get("uploadDate") or 0),
                    chapter_number=float(entry.get("chapterNumber") or -1.0),
                    scanlator=entry.get("scanlator") or None,
                )
            )
        return chapters

    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        """
        Return pages whose image_url points to the Suwayomi page-image endpoint.
        Suwayomi fetches the actual image from the source and proxies it.
        """
        parts = chapter.url.split("/", 1)
        if len(parts) != 2:
            return []
        manga_id, chapter_index = parts
        data = await self._get(
            f"/api/v1/manga/{manga_id}/chapter/{chapter_index}/"
        )
        page_count: int = int(data.get("pageCount") or 0)
        return [
            Page(
                index=i,
                image_url=(
                    f"{self._base_url}/api/v1/manga/{manga_id}"
                    f"/chapter/{chapter_index}/page/{i}"
                ),
            )
            for i in range(page_count)
        ]
