# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — какие выпуски модулей знает эта версия программы (26.09.2026).

ЗАЧЕМ. Владелец: «любая версия модуля должна устанавливаться; если программа знает, что есть
более новая версия, она просто предупреждает». Раньше «знание о новой версии» жило в карте
прав ядра (app/route_policy_registry.py) и работало как ЗАПРЕТ: модуль другой версии не
загружался вовсе. Теперь карта прав решает только, КТО может вызывать маршруты модуля, а
номер выпуска — только повод для предупреждения, и хранится он здесь.

ЧТО ЭТО. Последний известный выпуск каждого модуля, лежащего в папке проекта modules/<id>/.
Набор tools/test_module_version_tolerance.py сверяет таблицу с module.json всех модулей
проекта и краснеет при расхождении — так «программа знает не тот номер» ловится до сборки,
а не у владельца. Модуль, собранный отдельно и новее таблицы, всё равно ставится и работает:
расхождение даёт только отсутствие предупреждения, а не отказ.

ЧИСТЫЙ МОДУЛЬ: стандартная библиотека, без БД, сети и файловой системы.
"""

import re

KNOWN_MODULE_RELEASES = {
    "appearance": "0.17.6",
    "camera_wall": "0.4.4",
    "cost": "0.2.5",
    "inventory": "1.7.41",
    "messengers": "0.1.10",
    "quality": "0.2.3",
}


def _part(p):
    return (0, int(p), "") if re.fullmatch(r"[0-9]+", p) else (1, 0, p.lower())


def version_key(v):
    """Номер выпуска -> ключ для сравнения, как принято для номеров версий:
      * числа сравниваются как числа: «1.7.30» > «1.7.4», «1.10» > «1.9»;
      * «1.7» и «1.7.0» — одно и то же; ведущая «v» не считается («v1.2» == «1.2»);
      * хвост сборки после «+» не участвует («1.7.30+build5» == «1.7.30»);
      * предварительный выпуск старее окончательного: «1.8.0-beta» < «1.8.0»;
      * пустое или нечитаемое — самое старое. Цифры только ASCII (иначе int() падал бы)."""
    s = str(v or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    s = s.split("+", 1)[0]
    rel, _, pre = s.partition("-")
    nums = [p for p in re.split(r"[._ ]+", rel) if p]
    main = [_part(p) for p in nums]
    while main and main[-1] == (0, 0, ""):
        main.pop()
    pre_parts = tuple(_part(p) for p in re.split(r"[.\-_ ]+", pre) if p)
    return (tuple(main), 0 if pre_parts else 1, pre_parts)


def compare_versions(a, b):
    """-1, 0 или 1: a старее, равен или новее b."""
    ka, kb = version_key(a), version_key(b)
    return (ka > kb) - (ka < kb)


def newer_known(module_id, installed_version):
    """Номер более нового выпуска, если программа о нём знает, иначе ''."""
    known = KNOWN_MODULE_RELEASES.get(str(module_id or ""))
    if not known or not str(installed_version or "").strip():
        return ""
    return known if compare_versions(known, installed_version) > 0 else ""
