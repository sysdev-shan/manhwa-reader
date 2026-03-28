"""
Manga Detail screen — cover image + metadata + chapter list.
"""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Button, Label, Static, LoadingIndicator

from source_api.models import SManga, SChapter
from ui.widgets.chapter_list import ChapterList


class MangaDetailScreen(Screen):
    """Shows manga metadata and chapter list."""

    BINDINGS = [
        Binding("escape,q", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    MangaDetailScreen {
        layout: vertical;
    }
    #detail-header {
        height: auto;
        max-height: 20;
        layout: horizontal;
        background: $panel;
        padding: 1;
    }
    #cover-panel {
        width: 22;
        height: 16;
        content-align: center middle;
        background: $panel-darken-1;
        border: tall $panel;
        margin-right: 1;
    }
    #info-panel {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    #info-panel Label {
        margin-bottom: 1;
    }
    #detail-actions {
        height: 5;
        layout: horizontal;
        align: center middle;
        background: $panel;
        padding: 1;
    }
    #detail-actions Button {
        margin: 0 1;
        min-width: 20;
    }
    #chapters-header {
        height: 2;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    #chapter-list-container {
        height: 1fr;
    }
    #loading-detail {
        height: 3;
        content-align: center middle;
    }
    """

    def __init__(self, manga: SManga, source, **kwargs) -> None:
        super().__init__(**kwargs)
        self.manga = manga
        self.source = source
        self._chapters: list[SChapter] = []
        self._in_library: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="detail-header"):
            yield Static("🖼 Cover", id="cover-panel")
            with Vertical(id="info-panel"):
                yield Label(f"[bold]{self.manga.title}[/bold]", id="lbl-title")
                yield Label(f"Author: {self.manga.author or '—'}", id="lbl-author")
                yield Label(f"Artist: {self.manga.artist or '—'}", id="lbl-artist")
                yield Label(f"Status: {self.manga.status_label()}", id="lbl-status")
                yield Label(f"Genres: {self.manga.genre or '—'}", id="lbl-genre")
                yield Label(
                    (self.manga.description or "No description.")[:300],
                    id="lbl-desc",
                )

        with Horizontal(id="detail-actions"):
            yield Button("Add to Library", id="btn-library", variant="success")
            yield Button("Start Reading", id="btn-read", variant="primary")
            yield Button("Download All", id="btn-dl-all", variant="default")

        yield Label("Chapters (loading…)", id="chapters-header")
        yield LoadingIndicator(id="loading-detail")
        yield ChapterList(id="chapter-list-container")

    async def on_mount(self) -> None:
        self._load_data()
        self._check_library_status()

    # ------------------------------------------------------------------
    @work(exclusive=True)
    async def _load_data(self) -> None:
        try:
            manga = await self.source.get_manga_details(self.manga)
            self.manga = manga
            self._update_info()

            chapters = await self.source.get_chapter_list(self.manga)
            self._chapters = chapters

            # Get read chapters from history
            read_chapters: set[str] = set()
            try:
                from core.history import History
                entry = History().get(self.manga.url)
                if entry:
                    read_chapters.add(entry["last_chapter_url"])
            except Exception:
                pass

            self.query_one(ChapterList).update_chapters(chapters, read_chapters)
            self.query_one("#chapters-header", Label).update(
                f"Chapters ({len(chapters)})"
            )
        except Exception as exc:
            self.query_one("#chapters-header", Label).update(f"Error: {exc}")
        finally:
            self.query_one("#loading-detail", LoadingIndicator).remove()

    def _update_info(self) -> None:
        try:
            self.query_one("#lbl-title", Label).update(
                f"[bold]{self.manga.title}[/bold]"
            )
            self.query_one("#lbl-author", Label).update(
                f"Author: {self.manga.author or '—'}"
            )
            self.query_one("#lbl-artist", Label).update(
                f"Artist: {self.manga.artist or '—'}"
            )
            self.query_one("#lbl-status", Label).update(
                f"Status: {self.manga.status_label()}"
            )
            self.query_one("#lbl-genre", Label).update(
                f"Genres: {self.manga.genre or '—'}"
            )
            self.query_one("#lbl-desc", Label).update(
                (self.manga.description or "No description.")[:300]
            )
        except Exception:
            pass

    def _check_library_status(self) -> None:
        try:
            from core.library import Library
            self._in_library = Library().contains(self.manga.url)
            self._update_library_btn()
        except Exception:
            pass

    def _update_library_btn(self) -> None:
        try:
            btn = self.query_one("#btn-library", Button)
            if self._in_library:
                btn.label = "Remove from Library"
                btn.variant = "error"
            else:
                btn.label = "Add to Library"
                btn.variant = "success"
        except Exception:
            pass

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-library":
            self._toggle_library()
        elif event.button.id == "btn-read":
            self._start_reading(0)
        elif event.button.id == "btn-dl-all":
            self._download_all()

    def on_chapter_list_chapter_selected(self, event: ChapterList.ChapterSelected) -> None:
        idx = next(
            (i for i, c in enumerate(self._chapters) if c.url == event.chapter.url),
            0,
        )
        self._start_reading(idx)

    def _toggle_library(self) -> None:
        try:
            from core.library import Library
            lib = Library()
            if self._in_library:
                lib.remove(self.manga.url)
                self._in_library = False
            else:
                lib.add(self.manga)
                self._in_library = True
            self._update_library_btn()
        except Exception as exc:
            self.notify(f"Library error: {exc}", severity="error")

    def _start_reading(self, chapter_index: int) -> None:
        if not self._chapters:
            self.notify("No chapters available", severity="warning")
            return
        from ui.screens.reader import ReaderScreen
        self.app.push_screen(
            ReaderScreen(
                manga=self.manga,
                chapters=self._chapters,
                chapter_index=chapter_index,
                source=self.source,
            )
        )

    def _download_all(self) -> None:
        self.notify("Download all queued — check Downloads screen", severity="information")
        try:
            for ch in self._chapters:
                # We don't have page urls yet; schedule a task per chapter
                self.run_worker(self._enqueue_chapter(ch), exclusive=False)
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    async def _enqueue_chapter(self, chapter: SChapter) -> None:
        try:
            pages = await self.source.get_page_list(chapter)
            self.app.downloader.enqueue(
                manga_url=self.manga.url,
                manga_title=self.manga.title,
                chapter_url=chapter.url,
                chapter_name=chapter.name,
                page_urls=[p.image_url or p.url for p in pages],
            )
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._load_data()
