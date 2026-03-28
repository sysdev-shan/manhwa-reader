"""
Concrete Madara-theme subclasses for popular manhwa / manhua sites.

Each class only needs to set BASE_URL (and optionally SOURCE_NAME).
All scraping logic lives in MadaraSource.
"""
from __future__ import annotations

from .madara import MadaraSource


class FlameComicsSource(MadaraSource):
    """Flame Comics — https://flamecomics.xyz"""

    BASE_URL = "https://flamecomics.xyz"
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
