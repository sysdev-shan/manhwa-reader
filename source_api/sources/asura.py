"""
Asura Scans source — https://asuracomic.net

Asura Scans runs a custom Next.js / React frontend backed by a JSON API at
https://gg.asuracomic.net/api/.  This source uses that API for browse/search
and falls back to HTML scraping if the API is unreachable.

API endpoints
-------------
GET  https://gg.asuracomic.net/api/series/?page={n}&order={order}&status=0
GET  https://gg.asuracomic.net/api/series/?page={n}&name={q}
GET  https://gg.asuracomic.net/api/series/{slug}/
GET  https://gg.asuracomic.net/api/series/{slug}/chapters/
GET  https://asuracomic.net/series/{slug}/{chapter_id}/  (chapter reader HTML)
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from ..base import HttpSource
from ..models import (
    FilterList,
    MangasPage,
    Page,
    SChapter,
    SManga,
    STATUS_COMPLETED,
    STATUS_ON_HIATUS,
    STATUS_ONGOING,
    STATUS_UNKNOWN,
)

_API = "https://gg.asuracomic.net/api"
_SITE = "https://asuracomic.net"

_STATUS_MAP = {
    "ongoing": STATUS_ONGOING,
    "active": STATUS_ONGOING,
    "completed": STATUS_COMPLETED,
    "dropped": STATUS_COMPLETED,
    "hiatus": STATUS_ON_HIATUS,
    "on hiatus": STATUS_ON_HIATUS,
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": _SITE + "/",
    "Origin": _SITE,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class AsuraScansSource(HttpSource):
    """
    Source for Asura Scans (asuracomic.net).

    Communicates with Asura's own REST API.  No external server required.
    """

    SOURCE_NAME = "Asura Scans"
    SOURCE_LANG = "en"

    @property
    def id(self) -> int:
        return abs(hash("asurascans:asuracomic.net")) & 0x7FFF_FFFF_FFFF_FFFF

    @property
    def name(self) -> str:
        return self.SOURCE_NAME

    @property
    def lang(self) -> str:
        return self.SOURCE_LANG

    @property
    def base_url(self) -> str:
        return _SITE

    @property
    def supports_latest(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _get_json(self, path: str, **params) -> dict | list:
        url = f"{_API}{path}"
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return resp.json()

    async def _get_html(self, url: str) -> str:
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _manga_from_entry(self, entry: dict) -> SManga:
        slug = entry.get("slug") or str(entry.get("id", ""))
        title = entry.get("title") or entry.get("name") or "Unknown"
        thumb = entry.get("thumbnail") or entry.get("cover") or None
        if thumb and not thumb.startswith("http"):
            thumb = f"{_SITE}{thumb}"

        author = entry.get("author") or None
        if isinstance(author, dict):
            author = author.get("name") or None
        artist = entry.get("artist") or None
        if isinstance(artist, dict):
            artist = artist.get("name") or None

        status_str = str(entry.get("status", "")).lower()
        status = _STATUS_MAP.get(status_str, STATUS_UNKNOWN)

        genres_raw = entry.get("genres") or entry.get("tags") or []
        if isinstance(genres_raw, list):
            genre: str | None = ", ".join(
                g.get("name", g) if isinstance(g, dict) else str(g)
                for g in genres_raw
            ) or None
        else:
            genre = str(genres_raw) or None

        desc = entry.get("description") or entry.get("synopsis") or None

        return SManga(
            url=slug,
            title=title,
            author=author,
            artist=artist,
            description=desc,
            genre=genre,
            status=status,
            thumbnail_url=thumb,
            initialized=bool(desc),
        )

    # ------------------------------------------------------------------
    # CatalogueSource: manga lists
    # ------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        try:
            data = await self._get_json("/series/", page=page, order="rating", status=0)
            return self._page_from_response(data)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            raise RuntimeError(
                f"Asura Scans API is currently unavailable ({exc})."
            ) from exc

    async def get_latest_updates(self, page: int) -> MangasPage:
        try:
            data = await self._get_json("/series/", page=page, order="update", status=0)
            return self._page_from_response(data)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            raise RuntimeError(
                f"Asura Scans API is currently unavailable ({exc})."
            ) from exc

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        try:
            data = await self._get_json("/series/", page=page, name=query)
            return self._page_from_response(data)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            raise RuntimeError(
                f"Asura Scans search failed ({exc})."
            ) from exc

    def _page_from_response(self, data: dict | list) -> MangasPage:
        if isinstance(data, list):
            series_list = data
            has_next = False
        else:
            series_list = (
                data.get("data")
                or data.get("series")
                or data.get("result")
                or []
            )
            last_page = int(data.get("lastPage") or data.get("last_page") or 1)
            current = int(data.get("currentPage") or data.get("current_page") or 1)
            has_next = current < last_page

        mangas = [self._manga_from_entry(e) for e in series_list if isinstance(e, dict)]
        return MangasPage(mangas=mangas, has_next_page=has_next)

    def get_filter_list(self) -> FilterList:
        return []

    # ------------------------------------------------------------------
    # Source: detail
    # ------------------------------------------------------------------
    async def get_manga_details(self, manga: SManga) -> SManga:
        try:
            data = await self._get_json(f"/series/{manga.url}/")
        except (httpx.HTTPStatusError, httpx.RequestError):
            return manga

        if isinstance(data, list) and data:
            entry = data[0]
        elif isinstance(data, dict):
            entry = data.get("data") or data
        else:
            return manga

        return self._manga_from_entry(entry)

    # ------------------------------------------------------------------
    # Source: chapters
    # ------------------------------------------------------------------
    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        try:
            data = await self._get_json(f"/series/{manga.url}/chapters/")
        except httpx.HTTPStatusError:
            # Some slugs need the series detail which includes chapters
            try:
                detail = await self._get_json(f"/series/{manga.url}/")
                if isinstance(detail, dict):
                    data = detail.get("chapters") or []
                else:
                    data = []
            except (httpx.HTTPStatusError, httpx.RequestError):
                return []
        except httpx.RequestError:
            return []

        if isinstance(data, dict):
            entries = data.get("data") or data.get("chapters") or []
        elif isinstance(data, list):
            entries = data
        else:
            entries = []

        chapters: list[SChapter] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ch_id = str(entry.get("id") or entry.get("slug") or "")
            ch_name = entry.get("name") or entry.get("title") or f"Chapter {ch_id}"
            try:
                ch_num = float(entry.get("chapter") or entry.get("chapterNumber") or -1)
            except (ValueError, TypeError):
                ch_num = -1.0
            date_raw = entry.get("updatedAt") or entry.get("date") or ""
            ts = 0
            if date_raw:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
                    ts = int(dt.timestamp() * 1000)
                except Exception:
                    pass
            chapters.append(
                SChapter(
                    url=f"{manga.url}/{ch_id}",
                    name=ch_name,
                    date_upload=ts,
                    chapter_number=ch_num,
                )
            )

        chapters.sort(key=lambda c: c.chapter_number, reverse=True)
        return chapters

    # ------------------------------------------------------------------
    # Source: pages
    # ------------------------------------------------------------------
    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        """
        Fetch the chapter reader page and collect image URLs.
        URL: https://asuracomic.net/series/{manga_slug}/{chapter_id}/
        """
        parts = chapter.url.split("/", 1)
        manga_slug = parts[0]
        ch_id = parts[1] if len(parts) > 1 else ""
        url = f"{_SITE}/series/{manga_slug}/{ch_id}/"
        html = await self._get_html(url)
        return self._parse_page_images(html)

    def _parse_page_images(self, html: str) -> list[Page]:
        soup = BeautifulSoup(html, "html.parser")

        # Asura embeds a JSON blob for the reader
        m = re.search(
            r'"images"\s*:\s*(\[.*?\])',
            html,
            re.DOTALL,
        )
        if m:
            import json
            try:
                urls = json.loads(m.group(1))
                if isinstance(urls, list):
                    return [
                        Page(index=i, image_url=str(u))
                        for i, u in enumerate(urls)
                        if isinstance(u, str) and u.startswith("http")
                    ]
            except Exception:
                pass

        # HTML fallback: images in the reading container
        container = soup.select_one(
            "div#chapter-container, div.reading-content, "
            "main div[class*='chapter'], div[class*='reader']"
        )
        imgs = container.find_all("img") if container else []
        if not imgs:
            imgs = [
                img for img in soup.find_all("img")
                if (s := str(img.get("src", "")))
                and s.startswith("http")
                and "thumb" not in s.lower()
            ]

        pages: list[Page] = []
        for i, img in enumerate(imgs):
            if not isinstance(img, Tag):
                continue
            src = (
                str(img.get("src", "")).strip()
                or str(img.get("data-src", "")).strip()
                or str(img.get("data-lazy-src", "")).strip()
            )
            if src and src.startswith("http"):
                pages.append(Page(index=i, image_url=src))
        return pages
