# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Состояние AMS принтера Bambu из отчётов print.ams — чистая логика без сети и без сервера.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ (16.10.2026, R-139, R-116, R-006). Прежний разбор жил прямо в on_msg и
имел три дефекта, которые видно в коде:
  1. ПУСТОЙ список print.ams.ams пропускался («if amsd.get("ams")»), а именно так Bambu Studio
     узнаёт, что AMS сняли. Слоты снятого AMS оставались в программе, запуск слал use_ams=true с
     картой слотов принтеру без AMS — прошивка отвечает «Failed to get AMS mapping table»
     (07FF-8012) и ставит печать на паузу, а склад видел «заправленные» несуществующие слоты.
  2. Физическое наличие лотка не читалось вовсе: оно приходит отдельной битовой маской
     tray_exist_bits (датчик подачи AMS), а тип и цвет прошивка может держать от прошлой катушки.
     Пустой слот с «PLA» в отчёте подбор считал заправленным.
  3. Короткий словарь лотка {id, state} без tray_type превращался в «Empty» — терялся материал.

КОНТРАКТ — исходники Bambu Studio (src/slic3r/GUI/DeviceCore/DevFilaSystem.cpp, ParseV1_0 и
ParseAmsInfo), сверено с открытыми интеграциями ha-bambulab (PR #2113, issue #2164, #2131),
Bambuddy (ams_slot_presence.py) и printforce-link (PR #21), и с настоящим отчётом H2D из
ha-bambulab tests/pybambu/H2D.json:
  · ams_exist_bits / tray_exist_bits — шестнадцатеричные строки (у P1 бывает целое число);
    H2D: ams_exist_bits "11", tray_exist_bits "1000f" — AMS 0 со слотами 0-3 и AMS HT 128 (бит 16);
  · бит наличия блока: AMS, AMS Lite, AMS 2 Pro — бит ams_id; AMS HT — 4+(id-128);
    AMS Lite в смешанном режиме — бит 12;
  · бит наличия лотка: ams_id*4+slot; AMS HT — 16+(id-128)+slot; AMS Lite смешанный — 24+slot;
  · ams[].info — шестнадцатеричная строка: биты 0-3 — тип блока (1 AMS, 2 AMS Lite, 3 AMS 2 Pro,
    4 AMS HT, 5 AMS Lite смешанный), биты 8-11 — сопло, к которому подключён блок:
    0 — правое (основное), 1 — левое (второе), 0xE — переключатель. H2D: AMS 0 info "1101"
    (AMS на левом сопле), HT 128 info "2004" (HT на правом);
  · словарь лотка без tray_type — служебное обновление ({id, state}), материал не меняется;
    пустой слот прошивка шлёт голым {"id": "0"}, и решает здесь tray_exist_bits.

ПРАВИЛА СНЯТИЯ БЛОКА (решение R-139). Блок убирается из состояния только когда одновременно:
  · его нет в пришедшем списке print.ams.ams;
  · его бит в ams_exist_bits (этого или последнего отчёта) снят;
  · так было в двух отчётах со списком подряд, разделённых не меньше чем REMOVE_CONFIRM_S секунд.
Первый отчёт после подключения бывает с пустым списком при живом AMS (ha-bambulab PR #2113) —
один такой отчёт ничего не снимает. Маски нет вовсе — ничего не снимается никогда («a missing
bitmask is not an unload», printforce-link PR #21).

СЛЕД СНЯТОГО БЛОКА (16.10.2026, проверка пакета R-139). Номера слотов снятого блока остаются в
ams_removed, пока блок не вернётся в список. Ядро показывает их складу пустыми AMS-позициями
(server._printer_reported_filament): без этого склад решал «у принтера AMS нет вовсе» и включал
старое правило «внешняя катушка = слот 0» — печать с внешней катушки списывалась бы с катушки,
привязанной к слоту 0 снятого AMS. Запуск и очередь по-прежнему видят только ams_trays.

Номер слота в программе прежний: index = unit*4 + tray (у HT 512..540) — на нём держатся
привязки склада и интерфейс. Всё в модуле fail-safe: мусор в отчёте оставляет прежнее значение.
"""

REMOVE_CONFIRM_S = 10.0

UNIT_AMS, UNIT_LITE, UNIT_AMS2_PRO, UNIT_HT, UNIT_LITE_MIXED = 1, 2, 3, 4, 5
EXT_MAIN, EXT_DEPUTY = 0, 1          # сопло, к которому подключён блок: 0 правое, 1 левое (H2D)
HT_FIRST, HT_LAST = 128, 135         # номера блоков AMS HT
VIRTUAL_TRAYS = (254, 255)           # tray_now внешней катушки (254 — левая у H2D)

_EMPTY_COLOR = "#3f3f46"


def parse_bits(v):
    """Битовая маска отчёта -> int или None. Строка — шестнадцатеричная (как у Bambu Studio,
    stol(..., 16)); целое число принимается как есть (так шлёт часть прошивок P1). Мусор -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    try:
        s = str(v).strip()
        if not s:
            return None
        if s.lower().startswith("0x"):
            s = s[2:]
        n = int(s, 16)
        return n if n >= 0 else None
    except Exception:
        return None


def tray_remain(v):
    """Остаток в слоте процентами или None, если принтер его не знает (у катушек без метки RFID
    Bambu отдаёт -1). None честнее нуля: ноль означал бы «пусто». Правило то же, что у
    server._tray_remain — тот теперь зовёт эту функцию."""
    try:
        n = int(v)
    except Exception:
        return None
    return n if 0 <= n <= 100 else None


def unit_type(info, unit_id):
    """Тип блока из ams[].info (биты 0-3). Нет info — AMS HT по номеру (128..135), иначе обычный AMS."""
    if isinstance(info, int) and (info & 0xF) in (UNIT_AMS, UNIT_LITE, UNIT_AMS2_PRO, UNIT_HT, UNIT_LITE_MIXED):
        return info & 0xF
    return UNIT_HT if HT_FIRST <= int(unit_id) <= HT_LAST else UNIT_AMS


def unit_extruder(info):
    """Сопло, к которому подключён блок (ams[].info, биты 8-11): 0 правое, 1 левое; иначе None
    (переключатель 0xE, нет info) — в подборе такой блок по соплу не ограничивается."""
    if not isinstance(info, int):
        return None
    e = (info >> 8) & 0xF
    return e if e in (EXT_MAIN, EXT_DEPUTY) else None


def unit_bit(unit_id, utype):
    """Номер бита блока в ams_exist_bits (DevFilaSystem.cpp, m_exist)."""
    uid = int(unit_id)
    if utype == UNIT_LITE_MIXED:
        return 12
    if utype == UNIT_HT or HT_FIRST <= uid <= HT_LAST:
        return 4 + (uid - HT_FIRST)
    return uid


def tray_bit(unit_id, slot, utype):
    """Номер бита лотка в tray_exist_bits (DevFilaSystem.cpp, GetTrayId)."""
    uid, sl = int(unit_id), int(slot)
    if utype == UNIT_LITE_MIXED:
        return 24 + sl
    if utype == UNIT_HT or HT_FIRST <= uid <= HT_LAST:
        return 16 + (uid - HT_FIRST) + sl
    return uid * 4 + sl


def bit_set(mask, bit):
    """Бит маски: True / False; маски нет -> None (не знаем)."""
    if mask is None or bit is None or bit < 0:
        return None
    return bool((int(mask) >> int(bit)) & 1)


def _now_value(v, prev):
    """tray_now / tray_tar -> номер слота или -1 (внешняя катушка 254/255). Мусор — прежнее."""
    try:
        n = int(str(v).strip())
    except Exception:
        return prev
    return -1 if n in VIRTUAL_TRAYS else n


def _blank_tray(uid, sl):
    return {"index": uid * 4 + sl, "unit": uid, "tray": sl, "type": "Empty", "color": _EMPTY_COLOR,
            "color_raw": "", "remain": None, "tray_info_idx": ""}


def _material_from(tray, base):
    """Полный словарь лотка (есть tray_type) -> поля материала поверх base."""
    out = dict(base)
    tc = tray.get("tray_color")
    tc = tc if isinstance(tc, str) else ""
    out["type"] = str(tray.get("tray_type") or "") or "Empty"
    out["color"] = ("#" + tc[:6]) if tc else _EMPTY_COLOR
    out["color_raw"] = tc
    #  2.991: остаток процентами; -1 у катушек без метки — «не знаю», а не ноль.
    out["remain"] = tray_remain(tray.get("remain"))
    tid = tray.get("tray_info_idx")
    out["tray_info_idx"] = str(tid).strip() if isinstance(tid, (str, int)) and not isinstance(tid, bool) else ""
    return out


def _cleared(base):
    out = dict(base)
    out.update({"type": "Empty", "color": _EMPTY_COLOR, "color_raw": "", "remain": None, "tray_info_idx": ""})
    return out


def merge(prev, amsd, now):
    """Новое состояние AMS по прежнему (p_states принтера) и блоку print.ams очередного отчёта.

    prev — словарь состояния принтера (читаются ams_trays, ams_units, ams_exist_bits,
    tray_exist_bits, _ams_rm_pending, ams_removed, ams_now, ams_tar); amsd — print.ams отчёта или None;
    now — монотонные секунды. -> словарь с теми же ключами (для p_states). Ничего не пишет.
    Любая ошибка -> прежние значения: воркер принтера из-за отчёта не падает."""
    prev = prev if isinstance(prev, dict) else {}
    old = {
        "ams_trays": list(prev.get("ams_trays") or []),
        "ams_units": dict(prev.get("ams_units") or {}),
        "ams_exist_bits": prev.get("ams_exist_bits"),
        "tray_exist_bits": prev.get("tray_exist_bits"),
        "_ams_rm_pending": dict(prev.get("_ams_rm_pending") or {}),
        "ams_removed": list(prev.get("ams_removed") or []),
        "ams_now": prev.get("ams_now", -1),
        "ams_tar": prev.get("ams_tar"),
    }
    if not isinstance(amsd, dict):
        return old
    try:
        return _merge(old, amsd, float(now))
    except Exception:
        return old


def _merge(old, amsd, now):
    st = dict(old)
    # Маски наличия: пришли — обновляются, мусор/нет — прежнее значение.
    for key in ("ams_exist_bits", "tray_exist_bits"):
        if key in amsd:
            v = parse_bits(amsd.get(key))
            if v is not None:
                st[key] = v
    #  R-139: текущий и целевой лоток читаются всегда, а не только вместе со списком блоков.
    if amsd.get("tray_now") is not None:
        st["ams_now"] = _now_value(amsd.get("tray_now"), old["ams_now"])
    if amsd.get("tray_tar") is not None:
        st["ams_tar"] = _now_value(amsd.get("tray_tar"), old["ams_tar"])

    # Прежние лотки по (блок, слот) и сведения о блоках.
    trays = {}
    for t in old["ams_trays"]:
        try:
            trays[(int(t.get("unit")), int(t.get("tray")))] = dict(t)
        except Exception:
            continue
    units = {}
    for k, v in old["ams_units"].items():
        try:
            units[int(k)] = dict(v) if isinstance(v, dict) else {}
        except Exception:
            continue
    for (uid, _sl) in trays:
        units.setdefault(uid, {})
    pending = {}
    for k, v in old["_ams_rm_pending"].items():
        try:
            pending[int(k)] = float(v)
        except Exception:
            continue
    #  Слоты снятых блоков (см. «След снятого блока» в описании модуля): глобальный номер слота.
    removed = set()
    for v in old["ams_removed"]:
        try:
            removed.add(int(v))
        except Exception:
            continue

    tmask = st["tray_exist_bits"]
    lst = amsd.get("ams")
    if isinstance(lst, list):
        seen = set()
        for unit in lst:
            if not isinstance(unit, dict) or unit.get("id") is None:
                continue
            try:
                uid = int(str(unit.get("id")).strip())
            except Exception:
                continue
            seen.add(uid)
            pending.pop(uid, None)
            removed = {x for x in removed if x // 4 != uid}      # блок вернулся — следа больше нет
            info = parse_bits(unit.get("info"))
            u = units.setdefault(uid, {})
            if info is not None:
                u["info"] = info
            utype = unit_type(u.get("info"), uid)
            u["type"] = utype
            u["extruder"] = unit_extruder(u.get("info"))
            for tray in (unit.get("tray") or []) if isinstance(unit.get("tray"), list) else []:
                if not isinstance(tray, dict) or tray.get("id") is None:
                    continue
                try:
                    sl = int(str(tray.get("id")).strip())
                except Exception:
                    continue
                base = trays.get((uid, sl)) or _blank_tray(uid, sl)
                if "tray_type" in tray:
                    trays[(uid, sl)] = _material_from(tray, base)
                    continue
                #  Служебное обновление ({id, state}, голый {id}): материал прежний, если датчик
                #  подачи не сказал, что лотка нет (pybambu; ha-bambulab #2164).
                nt = dict(base)
                if "remain" in tray:
                    nt["remain"] = tray_remain(tray.get("remain"))
                if bit_set(tmask, tray_bit(uid, sl, utype)) is False:
                    nt = _cleared(nt)
                trays[(uid, sl)] = nt
        # Блоки, которых нет в списке: снятие только с подтверждением (см. описание модуля).
        umask = st["ams_exist_bits"]
        for uid in list(units):
            if uid in seen:
                continue
            gone = bit_set(umask, unit_bit(uid, unit_type(units[uid].get("info"), uid))) is False
            if not gone:
                pending.pop(uid, None)
                continue
            first = pending.get(uid)
            if first is None:
                pending[uid] = now
            elif now - first >= REMOVE_CONFIRM_S:
                pending.pop(uid, None)
                units.pop(uid, None)
                for key in [k for k in trays if k[0] == uid]:
                    trays.pop(key, None)
                    removed.add(key[0] * 4 + key[1])

    out = []
    for (uid, sl) in sorted(trays, key=lambda k: k[0] * 4 + k[1]):
        t = dict(trays[(uid, sl)])
        u = units.get(uid) or {}
        utype = u.get("type") or unit_type(u.get("info"), uid)
        t["index"] = uid * 4 + sl
        t["unit"] = uid
        t["tray"] = sl
        t.setdefault("tray_info_idx", "")
        #  Наличие лотка — только по датчику подачи; маски нет — «не знаем» (None), и потребители
        #  ведут себя как раньше (по типу в слоте).
        t["present"] = bit_set(tmask, tray_bit(uid, sl, utype))
        t["extruder"] = u.get("extruder")
        out.append(t)
    st["ams_trays"] = out
    st["ams_units"] = {str(uid): {"type": (units[uid].get("type") or unit_type(units[uid].get("info"), uid)),
                                  "extruder": units[uid].get("extruder"),
                                  **({"info": units[uid]["info"]} if units[uid].get("info") is not None else {})}
                       for uid in units}
    st["_ams_rm_pending"] = {str(k): v for k, v in pending.items()}
    st["ams_removed"] = sorted(removed - {t["index"] for t in out})
    return st


def hw_switch(v, prev):
    """print.hw_switch_state — датчик филамента в экструдере (основном): 1 есть, 0 нет -> True/False.
    Нет поля или мусор — прежнее значение (P1 шлёт отчёт частями)."""
    if v is None or isinstance(v, bool):
        return prev
    try:
        n = int(v)
    except Exception:
        return prev
    return 1 if n == 1 else (0 if n == 0 else prev)
