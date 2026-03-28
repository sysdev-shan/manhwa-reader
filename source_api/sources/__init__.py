from .mangadex import MangaDexSource
from .madara import MadaraSource
from .asura import AsuraScansSource
from .flame import (
    FlameComicsSource,
    LuminousScansSource,
    NightScansSource,
    CosmicScansSource,
)

# Registry of all built-in sources.  Browse screen uses this to populate
# the source picker — no external server required.
SOURCES: dict[str, type] = {
    "Asura Scans": AsuraScansSource,
    "Flame Comics": FlameComicsSource,
    "Luminous Scans": LuminousScansSource,
    "Night Scans": NightScansSource,
    "Cosmic Scans": CosmicScansSource,
}

__all__ = [
    "MangaDexSource",
    "MadaraSource",
    "AsuraScansSource",
    "FlameComicsSource",
    "LuminousScansSource",
    "NightScansSource",
    "CosmicScansSource",
    "SOURCES",
]
