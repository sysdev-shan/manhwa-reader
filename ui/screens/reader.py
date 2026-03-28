"""
Reader screen — launches an external GUI window (tkinter + Pillow) to display
chapter pages.  The Textual screen acts as a coordinator: it fetches the page
list, opens the viewer window, and handles the result (next/prev chapter or
quit).

The viewer window supports:
  ←/→ or h/l  previous / next page
  j / k        scroll down / up (webtoon mode)
  [ / ]        previous / next chapter (auto-opens next window)
  m            cycle reading mode (webtoon → single → double)
  b            cycle background colour (dark → light → sepia)
  f            toggle fullscreen
  d            download current chapter
  + / -        zoom in / out
  0            reset zoom
  q / Escape   close viewer (return to manga detail)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Label, ProgressBar, Static

from source_api.models import SManga, SChapter

if TYPE_CHECKING:
    pass

CACHE_DIR = Path.home() / ".manhwa-reader" / "cache"


class ReaderScreen(Screen):
    """
    Coordinator screen.  Opens a GUI viewer window for each chapter and
    manages transitions between chapters.

    The screen itself stays in the Textual stack (invisible while the viewer
    window is open) so that the app remains alive.  When the viewer closes
    with 'quit' this screen is popped off the stack.
    """

    BINDINGS = [
        Binding("q,escape", "quit_reader", "Exit reader"),
    ]

    DEFAULT_CSS = """
    ReaderScreen {
        layout: vertical;
        align: center middle;
    }
    ReaderScreen #reader-status {
        content-align: center middle;
        padding: 2 4;
        color: $text-muted;
    }
    ReaderScreen #reader-progress {
        width: 40;
        display: none;
    }
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

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static("Opening chapter viewer…", id="reader-status")
        yield ProgressBar(total=100, show_eta=False, id="reader-progress")

    async def on_mount(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._open_chapter()

    # ------------------------------------------------------------------
    # Chapter orchestration
    # ------------------------------------------------------------------
    @work(exclusive=True)
    async def _open_chapter(self) -> None:
        """Fetch pages and open the GUI viewer window."""
        if self.chapter_index < 0 or self.chapter_index >= len(self.chapters):
            self.app.pop_screen()
            return

        chapter = self.chapters[self.chapter_index]
        self._set_status(f"Loading  {chapter.name} …")
        self._show_progress(True)

        # Fetch page URLs
        try:
            pages = await self.source.get_page_list(chapter)
        except Exception as exc:
            self._set_status(f"[bold red]Error loading chapter:[/bold red] {exc}")
            self._show_progress(False)
            return

        if not pages:
            self._set_status("[bold red]No pages found for this chapter.[/bold red]")
            self._show_progress(False)
            return

        self._show_progress(False)
        self._set_status(f"Opening  {chapter.name}  ({len(pages)} pages)…")

        # Restore last-read page
        initial_page = 0
        try:
            from core.history import History
            initial_page = History().get_last_page(chapter.url)
        except Exception:
            pass
        initial_page = min(initial_page, max(len(pages) - 1, 0))

        # Get reading mode from settings
        mode = "webtoon"
        try:
            from core.settings import Settings
            mode = Settings().default_reading_mode
        except Exception:
            pass

        # Build download callback
        def _download_pages(pg_list):
            chapter_ = self.chapters[self.chapter_index]
            self.app.downloader.enqueue(
                manga_url=self.manga.url,
                manga_title=self.manga.title,
                chapter_url=chapter_.url,
                chapter_name=chapter_.name,
                page_urls=[p.image_url or p.url for p in pg_list],
            )

        # Run the viewer in a thread-pool thread so the Textual event
        # loop remains responsive while the Tk window is open.
        try:
            from ui.image_viewer import ChapterViewer
        except ImportError as exc:
            self._set_status(
                f"[bold red]GUI viewer unavailable:[/bold red] {exc}\n\n"
                "Install Pillow:  pip install Pillow"
            )
            return

        viewer = ChapterViewer(
            pages=pages,
            manga_title=self.manga.title,
            chapter_name=chapter.name,
            initial_page=initial_page,
            mode=mode,
            on_download=_download_pages,
        )

        loop = asyncio.get_event_loop()
        try:
            action, final_page = await loop.run_in_executor(None, viewer.run)
        except RuntimeError as exc:
            self._set_status(f"[bold red]Cannot open viewer window:[/bold red] {exc}")
            return

        # Persist read position
        try:
            from core.history import History
            History().record(
                manga_url=self.manga.url,
                title=self.manga.title,
                thumbnail_url=self.manga.thumbnail_url,
                chapter_url=chapter.url,
                chapter_name=chapter.name,
                page=final_page,
            )
        except Exception:
            pass

        # Handle result from viewer
        if action == "next_chapter":
            if self.chapter_index < len(self.chapters) - 1:
                self.chapter_index += 1
                self._open_chapter()
            else:
                self._set_status("End of series — no more chapters.")
        elif action == "prev_chapter":
            if self.chapter_index > 0:
                self.chapter_index -= 1
                self._open_chapter()
            else:
                self._set_status("Already at the first chapter.")
        else:
            # "quit" — return to manga detail
            self.app.pop_screen()

    def action_quit_reader(self) -> None:
        self.app.pop_screen()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#reader-status", Static).update(text)
        except Exception:
            pass

    def _show_progress(self, visible: bool) -> None:
        try:
            self.query_one("#reader-progress", ProgressBar).display = visible
        except Exception:
            pass
