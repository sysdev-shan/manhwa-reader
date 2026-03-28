"""
Asura Scans source — https://asuracomic.net

Uses the public REST API at https://api.asurascans.com/api/.

API reference (community-documented)
-------------------------------------
GET  /series                    — list all series (paginates via ?page=N)
GET  /series?search=<q>         — search
GET  /series/{slug}             — detail; returns {"series": {...}}
GET  /series/{slug}/chapters    — chapter list; returns {"data": [{...}]}
GET  /series/{slug}/chapters/{chapter_slug}
                                — page images; returns
                                  {"data": {"chapter": {"pages":[{"url":...}]}}}

Falls back to scraping the public website HTML (asuracomic.net) when the
API is unavailable or returns unexpected data.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

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

_API = "https://api.asurascans.com/api"
_SITE = "https://asuracomic.net"

# Approximate number of items returned per page — used to infer has_next_page
# when only HTML scraping is available (no pagination metadata).
_DEFAULT_PAGE_SIZE = 20

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

    Communicates with Asura's public REST API at api.asurascans.com.
    Falls back to HTML scraping when the API is unavailable.
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
    async def _api_get(self, path: str, **params) -> dict | list:
        """GET from the JSON API.  Raises httpx errors on failure."""
        url = f"{_API}{path}"
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return resp.json()

    async def _site_get(self, path: str, **params) -> str:
        """GET from the public website HTML."""
        url = f"{_SITE}{path}"
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # API response → SManga helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _manga_from_entry(entry: dict) -> SManga:
        slug = entry.get("slug") or entry.get("id") or ""
        slug = str(slug).strip()

        title = entry.get("title") or entry.get("name") or "Unknown"
        title = str(title).strip() or "Unknown"

        thumb = entry.get("cover") or entry.get("thumbnail") or ""
        thumb = str(thumb).strip() or None
        if thumb and not thumb.startswith("http"):
            thumb = f"{_SITE}{thumb}"

        # author/artist may be a string or a dict {"name": "..."}
        author_raw = entry.get("author")
        if isinstance(author_raw, dict):
            author: str | None = str(author_raw.get("name") or "").strip() or None
        else:
            author = str(author_raw).strip() if author_raw else None

        artist_raw = entry.get("artist")
        if isinstance(artist_raw, dict):
            artist: str | None = str(artist_raw.get("name") or "").strip() or None
        else:
            artist = str(artist_raw).strip() if artist_raw else None

        status_str = str(entry.get("status") or "").lower()
        status = _STATUS_MAP.get(status_str, STATUS_UNKNOWN)

        genres_raw = entry.get("genres") or []
        if isinstance(genres_raw, list):
            genre: str | None = ", ".join(
                g.get("name", g) if isinstance(g, dict) else str(g)
                for g in genres_raw
            ) or None
        else:
            genre = str(genres_raw).strip() or None

        desc_raw = entry.get("description") or entry.get("synopsis") or ""
        desc = str(desc_raw).strip() or None

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
    # HTML helpers — used when API is unavailable
    # ------------------------------------------------------------------
    def _extract_next_data(self, html: str) -> dict | None:
        """Extract __NEXT_DATA__ JSON blob embedded in Next.js pages."""
        m = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([^<]+)</script>',
            html,
        )
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        return None

    def _mangas_from_html(self, html: str) -> list[SManga]:
        """Parse manga cards from a series listing HTML page."""
        # Try __NEXT_DATA__ first (Next.js embeds all page props as JSON)
        nd = self._extract_next_data(html)
        if nd:
            try:
                props = nd["props"]["pageProps"]
                series_list = (
                    props.get("series")
                    or props.get("data")
                    or props.get("comics")
                    or []
                )
                if series_list:
                    return [
                        self._manga_from_entry(e)
                        for e in series_list
                        if isinstance(e, dict)
                    ]
            except (KeyError, TypeError):
                pass

        # HTML card fallback
        soup = BeautifulSoup(html, "html.parser")
        items: list[SManga] = []
        for card in soup.select(
            "div[class*='series-card'], div[class*='comic-card'], "
            "div[class*='manga-card'], a[href*='/series/']"
        ):
            link = card if card.name == "a" else card.find("a", href=True)
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", "")).rstrip("/")
            parts = [p for p in href.split("/") if p]
            if not parts:
                continue
            slug = parts[-1]
            title_el = card.find(["h3", "h4", "h5", "h2"])
            title = title_el.get_text(strip=True) if title_el else slug
            img = card.find("img")
            thumb: str | None = None
            if isinstance(img, Tag):
                thumb = (
                    str(img.get("src") or "").strip()
                    or str(img.get("data-src") or "").strip()
                    or None
                )
            if slug and title:
                items.append(SManga(url=slug, title=title, thumbnail_url=thumb))
        return items

    # ------------------------------------------------------------------
    # CatalogueSource: manga lists
    # ------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        try:
            data = await self._api_get("/series", page=page, order="rating")
            return self._page_from_api(data)
        except (httpx.HTTPStatusError, httpx.RequestError):
            # Fall back to HTML scraping
            try:
                html = await self._site_get("/series", page=page, order="rating")
                mangas = self._mangas_from_html(html)
                return MangasPage(
                    mangas=mangas,
                    has_next_page=len(mangas) >= _DEFAULT_PAGE_SIZE,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                raise RuntimeError(
                    f"Asura Scans is currently unavailable ({exc})."
                ) from exc

    async def get_latest_updates(self, page: int) -> MangasPage:
        try:
            data = await self._api_get("/series", page=page, order="update")
            return self._page_from_api(data)
        except (httpx.HTTPStatusError, httpx.RequestError):
            try:
                html = await self._site_get("/series", page=page, order="latest")
                mangas = self._mangas_from_html(html)
                return MangasPage(
                    mangas=mangas,
                    has_next_page=len(mangas) >= _DEFAULT_PAGE_SIZE,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                raise RuntimeError(
                    f"Asura Scans is currently unavailable ({exc})."
                ) from exc

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        try:
            data = await self._api_get("/series", page=page, search=query)
            return self._page_from_api(data)
        except (httpx.HTTPStatusError, httpx.RequestError):
            try:
                html = await self._site_get("/series", page=page, search=query)
                mangas = self._mangas_from_html(html)
                return MangasPage(
                    mangas=mangas,
                    has_next_page=len(mangas) >= _DEFAULT_PAGE_SIZE,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                raise RuntimeError(
                    f"Asura Scans search failed ({exc})."
                ) from exc

    def _page_from_api(self, data: dict | list) -> MangasPage:
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

        mangas = [
            self._manga_from_entry(e) for e in series_list if isinstance(e, dict)
        ]
        return MangasPage(mangas=mangas, has_next_page=has_next)

    def get_filter_list(self) -> FilterList:
        return []

    # ------------------------------------------------------------------
    # Source: detail
    # ------------------------------------------------------------------
    async def get_manga_details(self, manga: SManga) -> SManga:
        try:
            data = await self._api_get(f"/series/{manga.url}")
        except (httpx.HTTPStatusError, httpx.RequestError):
            return manga

        # API returns {"series": {...}} for details
        if isinstance(data, dict):
            entry = data.get("series") or data.get("data") or data
        elif isinstance(data, list) and data:
            entry = data[0]
        else:
            return manga

        if not isinstance(entry, dict):
            return manga
        return self._manga_from_entry(entry)

    # ------------------------------------------------------------------
    # Source: chapters
    # ------------------------------------------------------------------
    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        try:
            data = await self._api_get(f"/series/{manga.url}/chapters")
        except (httpx.HTTPStatusError, httpx.RequestError):
            return []

        # API returns {"data": [{number, title, slug, ...}]}
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

            ch_slug = str(entry.get("slug") or entry.get("id") or "").strip()
            title_raw = entry.get("title")
            ch_name = str(title_raw).strip() if title_raw else f"Chapter {entry.get('number', '')}"
            try:
                ch_num = float(entry.get("number") or entry.get("chapterNumber") or -1)
            except (ValueError, TypeError):
                ch_num = -1.0

            date_raw = entry.get("updatedAt") or entry.get("date") or ""
            ts = 0
            if date_raw:
                try:
                    dt = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
                    ts = int(dt.timestamp() * 1000)
                except Exception:
                    pass

            chapters.append(
                SChapter(
                    url=f"{manga.url}/{ch_slug}",
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
        URL stored in chapter is "{series_slug}/{chapter_slug}".
        API: GET /series/{series_slug}/chapters/{chapter_slug}
             → {"data": {"chapter": {"pages": [{"url": "..."}]}}}
        Falls back to HTML scraping of the reader page.
        """
        parts = chapter.url.split("/", 1)
        manga_slug = parts[0]
        ch_slug = parts[1] if len(parts) > 1 else ""

        # Try API first
        if ch_slug:
            try:
                data = await self._api_get(
                    f"/series/{manga_slug}/chapters/{ch_slug}"
                )
                pages = self._pages_from_api(data)
                if pages:
                    return pages
            except (httpx.HTTPStatusError, httpx.RequestError):
                pass

        # HTML fallback: reader at https://asuracomic.net/series/{slug}/{ch_slug}/
        try:
            html = await self._site_get(f"/series/{manga_slug}/{ch_slug}/")
            return self._pages_from_html(html)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            raise RuntimeError(
                f"Could not load chapter pages ({exc})."
            ) from exc

    @staticmethod
    def _pages_from_api(data: dict | list) -> list[Page]:
        """Extract page image URLs from the chapters detail API response."""
        if not isinstance(data, dict):
            return []
        chapter_data = (
            (data.get("data") or {}).get("chapter")
            or data.get("chapter")
            or {}
        )
        raw_pages = chapter_data.get("pages") or []
        pages: list[Page] = []
        for i, p in enumerate(raw_pages):
            if isinstance(p, dict):
                url = str(p.get("url") or p.get("image") or "").strip()
            else:
                url = str(p).strip() if p else ""
            if url and url.startswith("http"):
                pages.append(Page(index=i, image_url=url))
        return pages

    def _pages_from_html(self, html: str) -> list[Page]:
        """Extract page image URLs from the reader HTML page."""
        # Try __NEXT_DATA__ first
        nd = self._extract_next_data(html)
        if nd:
            try:
                props = nd["props"]["pageProps"]
                pages_raw = (
                    props.get("pages")
                    or props.get("images")
                    or (props.get("chapter") or {}).get("pages")
                    or []
                )
                if pages_raw:
                    result: list[Page] = []
                    for i, p in enumerate(pages_raw):
                        if isinstance(p, dict):
                            url = str(p.get("url") or p.get("image") or "").strip()
                        else:
                            url = str(p).strip() if p else ""
                        if url and url.startswith("http"):
                            result.append(Page(index=i, image_url=url))
                    if result:
                        return result
            except (KeyError, TypeError):
                pass

        # JSON blob extraction: "images":["url1",...]
        m = re.search(r'"images"\s*:\s*(\[.*?\])', html, re.DOTALL)
        if m:
            try:
                urls = json.loads(m.group(1))
                if isinstance(urls, list):
                    result = [
                        Page(index=i, image_url=str(u))
                        for i, u in enumerate(urls)
                        if isinstance(u, str) and u.startswith("http")
                    ]
                    if result:
                        return result
            except Exception:
                pass

        # HTML <img> fallback
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(
            "div#chapter-container, div.reading-content, "
            "main div[class*='chapter'], div[class*='reader']"
        )
        imgs = container.find_all("img") if container else []
        if not imgs:
            imgs = [
                img for img in soup.find_all("img")
                if (s := str(img.get("src") or ""))
                and s.startswith("http")
                and "thumb" not in s.lower()
            ]

        pages: list[Page] = []
        for i, img in enumerate(imgs):
            if not isinstance(img, Tag):
                continue
            src = (
                str(img.get("src") or "").strip()
                or str(img.get("data-src") or "").strip()
                or str(img.get("data-lazy-src") or "").strip()
            )
            if src and src.startswith("http"):
                pages.append(Page(index=i, image_url=src))
        return pages
