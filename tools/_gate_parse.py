# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841: СТРОГИЙ разбор результата одного тестового файла для релизного гейта.

ЗАЧЕМ. Прежний агрегатор считал пропуски как `out.count("SKIP")` — подсчёт подстроки.
Такой счёт ловит слово SKIP в комментарии, в имени переменной `FM_SKIP_BROWSER` и в
собственной итоговой строке теста `Итого: … SKIP=0`, а пропуск, названный другими словами,
не видит вовсе. Ноль, полученный так, ничего не доказывает.

ЧТО СЧИТАЕТСЯ ИСТОЧНИКОМ. Только опубликованный формат, распознанный ЦЕЛОЙ строкой:

  1) машиночитаемая строка теста     FM_TEST_RESULT_JSON={...}          (высший приоритет);
  2) машиночитаемая строка мутаций   FM_MUTATION_SUMMARY_JSON={...};
  3) сводная строка теста, ровно одна из опубликованных форм (см. _SUMMARY_RULES);
  4) построчный протокол проекта: строка, НАЧИНАЮЩАЯСЯ с PASS/FAIL/SKIP и разделителя.

Проза, комментарии и вхождения слова внутри строки источником НЕ являются.
Если ни одна форма не найдена — результат `unknown`, и это КРАСНЫЙ для гейта, а не ноль.

