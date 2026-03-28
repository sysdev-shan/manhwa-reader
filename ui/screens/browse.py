"""
Browse / Explore screen.

Tabs: Popular | Latest | Search

The source bar at the top shows the active Suwayomi source and lets the user
change it at any time via the [Change Source] button (or the `s` key).
If no source has been selected yet the picker is shown automatically on mount.
"""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
    TabbedContent,
    TabPane,
)

from source_api.models import SManga, MangasPage
from ui.widgets.filter_panel import FilterPanel


class MangaListItem(ListItem):
    """One row in a manga list."""

    DEFAULT_CSS = """
    MangaListItem {
        height: 4;
        padding: 0 1;
    }
    MangaListItem Label { width: 1fr; }
    MangaListItem .item-title { text-style: bold; }
    MangaListItem .item-meta { color: $text-muted; }
    """

    def __init__(self, manga: SManga, **kwargs) -> None:
        super().__init__(**kwargs)
        self.manga = manga

    def compose(self) -> ComposeResult:
        yield Label(self.manga.title, classes="item-title")
        yield Label(
            f"{self.manga.status_label()}  •  {self.manga.author or ''}",
            classes="item-meta",
        )


class BrowseScreen(Screen):
    """Browse popular/latest/search tabs."""

    BINDINGS = [
        Binding("escape,q", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "change_source", "Change Source"),
    ]

    DEFAULT_CSS = """
    BrowseScreen {
        layout: vertical;
    }
    #source-bar {
        height: 3;
        layout: horizontal;
        align: center middle;
        background: $panel-darken-1;
        padding: 0 1;
    }
    #source-bar Label {
        width: 1fr;
        color: $text;
    }
    #source-bar Button { min-width: 18; }
    #browse-content {
        height: 1fr;
        layout: horizontal;
    }
    #manga-list-pane {
        width: 1fr;
        height: 1fr;
    }
    #filter-pane {
        width: 32;
        height: 1fr;
        display: none;
    }
    #filter-pane.visible {
        display: block;
    }
    #search-bar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    #search-input { width: 1fr; }
    #btn-search { min-width: 10; margin-left: 1; }
    #btn-filter { min-width: 10; margin-left: 1; }
    #pagination-bar {
        height: 3;
        layout: horizontal;
        align: center middle;
        background: $panel;
    }
    #pagination-bar Button { min-width: 12; margin: 0 1; }
    #pagination-bar Label { min-width: 14; content-align: center middle; }
    #loading-browse {
        height: 3;
        content-align: center middle;
        display: none;
    }
    """

    def __init__(self, source, **kwargs) -> None:
        super().__init__(**kwargs)
        self.source = source
        self._page = 1
        self._has_next = False
        self._current_tab = "popular"
        self._query = ""
        self._filters = source.get_filter_list()

    def compose(self) -> ComposeResult:
        # Source bar — always visible; "Change Source" only meaningful for Suwayomi
        with Horizontal(id="source-bar"):
            yield Label("🔌 Source: —", id="lbl-source-name")
            yield Button("Change Source", id="btn-change-source", variant="primary")

        with TabbedContent(id="browse-tabs"):
            with TabPane("Popular", id="tab-popular"):
                yield ListView(id="list-popular")
            with TabPane("Latest", id="tab-latest"):
                yield ListView(id="list-latest")
            with TabPane("Search", id="tab-search"):
                with Horizontal(id="search-bar"):
                    yield Input(
                        placeholder="Search manhwa / manhua…",
                        id="search-input",
                    )
                    yield Button("Search", id="btn-search", variant="primary")
                    yield Button("Filters", id="btn-filter", variant="default")
                with Horizontal(id="browse-content"):
                    with Vertical(id="manga-list-pane"):
                        yield LoadingIndicator(id="loading-browse")
                        yield ListView(id="list-search")
                    yield FilterPanel(self._filters, id="filter-pane")

        with Horizontal(id="pagination-bar"):
            yield Button("◄ Prev", id="btn-prev-page", variant="default")
            yield Label("Page 1", id="lbl-page")
            yield Button("Next ►", id="btn-next-page", variant="default")

    async def on_mount(self) -> None:
        self._update_source_label()
        from source_api.sources.suwayomi import SuwayomiSource
        if isinstance(self.source, SuwayomiSource) and not self.source.source_id:
            # No source selected yet — show the picker after mount completes
            self.call_later(self._show_source_picker)
        else:
            self._load_popular()
            self._load_latest()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------
    def _update_source_label(self) -> None:
        try:
            name = getattr(self.source, "name", "Unknown")
            self.query_one("#lbl-source-name", Label).update(
                f"🔌 Source: {name}"
            )
        except Exception:
            pass

    def _show_source_picker(self) -> None:
        from source_api.sources.suwayomi import SuwayomiSource
        from ui.screens.source_select import SourcePickerScreen
        if isinstance(self.source, SuwayomiSource):
            self.app.push_screen(
                SourcePickerScreen(self.source),
                callback=self._on_source_picked,
            )

    def _on_source_picked(self, source_id: str | None) -> None:
        if source_id:
            # _activate_source is a @work method; _load_popular/_load_latest
            # are called from WITHIN the worker after activate_source() awaits,
            # so they run only once the source is fully activated.
            self._activate_source(source_id)
        else:
            # Cancelled — try anyway (will show "no source" error gracefully)
            self._load_popular()
            self._load_latest()

    @work
    async def _activate_source(self, source_id: str) -> None:
        from source_api.sources.suwayomi import SuwayomiSource
        if not isinstance(self.source, SuwayomiSource):
            return
        try:
            await self.source.activate_source(source_id)
        except Exception as exc:
            self.notify(f"Could not activate source: {exc}", severity="error")
            return
        self._update_source_label()
        self._load_popular()
        self._load_latest()

    def action_change_source(self) -> None:
        self._show_source_picker()

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    @work(exclusive=True, group="popular")
    async def _load_popular(self) -> None:
        self._set_loading(True)
        try:
            result: MangasPage = await self.source.get_popular_manga(self._page)
            lv = self.query_one("#list-popular", ListView)
            lv.clear()
            for manga in result.mangas:
                lv.append(MangaListItem(manga))
            self._has_next = result.has_next_page
            self._update_pagination()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")
        finally:
            self._set_loading(False)

    @work(exclusive=True, group="latest")
    async def _load_latest(self) -> None:
        try:
            result: MangasPage = await self.source.get_latest_updates(self._page)
            lv = self.query_one("#list-latest", ListView)
            lv.clear()
            for manga in result.mangas:
                lv.append(MangaListItem(manga))
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    @work(exclusive=True, group="search")
    async def _do_search(self) -> None:
        self._set_loading(True)
        try:
            result: MangasPage = await self.source.get_search_manga(
                self._page, self._query, self._filters
            )
            lv = self.query_one("#list-search", ListView)
            lv.clear()
            for manga in result.mangas:
                lv.append(MangaListItem(manga))
            self._has_next = result.has_next_page
            self._update_pagination()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")
        finally:
            self._set_loading(False)

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-change-source":
            self._show_source_picker()
        elif bid == "btn-search":
            self._query = self.query_one("#search-input", Input).value
            self._page = 1
            self._do_search()
        elif bid == "btn-filter":
            pane = self.query_one("#filter-pane")
            if "visible" in pane.classes:
                pane.remove_class("visible")
            else:
                pane.add_class("visible")
        elif bid == "btn-prev-page":
            if self._page > 1:
                self._page -= 1
                self._refresh_current_tab()
        elif bid == "btn-next-page":
            if self._has_next:
                self._page += 1
                self._refresh_current_tab()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._query = event.value
            self._page = 1
            self._do_search()

    def on_filter_panel_filters_applied(self, event: FilterPanel.FiltersApplied) -> None:
        self._filters = event.filters
        self._page = 1
        self._do_search()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._current_tab = str(event.tab.id).replace("tab-", "")
        self._page = 1

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, MangaListItem):
            self._open_detail(event.item.manga)

    # ------------------------------------------------------------------
    def _open_detail(self, manga: SManga) -> None:
        from ui.screens.manga_detail import MangaDetailScreen
        self.app.push_screen(MangaDetailScreen(manga=manga, source=self.source))

    def _refresh_current_tab(self) -> None:
        if self._current_tab == "popular":
            self._load_popular()
        elif self._current_tab == "latest":
            self._load_latest()
        else:
            self._do_search()

    def _update_pagination(self) -> None:
        try:
            self.query_one("#lbl-page", Label).update(f"Page {self._page}")
            self.query_one("#btn-prev-page", Button).disabled = self._page <= 1
            self.query_one("#btn-next-page", Button).disabled = not self._has_next
        except Exception:
            pass

    def _set_loading(self, loading: bool) -> None:
        try:
            li = self.query_one("#loading-browse", LoadingIndicator)
            li.display = loading
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._refresh_current_tab()
