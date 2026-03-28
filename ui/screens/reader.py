"""
Reader screen — full-screen page-by-page / webtoon reader.

Keyboard controls
-----------------
← / h          Previous page
→ / l          Next page
j / k          Scroll up/down (webtoon mode)
[ / ]          Previous / next chapter
m              Cycle reading mode (single → double → webtoon → single)
f              Toggle fullscreen / zen mode
b              Cycle background colour (dark → light → sepia)
d              Download current chapter
q / Escape     Exit reader
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.screen import Screen
from textual.widgets import Button, Label, ProgressBar, Static, Footer

from source_api.models import SManga, SChapter, Page

if TYPE_CHECKING:
    from source_api.sources.mangadex import MangaDexSource

CACHE_DIR = Path.home() / ".manhwa-reader" / "cache"

BACKGROUNDS = ["dark", "light", "sepia"]
MODES = ["single", "double", "webtoon"]


class PageDisplay(Static):
    """Renders a single manga page (or double-page spread)."""

    DEFAULT_CSS = """
    PageDisplay {
        height: 1fr;
        content-align: center middle;
        overflow: auto;
    }
    """

    def set_content(self, text: str) -> None:
        self.update(text)


class NavBar(Horizontal):
    """Bottom navigation bar with chapter/page controls."""

    DEFAULT_CSS = """
    NavBar {
        height: 3;
        dock: bottom;
        background: $panel;
        align: center middle;
        padding: 0 1;
    }
    NavBar Button {
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    NavBar Label {
        content-align: center middle;
        min-width: 14;
    }
    """

    def compose(self) -> ComposeResult:
        yield Button("◄ Prev Chapter", id="btn-prev-chap", variant="default")
        yield Button("◄◄", id="btn-prev-page", variant="default")
        yield Label("Page - / -", id="lbl-page")
        yield Button("►►", id="btn-next-page", variant="default")
        yield Button("Next Chapter ►", id="btn-next-chap", variant="default")


class ReaderScreen(Screen):
    """Full-screen reader pushed on top of MangaDetail."""

    BINDINGS = [
        Binding("left,h", "prev_page", "Prev page"),
        Binding("right,l", "next_page", "Next page"),
        Binding("j", "scroll_down", "Scroll down"),
        Binding("k", "scroll_up", "Scroll up"),
        Binding("[", "prev_chapter", "Prev chapter"),
        Binding("]", "next_chapter", "Next chapter"),
        Binding("m", "cycle_mode", "Mode"),
        Binding("f", "toggle_zen", "Zen"),
        Binding("b", "cycle_bg", "Background"),
        Binding("d", "download", "Download"),
        Binding("q,escape", "quit_reader", "Exit"),
    ]

    DEFAULT_CSS = """
    ReaderScreen {
        layout: vertical;
    }
    ReaderScreen #reader-status-bar {
        height: 1;
        dock: top;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    ReaderScreen #reader-progress {
        height: 1;
        dock: top;
        display: none;
    }
    ReaderScreen.zen #reader-status-bar { display: none; }
    ReaderScreen.zen NavBar { display: none; }
    """

    def __init__(
        self,
        manga: SManga,
        chapters: list[SChapter],
        chapter_index: int,
        source,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.manga = manga
        self.chapters = chapters
        self.chapter_index = chapter_index
        self.source = source

        self._pages: list[Page] = []
        self._page_index: int = 0
        self._mode: str = "single"
        self._bg_index: int = 0
        self._zen: bool = False
        self._loading: bool = False

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static("", id="reader-status-bar")
        yield ProgressBar(total=100, show_eta=False, id="reader-progress")
        yield PageDisplay(id="page-display")
        yield NavBar()

    async def on_mount(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Restore last-read mode from settings
        try:
            from core.settings import Settings
            self._mode = Settings().default_reading_mode
        except Exception:
            pass
        # _load_chapter is a @work method — call without await
        self._load_chapter()

    # ------------------------------------------------------------------
    # Chapter loading
    # ------------------------------------------------------------------
    @work(exclusive=True)
    async def _load_chapter(self) -> None:
        chapter = self.chapters[self.chapter_index]
        self._update_status("Loading chapter…")
        self._show_progress(True)

        try:
            self._pages = await self.source.get_page_list(chapter)
        except Exception as exc:
            self._update_status(f"Error loading chapter: {exc}")
            self._show_error(f"Failed to load chapter: {exc}")
            self._show_progress(False)
            return

        # Restore last-read page
        try:
            from core.history import History
            self._page_index = History().get_last_page(chapter.url)
        except Exception:
            self._page_index = 0

        self._page_index = min(self._page_index, max(0, len(self._pages) - 1))
        self._show_progress(False)
        await self._display_current_page()

    # ------------------------------------------------------------------
    # Page display
    # ------------------------------------------------------------------
    async def _display_current_page(self) -> None:
        if not self._pages:
            return

        display = self.query_one(PageDisplay)
        chapter = self.chapters[self.chapter_index]

        # Update nav bar labels
        self.query_one("#lbl-page", Label).update(
            f"Page {self._page_index + 1} / {len(self._pages)}"
        )
        self._update_status(
            f"{self.manga.title}  |  {chapter.name}  "
            f"|  Mode: {self._mode}  |  [m] mode  [b] bg  [f] zen  [d] dl  [q] exit"
        )

        if self._mode == "webtoon":
            await self._render_webtoon(display)
        elif self._mode == "double":
            await self._render_double(display)
        else:
            await self._render_single(display, self._page_index)

        # Auto-mark as read on last page
        if self._page_index >= len(self._pages) - 1:
            self._mark_read()

        # Persist last-read page
        try:
            from core.history import History
            History().record(
                manga_url=self.manga.url,
                title=self.manga.title,
                thumbnail_url=self.manga.thumbnail_url,
                chapter_url=chapter.url,
                chapter_name=chapter.name,
                page=self._page_index,
            )
        except Exception:
            pass

    async def _render_single(self, display: PageDisplay, idx: int) -> None:
        page = self._pages[idx]
        image_text = await self._fetch_and_render(page)
        display.set_content(image_text)

    async def _render_double(self, display: PageDisplay) -> None:
        left = await self._fetch_and_render(self._pages[self._page_index])
        right_idx = self._page_index + 1
        if right_idx < len(self._pages):
            right = await self._fetch_and_render(self._pages[right_idx])
            display.set_content(f"{left}   {right}")
        else:
            display.set_content(left)

    async def _render_webtoon(self, display: PageDisplay) -> None:
        """Show all pages stacked vertically (show current chunk)."""
        # For webtoon show a window of pages around current
        start = max(0, self._page_index - 1)
        end = min(len(self._pages), self._page_index + 3)
        parts = []
        for i in range(start, end):
            text = await self._fetch_and_render(self._pages[i])
            parts.append(text)
        display.set_content("\n".join(parts))

    async def _fetch_and_render(self, page: Page) -> str:
        """Download page image (using cache) and render via term-image."""
        url = page.image_url or page.url
        if not url:
            return "[No image URL]"

        # Use a hash of the full URL as cache key to avoid filename collisions
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        cache_key = f"{url_hash}{ext}"
        cache_path = CACHE_DIR / cache_key

        if not cache_path.exists():
            try:
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    cache_path.write_bytes(resp.content)
            except Exception as exc:
                return f"[Download error: {exc}]"

        return self._render_image(cache_path)

    @staticmethod
    def _render_image(path: Path) -> str:
        """Render image file to a terminal-compatible string."""
        try:
            from term_image.image import AutoImage
            img = AutoImage(str(path))
            # Set a reasonable size
            img.set_size(width=80)
            return str(img)
        except ImportError:
            # term-image not installed — show URL placeholder
            return f"📄 {path.name}\n[Install term-image for image rendering]"
        except Exception:
            # Terminal doesn't support image rendering — fall back gracefully
            return f"📄 {path.name}\n[Image: {path.name}]"

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------
    async def action_prev_page(self) -> None:
        if self._mode == "double":
            self._page_index = max(0, self._page_index - 2)
        else:
            self._page_index = max(0, self._page_index - 1)
        await self._display_current_page()

    async def action_next_page(self) -> None:
        if self._mode == "double":
            self._page_index = min(len(self._pages) - 1, self._page_index + 2)
        else:
            self._page_index = min(len(self._pages) - 1, self._page_index + 1)
        await self._display_current_page()

    async def action_scroll_down(self) -> None:
        if self._mode == "webtoon":
            await self.action_next_page()

    async def action_scroll_up(self) -> None:
        if self._mode == "webtoon":
            await self.action_prev_page()

    def action_prev_chapter(self) -> None:
        if self.chapter_index > 0:
            self.chapter_index -= 1
            self._page_index = 0
            # _load_chapter is a @work method — call without await
            self._load_chapter()

    def action_next_chapter(self) -> None:
        if self.chapter_index < len(self.chapters) - 1:
            self.chapter_index += 1
            self._page_index = 0
            # _load_chapter is a @work method — call without await
            self._load_chapter()

    def action_cycle_mode(self) -> None:
        idx = (MODES.index(self._mode) + 1) % len(MODES)
        self._mode = MODES[idx]
        self._update_status(f"Mode: {self._mode}")

    def action_toggle_zen(self) -> None:
        self._zen = not self._zen
        if self._zen:
            self.add_class("zen")
        else:
            self.remove_class("zen")

    def action_cycle_bg(self) -> None:
        self._bg_index = (self._bg_index + 1) % len(BACKGROUNDS)
        bg = BACKGROUNDS[self._bg_index]
        display = self.query_one(PageDisplay)
        if bg == "dark":
            display.styles.background = "#1a1a1a"
            display.styles.color = "#e0e0e0"
        elif bg == "light":
            display.styles.background = "#f5f5f5"
            display.styles.color = "#1a1a1a"
        elif bg == "sepia":
            display.styles.background = "#f4ecd8"
            display.styles.color = "#5c4a1e"

    def action_download(self) -> None:
        chapter = self.chapters[self.chapter_index]
        try:
            self.app.downloader.enqueue(
                manga_url=self.manga.url,
                manga_title=self.manga.title,
                chapter_url=chapter.url,
                chapter_name=chapter.name,
                page_urls=[p.image_url or p.url for p in self._pages],
            )
            self._update_status("Download queued!")
        except Exception as exc:
            self._update_status(f"Download error: {exc}")

    def action_quit_reader(self) -> None:
        self.app.pop_screen()

    # ------------------------------------------------------------------
    # Button events
    # ------------------------------------------------------------------
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-prev-page":
            await self.action_prev_page()
        elif bid == "btn-next-page":
            await self.action_next_page()
        elif bid == "btn-prev-chap":
            self.action_prev_chapter()
        elif bid == "btn-next-chap":
            self.action_next_chapter()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _update_status(self, text: str) -> None:
        try:
            self.query_one("#reader-status-bar", Static).update(text)
        except Exception:
            pass

    def _show_progress(self, visible: bool) -> None:
        try:
            bar = self.query_one("#reader-progress", ProgressBar)
            bar.display = visible
        except Exception:
            pass

    def _show_error(self, message: str) -> None:
        """Display an error message in the page area."""
        try:
            self.query_one(PageDisplay).set_content(
                f"[bold red]⚠ Error[/bold red]\n\n{message}\n\n"
                "[dim]Press [q] to go back or [[] / []] to switch chapters.[/dim]"
            )
        except Exception:
            pass

    def _mark_read(self) -> None:
        try:
            from core.history import History
            chapter = self.chapters[self.chapter_index]
            History().record(
                manga_url=self.manga.url,
                title=self.manga.title,
                thumbnail_url=self.manga.thumbnail_url,
                chapter_url=chapter.url,
                chapter_name=chapter.name,
                page=len(self._pages) - 1,
            )
        except Exception:
            pass
