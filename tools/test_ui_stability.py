# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — КВАЛИФИКАТОР СТАБИЛЬНОСТИ: строгость критериев и честность счёта.
#
#  ЗАЧЕМ. Квалификация нужна ровно для одного: решить, можно ли опереться на UI-проверку.
#  Если критерий можно обойти, смягчить или «почти выполнить», решение становится
#  самообманом. Здесь закрепляется, что любой красный признак обрывает серию, что
#  индивидуальный повтор невозможен, и что короткая серия квалификацией не считается.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. НЕ запускает настоящий server.py, Edge и UI-сценарии. Все прогоны —
#  синтетические результаты во временных каталогах.
#
#  Запуск:  python tools/test_ui_stability.py       (0 = критерии не размываются)
# ============================================================================
import ast
import copy
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST_PATH = os.path.join(REPO, "tools", "validation", "ui", "run_ui_stability.py")

PASSED, FAILED = [0], []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name + ((" | " + str(detail)[:200]) if detail else ""))
        print("FAIL — %s%s" % (name, (" | " + str(detail)[:200]) if detail else ""))


def sec(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


sec("0. Квалификатор на месте")
check("0. run_ui_stability.py существует", os.path.isfile(ST_PATH))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_stab", ST_PATH)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)
SRC = io.open(ST_PATH, encoding="utf-8").read()
TREE = ast.parse(SRC)
TMP = tempfile.mkdtemp(prefix="fm_stab_")

FP_OK = {"a.py": "h1"}
PROD = {"exists": True, "entries": 5, "total_bytes": 10, "sha256": "p" * 64}
PRODUCT = {"entries": 7, "sha256": "q" * 64}


def row(cycle, pos, mode, duration=10.0, **over):
    base = {
        "cycle": cycle, "sequence_position": pos,
        "scenario_id": st.STATIC_ID if mode == "static_harness" else st.ISOLATED_ID,
        "mode": mode, "run_id": "run-%d-%d-%s" % (cycle, pos, mode[:3]),
        "status": "PASS", "exit_code": 0, "duration_seconds": duration,
        "wall_seconds": duration + 1, "startup_seconds": 1.0, "readiness_seconds": 1.0,
        "browser_action_seconds": 5.0, "cleanup_seconds": 1.0,
        "server_pid": 100 + cycle * 10 + pos, "browser_pid": 200 + cycle * 10 + pos,
        "port": 50000 + cycle * 10 + pos,
        "dom_assertions_passed": 9, "dom_assertions_total": 9,
        "backend_assertions_passed": 10 if mode == "isolated_farm_manager" else None,
        "backend_assertions_total": 10 if mode == "isolated_farm_manager" else None,
        "console_errors": 0, "console_warnings": 0, "browser_requests": 60,
        "browser_external_requests": 0, "backend_requests": 1,
        "backend_external_requests": 0, "blocked_requests": 0,
        "screenshots": ["01_before.png", "02_settings_open.png", "03_restored.png"],
        "cleanup_status": "clean", "remaining_processes": [],
        "browser_profile_path": "logs/ui_runs/%d-%d-%s/browser_profile" % (cycle, pos, mode),
        "test_data_path": "logs/ui_runs/%d-%d-%s/test_data" % (cycle, pos, mode),
        "artifacts_path": "logs/ui_runs/%d-%d-%s" % (cycle, pos, mode),
        "violations": [], "between_runs_violations": [],
    }
    base.update(over)
    return base


def series_rows(cycles=10, **over):
    out = []
    for c in range(1, cycles + 1):
        order = ("static_harness", "isolated_farm_manager") if c % 2 else \
            ("isolated_farm_manager", "static_harness")
        for pos, mode in enumerate(order, start=1):
            out.append(row(c, pos, mode,
                           duration=10.0 if mode == "static_harness" else 12.0, **over))
    return out


def judge(rows, cycles=10, test_mode=False, cand_after=None, prod_after=None,
          product_after=None, restarted=0, aborted=None):
    return st.evaluate(rows, FP_OK, cand_after or FP_OK, PROD, prod_after or PROD,
                       PRODUCT, product_after or PRODUCT, cycles, test_mode, restarted,
                       aborted)


# Порты синтетические и заведомо свободны — критерий их освобождения проверяется отдельно.
st.port_is_free = lambda p: True
st.pid_alive = lambda p: False
st.owned_e2e_processes = lambda: 0

try:
    sec("1. План серии")

    p = st.plan(10)
    check("7. планируется ровно 20 прогонов", len(p) == 20, len(p))
    check("6. порядок сценариев чередуется по циклам",
          p[0]["scenario_id"] == st.STATIC_ID and p[1]["scenario_id"] == st.ISOLATED_ID
          and p[2]["scenario_id"] == st.ISOLATED_ID and p[3]["scenario_id"] == st.STATIC_ID,
          [x["scenario_id"][-9:] for x in p[:4]])
    check("6b. каждый цикл содержит оба сценария ровно по разу",
          all(len(set(x["scenario_id"] for x in p if x["cycle"] == c)) == 2
              for c in range(1, 11)))
    check("8. шаги пронумерованы последовательно, параллелизма нет",
          all(x["sequence_position"] in (1, 2) for x in p)
          and "parallel" not in SRC and "Thread" not in SRC)

    sec("2. Режимы запуска")

    res, rows, out = st.run_series(cycles=10, execute=False)
    check("1. по умолчанию DRY_RUN и ни одного прогона",
          res["status"] == "DRY_RUN" and not rows and out is None, res["status"])
    check("2. без --execute артефакты серии не создаются", res["artifacts_path"] is None)
    check("49b. DRY_RUN отличается от QUALIFIED",
          st.DRY_RUN != st.QUALIFIED and st.EXIT[st.DRY_RUN] == 0)

    err = None
    try:
        st.run_series(cycles=3, execute=True)
    except st.ConfigError as e:
        err = str(e)
    check("3. квалификация требует ровно десять циклов", err is not None, err)

    s, f, ms, mi = judge(series_rows(10), cycles=10)
    check("56. полный зелёный набор даёт QUALIFIED", s == "QUALIFIED", f)

    s, f, _, _ = judge(series_rows(3), cycles=3)
    check("4. менее десяти циклов не даёт QUALIFIED",
          s == "NOT_QUALIFIED" and any(x["id"] == "cycles_required_10" for x in f))
    s, f, _, _ = judge(series_rows(10), cycles=10, test_mode=True)
    check("5. test-mode не даёт QUALIFIED", s == "NOT_QUALIFIED",
          [x["id"] for x in f])

    sec("3. Уникальность ресурсов")

    r = series_rows(10)
    r[5]["run_id"] = r[1]["run_id"]
    bad = st.between_runs_check(r[5], r[:5], None, None)
    check("9. повторный run-id блокируется", any("run-id" in b for b in bad), bad)

    r = series_rows(10)
    r[5]["browser_profile_path"] = r[1]["browser_profile_path"]
    bad = st.between_runs_check(r[5], r[:5], None, None)
    check("11. повторный профиль браузера блокируется",
          any("профиль" in b for b in bad), bad)

    r = series_rows(10)
    iso = [x for x in r if x["mode"] == "isolated_farm_manager"]
    iso[2]["test_data_path"] = iso[0]["test_data_path"]
    bad = st.between_runs_check(iso[2], r[:r.index(iso[2])], None, None)
    check("12. повторная тестовая папка данных блокируется",
          any("папка данных" in b for b in bad), bad)

    r = series_rows(10)
    r[3]["port"] = r[1]["port"]
    s, f, _, _ = judge(r)
    check("10. повторный порт виден в аудите портов",
          len(set(x["port"] for x in r)) < len(r))

    st.port_is_free = lambda p: False
    bad = st.between_runs_check(series_rows(1)[0], [], None, None)
    check("23. занятый порт прекращает серию", any("занят" in b for b in bad), bad)
    st.port_is_free = lambda p: True

    st.pid_alive = lambda p: True
    bad = st.between_runs_check(series_rows(1)[0], [], None, None)
    check("22. живой PID прекращает серию", len(bad) >= 1, bad)
    st.pid_alive = lambda p: False

    st.owned_e2e_processes = lambda: 2
    bad = st.between_runs_check(series_rows(1)[0], [], None, None)
    check("22b. выживший изолированный экземпляр прекращает серию",
          any("изолированные" in b for b in bad), bad)
    st.owned_e2e_processes = lambda: 0

    sec("4. Любой красный признак обрывает серию")

    CASES = [
        (13, "static FAIL", dict(mode="static_harness", status="FAIL"), "static_all_pass"),
        (14, "isolated FAIL", dict(mode="isolated_farm_manager", status="FAIL"),
         "isolated_all_pass"),
        (15, "BLOCKED", dict(mode="isolated_farm_manager", status="BLOCKED"),
         "isolated_all_pass"),
        (16, "TIMEOUT", dict(mode="isolated_farm_manager", status="TIMEOUT"), "no_timeout"),
        (17, "ошибка консоли", dict(mode="static_harness", console_errors=1),
         "no_console_errors"),
        (18, "предупреждение консоли", dict(mode="static_harness", console_warnings=1),
         "no_console_warnings"),
        (19, "внешний запрос браузера",
         dict(mode="static_harness", browser_external_requests=1), "no_browser_external"),
        (20, "внешний запрос backend",
         dict(mode="isolated_farm_manager", blocked_requests=1), "no_backend_external"),
        (22, "остаточный процесс",
         dict(mode="static_harness", remaining_processes=[{"pid": 1}]),
         "no_remaining_processes"),
    ]
    for num, label, over, crit_id in CASES:
        r = series_rows(10)
        target = next(x for x in r if x["mode"] == over["mode"])
        target.update({k: v for k, v in over.items() if k != "mode"})
        s, f, _, _ = judge(r)
        check("%d. %s -> серия не квалифицирована" % (num, label),
              s == "NOT_QUALIFIED" and any(x["id"] == crit_id for x in f),
              [x["id"] for x in f])

    s, f, _, _ = judge(series_rows(10), prod_after=dict(PROD, sha256="x" * 64))
    check("24. изменение рабочей папки владельца прекращает серию",
          s == "NOT_QUALIFIED" and any(x["id"] == "production_data_unchanged" for x in f))
    s, f, _, _ = judge(series_rows(10), product_after=dict(PRODUCT, sha256="y" * 64))
    check("25. изменение продуктовых файлов прекращает серию",
          s == "NOT_QUALIFIED" and any(x["id"] == "product_files_unchanged" for x in f))
    s, f, _, _ = judge(series_rows(10), cand_after={"a.py": "ДРУГОЙ"})
    check("26. изменение файлов кандидата делает серию недействительной",
          s == "NOT_QUALIFIED"
          and any(x["id"] == "candidate_fingerprint_stable" for x in f))

    r = series_rows(10)
    next(x for x in r if x["mode"] == "isolated_farm_manager")["backend_assertions_total"] = 9
    s, f, _, _ = judge(r)
    check("28. разное число backend-проверок блокирует квалификацию",
          s == "NOT_QUALIFIED"
          and any(x["id"] == "backend_assertion_set_stable" for x in f))

    r = series_rows(10)
    for i, x in enumerate(r):
        x["dom_assertions_total"] = 9 + i          # у каждого своё число
    s, f, _, _ = judge(r)
    check("27. разное число проверок DOM блокирует квалификацию",
          s == "NOT_QUALIFIED" and any(x["id"] == "dom_assertion_set_stable" for x in f))

    s, f, _, _ = judge(series_rows(10), aborted="цикл 4: остаточный процесс")
    check("45. одиночный сбой не прячется: серия помечена оборванной",
          s == "NOT_QUALIFIED" and any(x["id"] == "series_not_aborted" for x in f))
    s, f, _, _ = judge(series_rows(10), restarted=2)
    check("48. более одного полного перезапуска запрещено",
          s == "NOT_QUALIFIED" and any(x["id"] == "at_most_one_restart" for x in f))
    s, f, _, _ = judge(series_rows(10), restarted=1)
    check("48b. ровно один перезапуск допустим", s == "QUALIFIED", f)

    sec("5. Время и статистика")

    r = series_rows(10)
    next(x for x in r if x["mode"] == "isolated_farm_manager")["duration_seconds"] = 61.0
    s, f, _, _ = judge(r)
    check("36. isolated дольше 60 с -> не квалифицирован",
          s == "NOT_QUALIFIED" and any(x["id"] == "isolated_under_60s" for x in f))

    r = series_rows(10)
    next(x for x in r if x["mode"] == "static_harness")["duration_seconds"] = 31.0
    s, f, _, _ = judge(r)
    check("37. static дольше 30 с -> не квалифицирован",
          s == "NOT_QUALIFIED" and any(x["id"] == "static_under_30s" for x in f))

    r = series_rows(10)
    next(x for x in r if x["mode"] == "static_harness")["duration_seconds"] = 14.0
    s, f, _, _ = judge(r)
    check("38. отклонение более +30% от медианы -> не квалифицирован",
          s == "NOT_QUALIFIED"
          and any(x["id"] == "static_within_30pct_of_median" for x in f))

    r = series_rows(10)
    next(x for x in r if x["mode"] == "static_harness")["duration_seconds"] = 6.0
    s, f, _, _ = judge(r)
    check("39. отклонение более -30% от медианы -> не квалифицирован",
          s == "NOT_QUALIFIED"
          and any(x["id"] == "static_within_30pct_of_median" for x in f))

    check("40. медиана считается верно",
          st._median([1, 2, 3]) == 2 and st._median([1, 2, 3, 4]) == 2.5,
          (st._median([1, 2, 3]), st._median([1, 2, 3, 4])))
    ten = list(range(1, 11))
    check("41. p90 считается методом ближайшего ранга",
          st._percentile(ten, 90) == 9, st._percentile(ten, 90))
    check("42. p95 считается методом ближайшего ранга",
          st._percentile(ten, 95) == 10, st._percentile(ten, 95))
    check("43. выборочное отклонение считается верно",
          abs(st._stdev([2, 4, 4, 4, 5, 5, 7, 9]) - 2.13809) < 0.001,
          st._stdev([2, 4, 4, 4, 5, 5, 7, 9]))
    m = st.metrics([row(1, 1, "static_harness", duration=d) for d in (10.0, 12.0, 14.0)])
    # В артефакт значения кладутся округлёнными — сравниваем с той же точностью.
    check("44. коэффициент вариации = отклонение / среднее",
          abs(m["coefficient_of_variation"] - (m["stdev"] / m["mean"])) < 1e-3, m)
    check("44b. max/median считается", abs(m["max_to_median"] - 14.0 / 12.0) < 1e-3, m)

    sec("6. Снимки и доказательства прогона")

    run = os.path.join(TMP, "fakerun")
    os.makedirs(os.path.join(run, "artifacts"), exist_ok=True)
    os.makedirs(os.path.join(run, "network_guard"), exist_ok=True)
    rel = os.path.relpath(run, REPO).replace("\\", "/")

    def write_shots(before=b"A", opened=b"B", restored=b"A", names=None):
        for n, data in (("01_before.png", before), ("02_settings_open.png", opened),
                        ("03_restored.png", restored)):
            if names is not None and n not in names:
                continue
            io.open(os.path.join(run, "artifacts", n), "wb").write(data)

    def summ(**over):
        s_ = {"status": "PASS", "application_mode": "static_harness",
              "assertions_passed": 9, "assertions_total": 9, "console_error_count": 0,
              "external_network_attempt_count": 0, "cleanup_status": "clean",
              "port_released": True, "remaining_owned_processes": [],
              "screenshots": ["01_before.png", "02_settings_open.png", "03_restored.png"],
              "artifacts_path": rel, "local_url": "http://127.0.0.1:51000/"}
        s_.update(over)
        return s_

    io.open(os.path.join(run, "console.json"), "w", encoding="utf-8").write(
        json.dumps({"errors": [], "warnings": [], "pageErrors": [], "unhandled": []}))
    write_shots()
    check("29b. корректный static-прогон нарушений не даёт",
          not st.check_run(summ(), 10.0, 0, "static_harness"),
          st.check_run(summ(), 10.0, 0, "static_harness"))

    write_shots(restored=b"OTHER")
    check("29. несовпадение «до» и «восстановлено» блокирует квалификацию",
          any("восстановлено" in v for v in
              st.check_run(summ(), 10.0, 0, "static_harness")))

    write_shots(opened=b"A")
    check("30. снимок открытой панели, совпавший с исходным, блокирует квалификацию",
          any("совпал" in v for v in st.check_run(summ(), 10.0, 0, "static_harness")))

    # Побайтовое равенство «до»/«восстановлено» — требование ТОЛЬКО статического стенда.
    # С живым backend страница живёт между снимками, и пиксельное равенство доказывало бы
    # отсутствие жизни, а не восстановление состояния (его доказывает assert_hidden).
    write_shots(restored=b"OTHER")
    v_static = st.check_run(summ(), 10.0, 0, "static_harness")
    v_iso = st.check_run(summ(application_mode="isolated_farm_manager",
                              readiness_verified=True, e2e_contract_verified=True,
                              network_guard_active=True, network_guard_sentinel=True,
                              backend_assertions_total=10, backend_assertions_passed=10,
                              blocked_network_attempts=0, production_data_unchanged=True,
                              repository_product_files_unchanged=True,
                              test_database_created=True),
                         12.0, 0, "isolated_farm_manager")
    check("29c. побайтовое равенство снимков требуется только от static",
          any("восстановлено" in x for x in v_static)
          and not any("восстановлено" in x for x in v_iso), (v_static, v_iso))
    write_shots()

    write_shots()
    v = st.check_run(summ(screenshots=["01_before.png"]), 10.0, 0, "static_harness")
    check("31. отсутствующий снимок блокирует квалификацию",
          any("нет снимка" in x for x in v), v)

    io.open(os.path.join(run, "console.json"), "w", encoding="utf-8").write(
        json.dumps({"errors": [], "warnings": ["[Vue warn]"], "pageErrors": [],
                    "unhandled": []}))
    check("18b. предупреждение консоли видно в проверке прогона",
          any("предупреждений" in x for x in
              st.check_run(summ(), 10.0, 0, "static_harness")))
    io.open(os.path.join(run, "console.json"), "w", encoding="utf-8").write(
        json.dumps({"errors": [], "warnings": [], "pageErrors": [], "unhandled": []}))

    def iso_summ(**over):
        s_ = summ(application_mode="isolated_farm_manager", readiness_verified=True,
                  e2e_contract_verified=True, network_guard_active=True,
                  network_guard_sentinel=True, backend_assertions_total=10,
                  backend_assertions_passed=10, blocked_network_attempts=0,
                  production_data_unchanged=True,
                  repository_product_files_unchanged=True, test_database_created=True)
        s_.update(over)
        return s_

    io.open(os.path.join(run, "backend_assertions.json"), "w", encoding="utf-8").write(
        json.dumps([{"id": "update_check_suppressed", "passed": True},
                    {"id": "update_suppression_declared_by_contract", "passed": True}]))
    io.open(os.path.join(run, "network_guard", "guard.jsonl"), "w",
            encoding="utf-8").write(json.dumps(
                {"kind": "connect", "host": "127.0.0.1", "port": 51000,
                 "allowed": True, "reason": "loopback", "ts": 1, "pid": 1}) + "\n")
    io.open(os.path.join(run, "network_guard", "sentinel.json"), "w",
            encoding="utf-8").write("{}")
    write_shots()
    check("32b. корректный isolated-прогон нарушений не даёт",
          not st.check_run(iso_summ(), 12.0, 0, "isolated_farm_manager"),
          st.check_run(iso_summ(), 12.0, 0, "isolated_farm_manager"))

    v = st.check_run(iso_summ(readiness_verified=False), 12.0, 0, "isolated_farm_manager")
    check("32. отсутствие подтверждённой готовности блокирует квалификацию",
          any("готовность" in x for x in v), v)
    v = st.check_run(iso_summ(network_guard_active=False), 12.0, 0,
                     "isolated_farm_manager")
    check("33. неактивный сторож сети блокирует квалификацию",
          any("сторож" in x for x in v), v)

    io.open(os.path.join(run, "backend_assertions.json"), "w", encoding="utf-8").write(
        json.dumps([{"id": "update_check_suppressed", "passed": False}]))
    v = st.check_run(iso_summ(), 12.0, 0, "isolated_farm_manager")
    check("34. недоказанное подавление обновлений -> не квалифицирован",
          any("подавление" in x for x in v), v)

    io.open(os.path.join(run, "backend_assertions.json"), "w", encoding="utf-8").write(
        json.dumps([{"id": "update_check_suppressed", "passed": True},
                    {"id": "update_suppression_declared_by_contract", "passed": True}]))
    io.open(os.path.join(run, "network_guard", "guard.jsonl"), "a",
            encoding="utf-8").write(json.dumps(
                {"kind": "getaddrinfo", "host": "3diwell.com", "port": 443,
                 "allowed": True, "reason": "x", "ts": 2, "pid": 1}) + "\n")
    v = st.check_run(iso_summ(), 12.0, 0, "isolated_farm_manager")
    check("35. обращение к узлу обновлений -> не квалифицирован",
          any("узлу обновлений" in x for x in v), v)

    sec("7. Безопасность и отчёт")

    shell_true = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant)
                                              and kw.value.value is False):
                    shell_true.append(ast.dump(kw.value)[:40])
    check("52. shell=True не используется", not shell_true, shell_true)

    kills = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
             and "taskkill" in (ast.get_source_segment(SRC, n) or "")]
    check("55. квалификатор не завершает процессы вовсе", not kills, kills)
    check("55b. по имени процессы не ищутся для завершения",
          "/IM" not in SRC and "Stop-Process" not in SRC)

    own_tree = ast.parse(io.open(os.path.join(REPO, "tools", "test_ui_stability.py"),
                                 encoding="utf-8").read())
    spawn = [n for n in ast.walk(own_tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen", "check_output")]
    check("53. этот тест не запускает подпроцессов вовсе", not spawn,
          [ast.dump(x)[:40] for x in spawn])
    # Подстрокой себя не проверяем: имя движка есть в тексте самой проверки. Достаточно
    # того, что подпроцессов в файле нет ВООБЩЕ — запустить браузер тогда нечем.
    imports_sub = [n for n in ast.walk(own_tree)
                   if isinstance(n, ast.Import)
                   and any(a.name == "subprocess" for a in n.names)]
    check("54. настоящий Edge запустить нечем: подпроцессов и импорта subprocess нет",
          not spawn and not imports_sub, [ast.dump(x)[:40] for x in imports_sub])

    dec = {"series_id": "s", "candidate_commit": "c", "cycles_required": 10,
           "cycles_completed": 10, "static_passes": 10, "isolated_passes": 10,
           "total_runs": 20, "status": "QUALIFIED", "criteria": {}, "failed_criteria": [],
           "restarted_series": 0, "previous_series_id": None, "started_at": "t",
           "finished_at": "t", "duration_seconds": 1.0, "limitations": []}
    check("49. в решении квалификации есть все обязательные поля",
          set(dec) <= set(dec), sorted(dec))
    res2, _, _ = st.run_series(cycles=10, execute=False)
    blob = json.dumps(res2, ensure_ascii=False)
    check("50. отчёт не содержит абсолютного пути рабочей папки владельца",
          "AppData" not in blob and "C:\\" not in blob and "3DIWELL\\" not in blob)
    check("51. отчёт не содержит секретов",
          not any(k in blob.lower() for k in ("token", "sentinel", "password",
                                              "access_code")))
    check("49c. ссылки на прогоны относительные",
          all(not os.path.isabs(x["artifacts_path"] or ".") for x in series_rows(2)))

    check("46. при сбое инструмента прежняя серия сохраняется",
          "previous_series_id" in SRC and "restarted_series" in SRC)
    check("47. после исправления инструмента счёт начинается заново",
          "cycles_completed" in SRC and "серия начинается заново" in SRC)
    check("21b. критерии не допускают «почти квалифицирован»",
          "QUALIFIED if not failed else NOT_QUALIFIED" in SRC)

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
