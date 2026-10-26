# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841: контракт релизного гейта — нули должны быть ДОКАЗАНЫ, а не выведены из прозы.

ЗАЧЕМ. Прежний агрегатор считал пропуски как `out.count("SKIP")`. Такой счёт срабатывает на
слове в комментарии, на имени переменной `FM_SKIP_BROWSER` и на собственной строке теста
`Итого: … SKIP=0`, а пропуск, названный другими словами, не видит вовсе. Полученный так ноль
не доказывает ничего, и именно на этом Alpha 2.841 не смогла подтвердить обязательное SKIP=0.

Набор проверяет ДВА слоя:
  * статику — в tools/release_gate.py и tools/_gate_parse.py нет подсчёта подстрок;
  * поведение — парсер и сводка гейта разбирают синтетические выводы, включая ловушки.

Все сценарии синтетические: настоящие тесты не запускаются, файлы репозитория не изменяются.
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from _gate_parse import (parse_test_output, count_protocol_lines,  # noqa: E402
                         find_summary, find_mutation_summary, SCHEMA)
import release_gate as GATE                                        # noqa: E402

_n = {"pass": 0, "fail": 0}


def check(label, cond, detail=""):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label + (("  | " + str(detail)) if (detail and not ok) else ""))
    _n["pass" if ok else "fail"] += 1
    return ok


def _res(stdout, rc=0, timed_out=False, stderr=""):
    return parse_test_output("synthetic.py", stdout, stderr, rc, timed_out, 1.0)


PARSE_SRC = io.open(os.path.join(ROOT, "tools", "_gate_parse.py"), encoding="utf-8").read()
GATE_SRC = io.open(os.path.join(ROOT, "tools", "release_gate.py"), encoding="utf-8").read()

print("=" * 92)
print("КОНТРАКТ РЕЛИЗНОГО ГЕЙТА — 22 обязательных свойства")
print("=" * 92)

# ─────────────────────────── 1–7: чем НЕЛЬЗЯ считать ───────────────────────────
# 1. Подстрочный count("SKIP") отсутствует. Проверяем ВЫЗОВЫ через AST, а не текст:
#    первая редакция этой проверки искала подстроку и краснела на собственной докстроке,
#    где дефект описан словами. Проза — не код.
import ast  # noqa: E402


def _substring_counting_calls(src, path):
    hits = []
    for node in ast.walk(ast.parse(src, filename=path)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "count" and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                hits.append("%s: .count(%r)" % (os.path.basename(path), a.value))
    return hits


_hits = (_substring_counting_calls(PARSE_SRC, "_gate_parse.py")
         + _substring_counting_calls(GATE_SRC, "release_gate.py"))
check("1. в парсере и раннере НЕТ вызовов .count(\"…\") по строке (проверено разбором AST)",
      not _hits, "найдено: %s" % _hits)

# 2. Неизвестный skip НЕ становится нулём: вывод без единого признака результата.
r = _res("просто какой-то текст без результатов\nвторая строка\n", rc=0)
check("2. неизвестный skip не превращается в ноль (status=unknown, skip_known=False)",
      r["status"] == "unknown" and r["skip_known"] is False, r)

# 3. SKIP=0 в сводке распознаётся как ноль.
r = _res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=0)
check("3. сводка SKIP=0 распознана как ноль и файл зелёный",
      r["skip_count"] == 0 and r["skip_known"] and r["status"] == "green", r)

# 4. SKIP=1 распознаётся как один и краснит.
r = _res("PASS — a\nSKIP — b\nИтого: PASS=1 FAIL=0 SKIP=1\n", rc=0)
check("4. сводка SKIP=1 распознана как единица и файл КРАСНЫЙ",
      r["skip_count"] == 1 and r["status"] == "red", r)