САМОПРОВЕРКА. Когда есть и сводка, и построчный протокол, они сверяются: расхождение по
провалам или пропускам переводит файл в `unknown`. Молча предпочесть одно другому нельзя —
именно так теряются пропуски.
"""
import json
import re

SCHEMA = "3diwell-test-result-v1"
RESULT_PREFIX = "FM_TEST_RESULT_JSON="
MUTATION_PREFIX = "FM_MUTATION_SUMMARY_JSON="

# ── Построчный протокол ──────────────────────────────────────────────────────────────────
# Строка результата: начало строки, маркер, разделитель, дальше непробельный текст.
# «Итого: PASS=…» этим НЕ матчится: строка начинается с «Итого», а не с «PASS».
_LINE = re.compile(r'^[ \t]*(PASS|FAIL|SKIP)[ \t]*(?:—|–|-|:)[ \t]*\S')

# ── Сводные строки: перечень ТОЧНЫХ опубликованных форм ──────────────────────────────────
# Каждое правило — regex целой строки и функция извлечения (pass, fail, skip).
_SUMMARY_RULES = (
    # ИТОГО: PASS=12 FAIL=0   /   Итого: PASS=12 FAIL=0 SKIP=0   /   … (порч: 22)
    (re.compile(r'^[ \t]*(?:ИТОГО|Итого)[ \t]*:[ \t]*PASS=(\d+)[ \t]+FAIL=(\d+)'
                r'(?:[ \t]+SKIP=(\d+))?'),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))),
    # Итого: 40 проверок пройдено, 0 провалено[, 0 пропущено]
    (re.compile(r'^[ \t]*(?:ИТОГО|Итого)[ \t]*:[ \t]*(\d+)[ \t]+проверок[ \t]+пройдено,'
                r'[ \t]*(\d+)[ \t]+провалено(?:,[ \t]*(\d+)[ \t]+пропущено)?'),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))),
    # PASS: 37 проверок
    (re.compile(r'^[ \t]*PASS:[ \t]*(\d+)[ \t]+проверок[ \t]*$'),
     lambda m: (int(m.group(1)), 0, 0)),
    # FAIL: 3 из 40 проверок провалено
    (re.compile(r'^[ \t]*FAIL:[ \t]*(\d+)[ \t]+из[ \t]+(\d+)[ \t]+проверок[ \t]+провалено'),
     lambda m: (int(m.group(2)) - int(m.group(1)), int(m.group(1)), 0)),
    # OK (17/17) — …
    (re.compile(r'^[ \t]*OK[ \t]*\((\d+)/(\d+)\)'),
     lambda m: (int(m.group(1)), int(m.group(2)) - int(m.group(1)), 0)),
    # FAIL 3/40
    (re.compile(r'^[ \t]*FAIL[ \t]+(\d+)/(\d+)[ \t]*$'),
     lambda m: (int(m.group(2)) - int(m.group(1)), int(m.group(1)), 0)),
)

# ── Сводные строки mutation proof: ТОЧНЫЕ формы ──────────────────────────────────────────
# Дают declared/executed/caught. Формы без «исполнено» считают executed равным declared
# ТОЛЬКО если сам набор печатает контрольную строку расхождения (см. _MUT_MISMATCH).
_MUT_RULES = (
    # ИТОГО: ПОЙМАНО 21 из 21 (объявлено поломок: 21)
    (re.compile(r'^[ \t]*ИТОГО:[ \t]*ПОЙМАНО[ \t]+(\d+)[ \t]+из[ \t]+(\d+)'
                r'[ \t]*\(объявлено поломок:[ \t]*(\d+)\)'),
     lambda m: (int(m.group(3)), int(m.group(2)), int(m.group(1)))),
    # ИТОГО: ПОЙМАНО 12 из 12 за 636 c   /   ИТОГО: ПОЙМАНО 33 из 33
    (re.compile(r'^[ \t]*ИТОГО:[ \t]*ПОЙМАНО[ \t]+(\d+)[ \t]+из[ \t]+(\d+)'),
     lambda m: (int(m.group(2)), int(m.group(2)), int(m.group(1)))),
    # … CAUGHT=34 MISS=0 HARNESS=0 (исполнено 34 из объявленных 34)
    (re.compile(r'CAUGHT=(\d+)[ \t]+MISS=(\d+)[ \t]+HARNESS=(\d+)[ \t]*'
                r'\(исполнено[ \t]+(\d+)[ \t]+из[ \t]+объявленных[ \t]+(\d+)\)'),
     lambda m: (int(m.group(5)), int(m.group(4)), int(m.group(1)))),
    # ИТОГО: CAUGHT=6 MISS=0 HARNESS=0 исполнено=6 из 6
    (re.compile(r'CAUGHT=(\d+)[ \t]+MISS=(\d+)[ \t]+HARNESS=(\d+)[ \t]+'
                r'исполнено=(\d+)[ \t]+из[ \t]+(\d+)'),
     lambda m: (int(m.group(5)), int(m.group(4)), int(m.group(1)))),
    # Mutation proof 2830: CAUGHT=19 MISS=0 (всего 19)
    (re.compile(r'CAUGHT=(\d+)[ \t]+MISS=(\d+)[ \t]*\(всего[ \t]+(\d+)\)'),
     lambda m: (int(m.group(3)), int(m.group(1)) + int(m.group(2)), int(m.group(1)))),
    # ИТОГО: поймано 24, не поймано 0, сбоев оснастки 0, время 22.1 c
    (re.compile(r'^[ \t]*ИТОГО:[ \t]*поймано[ \t]+(\d+),[ \t]*не[ \t]+поймано[ \t]+(\d+),'
                r'[ \t]*сбоев[ \t]+оснастки[ \t]+(\d+)'),
     lambda m: (int(m.group(1)) + int(m.group(2)) + int(m.group(3)),
                int(m.group(1)) + int(m.group(2)) + int(m.group(3)),
                int(m.group(1)))),
)

# Набор сам сообщает, что исполнено не совпало с объявленным, — это прямой признак дыры.
_MUT_MISMATCH = re.compile(r'ЧИСЛО[ \t]+ИСПОЛНЕННЫХ[ \t]+(?:ПОРЧ|ПОЛОМОК)|'
                           r'ЧИСЛО[ \t]+ПОРЧ[ \t]+\d+[ \t]*!=|'
                           r'набор[ \t]+недоказателен')
# Прямые признаки сбоя оснастки в построчном выводе набора.
_MUT_TIMEOUT = re.compile(r'^[ \t]*(?:HARNESS|ТАЙМАУТ)\b|ТАЙМАУТ[ \t]*$|:: таймаут')
_MUT_RESTORE_BAD = re.compile(r'Файлы[ \t]+восстановлены[ \t]+побайтово:[ \t]*НЕТ|'
                              r'SHA[- ]?256[ \t]+не[ \t]+совпал|откат[ \t]+не[ \t]+состоялся')
_MUT_LOCK_BUSY = re.compile(r'^mutation_lock_busy\b')


def _iter_lines(text):
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        yield raw


def _machine_line(text, prefix):
    """Последняя строка, НАЧИНАЮЩАЯСЯ с префикса. → dict или None."""
    found = None
    for line in _iter_lines(text):
        s = line.lstrip()
        if s.startswith(prefix):
            try:
                found = json.loads(s[len(prefix):].strip())
            except Exception:
                found = None
    return found


def count_protocol_lines(text):
    """Построчный протокол. → (pass, fail, skip). Проза не считается."""
    p = f = s = 0
    for line in _iter_lines(text):
        m = _LINE.match(line)
        if not m:
            continue
        kind = m.group(1)
        if kind == "PASS":
            p += 1
        elif kind == "FAIL":
            f += 1
        else:
            s += 1
    return p, f, s


def find_summary(text):
    """Сводная строка теста в одной из ТОЧНЫХ форм. → (pass, fail, skip) или None."""
    hit = None
    for line in _iter_lines(text):
        for rx, take in _SUMMARY_RULES:
            m = rx.match(line) if rx.pattern.startswith("^") else rx.search(line)
            if m:
                hit = take(m)
                break
    return hit


def find_mutation_summary(text):
    """Сводка mutation proof. → dict или None. Машиночитаемая форма имеет приоритет."""
    direct = _machine_line(text, MUTATION_PREFIX)
    if isinstance(direct, dict) and direct.get("schema") == "3diwell-mutation-summary-v1":
        d = dict(direct)
        d["source"] = "structured"
        return d

    parsed = None
    for line in _iter_lines(text):
        for rx, take in _MUT_RULES:
            m = rx.match(line) if rx.pattern.startswith("^") else rx.search(line)
            if m:
                parsed = take(m)
                break
    if parsed is None:
        return None
    declared, executed, caught = parsed
    timeouts = sum(1 for l in _iter_lines(text) if _MUT_TIMEOUT.search(l))
    restore_bad = sum(1 for l in _iter_lines(text) if _MUT_RESTORE_BAD.search(l))
    mismatch = 1 if any(_MUT_MISMATCH.search(l) for l in _iter_lines(text)) else 0
    not_applied = max(0, declared - executed)
    if mismatch and not_applied == 0:
        not_applied = 1          # набор объявил расхождение — верим ему, а не арифметике
    unexpected = max(0, executed - caught - timeouts)
    return {
        "schema": "3diwell-mutation-summary-v1",
        "source": "parsed",
        "declared_mutations": declared,
        "executed_mutations": executed,
        "caught_mutations": caught,
        "mutation_not_applied": not_applied,
        "unexpected_green": unexpected,
        "timeouts": timeouts,
        "restore_failures": restore_bad,
        "cleanup_failures": 0,
        "internal_failures": not_applied + unexpected + timeouts + restore_bad,
    }


def parse_test_output(test_file, stdout, stderr, process_rc, timed_out, duration_seconds):
    """Собрать структурированный результат ОДНОГО файла. → dict схемы 3diwell-test-result-v1.

    status: green | red | unknown. `unknown` — когда достоверного счёта нет; для гейта это
    КРАСНЫЙ, потому что недоказанное не равно нулю.
    """
    text = (stdout or "") + "\n" + (stderr or "")
    res = {
        "schema": SCHEMA,
        "test_file": test_file,
        "process_rc": int(process_rc),
        "timed_out": bool(timed_out),
        "duration_seconds": round(float(duration_seconds), 3),
        "pass_count": 0,
        "fail_count": 0,
        "error_count": 0,
        "skip_count": 0,
        "internal_mutation_failures": 0,
        "mutation_not_applied": 0,
        "unexpected_green": 0,
        "restore_failures": 0,
        "cleanup_failures": 0,
        "counts_source": "none",
        "skip_known": False,
        "notes": [],
        "status": "unknown",
    }

    if _machine_line(text, RESULT_PREFIX) is not None:
        j = _machine_line(text, RESULT_PREFIX)
        if isinstance(j, dict) and j.get("schema") == SCHEMA:
            for k in ("pass_count", "fail_count", "error_count", "skip_count"):
                res[k] = int(j.get(k, 0))
            res["counts_source"] = "structured"
            res["skip_known"] = True

    mut = find_mutation_summary(text)
    if mut:
        res["internal_mutation_failures"] = int(mut.get("internal_failures", 0))
        res["mutation_not_applied"] = int(mut.get("mutation_not_applied", 0))
        res["unexpected_green"] = int(mut.get("unexpected_green", 0))
        res["restore_failures"] = int(mut.get("restore_failures", 0))
        res["cleanup_failures"] = int(mut.get("cleanup_failures", 0))
        res["mutation_summary"] = mut

    if any(_MUT_LOCK_BUSY.match(l) for l in _iter_lines(text)):
        res["notes"].append("mutation_lock_busy: набор не начинал работу")
        res["cleanup_failures"] += 1

    # Машиночитаемая сводка mutation proof — САМОДОСТАТОЧНЫЙ источник результата: она
    # перечисляет ВСЕ исходы явно (объявлено/исполнено/поймано, неисполненные, ложно-зелёные,
    # таймауты, откат, уборка). Пропуск проверки в таком наборе не существует как понятие:
    # пропущенная порча — это mutation_not_applied, у которого свой счётчик. Правило не даёт
    # лазейки: любое отклонение уже попало в internal_failures и красит файл ниже.
    if res["counts_source"] == "none" and mut and mut.get("source") == "structured":
        res["pass_count"] = int(mut.get("caught_mutations", 0))
        res["skip_count"] = 0
        res["counts_source"] = "mutation-structured"
        res["skip_known"] = True

    if res["counts_source"] == "none":
        summary = find_summary(text)
        proto = count_protocol_lines(text)
        if summary is not None:
            sp, sf, ss = summary
            res["pass_count"], res["fail_count"], res["skip_count"] = sp, sf, ss
            res["counts_source"] = "summary"
            res["skip_known"] = True
            # Самопроверка: построчный протокол не должен противоречить сводке.
            if proto != (0, 0, 0) and (proto[1] != sf or proto[2] != ss):
                res["skip_known"] = False
                res["counts_source"] = "conflict"
                res["notes"].append(
                    "сводка PASS=%d FAIL=%d SKIP=%d расходится с построчным %d/%d/%d"
                    % (sp, sf, ss, proto[0], proto[1], proto[2]))
        elif proto != (0, 0, 0):
            res["pass_count"], res["fail_count"], res["skip_count"] = proto
            res["counts_source"] = "protocol"
            res["skip_known"] = True
        else:
            res["notes"].append(
                "файл не публикует ни FM_TEST_RESULT_JSON, ни сводную строку известной формы, "
                "ни построчный протокол PASS/FAIL/SKIP — число пропусков НЕИЗВЕСТНО")

    if timed_out:
        res["error_count"] = 1
        res["status"] = "red"
        res["notes"].append("процесс убит по таймауту")
        return res

    if not res["skip_known"]:
        res["status"] = "unknown"
        return res

    bad = (res["fail_count"] or res["skip_count"] or res["error_count"]
           or res["internal_mutation_failures"] or res["mutation_not_applied"]
           or res["unexpected_green"] or res["restore_failures"] or res["cleanup_failures"]
           or res["process_rc"] != 0)
    res["status"] = "red" if bad else "green"
    return res
