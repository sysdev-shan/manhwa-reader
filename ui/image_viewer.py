"""
Standalone GUI window for reading manga/manhwa chapters.

Opens a Tk window displaying chapter pages with Pillow.  Images are
downloaded to the shared cache directory in a background thread so the
window appears immediately with loading placeholders while images arrive.

Usage (from inside an asyncio context)
---------------------------------------
    import asyncio, functools
    loop   = asyncio.get_event_loop()
    viewer = ChapterViewer(pages, manga_title, chapter_name, initial_page=0)
    action, final_page = await loop.run_in_executor(None, viewer.run)
    # action ∈ {"quit", "next_chapter", "prev_chapter"}

Features
--------
* Modes: webtoon (vertical scroll), single page, double page
* Keyboard shortcuts matching the original reader:
    ←/h   previous page        →/l   next page
    k     scroll up            j     scroll down
    [     previous chapter     ]     next chapter
    m     cycle mode           b     cycle background
    f     toggle fullscreen    d     download chapter
    +/=   zoom in              -     zoom out
    0     reset zoom           q/Esc quit
* Background colours: dark / light / sepia
* Window position & size restored between consecutive chapters
* Zoom: 20 – 300 %
"""
from __future__ import annotations

import hashlib
import queue
import threading
from pathlib import Path
from typing import Callable

import httpx
from PIL import Image

# tkinter and PIL.ImageTk are only available when a display is present.
# Import them lazily so this module can be imported in headless environments
# (tests, CI) without crashing.
try:
    import tkinter as tk
    from PIL import ImageTk
    _TK_AVAILABLE = True
except (ImportError, RuntimeError):
    tk = None          # type: ignore[assignment]
    ImageTk = None     # type: ignore[assignment]
    _TK_AVAILABLE = False

from source_api.models import Page

# Shared image cache (same directory used by the old terminal reader)
CACHE_DIR = Path.home() / ".manhwa-reader" / "cache"

MODES = ["webtoon", "single", "double"]

BACKGROUNDS: dict[str, dict[str, str]] = {
    "dark":  {"bg": "#1a1a1a", "fg": "#e0e0e0", "btn": "#2d2d2d", "ph": "#2a2a2a", "ph_border": "#444"},
    "light": {"bg": "#f5f5f5", "fg": "#1a1a1a", "btn": "#dcdcdc", "ph": "#e0e0e0", "ph_border": "#bbb"},
    "sepia": {"bg": "#f4ecd8", "fg": "#5c4a1e", "btn": "#e8d5b0", "ph": "#e8d5b0", "ph_border": "#c0a060"},
}
BG_CYCLE = ["dark", "light", "sepia"]

# Sent to the loader thread as a sentinel to stop it
_STOP = -1

# Default window dimensions
_WIN_W = 960
_WIN_H = 760

# Shared geometry across chapters so window re-opens in the same position
_last_geometry: str | None = None


