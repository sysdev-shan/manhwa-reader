"""
Concrete Madara-theme subclasses for popular manhwa / manhua / manga sites.

Each class only needs to set BASE_URL and SOURCE_NAME.
All scraping logic lives in MadaraSource.

To add a new Madara-based site, subclass MadaraSource, set BASE_URL and
SOURCE_NAME, then register it in source_api/sources/__init__.py.
"""
from __future__ import annotations

from .madara import MadaraSource


class FlameComicsSource(MadaraSource):
    """Flame Comics — https://flamecomics.xyz"""

    BASE_URL = "https://flamecomics.xyz"
    MANGA_URL_PATH = "series"
    SOURCE_NAME = "Flame Comics"
    SOURCE_LANG = "en"


class LuminousScansSource(MadaraSource):
    """Luminous Scans — https://luminousscans.com"""

    BASE_URL = "https://luminousscans.com"
    SOURCE_NAME = "Luminous Scans"
    SOURCE_LANG = "en"


class NightScansSource(MadaraSource):
    """Night Scans — https://nightscans.net"""

    BASE_URL = "https://nightscans.net"
    SOURCE_NAME = "Night Scans"
    SOURCE_LANG = "en"


class CosmicScansSource(MadaraSource):
    """Cosmic Scans — https://cosmicscans.com"""

    BASE_URL = "https://cosmicscans.com"
    SOURCE_NAME = "Cosmic Scans"
    SOURCE_LANG = "en"


class ReaperScansSource(MadaraSource):
    """Reaper Scans — https://reaperscans.com"""

    BASE_URL = "https://reaperscans.com"
    MANGA_URL_PATH = "comics"
    SOURCE_NAME = "Reaper Scans"
    SOURCE_LANG = "en"
