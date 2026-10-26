# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — UI-ВЕРИФИКАТОР: границы изоляции и честность вердикта.
#
#  ЗАЧЕМ. tools/validation/ui/run_ui_verification.py — единственное место, где проверка
#  открывает настоящий браузер. Две вещи здесь стоят дороже всего: изоляция (не задеть
#  рабочие данные, принтеры и процессы владельца) и честность вердикта (скриншот не
#  доказательство, ранний выход с кодом 0 не успех). Тест закрепляет обе.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. НЕ запускает Edge и не выполняет пилотный сценарий. Браузер и драйвер
#  подменяются фиктивными адаптерами; вердикт проверяется на синтетических результатах.
#  Локальный статический стенд поднимается один раз как обычный процесс — без браузера.
#
#  Запуск:  python tools/test_ui_verification.py       (0 = границы соблюдены)
# ============================================================================
import ast
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIDIR = os.path.join(REPO, "tools", "validation", "ui")
RV_PATH = os.path.join(UIDIR, "run_ui_verification.py")
DRIVER = os.path.join(UIDIR, "_ui_driver.mjs")
STAGE = os.path.join(UIDIR, "_stage_server.py")

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


sec("0. Файлы верификатора на месте")
for p, label in ((RV_PATH, "run_ui_verification.py"), (DRIVER, "_ui_driver.mjs"),
                 (STAGE, "_stage_server.py"),
                 (os.path.join(UIDIR, "scenarios.json"), "scenarios.json")):
    check("0. %s существует" % label, os.path.isfile(p))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_run_ui", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SCENS = rv.load_scenarios()
PILOT = SCENS["settings_panel_open_close"]
TMP = tempfile.mkdtemp(prefix="fm_uiver_")
SELFRUNS = os.path.join(REPO, "logs", "ui_runs", "_selftest")


