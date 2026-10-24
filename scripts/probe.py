"""Живая проверка CurseForge API для бота. Запуск из корня проекта:

    uv run --env-file .env python -m scripts.probe
"""
import os
from collections import Counter
from datetime import UTC, datetime, timedelta

from bot.curseforge import CurseForgeClient, parse_date
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

    mods = curseforge.latest_released()
    dates = [d for d in (parse_date(m.get("dateReleased")) for m in mods) if d]
    print(f"== Поиск: {len(mods)} аддонов; по dateReleased убыв.: {dates == sorted(dates, reverse=True)}")
    if dates:
        print(f"   от {dates[-1]} до {dates[0]} (запас при опросе раз в 10 мин)")
    updates_of_old = 0
    created_recently = 0
    now = datetime.now(UTC)
    for m in mods:
        created, released = parse_date(m.get("dateCreated")), parse_date(m.get("dateReleased"))
        if created and released and released - created > timedelta(days=7):
            updates_of_old += 1
        if created and now - created <= timedelta(days=14):
            created_recently += 1
    print(f"== Обновления старых аддонов (dateCreated раньше dateReleased больше чем на 7 дней): {updates_of_old}")
    print(f"== Созданы за последние 14 дней: {created_recently}")
    print(f"== classId в выдаче: {dict(Counter(m.get('classId') for m in mods))}")
    with_forever = sum(
        1 for m in mods if any(i.get("gameVersionTypeId") == FOREVER_ID for i in m.get("latestFilesIndexes") or [])
    )
    print(f"== Аддонов с файлами под Forever ({FOREVER_ID}): {with_forever}")
    print("== Первые 5:")
    for m in mods[:5]:
        print(
            f"  {m['id']} {m.get('name')!r} created={m.get('dateCreated')} released={m.get('dateReleased')} [{format_flavors(mod_flavors(m, flavor_map))}]"
            f" logo={bool(m.get('logo'))} screenshots={len(m.get('screenshots') or [])}"
        )


if __name__ == "__main__":
    main()
