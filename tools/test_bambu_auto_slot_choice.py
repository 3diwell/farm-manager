# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.852 — «Авто (как в файле)» берёт слот AMS по ФАКТУ, а не по порядку в файле.

ЗАЧЕМ. 19.08.2026 владелец сообщил: при отправке на печать без ручного выбора слота печать
запускается, но слот всегда берётся первый — даже если он пустой. Отдельно то же самое при
пакетном запуске с интервалом: слот вручную никто не выбирает, принтеры уходят в первый слот,
обнаруживают пустоту, сами подтягивают следующий заряженный, и в уведомлениях появляется
«слот пуст».

КОРЕНЬ. _bambu_ams_mapping отдаёт тождественную карту range(N): филамент №1 файла -> слот №1.
Фактическое состояние AMS не смотрелось вообще — ни пустота слота, ни материал в нём.

РЕШЕНИЕ ВЛАДЕЛЬЦА (спрошено до кода):
  · материал сверяется СТРОГО, цвет — предпочтительно (точный, затем близкий, затем любой):
    из-за оттенка печать вставать не должна;
  · подходящего слота нет вовсе — запускать как раньше, картой из файла: цепочку запусков
    пакетного старта рвать нельзя.

ДОПОЛНЕНО 2.854. Журнал фермы 20.08.2026 показал, что этого мало: три запуска, все файлы с
ДВУМЯ объявленными филаментами, у всех «не доказан» и откат на карту файла [0, 1] — то есть
ровно в слот 1, который и жаловался. Правило «либо доказаны все филаменты, либо ничего»
отбрасывало верно найденный слот из-за лишнего филамента, который плита не печатает. Теперь
каждый филамент решается сам за себя, а слот недоказуемого резервируется за ним.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ: подбор слота на пустом слоте, на чужом материале, предпочтение цвета,
мультифиламент без коллизий, мульти-AMS и AMS HT с их глобальными номерами, откат к карте
файла, неприкосновенность явного выбора слота и внешней катушки. Отдельно — НЕ ВАКУУМ:
прежняя тождественная карта на тех же данных отправляла в пустой слот.

КАК. Ни сервер, ни принтер не поднимаются: из server.py в рантайме ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ
исходники (_bambu_tray2, _bambu_auto_slot_map, _bambu_auto_mapping, _bambu_resolve_ams) и
исполняются со стабом состояния принтера — тот же способ, что в tools/test_bambu_print_payload.py.
Правила сравнения материала и цвета берутся из НАСТОЯЩЕГО app/project_orchestrator (не копия),
чтобы тест не разъехался с планом подачи. Ни одна команда никуда не отправляется.

