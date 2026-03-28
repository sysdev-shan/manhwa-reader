"""
MangaDex API v5 source implementation.

Endpoints used
--------------
Popular  : GET /manga?order[followedCount]=desc&originalLanguage[]=ko&zh
Latest   : GET /manga?order[updatedAt]=desc&originalLanguage[]=ko&zh
Search   : GET /manga?title=…&…
Details  : GET /manga/{id}?includes[]=author&includes[]=artist&includes[]=cover_art
Chapters : GET /manga/{id}/feed?translatedLanguage[]=en&order[chapter]=desc&limit=500
Pages    : GET /at-home/server/{chapterId}
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..base import HttpSource
from ..models import (
    FilterList,
    MangasPage,
    Page,
    SChapter,
    SManga,
    SelectFilter,
    SortFilter,
    CheckBoxFilter,
    STATUS_ONGOING,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
    STATUS_ON_HIATUS,
)

BASE = "https://api.mangadex.org"
COVERS = "https://uploads.mangadex.org/covers"
PAGE_SIZE = 24
MAX_CHAPTERS = 500
_RATE_LIMIT_DELAY = 2.0   # seconds to wait after a 429

_STATUS_MAP = {
    "ongoing": STATUS_ONGOING,
    "completed": STATUS_COMPLETED,
    "cancelled": STATUS_CANCELLED,
    "hiatus": STATUS_ON_HIATUS,
}


def _attr(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dicts."""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


