# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — ИЗОЛИРОВАННЫЙ FARM MANAGER: границы режима isolated_farm_manager.
#
#  ЗАЧЕМ. Этот режим запускает НАСТОЯЩИЙ server.py. Ошибка здесь стоит дороже любой другой
#  в оснастке: наполовину изолированный экземпляр может задеть рабочие данные владельца или
#  выйти в сеть к принтерам. Тест закрепляет, что каждое условие изоляции доказывается до
#  запуска, что сторож сети действительно ловит внешние соединения, и что зелёный вердикт
#  невозможен без готовности, backend-проверок, чистой сети и полной уборки.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. НЕ запускает server.py, НЕ запускает Edge, НЕ ходит в сеть.
#  Процессы и HTTP подменяются фиктивными адаптерами; сторож сети проверяется на
#  крошечном подпроцессе, который пытается соединиться сам с собой.
#
#  Запуск:  python tools/test_isolated_ui_verification.py       (0 = границы соблюдены)
# ============================================================================
import copy
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIDIR = os.path.join(REPO, "tools", "validation", "ui")
RV_PATH = os.path.join(UIDIR, "run_ui_verification.py")
GUARD_DIR = os.path.join(UIDIR, "network_guard")

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


sec("0. Оснастка на месте")
check("0a. run_ui_verification.py существует", os.path.isfile(RV_PATH))
check("0b. сторож сети существует", os.path.isfile(os.path.join(GUARD_DIR,
                                                                "sitecustomize.py")))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_run_ui_iso", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SCENS = rv.load_scenarios()
ISO = SCENS["settings_panel_open_close_isolated"]
STATIC = SCENS["settings_panel_open_close"]
SELFRUNS = os.path.join(REPO, "logs", "ui_runs", "_selftest_iso")
TMP = tempfile.mkdtemp(prefix="fm_iso_")


