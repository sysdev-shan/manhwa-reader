"""
Scrollable chapter list widget.
"""
from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.message import Message

from source_api.models import SChapter


class ChapterItem(ListItem):
    """A single row in the chapter list."""

    DEFAULT_CSS = """
    ChapterItem {
        height: 3;
        padding: 0 1;
    }
    ChapterItem Label {
        width: 1fr;
    }
    ChapterItem .ch-read {
        color: $text-muted;
    }
    ChapterItem .ch-unread {
        color: $text;
        text-style: bold;
    }
    ChapterItem .ch-meta {
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, chapter: SChapter, is_read: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.chapter = chapter
        self.is_read = is_read

    def compose(self) -> ComposeResult:
        style_cls = "ch-read" if self.is_read else "ch-unread"
        date_str = ""
        if self.chapter.date_upload:
            dt = datetime.fromtimestamp(self.chapter.date_upload / 1000)
            date_str = dt.strftime("%Y-%m-%d")

        scanlator = f" [{self.chapter.scanlator}]" if self.chapter.scanlator else ""
        yield Label(f"{'✓ ' if self.is_read else ''}{self.chapter.name}", classes=style_cls)
        yield Label(f"{date_str}{scanlator}", classes="ch-meta")


class ChapterList(Static):
    """Scrollable list of chapters with read/unread indicators."""

    class ChapterSelected(Message):
        def __init__(self, chapter: SChapter) -> None:
            super().__init__()
            self.chapter = chapter

    DEFAULT_CSS = """
    ChapterList {
        height: 1fr;
        border: tall $panel;
    }
    ChapterList ListView {
        height: 1fr;
    }
    """

    def __init__(
        self,
        chapters: list[SChapter] | None = None,
        read_chapters: set[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._chapters: list[SChapter] = chapters or []
        self._read: set[str] = read_chapters or set()

    def compose(self) -> ComposeResult:
        items = [
            ChapterItem(ch, is_read=ch.url in self._read)
            for ch in self._chapters
        ]
        yield ListView(*items)

    def update_chapters(
        self,
        chapters: list[SChapter],
        read_chapters: set[str] | None = None,
    ) -> None:
        self._chapters = chapters
        self._read = read_chapters or set()
        lv = self.query_one(ListView)
        lv.clear()
        for ch in chapters:
            lv.append(ChapterItem(ch, is_read=ch.url in self._read))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, ChapterItem):
            self.post_message(self.ChapterSelected(event.item.chapter))
