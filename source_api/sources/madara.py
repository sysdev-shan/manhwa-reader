"""
Generic scraper for WordPress sites that use the **Madara** manga theme.

Many popular scanlation and aggregator sites share this theme and expose the
same `wp-admin/admin-ajax.php` endpoints.  Subclass `MadaraSource`, set
`BASE_URL` (and optionally `MANGA_URL_PATH`, `DATE_FORMAT`, etc.) and the
source works without extra code.

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
    "Referer": "",
}


class MadaraSource(HttpSource):
    """
    Base class for Madara WordPress manga sites.

    Required class attribute
    -----------------------
    BASE_URL : str   — root URL of the site (no trailing slash)

    Optional overrides
    ------------------
    MANGA_URL_PATH  : path segment between BASE_URL and the manga slug
                      (default: "manga")
    DATE_FORMAT     : strptime format string for chapter dates
                      (default: "%B %d, %Y")
    POSTS_PER_PAGE  : how many manga to request per page (default 20)
    SOURCE_NAME     : human-readable label (default: class name)
    SOURCE_LANG     : ISO-639-1 language code (default: "en")
    """

    BASE_URL: ClassVar[str]  # must be set by subclass
    MANGA_URL_PATH: ClassVar[str] = "manga"
    DATE_FORMAT: ClassVar[str] = "%B %d, %Y"
    POSTS_PER_PAGE: ClassVar[int] = 20
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

    async def _get_soup(self, url: str, **params) -> BeautifulSoup:
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params or None)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")

    async def _ajax_post(self, data: dict) -> str:
        url = f"{self.BASE_URL}/wp-admin/admin-ajax.php"
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            text = resp.text
            # admin-ajax may return JSON {"success": true, "data": "<html>"}
            if text.startswith("{"):
                import json
                try:
                    payload = json.loads(text)
                    return payload.get("data", text)
                except Exception:
                    pass
            return text

    # ------------------------------------------------------------------
    # HTML parsers
    # ------------------------------------------------------------------
    def _parse_manga_list(self, html: str) -> list[SManga]:
        """Parse manga from an admin-ajax HTML fragment."""
        soup = BeautifulSoup(html, "html.parser")
        items: list[SManga] = []
        for item in soup.select("div.page-item-detail, div.c-image-hover"):
            link = item.find("a", href=True)
            if not link:
                continue
            url = str(link["href"]).rstrip("/").split("/")[-1]
            title = link.get("title") or ""
            # Try heading
            h = item.find(["h3", "h5", "h4"])
            if h and h.get_text(strip=True):
                title = h.get_text(strip=True)
            img = item.find("img")
            thumb: str | None = None
            if img:
                thumb = (
                    str(img.get("data-src", ""))
                    or str(img.get("src", ""))
                    or None
                )
            if url and title:
                items.append(SManga(url=url, title=title, thumbnail_url=thumb or None))
        return items

    # ------------------------------------------------------------------
    # CatalogueSource: manga lists
    # ------------------------------------------------------------------
    async def get_popular_manga(self, page: int) -> MangasPage:
        html = await self._ajax_post(
            {
                "action": "madara_load_more",
                "template": "madara-core/content/content-archive-manga",
                "vars[orderby]": "meta_value_num",
                "vars[meta_key]": "_wp_manga_views",
                "vars[paged]": page - 1,
                "vars[posts_per_page]": self.POSTS_PER_PAGE,
                "vars[post_type]": "wp-manga",
                "vars[post_status]": "publish",
                "vars[template]": "archive-manga",
                "vars[sidebar]": "full",
            }
        )
        mangas = self._parse_manga_list(html)
        return MangasPage(mangas=mangas, has_next_page=len(mangas) >= self.POSTS_PER_PAGE)

    async def get_latest_updates(self, page: int) -> MangasPage:
        html = await self._ajax_post(
            {
                "action": "madara_load_more",
                "template": "madara-core/content/content-archive-manga",
                "vars[orderby]": "date",
                "vars[order]": "DESC",
                "vars[paged]": page - 1,
                "vars[posts_per_page]": self.POSTS_PER_PAGE,
                "vars[post_type]": "wp-manga",
                "vars[post_status]": "publish",
                "vars[template]": "archive-manga",
                "vars[sidebar]": "full",
            }
        )
        mangas = self._parse_manga_list(html)
        return MangasPage(mangas=mangas, has_next_page=len(mangas) >= self.POSTS_PER_PAGE)

    async def get_search_manga(
        self, page: int, query: str, filters: FilterList
    ) -> MangasPage:
        url = f"{self.BASE_URL}/"
        params: dict = {
            "s": query,
            "post_type": "wp-manga",
            "paged": page,
        }
        soup = await self._get_soup(url, **params)
        items: list[SManga] = []
        for item in soup.select("div.c-tabs-item__content, div.page-item-detail"):
            link = item.find("a", href=True)
            if not link:
                continue
            href = str(link["href"]).rstrip("/")
            url_slug = href.split("/")[-1]
            title = link.get("title") or ""
            h = item.find(["h3", "h5", "h4", "h2"])
            if h:
                title = h.get_text(strip=True) or title
            img = item.find("img")
            thumb: str | None = None
            if img:
                thumb = str(img.get("data-src", "")) or str(img.get("src", "")) or None
            if url_slug and title:
                items.append(SManga(url=url_slug, title=title, thumbnail_url=thumb or None))

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
        if img_el:
            thumb = str(img_el.get("data-src", "")) or str(img_el.get("src", "")) or None

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
        # First we need the WordPress post ID from the manga page
        manga_url = f"{self.BASE_URL}/{self.MANGA_URL_PATH}/{manga.url}/"
        soup = await self._get_soup(manga_url)

        post_id: str | None = None
        holder = soup.find(id="manga-chapters-holder")
        if isinstance(holder, Tag):
            post_id = str(holder.get("data-id") or "") or None

        if not post_id:
            # Fallback: look for nonce in page data
            match = re.search(r'"mangaId"\s*:\s*"?(\d+)"?', soup.text)
            if match:
                post_id = match.group(1)

        if post_id:
            html = await self._ajax_post(
                {
                    "action": "manga_get_chapters",
                    "manga": post_id,
                }
            )
        else:
            # Last resort: chapter list is already in the page HTML
            html = str(soup)

        return self._parse_chapter_list(html, manga_url)

    def _parse_chapter_list(self, html: str, manga_url: str) -> list[SChapter]:
        soup = BeautifulSoup(html, "html.parser")
        chapters: list[SChapter] = []
        for li in soup.select("li.wp-manga-chapter, li.a-h"):
            link = li.find("a", href=True)
            if not link:
                continue
            href = str(link["href"]).rstrip("/")
            ch_name = link.get_text(strip=True)
            ch_url = href  # full URL stored; get_page_list uses it directly

            # Date
            ts = 0
            date_el = li.select_one("span.chapter-release-date i, span.chapter-release-date a")
            if date_el:
                date_str = date_el.get_text(strip=True)
                try:
                    dt = datetime.strptime(date_str, self.DATE_FORMAT)
                    ts = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                except ValueError:
                    pass

            # Chapter number
            num = -1.0
            m = re.search(r"chapter[\s\-_]*([\d.]+)", ch_name, re.IGNORECASE)
            if m:
                try:
                    num = float(m.group(1))
                except ValueError:
                    pass

            chapters.append(SChapter(url=ch_url, name=ch_name, date_upload=ts, chapter_number=num))

        return chapters  # already newest-first from Madara

    # ------------------------------------------------------------------
    # Source: pages
    # ------------------------------------------------------------------
    async def get_page_list(self, chapter: SChapter) -> list[Page]:
        """
        Fetch the chapter page and extract image URLs.
        Madara embeds them via: ts_reader.run({"sources":[{"images":["url1",...]}]})
        """
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30.0, follow_redirects=True
        ) as client:
            resp = await client.get(chapter.url)
            resp.raise_for_status()
            html = resp.text

        # Try ts_reader pattern first
        m = re.search(
            r"ts_reader\.run\s*\(\s*(\{.*?\})\s*\)\s*;",
            html,
            re.DOTALL,
        )
        if m:
            import json
            try:
                data = json.loads(m.group(1))
                sources = data.get("sources", [])
                images: list[str] = []
                for src in sources:
                    images.extend(src.get("images", []))
                return [Page(index=i, image_url=url) for i, url in enumerate(images)]
            except Exception:
                pass

        # Fallback: find images in #chapter-content or .reading-content
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(
            "#chapter-content, .reading-content, .page-break, div.entry-content"
        )
        if container:
            imgs = container.find_all("img")
        else:
            imgs = soup.find_all("img", src=re.compile(r"wp-content/uploads"))

        pages: list[Page] = []
        for i, img in enumerate(imgs):
            src = str(img.get("data-src", "")) or str(img.get("src", ""))
            if src and src.startswith("http"):
                pages.append(Page(index=i, image_url=src.strip()))
        return pages
