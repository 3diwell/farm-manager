# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841: ПРЯМОЙ структурированный итог mutation proof.

ЗАЧЕМ. Релизный гейт обязан доказывать нули напрямую, а не выводить их из прозы.
До 2.841 сводка набора печаталась свободным текстом («ПОЙМАНО 21 из 21», «CAUGHT=… MISS=…»),
и агрегатор вынужден был угадывать смысл подсчётом подстрок. Подсчёт подстроки ловит слово
в комментарии и не видит пропуск, названный другими словами, — то есть доказывает не то.

КОНТРАКТ. Набор печатает ОДНУ машиночитаемую строку последней:

    FM_MUTATION_SUMMARY_JSON={"schema":"3diwell-mutation-summary-v1", ...}

Обязательные поля (все целые, кроме schema):
    declared_mutations   — сколько поломок ОБЪЯВЛЕНО в наборе;
    executed_mutations   — сколько РЕАЛЬНО исполнено (устаревший якорь → меньше объявленного);
    caught_mutations     — сколько поломок покраснили целевой тест;
    internal_failures    — внутренние сбои набора (не пойманные + сбои оснастки);
    mutation_not_applied — объявлено, но не исполнено (declared - executed);
    unexpected_green     — поломка внесена, а тест остался зелёным (= не поймана);
    timeouts             — проверок убито по времени;
    restore_failures     — файл не вернулся к исходным байтам;
    cleanup_failures     — не удалось убрать за собой (временные копии, процессы);
    process_rc           — код возврата, с которым набор собирается выйти.

ЗДОРОВЫЙ НАБОР: declared == executed == caught, все счётчики сбоев 0, process_rc 0.
Любое отклонение обязано давать красный статус И ненулевой process_rc — за этим следит
tools/test_mutation_proof_exit_contract.py.

Строка печатается в stdout последней и НЕ заменяет человекочитаемую сводку: та остаётся
для чтения глазами, эта — для гейта.
"""
import json
import sys

SCHEMA = "3diwell-mutation-summary-v1"
PREFIX = "FM_MUTATION_SUMMARY_JSON="

_FIELDS = (
    "declared_mutations",
    "executed_mutations",
    "caught_mutations",
    "internal_failures",
    "mutation_not_applied",
    "unexpected_green",
    "timeouts",
    "restore_failures",
    "cleanup_failures",
    "process_rc",
)


def build(declared, executed, caught, timeouts=0, restore_failures=0,
          cleanup_failures=0, extra_internal=0):
    """Собрать сводку из счётчиков набора. Производные поля считаются здесь, а не на глаз.

    mutation_not_applied — объявленное минус исполненное (никогда не отрицательное);
    unexpected_green     — исполненное минус пойманное минус то, что упало сбоем оснастки;
    internal_failures    — всё, что мешает считать набор доказательным.
    """
    declared = int(declared)
    executed = int(executed)
    caught = int(caught)
    timeouts = int(timeouts)
    restore_failures = int(restore_failures)
    cleanup_failures = int(cleanup_failures)

    not_applied = max(0, declared - executed)
    unexpected_green = max(0, executed - caught - timeouts)
    internal = (not_applied + unexpected_green + timeouts + restore_failures
                + cleanup_failures + int(extra_internal))
    healthy = (declared == executed == caught and internal == 0)
    return {
        "schema": SCHEMA,
        "declared_mutations": declared,
        "executed_mutations": executed,
        "caught_mutations": caught,
        "internal_failures": internal,
        "mutation_not_applied": not_applied,
        "unexpected_green": unexpected_green,
        "timeouts": timeouts,
        "restore_failures": restore_failures,
        "cleanup_failures": cleanup_failures,
        "process_rc": 0 if healthy else 1,
    }


def emit(summary):
    """Напечатать машиночитаемую строку. → process_rc, который набор обязан вернуть."""
    for f in _FIELDS:
        if f not in summary:
            raise KeyError("в сводке mutation proof нет обязательного поля %r" % f)
    sys.stdout.write(PREFIX + json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return int(summary["process_rc"])


def emit_and_exit(declared, executed, caught, timeouts=0, restore_failures=0,
                  cleanup_failures=0, extra_internal=0):
    """Собрать, напечатать и ВЫЙТИ с кодом из сводки. Одной строкой в конце набора."""
    raise SystemExit(emit(build(declared, executed, caught, timeouts, restore_failures,
                                cleanup_failures, extra_internal)))
