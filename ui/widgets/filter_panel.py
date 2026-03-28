"""
Filter / sort panel widget for the Browse screen.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, Select, Button, Label
from textual.containers import Vertical, Horizontal
from textual.message import Message

from source_api.models import FilterList, SelectFilter, SortFilter


class FilterPanel(Static):
    """Collapsible side panel showing available filters."""

    class FiltersApplied(Message):
        def __init__(self, filters: FilterList) -> None:
            super().__init__()
            self.filters = filters

    DEFAULT_CSS = """
    FilterPanel {
        width: 30;
        height: auto;
        border: tall $panel;
        padding: 1;
        background: $panel;
    }
    FilterPanel Label {
        color: $text-muted;
        margin-bottom: 1;
    }
    FilterPanel Select {
        width: 100%;
        margin-bottom: 1;
    }
    FilterPanel Button {
        width: 100%;
    }
    """

    def __init__(self, filters: FilterList, **kwargs) -> None:
        super().__init__(**kwargs)
        self._filters = list(filters)
        self._selects: dict[str, Select] = {}

    def compose(self) -> ComposeResult:
        yield Label("── Filters ──")
        for f in self._filters:
            if isinstance(f, SelectFilter):
                yield Label(f.name)
                sel = Select(
                    [(opt, opt) for opt in f.options],
                    value=f.options[f.state] if f.options else "",
                    id=f"filter-{f.name.lower().replace(' ', '-')}",
                )
                self._selects[f.name] = sel
                yield sel
            elif isinstance(f, SortFilter):
                yield Label(f.name)
                sel = Select(
                    [(opt, opt) for opt in f.options],
                    value=f.options[f.state] if f.options else "",
                    id=f"filter-{f.name.lower().replace(' ', '-')}",
                )
                self._selects[f.name] = sel
                yield sel

        yield Button("Apply", variant="primary", id="btn-apply-filters")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply-filters":
            self._sync_states()
            self.post_message(self.FiltersApplied(self._filters))

    def _sync_states(self) -> None:
        for f in self._filters:
            sel = self._selects.get(f.name)
            if sel is None:
                continue
            if isinstance(f, (SelectFilter, SortFilter)):
                val = sel.value
                if val and val in f.options:
                    f.state = f.options.index(val)
