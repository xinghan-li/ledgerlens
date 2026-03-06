"""
Address abbreviation normalization for matching.
Maps common street/address abbreviations to a canonical full form so that
"FANSHAWE PK RD" and "Fanshawe Park Rd" normalize to the same string.
Used by address_matcher and supabase_client backfill.
"""
import re
from typing import Optional

# Abbreviation (lowercase) -> canonical full form (lowercase) for word-boundary replacement.
# Order: longer tokens first to avoid partial match (e.g. BLVD before BLV).
ADDRESS_ABBREV_TO_FULL = {
    "hwy": "highway",
    "hwys": "highways",
    "pk": "park",
    "rd": "road",
    "rds": "roads",
    "st": "street",
    "sts": "streets",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "blv": "boulevard",
    "ct": "court",
    "cr": "circle",
    "dr": "drive",
    "ln": "lane",
    "trl": "trail",
    "trlr": "trailer",
    "pkwy": "parkway",
    "pkwy.": "parkway",
    "pl": "place",
    "cir": "circle",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
    # Canadian / common
    "rte": "route",
    "mt": "mount",
    "mtn": "mountain",
}


def expand_address_abbreviations(s: Optional[str]) -> str:
    """
    Replace known address abbreviations with full form (word-boundary).
    Input should be lowercased; output is lowercased.
    E.g. "1280 fanshawe pk rd w" -> "1280 fanshawe park road w"
    """
    if not s or not isinstance(s, str):
        return ""
    out = s.lower().strip()
    # Sort by length desc so e.g. "blvd" is tried before "blv"
    for abbr, full in sorted(ADDRESS_ABBREV_TO_FULL.items(), key=lambda x: -len(x[0])):
        out = re.sub(r"\b" + re.escape(abbr) + r"\b", full, out)
    return out
