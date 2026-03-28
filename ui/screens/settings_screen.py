"""
Settings screen.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static

from core.settings import Settings


class SettingsScreen(Screen):
    """App settings."""

    BINDINGS = [Binding("escape,q", "go_back", "Back")]

    DEFAULT_CSS = """
    SettingsScreen { layout: vertical; padding: 1 2; }
    #settings-header {
        height: 3;
        content-align: center middle;
        background: $panel;
        text-style: bold;
        margin-bottom: 1;
    }
    .settings-row {
        height: 5;
        layout: horizontal;
        align: center middle;
        margin-bottom: 1;
    }
    .settings-row Label { width: 30; }
    .settings-row Select { width: 1fr; }
    .settings-row Input { width: 1fr; }
    #btn-row {
        height: 3;
        layout: horizontal;
        margin-top: 2;
    }
    #btn-row Button { margin-right: 1; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._settings = Settings()

    def compose(self) -> ComposeResult:
        s = self._settings
        yield Static("⚙  Settings", id="settings-header")

        with Vertical(classes="settings-row"):
            yield Label("Reading Direction")
            yield Select(
                [("Left to Right", "ltr"), ("Right to Left", "rtl")],
                value=s.reading_direction,
                id="sel-direction",
            )

        with Vertical(classes="settings-row"):
            yield Label("Default Reading Mode")
            yield Select(
                [("Single Page", "single"), ("Double Page", "double"), ("Webtoon", "webtoon")],
                value=s.default_reading_mode,
                id="sel-mode",
            )

        with Vertical(classes="settings-row"):
            yield Label("Image Quality")
            yield Select(
                [("Data Saver", "data_saver"), ("Standard", "standard"), ("Original", "original")],
                value=s.image_quality,
                id="sel-quality",
            )

        with Vertical(classes="settings-row"):
            yield Label("Download Path")
            yield Input(value=s.download_path, id="inp-dl-path")

        with Vertical(id="btn-row"):
            yield Button("Save", id="btn-save", variant="primary")
            yield Button("Clear History", id="btn-clear-history", variant="warning")
            yield Button("Clear Cache", id="btn-clear-cache", variant="warning")
            yield Button("Back", id="btn-back", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-save":
            self._save()
        elif bid == "btn-clear-history":
            self._settings.clear_history()
            self.notify("History cleared", severity="information")
        elif bid == "btn-clear-cache":
            self._settings.clear_cache()
            self.notify("Cache cleared", severity="information")
        elif bid == "btn-back":
            self.action_go_back()

    def _save(self) -> None:
        try:
            direction = self.query_one("#sel-direction", Select).value
            mode = self.query_one("#sel-mode", Select).value
            quality = self.query_one("#sel-quality", Select).value
            dl_path = self.query_one("#inp-dl-path", Input).value

            if direction:
                self._settings.reading_direction = str(direction)
            if mode:
                self._settings.default_reading_mode = str(mode)
            if quality:
                self._settings.image_quality = str(quality)
            if dl_path:
                self._settings.download_path = dl_path

            self.notify("Settings saved!", severity="information")
        except Exception as exc:
            self.notify(f"Save error: {exc}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()