class MangaDexSource(HttpSource):
    """MangaDex source — manhwa (ko) + manhua (zh) with English translations."""

    # -------------------------------------------------------------------
    # Source identity
    # -------------------------------------------------------------------
    @property
    def id(self) -> int:
        return 2499283573021220648  # stable hash-based id

    @property
    def name(self) -> str:
        return "MangaDex"

    @property
    def lang(self) -> str:
        return "en"

    @property
    def base_url(self) -> str:
        return BASE

    @property
    def supports_latest(self) -> bool:
        return True

    # -------------------------------------------------------------------
    # HTTP helpers
    # -------------------------------------------------------------------
    async def _get(self, path: str, **params: Any) -> dict:
        """Perform a GET request with automatic 429 retry."""
        url = f"{BASE}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    await asyncio.sleep(_RATE_LIMIT_DELAY)
                    continue
                resp.raise_for_status()
                return resp.json()

    # -------------------------------------------------------------------
    # Manga list helpers
    # -------------------------------------------------------------------
    def _manga_from_entry(self, entry: dict) -> SManga:
        mid = entry.get("id", "")
        attrs = entry.get("attributes", {})
        rels = entry.get("relationships", [])

        title_map: dict = attrs.get("title", {})
        title = (
            title_map.get("en")
            or title_map.get("ko")
            or title_map.get("zh")
            or next(iter(title_map.values()), "Unknown")
        )

        author = next(
            (r["attributes"]["name"] for r in rels
             if r.get("type") == "author" and "attributes" in r),
            None,
        )
        artist = next(
            (r["attributes"]["name"] for r in rels
             if r.get("type") == "artist" and "attributes" in r),
            None,
        )

        cover_file = next(
            (_attr(r, "attributes", "fileName") for r in rels
             if r.get("type") == "cover_art"),
            None,
        )
        thumbnail = f"{COVERS}/{mid}/{cover_file}" if cover_file else None

        tags = [
            (_attr(t, "attributes", "name", "en") or "")
            for t in attrs.get("tags", [])
        ]
        genre = ", ".join(filter(None, tags))

        desc_map: dict = attrs.get("description", {}) or {}
        description = desc_map.get("en") or next(iter(desc_map.values()), None)

        status_raw = attrs.get("status", "")
        status = _STATUS_MAP.get(status_raw, 0)

        return SManga(
            url=f"/manga/{mid}",
            title=title,
            author=author,
            artist=artist,
            description=description,
            genre=genre,
            status=status,
            thumbnail_url=thumbnail,
            initialized=True,
        )

    # -------------------------------------------------------------------
    # CatalogueSource
    # -------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        data = await self._get(
            "/manga",
            **{
                "order[followedCount]": "desc",
                "originalLanguage[]": ["ko", "zh"],
                "includes[]": ["cover_art", "author", "artist"],
                "limit": PAGE_SIZE,
                "offset": (page - 1) * PAGE_SIZE,
                "contentRating[]": ["safe", "suggestive"],
            },
        )
        mangas = [self._manga_from_entry(e) for e in data.get("data", [])]
        total = _attr(data, "total") or 0
        return MangasPage(mangas=mangas, has_next_page=page * PAGE_SIZE < total)

    async def get_latest_updates(self, page: int) -> MangasPage:
        data = await self._get(
            "/manga",
            **{
                "order[updatedAt]": "desc",
                "originalLanguage[]": ["ko", "zh"],
                "includes[]": ["cover_art", "author", "artist"],
                "limit": PAGE_SIZE,
                "offset": (page - 1) * PAGE_SIZE,
                "contentRating[]": ["safe", "suggestive"],
            },
        )
        mangas = [self._manga_from_entry(e) for e in data.get("data", [])]
        total = _attr(data, "total") or 0
        return MangasPage(mangas=mangas, has_next_page=page * PAGE_SIZE < total)

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        params: dict[str, Any] = {
            "originalLanguage[]": ["ko", "zh"],
            "includes[]": ["cover_art", "author", "artist"],
            "limit": PAGE_SIZE,
            "offset": (page - 1) * PAGE_SIZE,
            "contentRating[]": ["safe", "suggestive"],
        }
        if query:
            params["title"] = query

        for f in filters:
            if isinstance(f, SelectFilter) and f.name == "Status":
                val = f.selected().lower()
                if val and val != "any":
                    params["status[]"] = val
            elif isinstance(f, SelectFilter) and f.name == "Content Type":
                lang_map = {"manhwa": "ko", "manhua": "zh"}
                val = f.selected().lower()
                if val in lang_map:
                    params["originalLanguage[]"] = [lang_map[val]]
            elif isinstance(f, SortFilter) and f.name == "Sort":
                sort_fields = [
                    "relevance",
                    "latestUploadedChapter",
                    "followedCount",
                    "rating",
                ]
                field_key = sort_fields[max(0, min(f.state, len(sort_fields) - 1))]
                direction = "asc" if f.ascending else "desc"
                params[f"order[{field_key}]"] = direction

        data = await self._get("/manga", **params)
        mangas = [self._manga_from_entry(e) for e in data.get("data", [])]
        total = _attr(data, "total") or 0
        return MangasPage(mangas=mangas, has_next_page=page * PAGE_SIZE < total)

    def get_filter_list(self) -> FilterList:
        return [
            SelectFilter(
                name="Content Type",
                options=["Any", "Manhwa", "Manhua"],
            ),
            SelectFilter(
                name="Status",
                options=["Any", "Ongoing", "Completed", "Hiatus", "Cancelled"],
            ),
            SortFilter(
                name="Sort",
                options=["Relevance", "Latest Upload", "Follows", "Rating"],
            ),
        ]

    # -------------------------------------------------------------------
    # Source
    # -------------------------------------------------------------------
    async def get_manga_details(self, manga: SManga) -> SManga:
        mid = manga.url.lstrip("/manga/").split("/")[-1]
        data = await self._get(
            f"/manga/{mid}",
            **{"includes[]": ["cover_art", "author", "artist"]},
        )
        return self._manga_from_entry(data.get("data", {}))

    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        mid = manga.url.lstrip("/manga/").split("/")[-1]
        chapters: list[SChapter] = []
        offset = 0

        while True:
            data = await self._get(
                f"/manga/{mid}/feed",
                **{
                    "translatedLanguage[]": "en",
                    "order[chapter]": "desc",
                    "limit": 96,
                    "offset": offset,
                    "includes[]": ["scanlation_group"],
                },
            )
            entries = data.get("data", [])
            if not entries:
                break

            for entry in entries:
                attrs = entry.get("attributes", {})
                rels = entry.get("relationships", [])
                cid = entry.get("id", "")

                ch_num_raw = attrs.get("chapter") or ""
                try:
                    ch_num = float(ch_num_raw)
                except (ValueError, TypeError):
                    ch_num = -1.0

                vol = attrs.get("volume") or ""
                ch_title = attrs.get("title") or ""
                name_parts = []
                if vol:
                    name_parts.append(f"Vol.{vol}")
                if ch_num_raw:
                    name_parts.append(f"Ch.{ch_num_raw}")
                if ch_title:
                    name_parts.append(ch_title)
                name = " ".join(name_parts) or f"Chapter {cid[:8]}"

                scanlator = next(
                    (_attr(r, "attributes", "name") for r in rels
                     if r.get("type") == "scanlation_group"),
                    None,
                )

                upload_raw = attrs.get("publishAt") or attrs.get("createdAt") or ""
                date_ms = 0
                if upload_raw:
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.fromisoformat(
                            upload_raw.replace("Z", "+00:00")
                        )
                        date_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        date_ms = 0

                chapters.append(
                    SChapter(
                        url=f"/chapter/{cid}",
                        name=name,
                        chapter_number=ch_num,
                        scanlator=scanlator,
                        date_upload=date_ms,
                    )
                )

            total = _attr(data, "total") or 0
            offset += len(entries)
            if offset >= min(total, MAX_CHAPTERS):
                break

        return chapters

    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        cid = chapter.url.lstrip("/chapter/").split("/")[-1]
        data = await self._get(f"/at-home/server/{cid}")
        base_url: str = data.get("baseUrl", "")
        chapter_data: dict = data.get("chapter", {})
        chapter_hash = chapter_data.get("hash", "")
        filenames: list[str] = chapter_data.get("data", [])

        return [
            Page(
                index=i,
                image_url=f"{base_url}/data/{chapter_hash}/{fn}",
            )
            for i, fn in enumerate(filenames)
        ]
