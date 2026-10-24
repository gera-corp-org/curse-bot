"""Подпись к уведомлению о новом аддоне и выбор картинок."""
from html import escape

from bot.flavors import Flavor, format_flavors

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram
MAX_IMAGES = 4  # логотип + до 3 скриншотов


def tg_len(text: str) -> int:
    """Длина так, как её считает Telegram: в UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def pick_images(mod: dict) -> list[str]:
    """Логотип и первые скриншоты, без повторов, не больше MAX_IMAGES."""
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
    head = [f"🆕 <b>{escape(mod.get('name', ''))}</b>"]
    meta = []
    authors = ", ".join(a["name"] for a in mod.get("authors") or [])
    if authors:
        meta.append(f"👤 {escape(authors)}")
    categories = ", ".join(c["name"] for c in mod.get("categories") or [])
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
    """Собрать подпись; если не влезает в лимит — обрезать только summary."""
    text = _render(head, summary, tail)
    if tg_len(text) <= CAPTION_LIMIT:
        return text
    # двоичный поиск самого длинного начала summary, которое ещё влезает
    lo, hi = 0, len(summary)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tg_len(_render(head, _cut(summary, mid), tail)) <= CAPTION_LIMIT:
            lo = mid
        else:
            hi = mid - 1
    return _render(head, _cut(summary, lo), tail)