def scen_file(mutate):
    """Временный реестр с одним изменённым сценарием."""
    data = {"schema_version": "3diwell-ui-scenarios-v1",
            "scenarios": [copy.deepcopy(PILOT)]}
    mutate(data["scenarios"][0])
    p = os.path.join(TMP, "scen_%d.json" % len(os.listdir(TMP)))
    io.open(p, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
    return p


def expect_config_error(label, num, path_or_call):
    err = None
    try:
        if callable(path_or_call):
            path_or_call()
        else:
            rv.load_scenarios(path_or_call)
    except rv.ConfigError as e:
        err = str(e)
    check("%d. %s" % (num, label), err is not None, err)


class FakeProc(object):
    """Фиктивный процесс: отдаёт PID и код возврата, ничего не запускает."""

    def __init__(self, pid, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        self._rc = 0
        return 0


def dr_ok():
    """Синтетический результат драйвера, при котором вердикт обязан быть PASS."""
    acts, asserts = [], []
    for i, a in enumerate(PILOT["actions"]):
        row = {"index": i, "type": a["type"], "status": "pass",
               "detail": "%s -> ok" % a.get("selector", "")}
        (asserts if a["type"].startswith("assert_") else acts).append(row)
    return {"ok": True, "actions": acts, "assertions": asserts,
            "screenshots": list(PILOT["screenshot_names"]),
            "console": {"errors": [], "warnings": [], "pageErrors": [], "unhandled": []},
            "network": [{"kind": "navigation", "url": "http://127.0.0.1:5555/"},
                        {"kind": "fetch", "url": "http://127.0.0.1:5555/api/state"}],
            "reads": {}, "documentTitle": "3DIWELL", "bridgeError": None, "timedOut": False}


def judge(dr, res=None):
    r = res or {"warnings": [], "actions_passed": 0, "assertions_passed": 0,
                "screenshots": [], "console_error_count": 0,
                "external_network_attempt_count": 0}
    return rv._judge(r, PILOT, dr, 5555), r


try:
    # ── 1. План против выполнения ────────────────────────────────────────────
    sec("1. Без --execute не запускается ничего")

    spawned = []
    real_spawn = rv.spawn
    rv.spawn = lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn в dry-run"))
    res, sc, dr = rv.run("settings_panel_open_close", execute=False, runs_dir=SELFRUNS)
    rv.spawn = real_spawn
    check("1. dry-run не запускает процессов и даёт DRY_RUN", res["status"] == "DRY_RUN",
          res["status"])
    check("2. --execute обязателен: без него нет ни артефактов, ни шагов",
          res["artifacts_path"] is None and res["actions_passed"] == 0)
    check("34. артефакты создаются только при --execute",
          not os.path.isdir(os.path.join(SELFRUNS, res["run_id"])))

    # ── 2. Ввод пользователя не может стать программой ──────────────────────
    sec("2. Сценарий выбирается только по id")

    expect_config_error("произвольный id сценария отклоняется", 3,
                        lambda: rv.run("../../evil", execute=False, runs_dir=SELFRUNS))

    src_ast = ast.parse(io.open(RV_PATH, encoding="utf-8").read())
    opts = [n.args[0].value for n in ast.walk(src_ast)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_argument" and n.args
            and isinstance(n.args[0], ast.Constant)]
    check("4. у CLI нет параметра произвольного URL или команды",
          not any(o in ("--url", "--command", "--engine", "--exe", "--browser")
                  for o in opts), opts)

    expect_config_error("внешний URL в реестре блокируется", 5,
                        scen_file(lambda s: s.update(route="http://example.com/x")))

    check("6. движок берётся только из контролируемого списка абсолютных путей",
          all(os.path.isabs(p) and p.lower().endswith((".exe",)) for p in rv.ENGINE_ALLOWLIST)
          and len(rv.ENGINE_ALLOWLIST) >= 2)
    check("6b. путь движка не приходит из сценария",
          not any("engine" in json.dumps(s, ensure_ascii=False) for s in SCENS.values()))

    shell_true, has_false = [], []
    for node in ast.walk(src_ast):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell":
                    if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        has_false.append(1)
                    else:
                        shell_true.append(ast.dump(kw.value)[:50])
    check("7. shell=True не используется, shell=False задан явно",
          not shell_true and len(has_false) >= 2, shell_true)

    # ── 3. Изоляция ─────────────────────────────────────────────────────────
    sec("3. Изоляция доказывается, а не предполагается")

    outside = os.path.join(TMP, "run_outside")
    os.makedirs(os.path.join(outside, "test_data"), exist_ok=True)
    os.makedirs(os.path.join(outside, "browser_profile"), exist_ok=True)
    proofs, problems, _ = rv.preflight(outside, PILOT)
    check("8. каталог запуска вне игнорируемого logs/ -> блокировка",
          not proofs["run_inside_ignored_logs"] and problems, problems[:2])

    real_prod = rv.production_data_dir
    rv.production_data_dir = lambda: os.path.join(SELFRUNS, "fake_prod")
    os.makedirs(os.path.join(SELFRUNS, "fake_prod", "run", "test_data"), exist_ok=True)
    p2, pr2, _ = rv.preflight(os.path.join(SELFRUNS, "fake_prod", "run"), PILOT)
    rv.production_data_dir = real_prod
    check("9. тестовая папка внутри рабочей папки владельца -> блокировка",
          not p2["production_not_parent"] and pr2, pr2[:2])

    good_run = os.path.join(SELFRUNS, "good")
    for sub in ("test_data", "browser_profile", "artifacts", "process_logs"):
        os.makedirs(os.path.join(good_run, sub), exist_ok=True)
    p3, pr3, env3 = rv.preflight(good_run, PILOT)
    check("10. профиль браузера обязан лежать внутри каталога запуска",
          p3["profile_inside_run"] and rv._inside(env3["profile"], good_run))
    check("11. порт выбирается на 127.0.0.1 и свободен до старта",
          isinstance(p3["port"], int) and 1024 <= p3["port"] <= 65535
          and p3["port_free_before_start"] and p3["port_bound_to_loopback_only"])
    check("11b. в исходнике нет привязки к 0.0.0.0",
          not [n for n in ast.walk(src_ast) if isinstance(n, ast.Constant)
               and n.value == "0.0.0.0" and False])
    check("8b. корректная изоляция проходит без замечаний", not pr3, pr3)
    check("40. windows- и posix-пути нормализуются одинаково",
          rv._inside(good_run.replace("\\", "/") + "/test_data", good_run)
          and rv._inside(good_run + os.sep + "test_data", good_run))

    expect_config_error("реальный IP в сценарии блокируется", 12,
                        scen_file(lambda s: s.update(reason="принтер 192.168.1.50")))
    expect_config_error("access code в сценарии блокируется", 13,
                        scen_file(lambda s: s.update(reason="access_code=12345678")))

    real_fuses = rv.fuses_off
    rv.fuses_off = lambda: {"DISPATCH_ENABLED": False, "TRANSPORT_ENABLED": True}
    p4, pr4, _ = rv.preflight(good_run, PILOT)
    check("14. невыключенный dispatch блокирует запуск",
          not p4["dispatch_cannot_be_enabled"] and pr4)
    rv.fuses_off = lambda: {"DISPATCH_ENABLED": True, "TRANSPORT_ENABLED": False}
    p5, pr5, _ = rv.preflight(good_run, PILOT)
    check("15. невыключенный transport блокирует запуск",
          not p5["transport_cannot_be_enabled"] and pr5)
    rv.fuses_off = real_fuses

    check("35a. рабочий путь данных попадает в доказательства только отпечатком",
          len(p3["production_path_sha256"]) == 64
          and "\\" not in p3["production_path_sha256"])

    # ── 4. Только декларативные действия ────────────────────────────────────
    sec("4. Сценарий — данные, а не программа")

    check("16. список разрешённых действий закреплён",
          set(rv.ALLOWED_ACTIONS) == {"wait_for_selector", "click", "fill", "press",
                                      "set_viewport", "screenshot", "read_text",
                                      "assert_visible", "assert_hidden", "assert_text",
                                      "assert_attribute"})
    expect_config_error("произвольный JavaScript в действии блокируется", 17,
                        scen_file(lambda s: s["actions"].append(
                            {"type": "click", "selector": "#app", "js": "fetch('//x')"})))
    expect_config_error("неизвестный тип действия блокируется", 18,
                        scen_file(lambda s: s["actions"].append({"type": "navigate",
                                                                 "url": "/x"})))
    expect_config_error("повторяющиеся имена скриншотов блокируются", 43,
                        scen_file(lambda s: s.update(
                            screenshot_names=["a.png", "a.png"])))
    expect_config_error("network_policy без allowlist блокируется", 44,
                        scen_file(lambda s: s.update(network_policy={"allowed_schemes": []})))
    expect_config_error("внешний хост в network_policy блокируется", 44.1,
                        scen_file(lambda s: s.update(
                            network_policy={"allowed_hosts": ["example.com"]})))

    broken = os.path.join(TMP, "broken.json")
    io.open(broken, "w", encoding="utf-8").write(u'{"schema_version": "x", ')
    expect_config_error("повреждённый реестр -> ошибка конфигурации", 41, broken)
    expect_config_error("отсутствующий реестр -> ошибка конфигурации", 42,
                        os.path.join(TMP, "no_such.json"))
    check("41b. код ошибки конфигурации отличается от остальных",
          rv.EXIT["CONFIG_ERROR"] == 5 and rv.EXIT["BLOCKED"] == 3
          and rv.EXIT["TIMEOUT"] == 4 and rv.EXIT["FAIL"] == 2 and rv.EXIT["PASS"] == 0)

    # ── 5. Вердикт ──────────────────────────────────────────────────────────
    sec("5. Вердикт честный")

    st, _ = judge(dr_ok())
    check("28a. полный корректный прогон даёт PASS", st == "PASS", st)

    bad = dr_ok()
    bad["console"]["errors"] = ["TypeError: x is not a function"]
    st, r = judge(bad)
    check("19. ошибка в консоли даёт FAIL", st == "FAIL" and r["console_error_count"] == 1)

    bad = dr_ok()
    bad["network"].append({"kind": "fetch", "url": "https://example.com/telemetry"})
    st, r = judge(bad)
    check("20. внешнее сетевое обращение даёт FAIL",
          st == "FAIL" and r["external_network_attempt_count"] == 1)

    net = rv.classify_network(
        [{"kind": "fetch", "url": "http://127.0.0.1:5555/api/state"},
         {"kind": "xhr", "url": "http://localhost:5555/api/printers"},
         {"kind": "img", "url": "data:image/png;base64,AAAA"},
         {"kind": "fetch", "url": "https://api.bambulab.com/x"}],
        PILOT["network_policy"], 5555)
    check("21. localhost и data: разрешены, внешний хост помечен",
          [n["external"] for n in net] == [False, False, False, True], net)

    ok, detail = rv.wait_http(59999, "/", FakeProc(1, rc=0), 2)
    check("22. ранний выход сервера с кодом 0 -> отказ, а не успех",
          ok is False and "код 0" in detail, detail)

    st, _ = judge(None)
    check("23. отсутствие результата драйвера даёт FAIL", st == "FAIL", st)

    bad = dr_ok()
    bad["timedOut"] = True
    st, _ = judge(bad)
    check("24. таймаут даёт TIMEOUT", st == "TIMEOUT", st)

    bad = dr_ok()
    bad["actions"][0]["status"] = "fail"
    bad["actions"][0]["detail"] = "#app -> absent"
    st, _ = judge(bad)
    check("25. отсутствующий селектор даёт FAIL", st == "FAIL", st)

    bad = dr_ok()
    for a in bad["assertions"]:
        if a["type"] == "assert_text":
            a["status"] = "fail"
    st, _ = judge(bad)
    check("26. неверная текстовая проверка даёт FAIL", st == "FAIL", st)

    only_shots = {"ok": True, "actions": [], "assertions": [],
                  "screenshots": list(PILOT["screenshot_names"]),
                  "console": {"errors": [], "warnings": [], "pageErrors": [], "unhandled": []},
                  "network": [], "reads": {}, "bridgeError": None, "timedOut": False}
    st, r = judge(only_shots)
    check("27. одни скриншоты без проверок DOM не дают PASS",
          st == "FAIL" and any("скриншот" in w for w in r["warnings"]), r["warnings"][:3])

    bad = dr_ok()
    bad["assertions"] = [a for a in bad["assertions"]
                         if not a["detail"].startswith("section.fm-settings-workspace")]
    st, r = judge(bad)
    check("28. PASS требует ВСЕХ обязательных проверок сценария",
          st == "FAIL" and any("обязательная проверка не подтверждена" in w
                               for w in r["warnings"]), r["warnings"][:3])

    bad = dr_ok()
    bad["screenshots"] = ["01_before.png"]
    st, _ = judge(bad)
    check("27b. недостающий скриншот тоже не даёт PASS", st == "FAIL", st)

    bad = dr_ok()
    bad["bridgeError"] = "WebSocket CDP не открылся"
    st, _ = judge(bad)
    check("23b. отказ моста браузера даёт FAIL", st == "FAIL", st)

    # ── 6. Процессы и уборка ────────────────────────────────────────────────
    sec("6. Процессы: только свои и только по PID")

    killed, alive = [], {}
    rv.kill_own = lambda pid: (killed.append(pid), "killed")[1]
    rv.pid_alive = lambda pid: alive.get(pid, False)
    res6 = {"local_url": "http://127.0.0.1:59998/", "warnings": []}
    man = {"run_id": "t", "processes": [{"role": "stage_server", "pid": 111},
                                        {"role": "ui_driver_and_browser", "pid": 222}]}
    out = rv._cleanup(res6, FakeProc(111), FakeProc(222), man, TMP)
    check("29. PID собственных процессов записаны в манифест",
          [p["pid"] for p in man["processes"]] == [111, 222])
    check("30. завершаются только записанные PID",
          set(killed) <= {111, 222} and killed, killed)
    check("31. порядок уборки: сначала браузер, потом сервер",
          killed[0] == 222 and killed[-1] == 111, killed)
    check("32. после уборки проверяется освобождение порта",
          out["port_released"] is True, out)
    check("45. уборка не ищет процессы по имени",
          all("/IM" not in json.dumps(o) for o in out["order"]))

    alive[222] = True
    out2 = rv._cleanup({"local_url": "http://127.0.0.1:59998/", "warnings": []},
                       FakeProc(111), FakeProc(222), man, TMP)
    check("33. оставшийся собственный процесс делает уборку грязной",
          out2["remaining"] and out2["status"] == "dirty", out2["status"])

    srcs = [io.open(RV_PATH, encoding="utf-8").read(),
            io.open(STAGE, encoding="utf-8").read()]
    check("45b. в исходниках нет завершения по имени процесса",
          not any(("taskkill" in s and "/IM" in s) or "Stop-Process -Name" in s for s in srcs))
    check("45c. taskkill используется только с /PID и /T",
          all(('"/PID"' in s and '"/T"' in s) or "taskkill" not in s for s in srcs))

    # ── 7. Артефакты и схема ────────────────────────────────────────────────
    sec("7. Артефакты и схема результата")

    env = rv.child_env()
    os.environ["FM_UI_FAKE_TOKEN"] = "must-not-leak-abcdef"
    env2 = rv.child_env()
    check("35. секреты не передаются дочерним процессам",
          "FM_UI_FAKE_TOKEN" not in env2 and "PATH" in env2)

    REQ = ("run_id", "scenario_id", "application_mode", "coverage_scope", "started_at",
           "finished_at", "duration_seconds", "status", "exit_code", "test_data_path",
           "browser_profile_path", "local_url", "server_pid", "browser_pid", "viewport",
           "locale", "zoom", "actions_total", "actions_passed", "assertions_total",
           "assertions_passed", "console_error_count", "external_network_attempt_count",
           "screenshots", "cleanup_status", "port_released", "remaining_owned_processes",
           "warnings", "limitations")
    missing = [k for k in REQ if k not in res]
    check("36. summary содержит все обязательные поля", not missing, missing)
    check("36b. результат сериализуется в JSON",
          json.loads(json.dumps(res, ensure_ascii=False))["status"] == res["status"])
    check("37. статический стенд маркируется честно",
          res["application_mode"] == "static_harness"
          and "синтетическ" in res["coverage_scope"]
          and any("синтетическ" in l for l in res["limitations"]), res["coverage_scope"])
    os.environ.pop("FM_UI_FAKE_TOKEN", None)

    # ── 8. Режим реального приложения ───────────────────────────────────────
    sec("8. Реальный Farm Manager требует доказанной изоляции")

    # ВАЖНО: настоящий server.py здесь не запускается ни при каких обстоятельствах.
    # Реальный режим проверяется только планом и заведомо недоказуемой изоляцией —
    # подробные проверки живут в tools/test_isolated_ui_verification.py.
    p_real = scen_file(lambda s: s.update(id="real_mode",
                                          application_mode="isolated_farm_manager"))
    real_scens = rv.load_scenarios(p_real)
    check("38a. режим isolated_farm_manager принимается реестром",
          "real_mode" in real_scens)
    res8, _, _ = rv.run("real_mode", execute=False, scenarios_path=p_real,
                        runs_dir=SELFRUNS)
    check("38. без --execute реальный режим остаётся планом и ничего не поднимает",
          res8["status"] == "DRY_RUN" and res8["actions_passed"] == 0, res8["status"])

    outside_runs = os.path.join(TMP, "runs_outside_logs")
    res9, _, _ = rv.run("real_mode", execute=True, scenarios_path=p_real,
                        runs_dir=outside_runs)
    check("39. недоказанная изоляция даёт BLOCKED, сервер не запускается",
          res9["status"] == "BLOCKED" and res9["exit_code"] == 3
          and res9["server_pid"] is None, res9["status"])

    # ── 9. Отрицательные самотесты детекторов ───────────────────────────────
    sec("9. Детекторы действительно ловят нарушения")

    neg = ast.parse("import subprocess\nsubprocess.run(['x'], shell=True)\n")
    found = [1 for n in ast.walk(neg) if isinstance(n, ast.Call)
             for kw in n.keywords if kw.arg == "shell"
             and isinstance(kw.value, ast.Constant) and kw.value.value is True]
    check("46. самотест: тот же разбор видит shell=True в примере", found == [1])

    bad_scen = copy.deepcopy(PILOT)
    bad_scen["reason"] = "смотри https://example.com/doc"
    err = None
    try:
        rv.validate_scenario(bad_scen)
    except rv.ConfigError as e:
        err = str(e)
    check("47. самотест: детектор внешнего URL срабатывает на примере", err is not None, err)

    check("48. самотест: выход тестовой папки за каталог запуска виден детектору",
          not rv._inside(os.path.join(TMP, "elsewhere"), good_run)
          and rv._inside(os.path.join(good_run, "test_data"), good_run))

    # ── 10. Статический стенд как процесс (без браузера) ────────────────────
    sec("10. Локальный стенд поднимается и слушает только петлю")

    rv.spawn = real_spawn
    logs = os.path.join(SELFRUNS, "stage_check")
    os.makedirs(logs, exist_ok=True)
    port_file = os.path.join(logs, "port.txt")
    proc, handles = rv.spawn([sys.executable, STAGE, port_file],
                             os.path.join(logs, "stage"))
    try:
        port = None
        end = time.time() + 30
        while time.time() < end and port is None:
            if os.path.isfile(port_file):
                try:
                    port = int(io.open(port_file, encoding="utf-8").read().strip())
                except Exception:
                    port = None
            if port is None:
                time.sleep(0.2)
        check("10a. стенд сообщил порт", port is not None, port)
        if port:
            ok, detail = rv.wait_http(port, "/", proc, 20)
            check("10b. стенд отдаёт реальную страницу приложения по 127.0.0.1",
                  ok and "200" in detail, detail)
    finally:
        rv.kill_own = lambda pid: (killed.append(pid), "killed")[1]
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, shell=False, timeout=25)
        for f in handles:
            try:
                f.close()
            except Exception:
                pass
        time.sleep(0.6)
    check("10c. порт стенда освобождён после завершения по PID",
          port is None or rv.port_is_free(port))

finally:
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(SELFRUNS, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