class ChapterViewer:
    """
    Tk-based chapter image viewer.

    Call ``run()`` to open the window (blocks until closed).
    Returns ``(action, page_index)`` where *action* is one of
    ``"quit"``, ``"next_chapter"``, ``"prev_chapter"``.
    """

    def __init__(
        self,
        pages: list[Page],
        manga_title: str,
        chapter_name: str,
        initial_page: int = 0,
        mode: str = "webtoon",
        on_download: Callable[[list[Page]], None] | None = None,
    ) -> None:
        self.pages = pages
        self.manga_title = manga_title
        self.chapter_name = chapter_name
        self.initial_page = max(0, min(initial_page, max(len(pages) - 1, 0)))
        self._mode = mode if mode in MODES else "webtoon"
        self._on_download = on_download

        self._result: str = "quit"
        self._page_index: int = self.initial_page
        self._bg_name: str = "dark"
        self._zoom: float = 1.0
        self._fullscreen: bool = False

        # idx → PIL Image (raw, resized lazily on display)
        self._raw: dict[int, Image.Image] = {}
        # idx → PhotoImage (must stay referenced while shown)
        self._photos: dict = {}

        self._load_queue: queue.Queue[int] = queue.Queue()
        self._loaded: set[int] = set()
        self._new_arrivals: bool = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> tuple[str, int]:
        """Open the window; blocks until it closes.  Returns (action, page)."""
        if not _TK_AVAILABLE:
            raise RuntimeError(
                "tkinter is not available on this system.  "
                "Install the 'python3-tk' package (e.g. `apt install python3-tk`) "
                "or use a Python installation that includes Tk."
            )
        global _last_geometry
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self._root = tk.Tk()
        self._root.title(f"{self.manga_title} — {self.chapter_name}")

        if _last_geometry:
            self._root.geometry(_last_geometry)
        else:
            self._root.geometry(f"{_WIN_W}x{_WIN_H}")

        self._root.minsize(400, 300)
        colors = BACKGROUNDS[self._bg_name]
        self._root.configure(bg=colors["bg"])
        self._root.protocol("WM_DELETE_WINDOW", self._close_quit)

        self._build_ui()
        self._bind_keys()

        # Launch background image-loader thread
        self._loader = threading.Thread(target=self._loader_worker, daemon=True)
        self._loader.start()
        # Queue all pages
        for i in range(len(self.pages)):
            self._load_queue.put(i)

        # First render (shows placeholders if images not yet ready)
        self._render()
        # Poll for newly loaded images
        self._poll()

        self._root.mainloop()

        # Save geometry for next chapter
        try:
            _last_geometry = self._root.winfo_geometry()
        except Exception:
            pass

        return self._result, self._page_index

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        c = BACKGROUNDS[self._bg_name]

        # ── Status bar (top) ─────────────────────────────────────────
        self._status_frame = tk.Frame(self._root, bg=c["bg"], height=26)
        self._status_frame.pack(fill=tk.X, side=tk.TOP)
        self._status_frame.pack_propagate(False)
        self._status_lbl = tk.Label(
            self._status_frame, text="", bg=c["bg"], fg=c["fg"],
            font=("Helvetica", 9), anchor="w", padx=8,
        )
        self._status_lbl.pack(fill=tk.X, expand=True)

        # ── Canvas + vertical scrollbar ─────────────────────────────
        self._mid_frame = tk.Frame(self._root, bg=c["bg"])
        self._mid_frame.pack(fill=tk.BOTH, expand=True)

        self._vbar = tk.Scrollbar(self._mid_frame, orient=tk.VERTICAL)
        self._vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._canvas = tk.Canvas(
            self._mid_frame, bg=c["bg"],
            yscrollcommand=self._vbar.set, highlightthickness=0,
        )
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._vbar.config(command=self._canvas.yview)

        # Mouse wheel
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", lambda e: self._canvas.yview_scroll(-3, "units"))
        self._canvas.bind("<Button-5>", lambda e: self._canvas.yview_scroll(3, "units"))

        # Resize → redraw
        self._canvas.bind("<Configure>", lambda e: self._root.after(60, self._render))

        # ── Nav bar (bottom) ─────────────────────────────────────────
        self._nav_frame = tk.Frame(self._root, bg=c["btn"], height=40)
        self._nav_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._nav_frame.pack_propagate(False)

        def btn(parent, text, cmd):
            b = tk.Button(
                parent, text=text, command=cmd,
                bg=c["btn"], fg=c["fg"], relief=tk.FLAT,
                padx=8, pady=4, font=("Helvetica", 10), cursor="hand2",
                activebackground=c["bg"], activeforeground=c["fg"],
            )
            b.pack(side=tk.LEFT, padx=3, pady=4)
            return b

        def lbl(parent, text):
            l = tk.Label(
                parent, text=text, bg=c["btn"], fg=c["fg"],
                font=("Helvetica", 10), padx=6,
            )
            l.pack(side=tk.LEFT, padx=2, pady=4)
            return l

        self._btn_prev_ch  = btn(self._nav_frame, "◄ Prev Ch",  self._prev_chapter)
        self._btn_prev_pg  = btn(self._nav_frame, "◄ Page",     self._prev_page)
        self._page_lbl     = lbl(self._nav_frame, "Page 1/1")
        self._btn_next_pg  = btn(self._nav_frame, "Page ►",     self._next_page)
        self._btn_next_ch  = btn(self._nav_frame, "Next Ch ►",  self._next_chapter)

        # Spacer
        tk.Label(self._nav_frame, text="", bg=c["btn"]).pack(side=tk.LEFT, expand=True)

        self._btn_dl   = btn(self._nav_frame, "⬇ DL",       self._download)
        self._btn_mode = btn(self._nav_frame, f"⊞ {self._mode.capitalize()}", self._cycle_mode)
        self._btn_bg   = btn(self._nav_frame, "🎨 BG",      self._cycle_bg)

        self._all_nav_widgets = [
            self._btn_prev_ch, self._btn_prev_pg, self._page_lbl,
            self._btn_next_pg, self._btn_next_ch, self._btn_dl,
            self._btn_mode, self._btn_bg,
        ]

    def _bind_keys(self) -> None:
        r = self._root
        r.bind("<Left>",   lambda e: self._prev_page())
        r.bind("<Right>",  lambda e: self._next_page())
        r.bind("<Up>",     lambda e: self._canvas.yview_scroll(-3, "units"))
        r.bind("<Down>",   lambda e: self._canvas.yview_scroll(3, "units"))
        r.bind("h",        lambda e: self._prev_page())
        r.bind("l",        lambda e: self._next_page())
        r.bind("j",        lambda e: self._canvas.yview_scroll(3, "units"))
        r.bind("k",        lambda e: self._canvas.yview_scroll(-3, "units"))
        r.bind("[",        lambda e: self._prev_chapter())
        r.bind("]",        lambda e: self._next_chapter())
        r.bind("m",        lambda e: self._cycle_mode())
        r.bind("b",        lambda e: self._cycle_bg())
        r.bind("f",        lambda e: self._toggle_fullscreen())
        r.bind("d",        lambda e: self._download())
        r.bind("<plus>",   lambda e: self._zoom_by(0.1))
        r.bind("<equal>",  lambda e: self._zoom_by(0.1))
        r.bind("<minus>",  lambda e: self._zoom_by(-0.1))
        r.bind("0",        lambda e: self._zoom_reset())
        r.bind("q",        lambda e: self._close_quit())
        r.bind("<Escape>", lambda e: self._close_quit())

    # ------------------------------------------------------------------
    # Background loader
    # ------------------------------------------------------------------
    def _loader_worker(self) -> None:
        """Runs in a daemon thread: download + decode images."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "image/webp,image/avif,image/*,*/*",
        }
        with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
            while True:
                idx = self._load_queue.get()
                if idx == _STOP:
                    self._load_queue.task_done()
                    break
                if idx in self._loaded:
                    self._load_queue.task_done()
                    continue
                try:
                    path = self._ensure_cached(client, idx)
                    img = Image.open(path).convert("RGB")
                    img.load()
                    with self._lock:
                        self._raw[idx] = img
                        self._loaded.add(idx)
                        self._new_arrivals = True
                except Exception:
                    pass
                self._load_queue.task_done()

    def _ensure_cached(self, client: httpx.Client, idx: int) -> Path:
        page = self.pages[idx]
        url = (page.image_url or page.url or "").strip()
        if not url:
            raise ValueError(f"No URL for page {idx}")
        h = hashlib.md5(url.encode()).hexdigest()[:16]
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        path = CACHE_DIR / f"{h}{ext}"
        if not path.exists():
            resp = client.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        return path

    def _poll(self) -> None:
        """Check if new images arrived; re-render if so. Re-schedules itself."""
        with self._lock:
            arrived = self._new_arrivals
            self._new_arrivals = False
        if arrived:
            self._render()
        self._root.after(250, self._poll)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self) -> None:
        if self._mode == "webtoon":
            self._render_webtoon()
        elif self._mode == "double":
            self._render_double()
        else:
            self._render_single()
        self._update_status()

    def _canvas_width(self) -> int:
        w = self._canvas.winfo_width()
        return w if w > 1 else _WIN_W

    def _fit(self, img: Image.Image, max_w: int) -> Image.Image:
        tw = max(1, int(max_w * self._zoom))
        if img.width == tw:
            return img
        ratio = tw / max(img.width, 1)
        nh = max(1, int(img.height * ratio))
        return img.resize((tw, nh), Image.Resampling.LANCZOS)

    def _placeholder(self, cw: int, label: str) -> int:
        """Draw a placeholder rectangle; returns its height."""
        c = BACKGROUNDS[self._bg_name]
        ph_h = 80
        self._canvas.create_rectangle(
            4, self._y_cursor, cw - 4, self._y_cursor + ph_h,
            fill=c["ph"], outline=c["ph_border"],
        )
        self._canvas.create_text(
            cw // 2, self._y_cursor + ph_h // 2,
            text=label, fill=c["fg"], font=("Helvetica", 11),
        )
        self._y_cursor += ph_h + 4
        return ph_h + 4

    def _render_webtoon(self) -> None:
        self._canvas.delete("all")
        self._photos.clear()
        cw = self._canvas_width()
        self._y_cursor = 0

        for idx in range(len(self.pages)):
            with self._lock:
                raw = self._raw.get(idx)
            if raw:
                img = self._fit(raw, cw)
                photo = ImageTk.PhotoImage(img)
                self._photos[idx] = photo
                self._canvas.create_image(cw // 2, self._y_cursor, anchor=tk.N, image=photo)
                self._y_cursor += img.height + 4
            else:
                self._placeholder(cw, f"Loading page {idx + 1} …")

        self._canvas.configure(scrollregion=(0, 0, cw, max(self._y_cursor, 1)))
        self._page_lbl.config(text=f"Page {self._page_index + 1}/{len(self.pages)}")

        # Scroll to saved page position
        if self._page_index > 0 and self._y_cursor > 0:
            frac = self._page_index / max(len(self.pages), 1)
            self._canvas.yview_moveto(frac)

    def _render_single(self) -> None:
        self._canvas.delete("all")
        self._photos.clear()
        cw = self._canvas_width()
        self._y_cursor = 0
        idx = self._page_index

        with self._lock:
            raw = self._raw.get(idx)

        if raw:
            img = self._fit(raw, cw)
            photo = ImageTk.PhotoImage(img)
            self._photos[idx] = photo
            self._canvas.create_image(cw // 2, 0, anchor=tk.N, image=photo)
            self._canvas.configure(scrollregion=(0, 0, cw, img.height))
        else:
            self._placeholder(cw, f"Loading page {idx + 1} …")
            self._canvas.configure(scrollregion=(0, 0, cw, 80))

        self._canvas.yview_moveto(0)
        self._page_lbl.config(text=f"Page {self._page_index + 1}/{len(self.pages)}")

    def _render_double(self) -> None:
        self._canvas.delete("all")
        self._photos.clear()
        cw = self._canvas_width()
        half = cw // 2
        max_h = 0

        for side, idx in enumerate([self._page_index, self._page_index + 1]):
            if idx >= len(self.pages):
                continue
            x_center = half // 2 + side * half
            with self._lock:
                raw = self._raw.get(idx)
            if raw:
                img = self._fit(raw, half - 4)
                photo = ImageTk.PhotoImage(img)
                self._photos[idx] = photo
                self._canvas.create_image(x_center, 0, anchor=tk.N, image=photo)
                max_h = max(max_h, img.height)
            else:
                self._canvas.create_text(
                    x_center, 60, text=f"Loading {idx + 1}…",
                    fill=BACKGROUNDS[self._bg_name]["fg"], font=("Helvetica", 11),
                )
                max_h = max(max_h, 120)

        self._canvas.configure(scrollregion=(0, 0, cw, max(max_h, 1)))
        self._canvas.yview_moveto(0)
        n = len(self.pages)
        r = min(self._page_index + 2, n)
        self._page_lbl.config(text=f"Pages {self._page_index + 1}–{r}/{n}")

    def _update_status(self) -> None:
        c = BACKGROUNDS[self._bg_name]
        self._status_lbl.config(
            text=(
                f"  {self.manga_title}  |  {self.chapter_name}  "
                f"|  {self._mode.capitalize()}  |  Zoom {int(self._zoom * 100)}%  "
                "|  ←/→ page  [/] chapter  m mode  b bg  f fullscreen  +/- zoom  d dl  q quit"
            ),
            bg=c["bg"], fg=c["fg"],
        )
        self._status_frame.configure(bg=c["bg"])

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------
    def _prev_page(self) -> None:
        if self._mode == "webtoon":
            self._canvas.yview_scroll(-5, "units")
            return
        step = 2 if self._mode == "double" else 1
        self._page_index = max(0, self._page_index - step)
        self._render()

    def _next_page(self) -> None:
        if self._mode == "webtoon":
            self._canvas.yview_scroll(5, "units")
            return
        step = 2 if self._mode == "double" else 1
        self._page_index = min(len(self.pages) - 1, self._page_index + step)
        self._render()

    def _prev_chapter(self) -> None:
        self._result = "prev_chapter"
        self._quit()

    def _next_chapter(self) -> None:
        self._result = "next_chapter"
        self._quit()

    def _cycle_mode(self) -> None:
        self._mode = MODES[(MODES.index(self._mode) + 1) % len(MODES)]
        self._btn_mode.config(text=f"⊞ {self._mode.capitalize()}")
        self._render()

    def _cycle_bg(self) -> None:
        self._bg_name = BG_CYCLE[(BG_CYCLE.index(self._bg_name) + 1) % len(BG_CYCLE)]
        c = BACKGROUNDS[self._bg_name]
        self._root.configure(bg=c["bg"])
        self._mid_frame.configure(bg=c["bg"])
        self._canvas.configure(bg=c["bg"])
        self._status_frame.configure(bg=c["bg"])
        self._nav_frame.configure(bg=c["btn"])
        for w in self._all_nav_widgets:
            try:
                w.configure(bg=c["btn"], fg=c["fg"])
            except Exception:
                pass
        self._render()

    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        self._root.attributes("-fullscreen", self._fullscreen)

    def _download(self) -> None:
        if self._on_download:
            try:
                self._on_download(self.pages)
                old = self._status_lbl.cget("text")
                self._status_lbl.config(text="  ✓ Download queued!")
                self._root.after(2500, lambda: self._status_lbl.config(text=old))
            except Exception as exc:
                old = self._status_lbl.cget("text")
                self._status_lbl.config(text=f"  Download error: {exc}")
                self._root.after(3000, lambda: self._status_lbl.config(text=old))

    def _zoom_by(self, delta: float) -> None:
        self._zoom = max(0.2, min(3.0, self._zoom + delta))
        self._render()

    def _zoom_reset(self) -> None:
        self._zoom = 1.0
        self._render()

    def _on_mousewheel(self, event: tk.Event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Close helpers
    # ------------------------------------------------------------------
    def _close_quit(self) -> None:
        self._result = "quit"
        self._quit()

    def _quit(self) -> None:
        # Stop the loader thread
        self._load_queue.put(_STOP)
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
