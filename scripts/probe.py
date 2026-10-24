"""Живая проверка CurseForge API для бота. Запуск из корня проекта:

    uv run --env-file .env python -m scripts.probe
"""
import os
from collections import Counter

from bot.curseforge import WOW_GAME_ID, CurseForgeClient
from bot.flavors import KNOWN_TYPES, build_flavor_map, format_flavors, mod_flavors

FOREVER_ID = 88568


def main() -> None:
    curseforge = CurseForgeClient(os.environ["CURSEFORGE_API_KEY"])

    types = curseforge.version_types()
    by_id = {t["id"]: t for t in types}
    print(f"== Типы версий: {len(types)} в API")
    for type_id, flavor in KNOWN_TYPES.items():
        t = by_id.get(type_id)
        found = "НЕТ В API" if t is None else f"{t.get('name')!r} slug={t.get('slug')!r}"
        print(f"  {type_id:>6} {flavor.group:<8} {flavor.label:<8} → {found}")

    flavor_map = build_flavor_map(types)
    print("== Типы из API, которых нет во встроенной таблице:")
    for t in types:
        if t["id"] not in KNOWN_TYPES:
            f = flavor_map[t["id"]]
            print(f"  {t['id']:>6} {t.get('name')!r} slug={t.get('slug')!r} → group={f.group} label={f.label!r}")

    max_id = curseforge.find_max_id()
    print(f"== Максимальный id аддона: {max_id}")
    mods = curseforge.get_mods(list(range(max_id - 9999, max_id + 1)))
    print(f"== Последние 10 000 id: найдено аддонов {len(mods)}")
    print(f"== Игры (топ-5 по числу аддонов): {Counter(m.get('gameId') for m in mods).most_common(5)}")
    wow = [m for m in mods if m.get("gameId") == WOW_GAME_ID]
    print(f"== Аддонов WoW: {len(wow)}")
    per_day = Counter((m.get("dateCreated") or "?")[:10] for m in wow)
    print("== WoW по дням создания:")
    for day, count in sorted(per_day.items()):
        print(f"  {day} {count}")
    print(f"== WoW (status, isAvailable): {dict(Counter((m.get('status'), m.get('isAvailable')) for m in wow))}")
    approved = [m for m in wow if m.get("status") == 4 and m.get("isAvailable")]
    with_forever = sum(
        1 for m in approved if any(i.get("gameVersionTypeId") == FOREVER_ID for i in m.get("latestFilesIndexes") or [])
    )
    print(f"== Одобренных WoW с файлами под Forever ({FOREVER_ID}): {with_forever} из {len(approved)}")
    print("== 5 новейших одобренных WoW:")
    for m in sorted(approved, key=lambda m: m.get("id", 0), reverse=True)[:5]:
        print(
            f"  {m.get('id')} {m.get('name')!r} created={m.get('dateCreated')} [{format_flavors(mod_flavors(m, flavor_map))}]"
            f" logo={bool(m.get('logo'))} screenshots={len(m.get('screenshots') or [])}"
        )


if __name__ == "__main__":
    main()
