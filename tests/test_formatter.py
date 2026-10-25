from bot.flavors import build_flavor_map, mod_flavors
from bot.formatter import CAPTION_LIMIT, build_caption, pick_images, tg_len

LOGO = "https://media.forgecdn.net/logo.png"
SHOTS = [f"https://media.forgecdn.net/s{i}.png" for i in range(1, 6)]
URL = "https://www.curseforge.com/wow/addons/mistweaver-teachings-bar"


def make_mod(**overrides):
    mod = {
        "id": 42,
        "name": "Mistweaver Teachings Bar",
        "summary": "Tracks Teachings of the Monastery.",
        "links": {"websiteUrl": URL},
        "authors": [{"name": "Alice"}, {"name": "Bob"}],
        "categories": [{"name": "Monk"}, {"name": "Combat"}],
        "logo": {"url": LOGO},
        "screenshots": [{"url": u} for u in SHOTS],
        "latestFilesIndexes": [
            {"gameVersionTypeId": 517},
            {"gameVersionTypeId": 67408},
            {"gameVersionTypeId": 88568},
        ],
    }
    mod.update(overrides)
    return mod


def caption_of(mod):
    return build_caption(mod, mod_flavors(mod, build_flavor_map([])))


def test_caption_layout():
    assert caption_of(make_mod()) == (
        "🆕 <b>Mistweaver Teachings Bar</b>\n"
        "👤 Alice, Bob · 📂 Monk, Combat\n"
        "🎮 Retail · Classic (Era) · Forever\n"
        "\n"
        "Tracks Teachings of the Monastery.\n"
        "\n"
        f"🔗 {URL}"
    )


def test_caption_escapes_html():
    caption = caption_of(make_mod(name="<Cool> & Co", summary="a < b", authors=[{"name": "R&D"}]))
    assert "<b>&lt;Cool&gt; &amp; Co</b>" in caption
    assert "a &lt; b" in caption
    assert "R&amp;D" in caption


def test_caption_skips_empty_parts():
    mod = make_mod(authors=[], categories=[], summary="  ", latestFilesIndexes=[], links={})
    assert caption_of(mod) == "🆕 <b>Mistweaver Teachings Bar</b>"


def test_long_summary_truncated_to_limit():
    caption = caption_of(make_mod(summary="&" * 3000))
    assert tg_len(caption) <= CAPTION_LIMIT
    assert "&amp;…" in caption  # truncated by the source text, entity intact
    assert caption.startswith("🆕 <b>Mistweaver Teachings Bar</b>\n")
    assert caption.endswith(f"🔗 {URL}")


def test_tg_len_counts_utf16():
    assert tg_len("abc") == 3
    assert tg_len("🆕") == 2


def test_pick_images_logo_plus_three_screenshots():
    assert pick_images(make_mod()) == [LOGO, *SHOTS[:3]]


def test_pick_images_without_screenshots():
    assert pick_images(make_mod(screenshots=[])) == [LOGO]


def test_pick_images_without_logo():
    assert pick_images(make_mod(logo=None)) == SHOTS[:4]


def test_pick_images_dedupes_logo():
    assert pick_images(make_mod(screenshots=[{"url": LOGO}, {"url": SHOTS[0]}])) == [LOGO, SHOTS[0]]


def test_pick_images_nothing():
    assert pick_images(make_mod(logo=None, screenshots=None)) == []


def test_none_name_and_nameless_people_tolerated():
    mod = make_mod(
        name=None,
        authors=[{"name": None}, {}, {"name": "Alice"}],
        categories=[{}, {"name": None}],
    )
    caption = build_caption(mod, [])
    assert caption.startswith("🆕 <b></b>")
    assert "👤 Alice" in caption
    assert "📂" not in caption
