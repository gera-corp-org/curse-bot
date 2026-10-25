"""Caption for a new-addon notification and image selection."""
from html import escape

from bot.flavors import Flavor, format_flavors

CAPTION_LIMIT = 1024  # Telegram photo caption limit
MAX_IMAGES = 4  # logo + up to 3 screenshots


def tg_len(text: str) -> int:
    """Length as Telegram counts it: in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def pick_images(mod: dict) -> list[str]:
    """Logo and first screenshots, without duplicates, at most MAX_IMAGES."""
    urls: list[str] = []
    logo = (mod.get("logo") or {}).get("url")
    if logo:
        urls.append(logo)
    for shot in mod.get("screenshots") or []:
        if len(urls) == MAX_IMAGES:
            break
        url = shot.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls


def build_caption(mod: dict, flavors: list[Flavor]) -> str:
    head = [f"🆕 <b>{escape(mod.get('name') or '')}</b>"]
    meta = []
    authors = ", ".join(a["name"] for a in mod.get("authors") or [] if a.get("name"))
    if authors:
        meta.append(f"👤 {escape(authors)}")
    categories = ", ".join(c["name"] for c in mod.get("categories") or [] if c.get("name"))
    if categories:
        meta.append(f"📂 {escape(categories)}")
    if meta:
        head.append(" · ".join(meta))
    versions = format_flavors(flavors)
    if versions:
        head.append(f"🎮 {escape(versions)}")

    url = (mod.get("links") or {}).get("websiteUrl")
    tail = f"🔗 {escape(url)}" if url else ""
    return _fit("\n".join(head), (mod.get("summary") or "").strip(), tail)


def _render(head: str, summary: str, tail: str) -> str:
    return "\n\n".join(part for part in (head, escape(summary), tail) if part)


def _cut(summary: str, keep: int) -> str:
    return summary[:keep].rstrip() + "…" if keep else ""


def _fit(head: str, summary: str, tail: str) -> str:
    """Build the caption; if it exceeds the limit, truncate only the summary."""
    text = _render(head, summary, tail)
    if tg_len(text) <= CAPTION_LIMIT:
        return text
    # binary search for the longest summary prefix that still fits
    lo, hi = 0, len(summary)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tg_len(_render(head, _cut(summary, mid), tail)) <= CAPTION_LIMIT:
            lo = mid
        else:
            hi = mid - 1
    return _render(head, _cut(summary, lo), tail)