Запуск:  python tools/test_bambu_auto_slot_choice.py      (0 = дефект закрыт)
"""
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
SENTINEL = "BAMBU_AUTO_SLOT_CHOICE_SENTINEL_2_852"

from app import project_orchestrator as _orch   # noqa: E402  настоящие правила сравнения
#  16.10.2026 (R-006, R-139): раскладка по слотам и разбор AMS — общие чистые модули, берутся настоящие.
from app import bambu_slot_match as _bslot      # noqa: E402
from app import bambu_ams_state as _bams        # noqa: E402

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def _slice(src, a, b):
    i = src.index(a)
    j = src.index(b, i)
    return src[i:j]


BLOCK = _slice(SRC, "def _bambu_tray2(", "\ndef _apply_bambu_print_opts(")
check("1. извлечён дословный исходник авто-подбора и разрешения источника подачи",
      "_bambu_auto_slot_map" in BLOCK and "_bambu_resolve_ams" in BLOCK and "_bambu_auto_mapping" in BLOCK)


class _Log:
    def __init__(self):
        self.lines = []

    def _w(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    info = debug = warning = error = _w


PID = "node_h2d"


def tray(index, kind, color=None, unit=None, slot=None, remain=None, present=None, fid="", ext=None):
    """Слот AMS в том виде, в каком его кладёт разбор отчёта принтера (on_msg).
    kind='Empty' — пустой слот; color_raw — сырой tray_color без решётки, как у Bambu.
    16.10.2026: present — датчик подачи (tray_exist_bits; None — маски нет), fid — tray_info_idx,
    ext — сопло, к которому подключён блок (ams[].info биты 8-11: 0 правое, 1 левое)."""
    return {"index": index, "unit": (index // 4 if unit is None else unit),
            "tray": (index % 4 if slot is None else slot),
            "type": kind, "color": ("#" + color) if color else "#3f3f46",
            "color_raw": color or "",
            #  2.991: остаток слота процентами; None = принтер не знает (у Bambu это -1).
            "remain": remain, "present": present, "tray_info_idx": fid, "extruder": ext}


def build(trays, filaments, file_map, plate=None, sides=None):
    """Исполняет извлечённый исходник со стабами состояния принтера и требований файла.
    sides — то, что вернёт _3mf_filament_sides (сопла филаментов H2D); None — файл их не описывает."""
    log = _Log()
    ns = {
        "p_states": {PID: {"ams_trays": list(trays)}},
        "log": log, "_exc_brief": (lambda: ""), "_orch": _orch, "_bslot": _bslot, "_bams": _bams,
        "_3mf_filament_requirements": (lambda fdata: {"filament_count": len(filaments),
                                                      "filaments": list(filaments)}),
        "_bambu_ams_mapping": (lambda fdata: (True, list(file_map))),
        #  16.10.2026 (R-136): какие филаменты печатает плита; None — плита не описана (все филаменты)
        "_3mf_plate_used": (lambda fdata: ({"ok": True, "source": "plate", "idx": list(plate)}
                                           if plate is not None else {"ok": False})),
        "_3mf_filament_sides": (lambda fdata: (dict(sides) if sides is not None else {"ok": False})),
    }
    exec(compile(BLOCK, "<ams>", "exec"), ns)
    ns["_log"] = log
    return ns


def fil(i, material, color=None, support=False, fid=None):
    return {"file_index": i, "material": material, "color_hex": color, "is_support": support,
            "filament_id": fid}


FDATA = b"PK-fake-3mf"          # содержимое не разбирается: требования приходят стабом

print("--- 2. Корень дефекта: первый слот пуст ---")
trays = [tray(0, "Empty"), tray(1, "PLA", "FF0000"), tray(2, "PETG", "00FF00"), tray(3, "Empty")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("2. авто-режим включает AMS", use is True, use)
check("3. КОРЕНЬ ДЕФЕКТА: слот взят по факту (1), а не первый по порядку (0)", mp == [1], mp)
check("4. ams_mapping2 указывает на РЕАЛЬНЫЕ unit/tray выбранного слота",
      mp2 == [{"ams_id": 0, "slot_id": 1}], mp2)
check("5. НЕ ВАКУУМ: прежняя тождественная карта отправляла ровно в пустой слот 0",
      ns["_bambu_ams_mapping"](FDATA)[1] == [0])
check("6. решение объяснено в логе (диагностика на ферме)",
      any("реальные слоты" in x for x in ns["_log"].lines), ns["_log"].lines)

print("--- 3. Чужой материал слотом не считается ---")
trays = [tray(0, "PETG", "FF0000"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("7. слот 0 заряжен, но другим материалом — берётся слот 1",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

trays = [tray(0, "PLA-CF", "FF0000"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("8. алиасы запрещены: PLA-CF это НЕ PLA (общие правила плана подачи)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

print("--- 4. Цвет: предпочтительно, но печать из-за него не встаёт ---")
trays = [tray(0, "PLA", "000000"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("9. среди подходящих по материалу выбирается ТОЧНЫЙ цвет", ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

trays = [tray(0, "PLA", "000000"), tray(1, "PLA", "FF0102")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("10. точного нет — берётся БЛИЗКИЙ цвет, а не первый попавшийся",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

trays = [tray(0, "PLA", "000000"), tray(1, "PLA", "00FF00")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("11. подходящего цвета нет вовсе — материал важнее, слот всё равно выбран (печать не встаёт)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])

trays = [tray(0, "Empty"), tray(1, "PLA", "00FF00")]
ns = build(trays, [fil(0, "PLA", None)], [0])
check("12. цвет в файле не назван — сверяется только материал, пустой слот всё равно пропущен",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

print("--- 5. Мультифиламент и несколько AMS ---")
trays = [tray(0, "Empty"), tray(1, "PETG", "0000FF"), tray(2, "PLA", "FF0000"), tray(3, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000"), fil(1, "PETG", "#0000FF")], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("13. каждый филамент уехал в свой подходящий слот", mp == [2, 1], mp)
check("14. один слот не достался двум филаментам", len(set(mp)) == len(mp), mp)

trays = [tray(0, "Empty"), tray(1, "PLA", "FF0000"), tray(2, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000"), fil(1, "PLA", "#FF0000")], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("15. два одинаковых филамента — два РАЗНЫХ заряженных слота", mp == [1, 2], mp)

# мульти-AMS и AMS HT: глобальные номера, а не позиция в списке
trays = [tray(0, "Empty"), tray(5, "Empty", unit=1, slot=1), tray(512, "PLA", "FF0000", unit=128, slot=0)]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("16. AMS HT: выбран глобальный слот 512, а не позиция в списке", mp == [512], mp)
check("17. и unit/tray для него взяты из отчёта принтера (128/0)",
      mp2 == [{"ams_id": 128, "slot_id": 0}], mp2)

print("--- 6. Границы: где авто-подбор НЕ вмешивается ---")
trays = [tray(0, "Empty"), tray(1, "Empty")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("18. РЕШЕНИЕ ВЛАДЕЛЬЦА: подходящего слота нет — уходит прежняя карта файла, запуск не рвётся",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])
check("19. и это честно сказано в логе, а не сделано молча",
      any("ничего не изменил" in x for x in ns["_log"].lines), ns["_log"].lines)
check("19a. в ту же строку журнала попали ОБЕ стороны сравнения — требования файла и слоты AMS",
      any(("файл требует" in x and "в AMS" in x) for x in ns["_log"].lines), ns["_log"].lines)

trays = [tray(0, "Empty"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, None, "#FF0000")], [0])
check("20. материал в файле не назван — не угадываем, карта файла остаётся",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])

trays = [tray(0, "Empty"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, -1, FDATA)
check("21. ВНЕШНЯЯ катушка (-1) авто-подбором не трогается", (use, mp, mp2) == (False, [-1], [{"ams_id": 255, "slot_id": 0}]),
      (use, mp, mp2))

use, mp, mp2 = ns["_bambu_resolve_ams"](PID, 0, FDATA)
check("22. ЯВНО выбранный слот 0 остаётся слотом 0 — выбор человека не переигрываем",
      (use, mp) == (True, [0]), (use, mp))

ns = build([], [fil(0, "PLA", "#FF0000")], [0])
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("23. принтер без AMS — по-прежнему внешняя подача", (use, mp) == (False, [-1]), (use, mp))

print("--- 6a. Пофиламентно, а не «всё или ничего» (случай фермы 20.08.2026) ---")

# Ровно то, что было на ферме: файл объявляет ДВА филамента, печатает по сути одним,
# в AMS лежит один подходящий. Прежнее правило отбрасывало верно найденный слот целиком.
trays = [tray(0, "Empty"), tray(1, "Empty"), tray(2, "PETG", "1A1A1A"), tray(3, "Empty")]
ns = build(trays, [fil(0, "PETG", "#1A1A1A"), fil(1, None)], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("26. КОРЕНЬ ЖАЛОБЫ: доказанный филамент получил реальный слот, несмотря на соседа без требований",
      mp == [2, 1], mp)
check("27. недоказуемый филамент остался на СВОЁМ слоте из файла (прежнее поведение)",
      mp[1] == 1, mp)
check("28. НЕ ВАКУУМ: прежнее правило «всё или ничего» на этих же данных вернуло бы карту файла",
      [0, 1] != mp, mp)

# Слот недоказуемого филамента резервируется: доказанный не имеет права его увести.
trays = [tray(0, "Empty"), tray(1, "PETG", "1A1A1A")]
ns = build(trays, [fil(0, "PETG", "#1A1A1A"), fil(1, None)], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("29. единственный подходящий слот занят соседом «как в файле» — карта не меняется, столкновения нет",
      mp == [0, 1] and len(set(mp)) == 2, mp)

# Требований прочиталось меньше, чем филаментов: недостающие остаются как в файле.
trays = [tray(0, "Empty"), tray(1, "Empty"), tray(2, "PLA", "FFFFFF")]
ns = build(trays, [fil(0, "PLA", "#FFFFFF")], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("30. требований меньше, чем филаментов — доказанный уходит в реальный слот, второй как в файле",
      mp == [2, 1], mp)

# Ни одного доказанного — карта обязана остаться прежней, ровно как до 2.854.
trays = [tray(0, "Empty"), tray(1, "Empty")]
ns = build(trays, [fil(0, "PETG", "#1A1A1A"), fil(1, "PETG", "#1A1A1A")], [0, 1])
check("31. ни одного доказанного слота — карта файла не тронута (хуже прежнего не становится)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0, 1])

print("--- 7. Правила сравнения общие с планом подачи, а не вторая копия ---")
#  16.10.2026: раскладка переехала в app/bambu_slot_match.py, поэтому проверяется ИСПОЛНЕНИЕМ, а не
#  текстом: подбор обязан звать правила оркестратора, которые ему передал сервер.
_calls = {"norm_material": 0, "color_relation": 0}


class _SpyOrch:
    REL_EXACT, REL_CLOSE = _orch.REL_EXACT, _orch.REL_CLOSE

    @staticmethod
    def norm_material(v):
        _calls["norm_material"] += 1
        return _orch.norm_material(v)

    @staticmethod
    def color_relation(a, b):
        _calls["color_relation"] += 1
        return _orch.color_relation(a, b)


ns = build([tray(0, "PLA", "000000"), tray(1, "PLA", "FF0000")], [fil(0, "PLA", "#FF0000")], [0])
ns["_orch"] = _SpyOrch
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("24. подбор использует norm_material и color_relation оркестратора (исполнением)",
      mp == [1] and _calls["norm_material"] > 0 and _calls["color_relation"] > 0, (mp, _calls))
ns = build([tray(0, "EMPTY"), tray(1, "Empty")], [fil(0, "empty", None)], [1])
check("25. пустой слот отсеивается явно: даже «материал» empty в файле не уводит в пустой слот 0",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])
check("32. сводка для журнала собирается отдельной функцией и показывает обе стороны",
      "_bambu_feed_report" in BLOCK and "файл требует" in BLOCK and "в AMS" in BLOCK)

print()
print("--- 6. Остаток в слоте (2.991): почти пустой уступает такому же полному ---")
#  Фото владельца 10.09.2026: через несколько минут после запуска H2D сообщил, что филамент
#  в слоте 1 кончился и он сам переключился на такой же. По документации Bambu это штатная
#  подмена (AMS Filament Backup), не ошибка. Но повод создавали мы: среди одинаково
#  подходящих слотов брался слот с меньшим номером, а сколько в нём осталось — не смотрели.
trays = [tray(0, "PETG", "0000FF", remain=4), tray(1, "PETG", "0000FF", remain=85)]
ns = build(trays, [fil(0, "PETG", "#0000FF")], [0])
use, mp, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("34. КОРЕНЬ: слот на исходе (4 %) уступает такому же полному (85 %)", mp == [1], mp)

#  НЕ ВАКУУМ: те же слоты без сведений об остатке дают прежний выбор — первый по номеру.
trays = [tray(0, "PETG", "0000FF"), tray(1, "PETG", "0000FF")]
ns = build(trays, [fil(0, "PETG", "#0000FF")], [0])
use, mp, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("35. НЕ ВАКУУМ: остаток неизвестен у обоих — выбор прежний (слот 0)", mp == [0], mp)

#  Катушки без метки RFID принтер отдаёт с remain=-1. Штрафовать их нельзя: иначе программа
#  систематически обходила бы весь филамент без меток.
trays = [tray(0, "PETG", "0000FF", remain=-1), tray(1, "PETG", "0000FF", remain=85)]
ns = build(trays, [fil(0, "PETG", "#0000FF")], [0])
use, mp, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("36. катушка без метки (остаток -1) не штрафуется — остаётся слот 0", mp == [0], mp)

#  Оба на исходе — выбирать не из чего, поведение прежнее.
trays = [tray(0, "PETG", "0000FF", remain=3), tray(1, "PETG", "0000FF", remain=5)]
ns = build(trays, [fil(0, "PETG", "#0000FF")], [0])
use, mp, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("37. оба слота на исходе — выбор прежний (слот 0), программа не выдумывает", mp == [0], mp)

#  Материал и цвет по-прежнему решают ПЕРВЫМИ: полный слот с другим материалом не уводит
#  печать у подходящего, пусть и небогатого.
trays = [tray(0, "PLA", "0000FF", remain=90), tray(1, "PETG", "0000FF", remain=6)]
ns = build(trays, [fil(0, "PETG", "#0000FF")], [0])
use, mp, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("38. материал важнее остатка: подходящий PETG (6 %) выбран, а не полный PLA", mp == [1], mp)

check("39. остаток виден в журнале подбора (диагностика на ферме)",
      any("%" in x for x in ns["_log"].lines), ns["_log"].lines)

print("--- 8. R-136: слоты — только филаментам отправляемой плиты (как у Bambu Studio) ---")
#  Проект объявляет PLA, PETG, PLA, ABS; плита печатает только PETG (индекс 1); PETG лежит в слоте 1 (индекс 0).
trays = [tray(0, "PETG", "0000FF"), tray(1, "Empty"), tray(2, "Empty"), tray(3, "Empty")]
_f4 = [fil(0, "PLA", "#FF0000"), fil(1, "PETG", "#0000FF"), fil(2, "PLA", "#00FF00"), fil(3, "ABS", "#000000")]
ns = build(trays, _f4, [0, 1, 2, 3])
use, mp_old, _ = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("40. НЕ ВАКУУМ: без описания плиты слот 0 остаётся за PLA проекта, PETG уезжает в пустой слот 1",
      mp_old[1] != 0, mp_old)
ns = build(trays, _f4, [0, 1, 2, 3], plate=[1])
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("41. плита печатает PETG — он получает слот, где PETG лежит; остальные филаменты проекта «не назначен» (-1)",
      use is True and mp == [-1, 0, -1, -1], mp)
check("42. ams_mapping2 для филаментов вне плиты — {255, 255}, как у Bambu Studio",
      mp2 == [{"ams_id": 255, "slot_id": 255}, {"ams_id": 0, "slot_id": 0},
              {"ams_id": 255, "slot_id": 255}, {"ams_id": 255, "slot_id": 255}], mp2)

#  Два одинаковых красных PLA в проекте, плита печатает второй; красный PLA в AMS один — в слоте 2.
trays = [tray(0, "Empty"), tray(1, "Empty"), tray(2, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000"), fil(1, "PLA", "#FF0000")], [0, 1], plate=[1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("43. одинаковый лишний филамент проекта больше не уводит катушку у того, что печатает плита",
      mp == [-1, 2], mp)

#  Плита печатает оба — поведение прежнее (тот же результат, что без описания плиты).
trays = [tray(0, "Empty"), tray(1, "PETG", "0000FF"), tray(2, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000"), fil(1, "PETG", "#0000FF")], [0, 1], plate=[0, 1])
check("44. плита печатает все филаменты проекта — раскладка прежняя",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [2, 1])

#  Явно выбранный слот и внешняя катушка подбором по-прежнему не трогаются.
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0], plate=[0])
check("45. явный выбор слота и внешней катушки не меняются",
      ns["_bambu_resolve_ams"](PID, 1, FDATA)[1] == [1] and ns["_bambu_resolve_ams"](PID, -1, FDATA)[0] is False)

print("--- 9. R-006 (16.10.2026): правила корректности Bambu Studio ---")
#  Цвет: внутри одной степени совпадения решает расстояние ΔE00, а не номер слота.
#  Красный файла: белый (ΔE00 ≈ 46) в слоте 1, тёмно-красный (ΔE00 ≈ 24) в слоте 2.
trays = [tray(0, "Empty"), tray(1, "PLA", "FFFFFF"), tray(2, "PLA", "8B0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("46. красному ближе тёмно-красный (слот 2), а не белый с меньшим номером", mp == [2], mp)

#  Самая близкая пара — первой: файл чёрный + белый, в AMS белый (0) и серый (1).
trays = [tray(0, "PLA", "FFFFFF"), tray(1, "PLA", "808080")]
ns = build(trays, [fil(0, "PLA", "#000000"), fil(1, "PLA", "#FFFFFF")], [0, 1])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("47. белый файла получает белый слот, чёрный — серый (по порядку в файле было бы наоборот)",
      mp == [1, 0], mp)

#  Датчик подачи: лоток не видит (tray_exist_bits = 0), хотя тип от прошлой катушки остался.
trays = [tray(0, "PLA", "FF0000", present=False), tray(1, "PLA", "FF0000", present=True)]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("48. слот без лотка (датчик подачи) кандидатом не бывает — берётся слот 1", mp == [1], mp)
trays = [tray(0, "PLA", "FF0000"), tray(1, "PLA", "FF0000")]
ns = build(trays, [fil(0, "PLA", "#FF0000")], [0])
check("48b. маски наличия в отчёте нет (present None) — поведение прежнее, слот 0",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])

#  H2D как в отчёте ha-bambulab H2D.json: AMS 0 на ЛЕВОМ сопле (info 0x1101), HT 128 на ПРАВОМ (0x2004).
_h2d = [tray(0, "PLA", "FFFFFF", ext=1, present=True), tray(1, "ABS", "000000", ext=1, present=True),
        tray(512, "PLA", "FFFFFF", unit=128, slot=0, ext=0, present=True)]
_right = {"ok": True, "maps": [2], "extruders": 2, "source": "slice_info"}
ns = build(_h2d, [fil(0, "PLA", "#FFFFFF")], [0], sides=_right)
use, mp, mp2 = ns["_bambu_resolve_ams"](PID, None, FDATA)
check("49. H2D: филамент правого сопла получает слот HT (правое), а не AMS 0 на левом",
      mp == [512] and mp2 == [{"ams_id": 128, "slot_id": 0}], (mp, mp2))
_h2d_no = [tray(0, "PLA", "FFFFFF", ext=1, present=True), tray(1, "ABS", "000000", ext=1, present=True),
           tray(512, "PETG", "FFFFFF", unit=128, slot=0, ext=0, present=True)]
ns = build(_h2d_no, [fil(0, "PLA", "#FFFFFF")], [1], sides=_right)
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("49b. H2D: на правом сопле нужного нет — слот файла остаётся, слот 0 левого AMS НЕ выбирается",
      mp == [1], mp)
#  16.10.2026 (проверка пакета R-006): слот файла 1 — это AMS ЛЕВОГО сопла. Такую карту Bambu Studio не строит,
#  и запуск её не отправит: проверка сопла (_bambu_cross_nozzle) называет филамент, сторону и слот.
ns["p_states"][PID]["nozzle_count"] = 2
_x = ns["_bambu_cross_nozzle"](PID, FDATA, mp)
check("49g. та же карта у двухсопельного — перекрёстная: филамент 1 правого сопла в слоте 1 блока на левом сопле",
      _x and (_x["i"], _x["side"], _x["slot"], _x["extruder"]) == (0, 2, 1, 1) and "правое сопло" in _x["why"], _x)
ns["p_states"][PID]["nozzle_count"] = 1
check("49h. односопельному та же карта не запрещается (сопло блока к нему не относится)",
      ns["_bambu_cross_nozzle"](PID, FDATA, mp) is None)
ns = build(_h2d_no, [fil(0, "PLA", "#FFFFFF")], [1], sides=None)
mp = ns["_bambu_resolve_ams"](PID, None, FDATA)[1]
check("49c. сопло файла неизвестно — по соплу не ограничиваем (прежнее поведение: PLA в слоте 0)",
      mp == [0], mp)
ns = build(_h2d_no, [fil(0, "PLA", "#FFFFFF")], [1],
           sides={"ok": True, "maps": [2], "extruders": 1, "source": "project_settings"})
check("49d. файл на одно сопло — filament_maps не ограничивает выбор",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])
_left = {"ok": True, "maps": [1], "extruders": 2, "source": "slice_info"}
ns = build(_h2d, [fil(0, "PLA", "#FFFFFF")], [1], sides=_left)
check("49e. филамент левого сопла — слот AMS 0 (левое), а не HT",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])
_h2d_sw = [tray(0, "PLA", "FFFFFF", ext=None, present=True), tray(512, "PETG", "FFFFFF", unit=128, slot=0, ext=0)]
ns = build(_h2d_sw, [fil(0, "PLA", "#FFFFFF")], [1], sides=_right)
check("49f. сопло блока неизвестно (переключатель/нет info) — по соплу не ограничиваем",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])

#  Опорные материалы — как в Bambu Studio.
trays = [tray(0, "PLA", "FFFFFF"), tray(1, "Sup.PLA", "FFFFFF")]
ns = build(trays, [fil(0, "PLA", "#FFFFFF", support=True)], [0])
check("50. опорный PLA файла (filament_is_support) уходит в Sup.PLA, а не в обычный PLA",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])
trays = [tray(0, "Sup.PLA", "FFFFFF"), tray(1, "PLA", "FFFFFF")]
ns = build(trays, [fil(0, "PLA", "#FFFFFF")], [0])
check("50b. обычный PLA не уходит в слот опорного Sup.PLA",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])
trays = [tray(0, "PA", "FFFFFF"), tray(1, "Support G", "FFFFFF"), tray(2, "Support W", "FFFFFF")]
ns = build(trays, [fil(0, "PA", "#FFFFFF", support=True), fil(1, "PLA", "#FFFFFF", support=True)], [0, 1])
check("50c. Support G — PA-S, Support W — PLA-S (опорные PA и PLA файла)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1, 2])
trays = [tray(0, "Empty"), tray(1, "PLA", "FFFFFF")]
ns = build(trays, [fil(0, "PLA", "#FFFFFF", support=True)], [0])
check("50d. опорному PLA обычный PLA не годится — слот файла остаётся",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])

#  При равенстве — тот же filament_id (tray_info_idx): Basic GFA00 и Matte GFA01 одного цвета.
trays = [tray(0, "PLA", "FFFFFF", fid="GFA01"), tray(1, "PLA", "FFFFFF", fid="GFA00")]
ns = build(trays, [fil(0, "PLA", "#FFFFFF", fid="GFA00")], [0])
check("51. одинаковые по материалу и цвету — выбирается тот же filament_id (GFA00 в слоте 1)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])
ns = build(trays, [fil(0, "PLA", "#FFFFFF")], [0])
check("51b. filament_id в файле не назван — выбор прежний (слот 0)",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [0])
trays = [tray(0, "PLA", "FFFFFF", fid="GFA00", remain=5), tray(1, "PLA", "FFFFFF", fid="GFA01", remain=80)]
ns = build(trays, [fil(0, "PLA", "#FFFFFF", fid="GFA00")], [0])
check("51c. политика фермы 2.991 важнее filament_id: почти пустая катушка уступает полной",
      ns["_bambu_resolve_ams"](PID, None, FDATA)[1] == [1])

#  Команда принтеру: AMS HT в плоском ams_mapping — номер блока, внутри программы — 512.
_wire = ns.get("_bambu_wire_mapping", lambda m: list(m))
check("52. плоская карта команды: 512 -> 128, 516 -> 129, слоты AMS и -1 без изменений",
      _wire([512, -1, 3, 516, 15]) == [128, -1, 3, 129, 15], _wire([512, -1, 3, 516, 15]))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
