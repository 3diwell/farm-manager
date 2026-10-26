# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Раскладка филаментов файла по слотам AMS — ОДНА на запуск и на очередь. Чистая логика.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ (16.10.2026, R-006). Раньше раскладка жила двумя копиями: подбор запуска
(server._bambu_auto_slot_map) и его зеркало для опроса очереди (server._qw_auto_slot_mirror), и
каждую правку приходилось вносить дважды. Теперь обе функции — тонкие обёртки над assign().

ПРАВИЛА ФЕРМЫ, которые сохраняются как были:
  · материал сверяется строго (norm_material оркестратора, алиасов нет), цвет — предпочтительно;
  · слоты получают только филаменты отправляемой плиты (R-136), остальным -1;
  · филамент, которому доказать нечем, остаётся на СВОЁМ слоте из файла, и этот слот закреплён за ним;
  · один слот не достаётся двум филаментам — иначе вся карта откатывается на карту файла;
  · 2.991: среди одинаково подходящих слотов почти пустой уступает такому же полному. Это
    сознательно наоборот Bambu Studio («сначала начатые катушки»): на ферме без человека катушка,
    кончившаяся посреди печати, — это подмена катушки или пауза.

ЧТО ДОБАВЛЕНО — правила корректности из Bambu Studio (DeviceCore/DevMapping.cpp,
ams_filament_mapping; SelectMachine.cpp; DevFilaSystem.cpp) и Bambuddy (print_scheduler.py):
  · слот, где датчик подачи не видит лотка (present == False, tray_exist_bits), кандидатом не бывает
    (Studio is_valid_mapping_result, check_empty_slot);
  · внутри одной степени совпадения цвета решает расстояние ΔE00 (color_relation оркестратора), а не
    номер слота: красному файла тёмно-красный слот ближе белого;
  · пары «филамент — слот» назначаются от самой близкой ко всё более далёким по всем филаментам
    сразу, а не по порядку в файле (Studio: closest pair first);
  · при равенстве — тот же filament_id (tray_info_idx у слота, filament_ids в файле);
  · опорные материалы приводятся к одному имени, как в Studio: у слота Sup.PLA / Support W /
    Support -> PLA-S, Sup.PA / Support G -> PA-S, Sup.ABS -> ABS-S (DevAmsTray::get_filament_type,
    у «Support» с filament_id GFS01 — PA-S); у файла PLA с filament_is_support -> PLA-S, PA -> PA-S
    (PrintConfig.cpp, get_filament_type);
  · двухсопельные принтеры (H2D): если известны И сопло, к которому подключён AMS (ams[].info,
    биты 8-11: 0 правое, 1 левое), И сопло филамента в файле (filament_maps плиты: 1 левое,
    2 правое), кандидатами остаются только слоты того же сопла. Неизвестно хоть одно — как раньше,
    по соплу не ограничиваем и не угадываем.
