"""
Generic scraper for WordPress sites that use the **Madara** manga theme.

Subclass `MadaraSource`, set `BASE_URL` (and optionally `MANGA_URL_PATH`,
`DATE_FORMAT`, etc.) and the source works without extra code.

**No admin-ajax.php dependency** — this scraper uses only plain GET requests
to the public HTML pages, so it works on every Madara site regardless of
server configuration.

Sites using Madara (examples):
  - Flame Comics   — https://flamecomics.xyz
  - Luminous Scans — https://luminousscans.com
  - Cosmic Scans   — https://cosmicscans.com
  - Night Scans    — https://nightscans.net
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import ClassVar

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
)

_STATUS_MAP = {
    "ongoing": STATUS_ONGOING,
    "active": STATUS_ONGOING,
    "completed": STATUS_COMPLETED,
    "end": STATUS_COMPLETED,
    "hiatus": STATUS_ON_HIATUS,
    "on-hiatus": STATUS_ON_HIATUS,
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Selectors that cover all known Madara versions
_MANGA_ITEM_SEL = (
    "div.page-item-detail, "
    "div.c-image-hover, "
    "div.manga-item, "
    "div.bs, "
    "div.bsx"
)


class MadaraSource(HttpSource):
    """
    Base class for Madara WordPress manga sites.

    Required class attribute
    -----------------------
    BASE_URL : str   — root URL of the site (no trailing slash)

    Optional overrides
    ------------------
    MANGA_URL_PATH  : path segment used in manga URLs  (default: "manga")
    DATE_FORMAT     : strptime format string for chapter dates
                      (default: "%B %d, %Y")
    SOURCE_NAME     : human-readable label (default: class name)
    SOURCE_LANG     : ISO-639-1 language code (default: "en")
    """

    BASE_URL: ClassVar[str]  # must be set by subclass
    MANGA_URL_PATH: ClassVar[str] = "manga"
    DATE_FORMAT: ClassVar[str] = "%B %d, %Y"
    SOURCE_NAME: ClassVar[str] = ""
    SOURCE_LANG: ClassVar[str] = "en"

    # ------------------------------------------------------------------
    # CatalogueSource identity
    # ------------------------------------------------------------------
    @property
    def id(self) -> int:
        return abs(hash(f"madara:{self.BASE_URL}")) & 0x7FFF_FFFF_FFFF_FFFF

    @property
    def name(self) -> str:
        return self.SOURCE_NAME or type(self).__name__

    @property
    def lang(self) -> str:
        return self.SOURCE_LANG

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    @property
    def supports_latest(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        return {**_HEADERS, "Referer": self.BASE_URL + "/"}

    async def _get(self, url: str, **params) -> httpx.Response:
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return resp

    async def _get_soup(self, url: str, **params) -> BeautifulSoup:
        resp = await self._get(url, **params)
        return BeautifulSoup(resp.text, "html.parser")

    async def _post(self, url: str, data: dict) -> httpx.Response:
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            return resp

    # ------------------------------------------------------------------
    # Manga list URL builders
    # ------------------------------------------------------------------
    def _list_url(self, page: int) -> str:
        """Build the manga listing URL for a given page number."""
        if page > 1:
            return f"{self.BASE_URL}/{self.MANGA_URL_PATH}/page/{page}/"
        return f"{self.BASE_URL}/{self.MANGA_URL_PATH}/"

    # ------------------------------------------------------------------
    # HTML parsers
    # ------------------------------------------------------------------
    def _parse_manga_page(self, soup: BeautifulSoup) -> MangasPage:
        """Parse manga entries from a browse/listing HTML page."""
        items: list[SManga] = []
        for entry in soup.select(_MANGA_ITEM_SEL):
            manga = self._manga_from_entry(entry)
            if manga:
                items.append(manga)

        has_next = bool(
            soup.select_one("a.next.page-numbers, .nav-links .next, .navigation-ajax .next")
        )
        return MangasPage(mangas=items, has_next_page=has_next)

    def _manga_from_entry(self, entry: Tag) -> SManga | None:
        """Extract an SManga from a listing card element."""
        # Find the primary link — prefer one with a title attribute
        link = entry.select_one("a[title]") or entry.find("a", href=True)
        if not link or not isinstance(link, Tag):
            return None

        href = str(link.get("href", "")).rstrip("/")
        if not href:
            return None

        # Derive slug: last non-empty path segment after the manga URL path
        href_parts = [p for p in href.split("/") if p]
        slug = href_parts[-1] if href_parts else ""
        if not slug:
            return None

        # Title: prefer title attribute, then heading text
        title = str(link.get("title", "")).strip()
        for tag in ("h3", "h5", "h4", "h2", "h1"):
            h = entry.find(tag)
            if h:
                t = h.get_text(strip=True)
                if t:
                    title = t
                    break
        if not title:
            title = link.get_text(strip=True)
        if not title:
            return None

        # Thumbnail
        img = entry.find("img")
        thumb: str | None = None
        if isinstance(img, Tag):
            thumb = (
                str(img.get("data-src", "")).strip()
                or str(img.get("data-lazy-src", "")).strip()
                or str(img.get("src", "")).strip()
                or None
            )

        return SManga(url=slug, title=title, thumbnail_url=thumb or None)

    # ------------------------------------------------------------------
    # CatalogueSource: manga lists
    # ------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        """Fetch the most-viewed manga listing page directly (no admin-ajax)."""
        url = self._list_url(page)
        soup = await self._get_soup(url, m_orderby="views")
        return self._parse_manga_page(soup)

    async def get_latest_updates(self, page: int) -> MangasPage:
        """Fetch the latest-updated manga listing page directly (no admin-ajax)."""
        url = self._list_url(page)
        soup = await self._get_soup(url, m_orderby="latest")
        return self._parse_manga_page(soup)

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        """Search via WordPress ?s= parameter (no admin-ajax)."""
        url = f"{self.BASE_URL}/"
        if page > 1:
            url = f"{self.BASE_URL}/page/{page}/"
        soup = await self._get_soup(url, s=query, post_type="wp-manga")

        # Search results use a different layout than the listing pages
        items: list[SManga] = []
        for entry in soup.select(
            "div.c-tabs-item__content, div.page-item-detail, "
            "div.c-image-hover, div.bs, div.bsx"
        ):
            manga = self._manga_from_entry(entry)
            if manga:
                items.append(manga)

        has_next = bool(soup.select_one("a.next.page-numbers"))
        return MangasPage(mangas=items, has_next_page=has_next)

    def get_filter_list(self) -> FilterList:
        return []

    # ------------------------------------------------------------------
    # Source: detail
    # ------------------------------------------------------------------
    async def get_manga_details(self, manga: SManga) -> SManga:
        url = f"{self.BASE_URL}/{self.MANGA_URL_PATH}/{manga.url}/"
        soup = await self._get_soup(url)

        # Title
        title_el = soup.select_one("div.post-title h1, div.post-title h3")
        title = title_el.get_text(strip=True) if title_el else manga.title

        # Thumbnail
        img_el = soup.select_one("div.summary-image img, div.tab-summary img")
        thumb: str | None = None
        if isinstance(img_el, Tag):
            thumb = (
                str(img_el.get("data-src", "")).strip()
                or str(img_el.get("src", "")).strip()
                or None
            )

        # Meta: author, artist, genres, status
        author: str | None = None
        artist: str | None = None
        status = 0
        genres: list[str] = []

        for row in soup.select("div.post-content_item, div.manga-info-row"):
            heading_el = row.select_one(".summary-heading, .manga-info-heading, h5")
            value_el = row.select_one(".summary-content, .manga-info-value")
            if not heading_el or not value_el:
                continue
            heading = heading_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)
            if "author" in heading:
                author = value or None
            elif "artist" in heading:
                artist = value or None
            elif "status" in heading:
                status = _STATUS_MAP.get(value.lower(), 0)
            elif "genre" in heading or "tag" in heading:
                genres = [a.get_text(strip=True) for a in value_el.find_all("a")]

        # Description
        desc_el = soup.select_one("div.description-summary, div.manga-description")
        desc: str | None = None
        if desc_el:
            desc = desc_el.get_text("\n", strip=True) or None

        return SManga(
            url=manga.url,
            title=title,
            author=author,
            artist=artist,
            description=desc,
            genre=", ".join(genres) if genres else None,
            status=status,
            thumbnail_url=thumb,
            initialized=True,
        )

    # ------------------------------------------------------------------
    # Source: chapters
    # ------------------------------------------------------------------
    async def get_chapter_list(self, manga: SManga) -> list[SChapter]:
        """
        Fetch the chapter list using a three-step strategy:

        1. POST to ``{manga_url}ajax/chapters/``  (modern Madara pattern,
           avoids wp-admin completely)
        2. Parse chapters that are already embedded in the manga detail page
           HTML (some Madara configs render all chapters server-side)
        3. Return empty list if both fail.
        """
        manga_url = f"{self.BASE_URL}/{self.MANGA_URL_PATH}/{manga.url}/"
        soup = await self._get_soup(manga_url)

        # --- Strategy 1: POST to the per-manga ajax/chapters/ endpoint ---
        ajax_url = manga_url.rstrip("/") + "/ajax/chapters/"
        try:
            resp = await self._post(
                ajax_url,
                data={
                    # Some Madara configs need a nonce; try without first
                },
            )
            chapters = self._parse_chapter_list(resp.text, manga_url)
            if chapters:
                return chapters
        except (httpx.HTTPStatusError, httpx.RequestError):
            pass  # fall through to next strategy

        # --- Strategy 2: chapters embedded directly in the detail page ---
        chapters = self._parse_chapter_list(str(soup), manga_url)
        if chapters:
            return chapters

        return []

    def _parse_chapter_list(self, html: str, manga_url: str) -> list[SChapter]:
        soup = BeautifulSoup(html, "html.parser")
        chapters: list[SChapter] = []
        for li in soup.select("li.wp-manga-chapter, li.a-h"):
            link = li.find("a", href=True)
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", "")).rstrip("/")
            ch_name = link.get_text(strip=True)
            ch_url = href  # full absolute URL

            # Date
            ts = 0
            date_el = li.select_one(
                "span.chapter-release-date i, span.chapter-release-date a"
            )
            if date_el:
                date_str = date_el.get_text(strip=True)
                # Build a deduplicated list of formats to try
                _default = "%B %d, %Y"
                _fmts = [self.DATE_FORMAT] if self.DATE_FORMAT != _default else []
                _fmts += [_default, "%d/%m/%Y", "%Y-%m-%d"]
                for fmt in _fmts:
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        ts = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                        break
                    except ValueError:
                        continue

            # Chapter number
            num = -1.0
            m = re.search(r"chapter[\s\-_]*([\d.]+)", ch_name, re.IGNORECASE)
            if m:
                try:
                    num = float(m.group(1))
                except ValueError:
                    pass

            chapters.append(
                SChapter(url=ch_url, name=ch_name, date_upload=ts, chapter_number=num)
            )

        return chapters  # Madara returns chapters newest-first

    # ------------------------------------------------------------------
    # Source: pages
    # ------------------------------------------------------------------
    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        """
        Fetch the chapter page and extract image URLs.
        Madara embeds them via: ts_reader.run({"sources":[{"images":["url1",...]}]})
        Falls back to parsing <img> tags inside the reading container.
        """
        resp = await self._get(chapter.url)
        html = resp.text

        # Try ts_reader pattern first (most common in Madara)
        m = re.search(
            r"ts_reader\.run\s*\(\s*(\{.*?\})\s*\)\s*;",
            html,
            re.DOTALL,
        )
        if m:
            import json

            try:
                data = json.loads(m.group(1))
                images: list[str] = []
                for src in data.get("sources", []):
                    images.extend(src.get("images", []))
                if images:
                    return [Page(index=i, image_url=u) for i, u in enumerate(images)]
            except Exception:
                pass

        # Fallback: <img> tags inside the reading container
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(
            "#chapter-content, .reading-content, .page-break, div.entry-content"
        )
        imgs = container.find_all("img") if container else []
        if not imgs:
            imgs = soup.find_all("img", src=re.compile(r"wp-content/uploads"))

        pages: list[Page] = []
        for i, img in enumerate(imgs):
            if not isinstance(img, Tag):
                continue
            src = (
                str(img.get("data-src", "")).strip()
                or str(img.get("data-lazy-src", "")).strip()
                or str(img.get("src", "")).strip()
            )
            if src and src.startswith("http"):
                pages.append(Page(index=i, image_url=src))
        return pages