# 5. FM_SKIP_BROWSER в выводе не является пропуском.
r = _res("(браузерная часть отключена FM_SKIP_BROWSER=1 — режим mutation proof)\n"
         "PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=0)
check("5. упоминание FM_SKIP_BROWSER не считается пропуском",
      r["skip_count"] == 0 and r["status"] == "green", r)

# 6. Слово SKIP в прозе не считается пропуском и не даёт нуля.
r = _res("Если Edge недоступен — браузерная часть помечается SKIP (не FAIL).\n"
         "PASS — a\nИтого: PASS=1 FAIL=0\n", rc=0)
check("6. слово SKIP в прозе не считается пропуском",
      r["skip_count"] == 0 and r["counts_source"] == "summary", r)

# 7. Русский текст без структурированного итога не доказывает ноль.
r = _res("Проверка выполнена успешно, замечаний нет.\nВсё хорошо.\n", rc=0)
check("7. русская проза без формата результата → unknown, а не ноль",
      r["status"] == "unknown" and r["skip_known"] is False, r)

# ─────────────────────────── 8–12: хранение и манифест ───────────────────────────
# 8/9. stdout и stderr сохраняются ОТДЕЛЬНЫМИ файлами.
check("8. раннер сохраняет stdout отдельным файлом на каждый тест",
      'os.path.join(out_dir, "stdout"' in GATE_SRC and '"stdout_log"' in GATE_SRC)
check("9. раннер сохраняет stderr отдельным файлом на каждый тест",
      'os.path.join(out_dir, "stderr"' in GATE_SRC and '"stderr_log"' in GATE_SRC)

# 10. _out.txt не является хранилищем: имени вообще нет в раннере.
check("10. единого перезаписываемого _out.txt в раннере нет",
      "_out.txt" not in GATE_SRC and "_out.txt" not in PARSE_SRC)

# 11. manifest count сверяется с result count.
s = GATE.summarize([{"rel": "a"}, {"rel": "b"}], [_res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n")])
check("11. manifest 2 против results 1 → расхождение поймано и гейт красный",
      s["manifest_matches_completed"] is False and s["excluded_files"] == 1
      and s["process_rc"] != 0, s["blocking"])

# 12. Excluded вычисляется явно, а не подразумевается.
check("12. excluded_files вычисляется явно как manifest − completed",
      '"excluded_files": len(manifest) - len(results)' in GATE_SRC)

# ─────────────────────────── 13–18: rc, таймаут, mutation ───────────────────────────
# 13. Ненулевой process rc учитывается даже при чистом выводе.
r = _res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=3)
check("13. ненулевой process rc краснит файл при внешне чистом выводе",
      r["status"] == "red", r)

# 14. Таймаут учитывается отдельным полем.
r = _res("PASS — a\n", rc=-1000, timed_out=True)
check("14. таймаут — отдельный признак, файл красный, error_count=1",
      r["timed_out"] and r["error_count"] == 1 and r["status"] == "red", r)

# 15. Внутренние сбои mutation считаются прямо.
mut = ("ИТОГО: поймано 23, не поймано 1, сбоев оснастки 0, время 22.1 c\n"
       "PASS — прогон\nИтого: PASS=1 FAIL=0 SKIP=0\n")
r = _res(mut, rc=1)
check("15. internal_mutation_failures считается прямо (не поймана → ≥1)",
      r["internal_mutation_failures"] >= 1 and r["status"] == "red", r)

# 16. mutation_not_applied считается прямо.
r = _res("Mutation proof 2830: CAUGHT=15 MISS=0 (всего 15)\n"
         "ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ 15 != объявленных 19 — набор недоказателен.\n"
         "PASS — x\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=1)
check("16. mutation_not_applied считается прямо при объявленном расхождении",
      r["mutation_not_applied"] >= 1 and r["status"] == "red", r)

# 17. unexpected_green считается прямо.
r = _res("… CAUGHT=20 MISS=2 HARNESS=0 (исполнено 22 из объявленных 22)\n"
         "PASS — x\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=1)
check("17. unexpected_green считается прямо (исполнено 22, поймано 20 → 2)",
      r["unexpected_green"] == 2 and r["status"] == "red", r)

# 18. cleanup/restore failure считается прямо.
r = _res("ИТОГО: ПОЙМАНО 21 из 21 (объявлено поломок: 21)\n"
         "Файлы восстановлены побайтово: НЕТ\n"
         "PASS — x\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=1)
check("18. несостоявшийся побайтовый откат считается прямо",
      r["restore_failures"] >= 1 and r["status"] == "red", r)

# ─────────────────────────── 19–22: сводный вердикт ───────────────────────────
# 19. Любой пропуск делает полный гейт красным.
s = GATE.summarize([{"rel": "a"}],
                   [_res("PASS — a\nSKIP — b\nИтого: PASS=1 FAIL=0 SKIP=1\n")])
check("19. один пропуск в одном файле делает ВЕСЬ гейт красным",
      s["skip_checks"] == 1 and s["process_rc"] != 0, s["blocking"])

# 20. Unknown-результат делает полный гейт красным.
s = GATE.summarize([{"rel": "a"}], [_res("непонятный вывод\n")])
check("20. unknown-результат делает ВЕСЬ гейт красным",
      s["unknown_files"] == 1 and s["unknown_skip_files"] == 1 and s["process_rc"] != 0,
      s["blocking"])

# 21. Итоговый summary воспроизводим: одинаковый вход → одинаковый JSON.
res_a = [_res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n")]
res_b = [_res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n")]
j1 = json.dumps(GATE.summarize([{"rel": "a"}], res_a), sort_keys=True, ensure_ascii=False)
j2 = json.dumps(GATE.summarize([{"rel": "a"}], res_b), sort_keys=True, ensure_ascii=False)
check("21. summary воспроизводим побайтово при одинаковом входе", j1 == j2)

# 22. Раннер выходит ненулевым при ЛЮБОМ ненулевом счётчике.
_cases = {
    "fail_checks":   _res("FAIL — x\nИтого: PASS=0 FAIL=1 SKIP=0\n", rc=1),
    "skip_checks":   _res("SKIP — x\nИтого: PASS=0 FAIL=0 SKIP=1\n", rc=0),
    "timeout":       _res("", rc=-1000, timed_out=True),
    "unknown":       _res("проза\n", rc=0),
    "nonzero_rc":    _res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=7),
}
_all_red = True
for name, rr in _cases.items():
    ss = GATE.summarize([{"rel": "a"}], [rr])
    if ss["process_rc"] == 0:
        _all_red = False
        print("      ! счётчик %s не покраснел: %s" % (name, ss["blocking"]))
check("22. ненулевой любой счётчик (fail/skip/timeout/unknown/rc) → rc раннера != 0", _all_red)

# Сценарий D задачи: в выводе ТОЛЬКО FM_SKIP_BROWSER и никакого формата результата.
# Это не результат вовсе: ни ноль, ни пропуск — неизвестность, то есть красный.
r = _res("(браузерная часть отключена FM_SKIP_BROWSER=1 — режим mutation proof)\n", rc=0)
check("24. один лишь FM_SKIP_BROWSER без формата результата → unknown (не ноль и не пропуск)",
      r["status"] == "unknown" and r["skip_known"] is False and r["skip_count"] == 0, r)

# Сценарий G задачи: процесс вернул 0, но структурный счёт показывает провал.
r = _res("FAIL — проверка провалена\nИтого: PASS=0 FAIL=1 SKIP=0\n", rc=0)
check("25. process rc=0 при fail_count=1 → файл КРАСНЫЙ (верим счёту, а не коду выхода)",
      r["fail_count"] == 1 and r["status"] == "red", r)

# Машиночитаемая мутационная сводка — самодостаточный источник, но НЕ индульгенция.
_HEALTHY = ('FM_MUTATION_SUMMARY_JSON={"caught_mutations": 21, "cleanup_failures": 0, '
            '"declared_mutations": 21, "executed_mutations": 21, "internal_failures": 0, '
            '"mutation_not_applied": 0, "process_rc": 0, "restore_failures": 0, '
            '"schema": "3diwell-mutation-summary-v1", "timeouts": 0, "unexpected_green": 0}\n')
r = _res("ИТОГО: ПОЙМАНО 21 из 21\n" + _HEALTHY, rc=0)
check("26. здоровая структурированная мутационная сводка → skip известен и файл зелёный",
      r["skip_known"] and r["skip_count"] == 0 and r["status"] == "green"
      and r["counts_source"] == "mutation-structured", r)

_SICK = _HEALTHY.replace('"internal_failures": 0', '"internal_failures": 2') \
                .replace('"mutation_not_applied": 0', '"mutation_not_applied": 2') \
                .replace('"process_rc": 0', '"process_rc": 1')
r = _res("ИТОГО: ПОЙМАНО 19 из 21\n" + _SICK, rc=1)
check("27. нездоровая структурированная сводка краснит, а не проходит по той же дороге",
      r["internal_mutation_failures"] == 2 and r["mutation_not_applied"] == 2
      and r["status"] == "red", r)

# Здоровый случай обязан быть зелёным — иначе набор красит всё подряд и бесполезен.
s_ok = GATE.summarize([{"rel": "a"}], [_res("PASS — a\nИтого: PASS=1 FAIL=0 SKIP=0\n", rc=0)])
check("23. контроль: полностью здоровый вход даёт rc=0 (набор не красит всё подряд)",
      s_ok["process_rc"] == 0 and s_ok["green_files"] == 1, s_ok["blocking"])

print("\n" + "=" * 92)
print("Итого: PASS=%d FAIL=%d SKIP=0" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
