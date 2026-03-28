"""
MangaCard widget — shows cover thumbnail (via term-image) and title.
Falls back to a plain text box when term-image is unavailable.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.reactive import reactive


class MangaCard(Static):
    """Compact card displaying a manga's cover and title."""

    DEFAULT_CSS = """
    MangaCard {
        width: 22;
        height: 12;
        border: tall $panel;
        padding: 0 1;
        margin: 1;
        background: $panel;
        content-align: center middle;
        overflow: hidden;
    }
    MangaCard:hover {
        border: tall $accent;
    }
    MangaCard:focus {
        border: tall $accent;
    }
    MangaCard .manga-title {
        text-align: center;
        color: $text;
        text-style: bold;
        width: 100%;
        content-align: center bottom;
        overflow: hidden;
    }
    MangaCard .manga-cover {
        text-align: center;
        color: $text-muted;
        width: 100%;
        height: 8;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        manga_url: str,
        title: str,
        thumbnail_url: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.manga_url = manga_url
        self._title = title
        self.thumbnail_url = thumbnail_url

    def compose(self) -> ComposeResult:
        # Cover placeholder — term-image rendering happens asynchronously
        yield Static("🖼", classes="manga-cover", id=f"cover-{id(self)}")
        yield Label(
            self._title[:18] + ("…" if len(self._title) > 18 else ""),
            classes="manga-title",
        )

    async def on_mount(self) -> None:
        if self.thumbnail_url:
            await self._render_cover()

    async def _render_cover(self) -> None:
        """Try to render cover via term-image; fall back to emoji placeholder."""
        try:
            import asyncio
            import httpx
            from pathlib import Path
            import tempfile

            # Download thumbnail to temp file
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self.thumbnail_url)
                resp.raise_for_status()

            suffix = Path(self.thumbnail_url.split("?")[0]).suffix or ".jpg"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            tmp = Path(tmp_path)
            try:
                import os
                os.write(fd, resp.content)
            finally:
                os.close(fd)

            try:
                from term_image.image import AutoImage
                img = AutoImage(str(tmp))
                cover_widget = self.query_one(f"#cover-{id(self)}", Static)
                cover_widget.update(str(img))  # type: ignore[arg-type]
            except Exception:
                pass
            finally:
                tmp.unlink(missing_ok=True)
        except Exception:
            pass  # Silently fall back to placeholder
