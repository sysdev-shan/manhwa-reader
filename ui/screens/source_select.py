"""
Source picker modal screen.

Shows all built-in manga sources (Asura Scans, Flame Comics, etc.) and lets
the user select one.  Dismissed with the selected source key (str) or None if
cancelled.  No external server required.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListItem, ListView, Static

from source_api.sources import SOURCES


class SourceItem(ListItem):
    """One row in the source picker list."""

    DEFAULT_CSS = """
    SourceItem { height: 3; padding: 0 1; }
    SourceItem .src-name { text-style: bold; }
    SourceItem .src-meta { color: $text-muted; }
    """

    def __init__(self, key: str, source_cls: type, **kwargs) -> None:
        super().__init__(**kwargs)
        self.source_key = key
        self._source_cls = source_cls

    def compose(self) -> ComposeResult:
        instance = self._source_cls()
        lang = getattr(instance, "lang", "en").upper()
        yield Label(self.source_key, classes="src-name")
        yield Label(f"[{lang}]", classes="src-meta")


class SourcePickerScreen(ModalScreen):
    """
    Modal overlay for selecting a manga source.

    Dismissed with the selected source key (str from SOURCES dict), or None
    if cancelled.  Use ``push_screen(SourcePickerScreen(), callback=cb)`` —
    the callback receives ``str | None``.
    """

    BINDINGS = [Binding("escape,q", "cancel_pick", "Cancel")]

    DEFAULT_CSS = """
    SourcePickerScreen {
        align: center middle;
    }
    #src-dialog {
        width: 60;
        height: auto;
        max-height: 28;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #src-dialog-header {
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $text;
        background: $panel;
        margin-bottom: 1;
    }
    #src-list { height: 1fr; min-height: 10; }
    #btn-src-cancel {
        margin-top: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="src-dialog"):
            yield Static("📚  Select a Source", id="src-dialog-header")
            yield ListView(id="src-list")
            yield Button("Cancel", id="btn-src-cancel", variant="default")

    async def on_mount(self) -> None:
        # Populate list after mount so the widget tree is ready
        lv = self.query_one("#src-list", ListView)
        lv.clear()
        for key, cls in SOURCES.items():
            lv.append(SourceItem(key, cls))

    # ------------------------------------------------------------------
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SourceItem):
            key = event.item.source_key
            self.dismiss(key if key else None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-src-cancel":
            self.action_cancel_pick()

    def action_cancel_pick(self) -> None:
        self.dismiss(None)
