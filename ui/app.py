"""
Main Textual application.
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from source_api.sources.mangadex import MangaDexSource
from core.downloader import Downloader
from core.settings import Settings
from ui.screens.home import HomeScreen


APP_CSS = """
App {
    background: $background;
}
"""


class ManhwaReaderApp(App):
    """Terminal Manhwa / Manhua Reader — powered by MangaDex."""

    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+b", "push_browse", "Browse"),
        Binding("ctrl+d", "push_downloads", "Downloads"),
        Binding("ctrl+s", "push_settings", "Settings"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._source = MangaDexSource()
        self._downloader = Downloader()
        self._settings = Settings()

    @property
    def source(self) -> MangaDexSource:
        return self._source

    @property
    def downloader(self) -> Downloader:
        return self._downloader

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield HomeScreen()
        yield Footer()

    async def on_mount(self) -> None:
        # Start download worker in the background
        asyncio.get_event_loop().create_task(self._downloader.run())

    # ------------------------------------------------------------------
    def action_push_browse(self) -> None:
        from ui.screens.browse import BrowseScreen
        self.push_screen(BrowseScreen(source=self.source))

    def action_push_downloads(self) -> None:
        from ui.screens.downloads import DownloadsScreen
        self.push_screen(DownloadsScreen())

    def action_push_settings(self) -> None:
        from ui.screens.settings_screen import SettingsScreen
        self.push_screen(SettingsScreen())
