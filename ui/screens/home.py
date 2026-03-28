"""
Home screen — Library | Updates | History tabs.
"""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
    Footer,
)

from source_api.models import SManga


class LibraryItem(ListItem):
    DEFAULT_CSS = """
    LibraryItem { height: 3; padding: 0 1; }
    LibraryItem .lib-title { text-style: bold; width: 1fr; }
    LibraryItem .lib-meta { color: $text-muted; }
    LibraryItem .lib-unread { color: $warning; }
    """

    def __init__(self, entry: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry

    def compose(self) -> ComposeResult:
        unread = self.entry.get("unread_count", 0)
        unread_str = f"  [{unread} new]" if unread else ""
        yield Label(self.entry.get("title", "Unknown"), classes="lib-title")
        yield Label(
            f"{self.entry.get('author') or ''}{unread_str}",
            classes="lib-meta" + (" lib-unread" if unread else ""),
        )


class HistoryItem(ListItem):
    DEFAULT_CSS = """
    HistoryItem { height: 3; padding: 0 1; }
    HistoryItem .hist-title { text-style: bold; width: 1fr; }
    HistoryItem .hist-chapter { color: $text-muted; }
    """

    def __init__(self, entry: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry

    def compose(self) -> ComposeResult:
        from datetime import datetime
        ts = self.entry.get("timestamp", 0)
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
        yield Label(self.entry.get("title", "Unknown"), classes="hist-title")
        yield Label(
            f"{self.entry.get('last_chapter_name', '')}  •  {date_str}",
            classes="hist-chapter",
        )


class HomeScreen(Screen):
    """Home screen with Library, Updates and History tabs."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh Library"),
        Binding("b", "browse", "Browse"),
    ]

    DEFAULT_CSS = """
    HomeScreen { layout: vertical; }
    #home-header {
        height: 3;
        background: $accent;
        content-align: center middle;
        color: $text;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(" 📚  Manhwa Reader ", id="home-header")
        with TabbedContent():
            with TabPane("Library", id="tab-library"):
                yield ListView(id="list-library")
            with TabPane("Updates", id="tab-updates"):
                yield Static(
                    "Press [r] to refresh your library for new chapters.",
                    id="updates-placeholder",
                )
                yield ListView(id="list-updates")
            with TabPane("History", id="tab-history"):
                yield ListView(id="list-history")
        yield Footer()

    async def on_mount(self) -> None:
        self._load_library()
        self._load_history()

    # ------------------------------------------------------------------
    def _load_library(self) -> None:
        try:
            from core.library import Library
            lv = self.query_one("#list-library", ListView)
            lv.clear()
            for entry in Library().all():
                lv.append(LibraryItem(entry))
        except Exception as exc:
            self.notify(f"Library error: {exc}", severity="error")

    def _load_history(self) -> None:
        try:
            from core.history import History
            lv = self.query_one("#list-history", ListView)
            lv.clear()
            for entry in History().recent():
                lv.append(HistoryItem(entry))
        except Exception as exc:
            self.notify(f"History error: {exc}", severity="error")

    # ------------------------------------------------------------------
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, (LibraryItem, HistoryItem)):
            self._open_from_entry(event.item.entry)

    def _open_from_entry(self, entry: dict) -> None:
        manga_url = entry.get("manga_url") or entry.get("url", "")
        title = entry.get("title", "Unknown")
        thumbnail_url = entry.get("thumbnail_url")

        manga = SManga(
            url=manga_url,
            title=title,
            author=entry.get("author"),
            thumbnail_url=thumbnail_url,
            status=entry.get("status", 0),
            genre=entry.get("genre"),
        )
        from ui.screens.manga_detail import MangaDetailScreen
        source = self.app.source
        self.app.push_screen(MangaDetailScreen(manga=manga, source=source))

    # ------------------------------------------------------------------
    def action_refresh(self) -> None:
        self._load_library()
        self._load_history()
        self.notify("Library refreshed", severity="information")

    def action_browse(self) -> None:
        from ui.screens.browse import BrowseScreen
        self.app.push_screen(BrowseScreen(source=self.app.source))
