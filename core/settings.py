"""
App preferences persisted as JSON in ~/.manhwa-reader/settings.json.
"""
from __future__ import annotations
import json
from pathlib import Path

DATA_DIR = Path.home() / ".manhwa-reader"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS: dict = {
    "reading_direction": "ltr",          # ltr | rtl
    "default_reading_mode": "single",    # single | double | webtoon
    "image_quality": "standard",         # data_saver | standard | original
    "download_path": str(DATA_DIR / "downloads"),
    "theme": "dark",
}


class Settings:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if SETTINGS_FILE.exists():
            try:
                self._data = json.loads(SETTINGS_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        # Fill missing keys from defaults
        for k, v in DEFAULTS.items():
            self._data.setdefault(k, v)

    def _save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(self._data, indent=2))

    # ------------------------------------------------------------------
    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------
    @property
    def reading_direction(self) -> str:
        return self._data["reading_direction"]

    @reading_direction.setter
    def reading_direction(self, v: str) -> None:
        self.set("reading_direction", v)

    @property
    def default_reading_mode(self) -> str:
        return self._data["default_reading_mode"]

    @default_reading_mode.setter
    def default_reading_mode(self, v: str) -> None:
        self.set("default_reading_mode", v)

    @property
    def image_quality(self) -> str:
        return self._data["image_quality"]

    @image_quality.setter
    def image_quality(self, v: str) -> None:
        self.set("image_quality", v)

    @property
    def download_path(self) -> str:
        return self._data["download_path"]

    @download_path.setter
    def download_path(self, v: str) -> None:
        self.set("download_path", v)

    def clear_history(self) -> None:
        from .history import History
        History().clear()

    def clear_cache(self) -> None:
        import shutil
        cache = DATA_DIR / "cache"
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir(parents=True, exist_ok=True)

    def all(self) -> dict:
        return dict(self._data)
