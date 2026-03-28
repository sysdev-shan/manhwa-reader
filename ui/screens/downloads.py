"""
Downloads management screen.
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, ListItem, ListView, ProgressBar, Static

from core.downloader import DownloadJob, DownloadStatus


class DownloadItem(ListItem):
    DEFAULT_CSS = """
    DownloadItem { height: 5; padding: 0 1; }
    DownloadItem .dl-title { text-style: bold; }
    DownloadItem .dl-status { color: $text-muted; }
    """

    def __init__(self, job: DownloadJob, **kwargs) -> None:
        super().__init__(**kwargs)
        self.job = job

    def compose(self) -> ComposeResult:
        pct = int(self.job.progress_pct())
        status_str = self.job.status.name.title()
        if self.job.error:
            status_str += f" – {self.job.error}"
        yield Label(
            f"{self.job.manga_title} / {self.job.chapter_name}",
            classes="dl-title",
        )
        yield Label(
            f"{status_str}  {self.job.progress}/{self.job.total} pages",
            classes="dl-status",
        )
        yield ProgressBar(total=100, id=f"pb-{id(self.job)}", show_eta=False)

    async def on_mount(self) -> None:
        try:
            pb = self.query_one(ProgressBar)
            pb.progress = self.job.progress_pct()
        except Exception:
            pass


class DownloadsScreen(Screen):
    """Shows the download queue and progress."""

    BINDINGS = [
        Binding("escape,q", "go_back", "Back"),
        Binding("c", "clear_done", "Clear completed"),
    ]

    DEFAULT_CSS = """
    DownloadsScreen { layout: vertical; }
    #dl-header {
        height: 3;
        background: $panel;
        content-align: center middle;
        text-style: bold;
    }
    #dl-actions {
        height: 3;
        layout: horizontal;
        align: center middle;
        background: $panel;
    }
    #dl-actions Button { margin: 0 1; min-width: 18; }
    """

    def compose(self) -> ComposeResult:
        yield Static("⬇  Downloads", id="dl-header")
        with Vertical(id="dl-actions"):
            yield Button("Clear Completed", id="btn-clear", variant="default")
            yield Button("Back", id="btn-back", variant="default")
        yield ListView(id="list-downloads")

    async def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        try:
            lv = self.query_one("#list-downloads", ListView)
            lv.clear()
            for job in self.app.downloader.all_jobs():
                lv.append(DownloadItem(job))
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-clear":
            self.action_clear_done()
        elif bid == "btn-back":
            self.action_go_back()

    def action_clear_done(self) -> None:
        try:
            self.app.downloader.clear_completed()
            self._refresh_list()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()
