"""WoW versions: CurseForge gameVersionTypeId -> group (Retail/Classic/Forever) and label."""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

RETAIL = "retail"
CLASSIC = "classic"
FOREVER = "forever"
GROUPS = frozenset({RETAIL, CLASSIC, FOREVER})

_GROUP_ORDER = (RETAIL, CLASSIC, FOREVER)
_GROUP_TITLES = {RETAIL: "Retail", CLASSIC: "Classic", FOREVER: "Forever"}


@dataclass(frozen=True)
class Flavor:
    group: str | None  # None - the type belongs to no group
    label: str  # for Classic - short version name ("Era", "MoP")


# IDs from https://api.curseforge.com/v1/games/1/version-types (checked against instawow).
KNOWN_TYPES: dict[int, Flavor] = {
    517: Flavor(RETAIL, "Retail"),
    67408: Flavor(CLASSIC, "Era"),
    73246: Flavor(CLASSIC, "TBC"),
    73713: Flavor(CLASSIC, "Wrath"),
    81212: Flavor(CLASSIC, "Titan"),
    77522: Flavor(CLASSIC, "Cata"),
    79434: Flavor(CLASSIC, "MoP"),
    88568: Flavor(FOREVER, "Forever"),
}

_CLASSIC_ORDER = [f.label for f in KNOWN_TYPES.values() if f.group == CLASSIC]


def build_flavor_map(version_types: list[dict]) -> dict[int, Flavor]:
    """Built-in table + types from the API response that are missing from it (recognized by name)."""
    result = dict(KNOWN_TYPES)
    for vt in version_types:
        type_id = vt.get("id")
        if not isinstance(type_id, int) or type_id in result:
            continue
        name = vt.get("name") or vt.get("slug") or f"type {type_id}"
        text = f"{name} {vt.get('slug') or ''}".lower()
        if "forever" in text:
            flavor = Flavor(FOREVER, "Forever")
        elif "classic" in text:
            flavor = Flavor(CLASSIC, name)
        else:
            flavor = Flavor(None, name)
        log.warning("unknown version type %s (%s) → %s", type_id, name, flavor.group or "no group")
        result[type_id] = flavor
    return result


def mod_flavors(mod: dict, flavor_map: dict[int, Flavor]) -> list[Flavor]:
    """Unique game versions the addon has files for, in display order."""
    found: dict[Flavor, None] = {}
    for index in mod.get("latestFilesIndexes") or []:
        type_id = index.get("gameVersionTypeId")
        if type_id is None:
            continue
        found.setdefault(flavor_map.get(type_id, Flavor(None, f"type {type_id}")), None)
    return sorted(found, key=_sort_key)


def passes_filter(flavors: list[Flavor], wanted: frozenset[str]) -> bool:
    """An empty filter lets everything through; otherwise at least one group from wanted is required."""
    return not wanted or any(f.group in wanted for f in flavors)


def format_flavors(flavors: list[Flavor]) -> str:
    """'Retail · Classic (Era, MoP) · Forever'; empty string if there are no versions."""
    parts = []
    for group in _GROUP_ORDER:
        labels = [f.label for f in flavors if f.group == group]
        if not labels:
            continue
        parts.append(f"Classic ({', '.join(labels)})" if group == CLASSIC else _GROUP_TITLES[group])
    parts += [f.label for f in flavors if f.group is None]
    return " · ".join(parts)


def _sort_key(flavor: Flavor) -> tuple[int, int, str]:
    group_rank = _GROUP_ORDER.index(flavor.group) if flavor.group in _GROUP_ORDER else len(_GROUP_ORDER)
    label_rank = _CLASSIC_ORDER.index(flavor.label) if flavor.label in _CLASSIC_ORDER else len(_CLASSIC_ORDER)
    return group_rank, label_rank, flavor.label
