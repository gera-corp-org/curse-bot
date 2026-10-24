from bot.flavors import (
    CLASSIC,
    FOREVER,
    RETAIL,
    Flavor,
    build_flavor_map,
    format_flavors,
    mod_flavors,
    passes_filter,
)


def mod_with_types(*type_ids):
    return {"id": 1, "latestFilesIndexes": [{"gameVersionTypeId": t} for t in type_ids]}


def test_known_types_map_to_groups():
    fmap = build_flavor_map([])
    assert fmap[517] == Flavor(RETAIL, "Retail")
    assert fmap[67408] == Flavor(CLASSIC, "Era")
    assert fmap[79434] == Flavor(CLASSIC, "MoP")
    assert fmap[88568] == Flavor(FOREVER, "Forever")


def test_unknown_types_from_api_are_guessed_by_name():
    fmap = build_flavor_map([
        {"id": 517, "name": "WoW Retail", "slug": "wow_retail"},
        {"id": 90001, "name": "WoW Forever Hardcore", "slug": "wow-forever-hc"},
        {"id": 90002, "name": "Legion Classic", "slug": "wow-legion-classic"},
        {"id": 90003, "name": "Plunderstorm", "slug": "wow-plunderstorm"},
    ])
    assert fmap[517] == Flavor(RETAIL, "Retail")  # известные не переопределяются
    assert fmap[90001] == Flavor(FOREVER, "Forever")
    assert fmap[90002] == Flavor(CLASSIC, "Legion Classic")
    assert fmap[90003] == Flavor(None, "Plunderstorm")


def test_mod_flavors_dedupes_and_orders():
    flavors = mod_flavors(mod_with_types(88568, 79434, 517, 67408, 517), build_flavor_map([]))
    assert flavors == [
        Flavor(RETAIL, "Retail"),
        Flavor(CLASSIC, "Era"),
        Flavor(CLASSIC, "MoP"),
        Flavor(FOREVER, "Forever"),
    ]


def test_mod_flavors_id_missing_from_map():
    assert mod_flavors(mod_with_types(12345), build_flavor_map([])) == [Flavor(None, "type 12345")]


def test_mod_flavors_without_files():
    assert mod_flavors({"id": 1}, build_flavor_map([])) == []


def test_format_flavors():
    flavors = mod_flavors(mod_with_types(517, 67408, 79434, 88568, 12345), build_flavor_map([]))
    assert format_flavors(flavors) == "Retail · Classic (Era, MoP) · Forever · type 12345"


def test_format_flavors_single_and_empty():
    assert format_flavors(mod_flavors(mod_with_types(88568), build_flavor_map([]))) == "Forever"
    assert format_flavors([]) == ""


def test_passes_filter():
    fmap = build_flavor_map([])
    retail_only = mod_flavors(mod_with_types(517), fmap)
    unknown_only = mod_flavors(mod_with_types(12345), fmap)
    assert passes_filter(retail_only, frozenset())
    assert passes_filter(retail_only, frozenset({RETAIL, FOREVER}))
    assert not passes_filter(retail_only, frozenset({CLASSIC}))
    assert passes_filter(unknown_only, frozenset())
    assert not passes_filter(unknown_only, frozenset({RETAIL}))
    assert not passes_filter([], frozenset({RETAIL}))


def test_build_flavor_map_tolerates_bad_entries():
    fmap = build_flavor_map([
        {"name": "no id"},
        {"id": "x", "name": "string id"},
        {"id": 999, "name": "WoW Something", "slug": None},
    ])
    assert fmap[999] == Flavor(None, "WoW Something")
    assert "x" not in fmap