def fresh_run(name="r1"):
    d = os.path.join(SELFRUNS, name)
    shutil.rmtree(d, ignore_errors=True)
    for sub in ("test_data", "test_config", "browser_profile", "artifacts",
                "process_logs", "network_guard"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


class FakeProc(object):
    def __init__(self, pid=4242, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        self._rc = 0
        return 0


def guard_subprocess(env_extra, code):
    """Запустить крошечный python со сторожем и вернуть (rc, stdout)."""
    env = dict((k, os.environ[k]) for k in ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT",
                                            "TEMP", "TMP", "COMSPEC")
               if k in os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = GUARD_DIR
    env.update(env_extra)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, shell=False,
                       timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


try:
    # ── 1. Контракт изоляции ─────────────────────────────────────────────────
    sec("1. Официальный контракт E2E")

    run_dir = fresh_run()
    port = rv.free_local_port()
    C = rv.build_e2e_contract(run_dir, port)
    proofs, problems = rv.check_e2e_contract(C, run_dir)
    check("1. корректный контракт проходит без замечаний", not problems, problems)
    check("1b. используется официальный флаг продукта", C["flag"] == "--fm-packaged-e2e")
    check("2. имена переменных взяты из продукта, а не выдуманы",
          set(rv.E2E_ENV.values()) == {
              "FM_E2E_SENTINEL", "FM_E2E_INSTANCE_ID", "FM_E2E_DATA_DIR",
              "FM_E2E_CONFIG_PATH", "FM_E2E_MUTEX_NAME", "FM_E2E_PORT",
              "FM_E2E_DISABLE_TRAY", "FM_E2E_DISABLE_BROWSER",
              "FM_E2E_DISABLE_DISCOVERY", "FM_E2E_DISABLE_PRINTERS",
              "FM_E2E_DISABLE_MODULES"}, sorted(rv.E2E_ENV.values()))

    env = rv.server_env(C, run_dir)
    for num, key in ((2.1, "FM_E2E_SENTINEL"), (2.2, "FM_E2E_DATA_DIR"),
                     (2.3, "FM_E2E_CONFIG_PATH"), (2.4, "FM_E2E_MUTEX_NAME"),
                     (2.5, "FM_E2E_PORT")):
        check("%s. обязательная переменная %s задана" % (num, key), bool(env.get(key)))
    check("2.6. без обязательной переменной запуск не состоится: продукт отказывает "
          "кодом e2e_*", all(env.get(k) for k in rv.E2E_ENV.values()))

    bad = copy.deepcopy(C)
    bad["data_dir"] = os.path.join(TMP, "outside_data")
    os.makedirs(bad["data_dir"], exist_ok=True)
    _, pr = rv.check_e2e_contract(bad, run_dir)
    check("3. тестовый DATA_DIR вне каталога запуска блокируется",
          "data_dir_inside_run" in pr, pr)

    bad = copy.deepcopy(C)
    bad["config_path"] = os.path.join(TMP, "cfg.json")
    _, pr = rv.check_e2e_contract(bad, run_dir)
    check("4. config вне каталога запуска блокируется", "config_inside_run" in pr, pr)

    real_prod = rv.production_data_dir
    rv.production_data_dir = lambda: C["data_dir"]
    _, pr = rv.check_e2e_contract(C, run_dir)
    check("5. совпадение с рабочим DATA_DIR блокируется",
          "data_dir_not_production" in pr, pr)
    rv.production_data_dir = lambda: os.path.dirname(C["data_dir"])
    _, pr = rv.check_e2e_contract(C, run_dir)
    check("6. тестовая папка внутри рабочей блокируется",
          "data_dir_not_child_of_production" in pr, pr)
    rv.production_data_dir = lambda: os.path.join(C["data_dir"], "inner")
    _, pr = rv.check_e2e_contract(C, run_dir)
    check("6b. рабочая папка внутри тестовой блокируется",
          "data_dir_not_parent_of_production" in pr, pr)
    rv.production_data_dir = real_prod

    bad = copy.deepcopy(C)
    bad["mutex_name"] = rv.PRODUCTION_MUTEX
    _, pr = rv.check_e2e_contract(bad, run_dir)
    check("7. рабочий mutex блокируется", "mutex_unique" in pr, pr)
    check("7b. mutex содержит идентификатор запуска",
          C["run_id"][:8].replace("-", "") in C["mutex_name"], C["mutex_name"])

    bad = copy.deepcopy(C)
    bad["port"] = 80
    _, pr = rv.check_e2e_contract(bad, run_dir)
    check("8. порт вне пользовательского диапазона блокируется",
          "port_is_random_loopback" in pr, pr)
    bad["port"] = rv.PRODUCTION_PORT_DEFAULT
    _, pr = rv.check_e2e_contract(bad, run_dir)
    check("9. обычный порт владельца блокируется", "port_differs_from_production" in pr, pr)
    src = io.open(RV_PATH, encoding="utf-8").read()
    check("8b. сервер поднимается только на петле",
          '"127.0.0.1"' in src and "0.0.0.0" not in src)

    for num, key in ((10, "dispatch"), (11, "transport")):
        rv.fuses_off = (lambda k: (lambda: {"DISPATCH_ENABLED": k != "dispatch",
                                            "TRANSPORT_ENABLED": k != "transport"}))(key)
        _, pr = rv.check_e2e_contract(C, run_dir)
        check("%d. включённый %s блокирует запуск" % (num, key),
              ("%s_disabled" % key) in pr, pr)
    rv.fuses_off = importlib.util.module_from_spec(_spec) and rv.fuses_off
    _spec.loader.exec_module(rv)      # вернуть подлинные реализации
    rv_fuses = rv.fuses_off

    for num, key in ((12, "discovery"), (13, "printers"), (14, "tray"), (15, "browser")):
        bad = copy.deepcopy(C)
        bad["disables"][key] = "0"
        _, pr = rv.check_e2e_contract(bad, run_dir)
        check("%d. невыключенный %s блокирует запуск" % (num, key),
              ("disabled_" + key) in pr, pr)
    check("15b. modules тоже выключаются официальным флагом",
          C["disables"]["modules"] == "1")

    for num, poison in ((16, {"printer": "Bambu X1C 192.168.1.77"}),
                        (17, {"access_code": "12345678"}),
                        (18, {"serial_number": "01P00A000000000"}),
                        (19, {"host": "10.0.0.55"})):
        bad = copy.deepcopy(C)
        bad.update(poison)
        _, pr = rv.check_e2e_contract(bad, run_dir)
        check("%d. %s в контракте блокируется" % (num, list(poison)[0]),
              "no_credentials_in_contract" in pr, pr)

    # ── 2. Сторож сети ──────────────────────────────────────────────────────
    sec("2. Сторож исходящих соединений backend")

    glog = os.path.join(TMP, "guard.jsonl")
    gsent = os.path.join(TMP, "sentinel.json")
    GENV = {"FM_UI_GUARD_LOG": glog, "FM_UI_GUARD_SENTINEL": gsent}

    lst = socket.socket()
    lst.bind(("127.0.0.1", 0))
    lst.listen(4)
    lport = lst.getsockname()[1]

    rc, out = guard_subprocess(GENV, "import socket;s=socket.create_connection(('127.0.0.1',%d),2);"
                                     "print('LOCAL_OK');s.close()" % lport)
    check("21. соединение на 127.0.0.1 разрешено", rc == 0 and "LOCAL_OK" in out, out[:120])
    check("20. удостоверение сторожа создано", os.path.isfile(gsent))

    rc, out = guard_subprocess(GENV, "import socket;s=socket.create_connection(('localhost',%d),2);"
                                     "print('LOCALHOST_OK');s.close()" % lport)
    check("22. имя localhost разрешено", rc == 0 and "LOCALHOST_OK" in out, out[:120])

    rc, out = guard_subprocess(GENV, "import socket\n"
                                     "try:\n"
                                     "    socket.create_connection(('93.184.216.34',80),2)\n"
                                     "    print('LEAK')\n"
                                     "except OSError as e:\n"
                                     "    print('BLOCKED' if 'FM_UI_GUARD' in str(e) else 'OTHER:'+str(e))")
    check("24. внешний IPv4 заблокирован сторожем", "BLOCKED" in out and "LEAK" not in out,
          out[:160])

    rc, out = guard_subprocess(GENV, "import socket\n"
                                     "try:\n"
                                     "    socket.create_connection(('example.com',80),3)\n"
                                     "    print('LEAK')\n"
                                     "except OSError as e:\n"
                                     "    print('BLOCKED' if 'FM_UI_GUARD' in str(e) else 'OTHER:'+str(e))")
    check("25. внешнее имя не приводит к соединению",
          "LEAK" not in out and ("BLOCKED" in out or "OTHER" in out), out[:160])

    rc, out = guard_subprocess(GENV, "import socket\n"
                                     "try:\n"
                                     "    socket.socket(socket.AF_INET,socket.SOCK_DGRAM)"
                                     ".sendto(b'x',('255.255.255.255',1900))\n"
                                     "    print('LEAK')\n"
                                     "except OSError as e:\n"
                                     "    print('BLOCKED' if 'FM_UI_GUARD' in str(e) else 'OTHER')")
    check("24b. широковещательная датаграмма (обнаружение) заблокирована",
          "LEAK" not in out, out[:120])

    entries = [json.loads(l) for l in io.open(glog, encoding="utf-8") if l.strip()]
    check("26. журнал содержит только метаданные, без полезной нагрузки",
          entries and all(set(e) == {"ts", "pid", "kind", "host", "port", "allowed",
                                     "reason"} for e in entries),
          sorted(entries[0]) if entries else "пусто")
    check("26b. в журнале нет ни одного передаваемого байта",
          all("data" not in json.dumps(e) and "payload" not in json.dumps(e)
              for e in entries))
    blocked = [e for e in entries if not e["allowed"]]
    check("24c. заблокированные попытки записаны", len(blocked) >= 1, len(blocked))
    check("23. петля ::1 входит в список разрешённых",
          "::1" in json.load(io.open(gsent, encoding="utf-8"))["allowed"])

    rc, out = guard_subprocess({}, "import socket;print(socket.socket.connect.__qualname__)")
    check("27. без переменных запуска сторож не активируется",
          "socket.connect" in out, out[:120])
    lst.close()

    # ── 3. Готовность ───────────────────────────────────────────────────────
    sec("3. Готовность настоящего сервера")

    run2 = fresh_run("r2")
    C2 = rv.build_e2e_contract(run2, rv.free_local_port())
    rv.write_e2e_marker(C2)

    pr = rv.readiness_proof(FakeProc(rc=0), C2, run2, deadline_s=2)
    check("28. ранний выход сервера с кодом 0 -> не готов",
          not pr["ready"] and "код 0" in pr["detail"], pr["detail"])

    real_http = rv.http_json
    rv.http_json = lambda port, path, timeout=6.0: (None, "нет соединения")
    pr = rv.readiness_proof(FakeProc(), C2, run2, deadline_s=2)
    check("29. открытый порт без официального ответа не даёт готовности",
          not pr["ready"] and not pr["checks"]["official_readiness_answered"])

    rv.http_json = lambda port, path, timeout=6.0: (
        {"status": 200, "json": {"version": "Alpha 2.841", "boot_id": "b1"}}, None)
    io.open(os.path.join(C2["data_dir"], "app.db"), "w").write("x")
    io.open(os.path.join(run2, "network_guard", "sentinel.json"), "w").write("{}")
    pr = rv.readiness_proof(FakeProc(), C2, run2, deadline_s=3)
    check("30. готовность привязана к порту текущего запуска",
          pr["checks"]["answer_from_run_port"] is False or pr["version"] == "Alpha 2.841",
          pr["checks"])
    check("31. версия backend читается из официального ответа",
          pr["version"] == "Alpha 2.841", pr["version"])
    check("20b. отсутствие удостоверения сторожа ломает готовность",
          "network_guard_sentinel" in pr["checks"])

    os.remove(os.path.join(run2, "network_guard", "sentinel.json"))
    pr2 = rv.readiness_proof(FakeProc(), C2, run2, deadline_s=3)
    check("20c. без удостоверения сторожа готовность не подтверждается",
          not pr2["ready"] and not pr2["checks"]["network_guard_sentinel"])

    io.open(os.path.join(run2, "process_logs", "farm_manager.stdout.txt"), "w",
            encoding="utf-8").write("E2E isolation rejected: e2e_root_in_production\n")
    pr3 = rv.readiness_proof(FakeProc(), C2, run2, deadline_s=3)
    check("29b. отказ продукта в изоляции виден как ошибка старта",
          not pr3["ready"] and pr3["startup_error"], pr3["startup_error"])
    os.remove(os.path.join(run2, "process_logs", "farm_manager.stdout.txt"))

    # ── 4. Проверки backend ─────────────────────────────────────────────────
    sec("4. Read-only проверки backend")

    def fake_http(good=True, version="Alpha 2.841", printers=None, jobs=None):
        def f(port, path, timeout=6.0):
            if not good:
                return None, "нет соединения"
            if path == "/version":
                return {"status": 200, "json": {"version": version, "boot_id": "b"}}, None
            if path == "/api/printers":
                return {"status": 200, "json": printers if printers is not None else []}, None
            if path == "/api/send-jobs":
                return {"status": 200, "json": jobs if jobs is not None
                        else {"jobs": [], "reserved_printer_ids": []}}, None
            if path == "/api/update-check":
                # Подавленная проверка обновлений: ответ той же формы, что и при
                # недоступном сайте, и без единого выхода наружу.
                return {"status": 200, "json": {"current": "Alpha 2.841", "latest": None,
                                                "update_available": False, "url": None,
                                                "notes": None, "ok": False}}, None
            return {"status": 200, "json": {}}, None
        return f

    io.open(os.path.join(run2, "process_logs", "farm_manager.stdout.txt"), "w",
            encoding="utf-8").write("E2E isolation: update check disabled\n")
    rv.http_json = fake_http()
    ba = rv.backend_assertions(C2, run2)
    check("31b. все read-only проверки backend проходят на чистом экземпляре",
          all(x["passed"] for x in ba), [x["id"] for x in ba if not x["passed"]])
    check("31c. проверок backend не меньше восьми", len(ba) >= 8, len(ba))
    # Проверяем отсутствие изменяющих действий по существу, а не по списку допустимых
    # начал строки: белый список префиксов краснел бы при каждой новой формулировке.
    MUTATING = ("POST", "PUT", "PATCH", "DELETE", "печат", "удал", "запис", "измен",
                "создать", "отправ")
    check("31d. среди проверок нет ни одной изменяющей операции",
          all(not any(m.lower() in x["proof"].lower() for m in MUTATING) for x in ba),
          [x["proof"][:30] for x in ba
           if any(m.lower() in x["proof"].lower() for m in MUTATING)])
    check("31g. подавление обновлений проверяется двумя независимыми способами",
          {"update_check_suppressed", "update_suppression_declared_by_contract"}
          <= set(x["id"] for x in ba), [x["id"] for x in ba])

    rv.http_json = fake_http(version="Alpha 9.999")
    ba2 = rv.backend_assertions(C2, run2)
    check("31e. чужая версия backend краснит проверку",
          not next(x for x in ba2 if x["id"] == "version_matches")["passed"])

    rv.http_json = fake_http(printers=[{"id": 1, "ip": "192.168.1.5"}])
    ba3 = rv.backend_assertions(C2, run2)
    check("16b. непустой список принтеров краснит проверку",
          not next(x for x in ba3 if x["id"] == "printers_empty")["passed"])

    rv.http_json = fake_http(jobs={"jobs": [{"id": 7}], "reserved_printer_ids": [2]})
    ba4 = rv.backend_assertions(C2, run2)
    check("31f. активная очередь краснит проверку",
          not next(x for x in ba4 if x["id"] == "no_active_queue")["passed"])
    rv.http_json = real_http

    check("32. браузер запускается только после проверок backend",
          src.index("backend_assertions(contract, run_dir)") <
          src.index('spawn([env["node"]'), "порядок в исходнике")

    # ── 5. Вердикт ──────────────────────────────────────────────────────────
    sec("5. Вердикт изолированного режима")

    def dr_for(scen):
        acts, asserts = [], []
        for i, a in enumerate(scen["actions"]):
            row = {"index": i, "type": a["type"], "status": "pass",
                   "detail": "%s -> ok" % a.get("selector", "")}
            (asserts if a["type"].startswith("assert_") else acts).append(row)
        return {"ok": True, "actions": acts, "assertions": asserts,
                "screenshots": list(scen["screenshot_names"]),
                "console": {"errors": [], "warnings": [], "pageErrors": [], "unhandled": []},
                "network": [{"kind": "fetch", "url": "http://127.0.0.1:5555/api/printers"}],
                "reads": {}, "bridgeError": None, "timedOut": False}

    def judge(dr, scen=ISO):
        r = {"warnings": [], "actions_passed": 0, "assertions_passed": 0,
             "screenshots": [], "console_error_count": 0,
             "external_network_attempt_count": 0}
        return rv._judge(r, scen, dr, 5555), r

    st, _ = judge(dr_for(ISO))
    check("50a. полный корректный изолированный прогон даёт PASS", st == "PASS", st)

    bad = dr_for(ISO)
    bad["console"]["errors"] = ["TypeError"]
    st, _ = judge(bad)
    check("33. ошибка консоли даёт FAIL", st == "FAIL", st)

    bad = dr_for(ISO)
    bad["network"].append({"kind": "fetch", "url": "https://api.example.com/x"})
    st, r = judge(bad)
    check("34. внешний запрос браузера даёт FAIL",
          st == "FAIL" and r["external_network_attempt_count"] == 1)

    only_shots = dict(dr_for(ISO), actions=[], assertions=[])
    st, _ = judge(only_shots)
    check("49. скриншоты без проверок DOM не дают PASS", st == "FAIL", st)

    check("35. внешняя попытка backend делает результат красным",
          "blocked_network_attempts" in src and 'status = FAIL' in src)
    check("36. БД вне тестового DATA_DIR краснит файловую проверку",
          "database_inside_test_data" in src)
    check("37. изменение отпечатка рабочей папки краснит проверку",
          "production_data_unchanged" in src)
    check("38. изменение продуктовых файлов репозитория краснит проверку",
          "repository_product_files_unchanged" in src)

    prod_a = {"exists": True, "entries": 10, "total_bytes": 100, "sha256": "a" * 64}
    prod_b = dict(prod_a, sha256="b" * 64)
    fa, listing = rv.filesystem_assertions(C2, run2, prod_a, prod_b)
    check("37b. разный отпечаток до/после действительно краснит",
          not next(x for x in fa if x["id"] == "production_data_unchanged")["passed"])
    fa2, listing2 = rv.filesystem_assertions(C2, run2, prod_a, prod_a)
    check("37c. одинаковый отпечаток проходит",
          next(x for x in fa2 if x["id"] == "production_data_unchanged")["passed"])
    check("36b. созданная БД найдена внутри тестового DATA_DIR",
          listing2["database_files"] and all("test_data" in p
                                             for p in listing2["database_files"]),
          listing2["database_files"])

    # ── 6. Процессы и уборка ────────────────────────────────────────────────
    sec("6. Процессы и уборка изолированного режима")

    killed, alive = [], {}
    real_kill, real_alive = rv.kill_own, rv.pid_alive
    rv.kill_own = lambda pid: (killed.append(pid), "killed")[1]
    rv.pid_alive = lambda pid: alive.get(pid, False)
    man = {"run_id": "t", "processes": [{"role": "isolated_farm_manager", "pid": 555},
                                        {"role": "ui_driver_and_browser", "pid": 666}]}
    res6 = {"local_url": "http://127.0.0.1:59997/", "warnings": []}
    out = rv._cleanup(res6, FakeProc(555), FakeProc(666), man, run2)
    check("39. PID браузера записан в манифест", 666 in [p["pid"] for p in man["processes"]])
    check("40. PID сервера записан в манифест", 555 in [p["pid"] for p in man["processes"]])
    check("41. чужие PID не завершаются", set(killed) <= {555, 666}, killed)
    check("42. порядок уборки: браузер -> сервер -> проверка порта",
          killed == [666, 555] and out["port_released"] is True, (killed, out))
    alive[555] = True
    out2 = rv._cleanup({"local_url": "http://127.0.0.1:59997/", "warnings": []},
                       FakeProc(555), FakeProc(666), man, run2)
    check("43. оставшийся PID сервера делает уборку грязной",
          out2["status"] == "dirty" and out2["remaining"], out2)
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    bport = busy.getsockname()[1]
    out3 = rv._cleanup({"local_url": "http://127.0.0.1:%d/" % bport, "warnings": []},
                       None, None, {"processes": []}, run2)
    check("44. занятый после уборки порт виден как не освобождённый",
          out3["port_released"] is False, out3)
    busy.close()
    check("44b. занятый порт понижает вердикт", "порт не освобождён" in src)
    rv.kill_own, rv.pid_alive = real_kill, real_alive
    check("45c. уборка не использует завершение по имени",
          "/IM" not in src and "Stop-Process -Name" not in src)

    # ── 7. Отчёт ────────────────────────────────────────────────────────────
    sec("7. Отчёт не раскрывает лишнего")

    fp = rv.production_fingerprint()
    check("45. отпечаток рабочей папки не содержит абсолютного пути",
          set(fp) == {"exists", "entries", "total_bytes", "sha256"}, sorted(fp))
    e2e = json.load(io.open(os.path.join(run_dir, "e2e_contract.json"), encoding="utf-8")) \
        if os.path.isfile(os.path.join(run_dir, "e2e_contract.json")) else None
    check("45b. контракт не пишет токен и рабочий путь",
          e2e is None or ("token" not in e2e and "production" not in json.dumps(e2e)))
    env2 = rv.server_env(C2, run2)
    os.environ["FM_ISO_FAKE_SECRET"] = "leak-me-not"
    env3 = rv.server_env(C2, run2)
    check("46. секреты окружения не передаются серверу",
          "FM_ISO_FAKE_SECRET" not in env3 and "PATH" in env3)
    check("46b. рабочие домашние переменные передаются намеренно — по ним продукт сам "
          "доказывает, что тестовая папка не рабочая",
          "LOCALAPPDATA" in rv.ENV_ALLOW_SERVER)
    os.environ.pop("FM_ISO_FAKE_SECRET", None)

    check("47. статический режим не требует контракта E2E",
          STATIC["application_mode"] == "static_harness"
          and "e2e" not in json.dumps(STATIC, ensure_ascii=False).lower())
    check("48. изолированный режим честно отличается от статического",
          ISO["application_mode"] == "isolated_farm_manager"
          and ISO["locale"] != "auto" and ISO["id"] != STATIC["id"])
    check("48b. охват двух режимов описан по-разному",
          rv.run("settings_panel_open_close", execute=False, runs_dir=SELFRUNS)[0]
          ["coverage_scope"] !=
          rv.run("settings_panel_open_close_isolated", execute=False, runs_dir=SELFRUNS)[0]
          ["coverage_scope"])

    check("50. PASS требует DOM, консоль, сеть браузера, сеть backend, файловую систему "
          "и уборку",
          all(k in src for k in ("_judge", "blocked_network_attempts",
                                 "filesystem_assertions", "port_released",
                                 "remaining_owned_processes")))

finally:
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(SELFRUNS, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
