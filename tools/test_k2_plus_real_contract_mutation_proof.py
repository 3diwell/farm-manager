# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.840 — mutation proof: ≥24 порчи рекурсивного контракта калибровки стола обязаны
краснить тесты. Каждая мутация вносится, целевой тест запускается, файл восстанавливается
байт-в-байт (SHA-256). Production data не трогается; PYTHONDONTWRITEBYTECODE.

ЗАЧЕМ ИМЕННО ЭТО. Все проверки контракта устроены как «докажи, иначе откажи», а такие
проверки легче всего сделать ложно-зелёными: достаточно снять один предохранитель, и
недоказанное начинает считаться доказанным. Здесь каждый предохранитель снимается по
очереди, и ни одна порча не имеет права остаться незамеченной."""
import ast
import hashlib
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(ROOT, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_k2_plus_real_contract_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
BASE_ENV = dict(os.environ)
BASE_ENV["PYTHONIOENCODING"] = "utf-8"
BASE_ENV["PYTHONDONTWRITEBYTECODE"] = "1"

SRV = os.path.join(ROOT, "server.py")
PRB = os.path.join(ROOT, "app", "klipper_contract_probe.py")
APP = os.path.join(ROOT, "web", "app.js")

REAL = "test_k2_plus_real_contract"
EXEC = "test_klipper_bed_mesh_execution"


def b(x):
    return x.encode("utf-8")


# (file, find, replace, test, label)
MUT = [
    # ── Предохранители обхода графа ────────────────────────────────────────────────────────
    (PRB, b("GRAPH_MAX_DEPTH = 6"), b("GRAPH_MAX_DEPTH = 9999"),
     REAL, "1: ограничение глубины обхода снято"),
    (PRB, b("GRAPH_MAX_NODES = 120"), b("GRAPH_MAX_NODES = 99999"),
     REAL, "2: ограничение числа узлов снято"),
    (PRB, b("BODY_MAX_CHARS = 24000"), b("BODY_MAX_CHARS = 99999999"),
     REAL, "3: ограничение длины тела снято"),
    (PRB, b("            if c in path:                       # цикл: дальше не идём\n"
            "                    if c not in cycles:\n"
            "                        cycles.append(c)\n"
            "                    continue"),
     b("            if False:                       # цикл: дальше не идём\n"
       "                    if c not in cycles:\n"
       "                        cycles.append(c)\n"
       "                    continue"),
     REAL, "4: обнаружение циклов отключено"),
    (PRB, b("            if name not in unknown:\n                unknown.append(name)"),
     b("            if False:\n                unknown.append(name)"),
     REAL, "5: непрочитанные макросы больше не перечисляются"),
    (PRB, b('nodes[name] = dict({"kind": "unknown", "source": "", "calls": [],\n'
            '                                "parameters": [], "body_available": False,'),
     b('nodes[name] = dict({"kind": "unknown", "source": "", "calls": [],\n'
       '                                "parameters": [], "body_available": True,'),
     REAL, "6: непрочитанный узел выдаётся за прочитанный"),
    (PRB, b('        "calls_bed_mesh_clear": bool(c & set(MESH_CLEAR_TOKENS)),'),
     b('        "calls_bed_mesh_clear_": bool(c & set(MESH_CLEAR_TOKENS)),'),
     REAL, "7: флаг очистки сетки у узла исчез"),
    # Порча целится в РАЗБОР строки, а не в отбрасывание Jinja: у Jinja-строк два независимых
    # предохранителя сразу (префикс «{» и формат имени), и снятие одного из них ничего не меняет.
    (PRB, b('        tok = re.split(r"[\\s=]", s, maxsplit=1)[0].upper()'), b('        tok = s.upper()'),
     REAL, "8: команда с аргументами перестала распознаваться как вызов"),

    # ── Модель риска ───────────────────────────────────────────────────────────────────────
    (PRB, b('    if ev and (g.get("truncated") or g.get("unknown") or hit["danger"]):'),
     b('    if ev and (g.get("unknown") and hit["danger"]):'),
     REAL, "9: обрезанный граф больше не даёт unknown"),
    (PRB, b('        return (RISK_UNKNOWN, ["graph_empty"])'),
     b('        return (RISK_NONE, ["graph_empty"])'),
     REAL, "10: пустой граф считается безопасным"),
    (PRB, b('MESH_CLEAR_TOKENS = ("BED_MESH_CLEAR", "BED_MESH_SET_DISABLE")'),
     b('MESH_CLEAR_TOKENS = ("BED_MESH_CLEAR_NEVER",)'),
     REAL, "11: очистка сетки перестала распознаваться"),
    (PRB, b('MESH_PROFILE_TOKENS = ("BED_MESH_PROFILE",)'),
     b('MESH_PROFILE_TOKENS = ("BED_MESH_PROFILE_NEVER",)'),
     REAL, "12: загрузка чужого профиля перестала распознаваться"),
    (PRB, b('    if hit["cal"]:\n        return (RISK_RECALIBRATES, sorted(set(ev)))'),
     b('    if False:\n        return (RISK_RECALIBRATES, sorted(set(ev)))'),
     REAL, "13: повторная калибровка стартовым макросом не замечается"),

    # ── Доказательство vendor-макроса ──────────────────────────────────────────────────────
    (PRB, b('    if not (calls & set(MESH_CALIBRATE_TOKENS)):\n'
            '        return (False, "vendor_does_not_calibrate", g)'),
     b('    if False:\n        return (False, "vendor_does_not_calibrate", g)'),
     REAL, "14: имя vendor-макроса считается доказательством"),
    (PRB, b('    if calls & set(DANGEROUS_TOKENS):\n        return (False, "vendor_state_changing", g)'),
     b('    if False:\n        return (False, "vendor_state_changing", g)'),
     REAL, "15: vendor-макрос с SAVE_CONFIG считается доказанным"),
    (PRB, b('    if g.get("truncated") or g.get("unknown"):\n'
            '        return (False, "vendor_graph_incomplete", g)'),
     b('    if False:\n        return (False, "vendor_graph_incomplete", g)'),
     REAL, "16: недочитанный vendor-граф считается доказанным"),
    (PRB, b('                        homing=("G28" not in _vcalls),'),
     b('                        homing=True,'),
     REAL, "17: паркующийся сам vendor-макрос требует лишней парковки"),

    # ── Резолвер ───────────────────────────────────────────────────────────────────────────
    # Alpha 2.841: недоказуемость (unknown) больше НЕ закрывает автомат — калибруем сами.
    # Но ДОКАЗАННЫЙ вред (clears/replaces) закрывать обязан, иначе наша работа была бы выброшена.
    (PRB, b('    if risk in (RISK_CLEARS, RISK_REPLACES):\n        _ru = {'),
     b('    if False:\n        _ru = {'),
     REAL, "18: доказанный вред сетке больше не закрывает автомат"),
    (PRB, b('    if risk == RISK_UNKNOWN:\n        return _out(MODE_STANDARD,'),
     b('    if risk == RISK_UNKNOWN:\n        return _out(MODE_UNSAFE,'),
     REAL, "18b(2.841): недоказуемый макрос снова оставляет стол без калибровки"),
    (PRB, b('    bmc_overridden = "BED_MESH_CALIBRATE" in macros'),
     b('    bmc_overridden = False'),
     REAL, "19: переопределённая калибровка считается встроенной"),
    (PRB, b('    if "G28" in macros:\n        return _out(MODE_UNSAFE, "homing_overridden",'),
     b('    if False:\n        return _out(MODE_UNSAFE, "homing_overridden",'),
     REAL, "20: переопределённая парковка перестала закрывать автомат"),
    (PRB, b('    if "bed_mesh" not in obj:'), b('    if False:'),
     REAL, "21: отсутствие объекта bed_mesh игнорируется"),
    (PRB, b('    if "bed_mesh_calibrate" in fc:'), b('    if False:'),
     EXEC, "22: операция файла выполняется ВТОРОЙ раз"),
    (PRB, b('    return {"profile_name": str(st.get("profile_name") or ""),'),
     b('    return {"profile_name": "",'),
     EXEC, "23: смена профиля сетки перестала быть доказательством"),

    # ── Отчёт ──────────────────────────────────────────────────────────────────────────────
    (PRB, b('        "post_start_mesh_risk": _risk,\n        "unresolved_graph_nodes": _unresolved_nodes,'),
     b('        "post_start_mesh_risk": "none",\n        "unresolved_graph_nodes": [],'),
     REAL, "24: отчёт скрывает риск и непрочитанные узлы"),
    (PRB, b('        "report_schema_version": REPORT_SCHEMA,'),
     b('        "report_schema_version": "3diwell-klipper-contract-report-v2",'),
     REAL, "25: схема отчёта молча ломает читателя v1"),

    # ── Исполнение (server.py — CRLF) ──────────────────────────────────────────────────────
    (SRV, b('    if plan["requires_homing"]:\n        _hx = homed_axes()\n'
            '        if not all(a in _hx for a in ("x", "y", "z")):'),
     b('    if plan["requires_homing"]:\n        _hx = homed_axes()\n        if True:'),
     EXEC, "26: G28 отправляется даже запаркованному принтеру"),
    (SRV, b('    r = _send(cmd, cls, 900.0)\n    if r == "timeout":'),
     b('    r = _send(cmd, cls, 900.0)\n    r = _send(cmd, cls, 900.0)\n    if r == "timeout":'),
     EXEC, "27: калибровка отправляется дважды"),
    (SRV, b('    _bad = (_ps not in _KLIPPER_IDLE_STATES) or (_wh not in ("", "ready"))'
            ' or (not fp_after.get("present"))'),
     b('    _bad = False'),
     EXEC, "28: HTTP-ответ считается доказательством завершения"),
    (SRV, b('        if not _ok_bm:\n            return (False, _why_bm)'),
     b('        if False:\n            return (False, _why_bm)'),
     EXEC, "29: недоказанная калибровка больше не блокирует печать"),
    (SRV, b('    _pcb_pre(stage="checking_state")'), b('    pass'),
     EXEC, "30: стадия проверки состояния исчезла из панели"),
    (SRV, b('"calibration_done", "uploading", "starting_file", "sending_command"'),
     b('"calibration_done", "uploading", "sending_command"'),
     REAL, "31: реестр отправок молча глотает стадию запуска файла"),

    # ── Интерфейс ──────────────────────────────────────────────────────────────────────────
    (APP, b("homing: 'Парковка осей…'"), b("homing_: 'Парковка осей…'"),
     REAL, "32: стадия парковки осталась без подписи"),
    (APP, b("? (ru ? 'Встроенная команда Klipper — выполнится до отправки файла' : 'Klipper built-in — runs before the file is sent')\n"
            "                : (ru ? 'Макрос принтера — выполнится до отправки файла' : 'Printer macro — runs before the file is sent');"),
     b("? (ru ? 'Встроенная команда Klipper — выполнится до отправки файла' : 'Klipper built-in — runs before the file is sent')\n"
       "                : (ru ? 'Встроенная команда Klipper — выполнится до отправки файла' : 'Klipper built-in — runs before the file is sent');"),
     REAL, "33: источник «макрос принтера» больше не называется"),
]

_n = {"caught": 0, "miss": 0, "harness": 0, "not_applied": 0}


TIMEOUT_RC = -1001      # Alpha 2.841: НЕ путать с кодом возврата теста (см. ниже)


def run_test(name):
    # Таймаут короткий НАМЕРЕННО: испорченный предохранитель может не покраснеть, а зависнуть
    # (например, снятый лимит длины тела).
    #
    # Alpha 2.841. Раньше здесь возвращалось 124, а вердикт был `ok = rc != 0 and reverted` —
    # то есть ЗАВИСШАЯ проверка засчитывалась как успешно пойманная порча. Набор рапортовал
    # «CAUGHT» и выходил нулём, ничего не доказав. Теперь таймаут отдаёт собственный код,
    # который вердикт трактует как ОТКАЗ САМОЙ ОСНАСТКИ и краснит набор.
    try:
        return subprocess.run([sys.executable, os.path.join(ROOT, "tools", name + ".py")],
                              env=BASE_ENV, capture_output=True, timeout=120).returncode
    except subprocess.TimeoutExpired:
        return TIMEOUT_RC


def _fit_eol(src, find, repl):
    r"""Подогнать якорь под окончания строк КОНКРЕТНОГО файла, а не под предположение о них.

    Alpha 2.868. ЗДЕСЬ БЫЛ ДЕФЕКТ. Стояло безусловное преобразование для server.py:
        if path == SRV: find = find.replace(b"\n", b"\r\n")
    Оно опиралось на то, что server.py целиком CRLF. С Alpha 2.863 файл лежит с LF
    (измерено 22.08.2026: 0 CRLF, 18066 LF; перевернулся при правке журнала «Что нового»
    в коммите c708cca). Окончания строк в проекте НЕ нормализуются вовсе — .gitattributes
    хранит файлы побайтово (* -text), — поэтому предполагать их нельзя ни в одну сторону.
    После подмены на CRLF многострочные якоря не находились НИ РАЗУ: три порчи из 34 молча
    превращались в «SETUP FAIL», и набор был красным, ничего не доказывая.

    Порядок: сначала якорь как записан, затем вариант с CRLF. Ослабления нет — если не нашлось
    ни одного однозначного совпадения, возвращается исходный якорь и вызывающий код краснеет
    на count != 1, как и раньше.
    """
    if src.count(find) == 1:
        return find, repl
    crlf_find = find.replace(b"\n", b"\r\n")
    if src.count(crlf_find) == 1:
        return crlf_find, repl.replace(b"\n", b"\r\n")
    return find, repl


def main():
    for name in sorted({m[3] for m in MUT}):
        if run_test(name) != 0:
            print("BASELINE FAIL:", name)
            return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, label in MUT:
        orig = open(path, "rb").read()
        find, repl = _fit_eol(orig, find, repl)
        sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) != 1:
            print("SETUP FAIL — якорь не найден/не уникален (%d): [%s]" % (orig.count(find), label))
            # Alpha 2.841: порча НЕ внесена. Считаем ОТДЕЛЬНО, иначе executed == declared
            # тождественно и поле mutation_not_applied мертво по построению.
            _n["miss"] += 1
            _n["not_applied"] += 1
            continue
        try:
            open(path, "wb").write(orig.replace(find, repl, 1))
            rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        if rc == TIMEOUT_RC:
            _n["harness"] += 1
            print("HARNESS — [%-58s] %-26s ТАЙМАУТ revert=%s"
                  % (label, test.replace("test_", ""), reverted))
            continue
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-58s] %-26s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_", ""), rc, reverted))
    # Все порчи должны быть синтаксически валидны — иначе тест краснеет «не за то».
    for _p in (PRB, SRV):
        ast.parse(open(_p, "rb").read().decode("utf-8", "surrogateescape"))
    # Alpha 2.841: сверка ЧИСЛА. Раньше знаменатель печатался как len(MUT) и был самоссылочным —
    # он равен числу итераций по построению и не мог заметить, что порчи не исполнялись.
    executed = _n["caught"] + _n["miss"] + _n["harness"]
    count_ok = executed == len(MUT)
    print("\n" + "=" * 84)
    print("Mutation proof 2840: CAUGHT=%d MISS=%d HARNESS=%d (исполнено %d из объявленных %d)"
          % (_n["caught"], _n["miss"], _n["harness"], executed, len(MUT)))
    if not count_ok:
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ НЕ СОВПАЛО С ОБЪЯВЛЕННЫМ — набор недоказателен.")
    if _n["harness"]:
        print("ОТКАЗ САМОЙ ОСНАСТКИ (таймаут): %d" % _n["harness"])
    # Alpha 2.841: машиночитаемый итог для релизного гейта — печатается ПОСЛЕ
    # человекочитаемой сводки и не заменяет её. Прежнее условие выхода сохранено
    # как _rc_prev; ненулевым итог становится от любого из двух источников.
    # Отдельного счётчика несостоявшегося отката здесь нет: неоткатившаяся порча
    # уже учтена как MISS (ok = rc != 0 and reverted), поэтому restore_failures=0.
    _rc_prev = 0 if (not _n["miss"] and not _n["harness"] and count_ok) else 1
    _summary = _mut_build(declared=len(MUT), executed=executed - _n["not_applied"],
                          caught=_n["caught"],
                          timeouts=_n["harness"], restore_failures=0, cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