"""

GRADE_EXACT, GRADE_CLOSE, GRADE_OTHER = 0, 1, 2
DIST_UNKNOWN = 1000.0          # цвет не сравнить — дальше любого известного (Studio ограничивает 0..1000)

#  Опорные материалы слота -> общее имя (Bambu Studio, DevAmsTray::get_filament_type).
_TRAY_SUPPORT = {"sup.pla": "PLA-S", "support w": "PLA-S", "sup.pa": "PA-S", "support g": "PA-S",
                 "sup.abs": "ABS-S"}
#  Файл: опорный филамент с базовым типом -> общее имя (PrintConfig.cpp, get_filament_type).
_FILE_SUPPORT = {"pla": "PLA-S", "pa": "PA-S"}

#  Сторона в файле (filament_maps) -> номер сопла в отчёте AMS (info, биты 8-11).
SIDE_LEFT, SIDE_RIGHT = 1, 2
_SIDE_TO_EXTRUDER = {SIDE_LEFT: 1, SIDE_RIGHT: 0}


def fila_type(material, is_support=False, filament_id=None):
    """Тип материала для сравнения слота и файла с учётом опорных материалов. Пусто -> ''."""
    s = " ".join(str(material or "").split())
    k = s.casefold()
    if not k:
        return ""
    if k in _TRAY_SUPPORT:
        return _TRAY_SUPPORT[k]
    if k == "support":
        return "PA-S" if str(filament_id or "").strip().upper() == "GFS01" else "PLA-S"
    if is_support and k in _FILE_SUPPORT:
        return _FILE_SUPPORT[k]
    return s


def side_ok(side, extruder):
    """Можно ли филамент стороны side (1 левое, 2 правое, None) печатать из блока на сопле extruder
    (0 правое, 1 левое, None). Неизвестна любая сторона — можно (как было до 16.10.2026)."""
    want = _SIDE_TO_EXTRUDER.get(side)
    if want is None or extruder not in (0, 1):
        return True
    return want == extruder


def with_sides(fils, sides):
    """Филаменты файла + сторона сопла каждого (ключ "side": 1/2/None). sides — результат
    server._3mf_filament_sides. Сопло учитывается только у файла на два сопла."""
    out = []
    maps = []
    try:
        if isinstance(sides, dict) and sides.get("ok") and int(sides.get("extruders") or 0) >= 2:
            maps = list(sides.get("maps") or [])
    except Exception:
        maps = []
    for i, f in enumerate(fils or []):
        d = dict(f) if isinstance(f, dict) else {}
        s = maps[i] if i < len(maps) else None
        d["side"] = s if s in (SIDE_LEFT, SIDE_RIGHT) else None
        out.append(d)
    return out


def _relation(orch, want_col, tray_col, rel_cache):
    """(степень, расстояние) цвета; rel_cache — сравнения за один опрос очереди."""
    ck = (want_col, tray_col)
    if rel_cache is not None and ck in rel_cache:
        rel, dist = rel_cache[ck]
    else:
        rel, dist = orch.color_relation(want_col, tray_col)
        if rel_cache is not None:
            rel_cache[ck] = (rel, dist)
    grade = {orch.REL_EXACT: GRADE_EXACT, orch.REL_CLOSE: GRADE_CLOSE}.get(rel, GRADE_OTHER)
    try:
        d = float(dist) if dist is not None else DIST_UNKNOWN
    except Exception:
        d = DIST_UNKNOWN
    return grade, min(max(d, 0.0), DIST_UNKNOWN)


def assign(trays, fils, file_map, low_pct, orch, remain_fn, plate_idx=None, rel_cache=None):
    """Раскладка филаментов по слотам -> (карта, откат). Карта — список глобальных индексов слотов
    длиной с file_map (-1 — филамент вне плиты); откат True — подбор дал один слот двум филаментам,
    и возвращена карта файла. Ничего не читает и не пишет, только считает."""
    out = [int(x) for x in file_map]
    if plate_idx is not None:
        on = set(plate_idx)
        if any(i in on for i in range(len(out))):
            out = [(v if i in on else -1) for i, v in enumerate(out)]
    # Шаг 1. Кому доказать нечем — закрепляется его слот файла.
    used, provable = set(), []
    for i in range(len(out)):
        if out[i] < 0:
            continue                         # плита его не печатает — слот ему не нужен
        req = fils[i] if i < len(fils) and isinstance(fils[i], dict) else {}
        mat = orch.norm_material(fila_type(req.get("material"), bool(req.get("is_support")),
                                           req.get("filament_id")))
        if mat:
            provable.append((i, mat, req))
        else:
            used.add(out[i])
    # Шаг 2. Кандидаты каждого доказуемого филамента: тот же материал, лоток на месте, то же сопло.
    cand = {}
    for i, mat, req in provable:
        lst = []
        want_col = req.get("color_hex")
        want_fid = str(req.get("filament_id") or "").strip().upper()
        for t in trays or []:
            if not isinstance(t, dict) or t.get("index") is None:
                continue
            try:
                idx = int(t.get("index"))
            except Exception:
                continue
            if t.get("present") is False:
                continue                     # датчик подачи лотка не видит — слот пуст
            t_type = str(t.get("type") or "").strip()
            if not t_type or t_type.lower() == "empty":
                continue                     # ПУСТОЙ слот кандидатом не бывает
            t_fid = str(t.get("tray_info_idx") or "").strip().upper()
            if orch.norm_material(fila_type(t_type, False, t_fid)) != mat:
                continue
            if not side_ok(req.get("side"), t.get("extruder")):
                continue                     # блок подключён к другому соплу
            grade, dist = _relation(orch, want_col, t.get("color_raw") or t.get("color"), rel_cache)
            rem = remain_fn(t.get("remain"))
            low = 1 if (rem is not None and rem <= low_pct) else 0
            fid_miss = 0 if (want_fid and t_fid and want_fid == t_fid) else 1
            lst.append(((grade, low, dist, fid_miss, idx), idx))
        cand[i] = lst
    for i, _m, _r in provable:
        if not cand[i]:
            used.add(out[i])                 # подходящих слотов нет вовсе — остаётся слот файла
    # Шаг 3. Самая близкая пара — первой, по всем филаментам сразу.
    pending = [i for i, _m, _r in provable if cand[i]]
    while pending:
        best = None
        for i in pending:
            for key, idx in cand[i]:
                if idx in used:
                    continue
                k = key + (i,)
                if best is None or k < best[0]:
                    best = (k, i, idx)
        if best is None:
            break                            # остальным слотов не хватило — остаются как в файле
        _k, i, idx = best
        out[i] = idx
        used.add(idx)
        pending.remove(i)
    #  2.978: инвариант «один слот не достаётся двум филаментам». Повтор слота при разных слотах
    #  файла — подбор отменяется целиком: карта файла хуже не будет.
    fm = [int(x) for x in file_map]
    act = [i for i in range(len(out)) if out[i] >= 0]
    if len({out[i] for i in act}) < len({fm[i] for i in act}):
        return [(fm[i] if out[i] >= 0 else -1) for i in range(len(out))], True
    return out, False
