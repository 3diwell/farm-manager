# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — ИСПОЛНИТЕЛЬ ПРОФИЛЯ: что он может выполнить, а что не может никогда.
#
#  ЗАЧЕМ. tools/validation/run_profile.py — единственное место, где проверка перестаёт
#  быть планом и становится запущенным процессом. Цена ошибки здесь выше обычной: неверная
#  граница означает либо запуск чего-то разрушительного, либо зелёный отчёт о проверке,
#  которой не было. Тест закрепляет обе границы.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. Не запускает продуктовые тесты, release gate, mutation proof, браузер
#  и сборку. Все положительные сценарии выполнения используют временные каталоги и
#  собственные крошечные python-скрипты.
#
#  Запуск:  python tools/test_run_profile.py       (0 = границы соблюдены)
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALDIR = os.path.join(REPO, "tools", "validation")
RP_PATH = os.path.join(VALDIR, "run_profile.py")

PASSED, FAILED = [0], []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name + ((" | " + str(detail)[:220]) if detail else ""))
        print("FAIL — %s%s" % (name, (" | " + str(detail)[:220]) if detail else ""))


def sec(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sec("0. Модули на месте")
check("0a. tools/validation/run_profile.py существует", os.path.isfile(RP_PATH))
check("0b. реестр команд существует", os.path.isfile(os.path.join(VALDIR,
                                                                 "command_registry.json")))
check("0c. каталог тестов существует", os.path.isfile(os.path.join(VALDIR,
                                                                   "test_catalog.json")))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

rp = _load("fm_run_profile", RP_PATH)
sel = _load("fm_select_profile_t", os.path.join(VALDIR, "select_profile.py"))
REGISTRY = rp.load_registry()
CATALOG = rp.load_catalog(strict=False)
RISK_MAP = sel.load_map()
NODE = rp.find_node()

DOC = "docs/validation/profile-selection.md"      # безопасная цель для реального запуска
TMP = tempfile.mkdtemp(prefix="fm_runprof_")


def mk(profile, risk, changed=(), targeted=(), subsystem=(), ui=False, blocked=False):
    """Синтетический результат селектора — чтобы не гонять сам селектор ради формы."""
    return {"schema_version": "x", "changed_files": list(changed), "matched_rules": [],
            "unmatched_files": [], "components": [], "risk": risk, "profile": profile,
            "ui_required": ui, "build_required": False, "hardware_required": False,
            "targeted_tests": list(targeted), "subsystem_tests": list(subsystem),
            "reasons": [], "warnings": [], "blocked": blocked,
            "blocked_reason": "тест" if blocked else None, "plan": []}


def steps_for(s):
    return rp.build_steps(s, REGISTRY, CATALOG, sel, NODE)


def pick(cap):
    """Реальный тест из каталога с указанной способностью."""
    for t in sorted(CATALOG.values(), key=lambda x: x["path"]):
        if t.get(cap) and t["path"].endswith(".py"):
            return t["path"]
    return None


def safe_test():
    for t in sorted(CATALOG.values(), key=lambda x: x["path"]):
        if t["safe_for_targeted"] and t["path"].endswith(".py"):
            return t["path"]
    return None


try:
    # ── 1. План против выполнения ────────────────────────────────────────────
    sec("1. Планирование и выполнение раздельны")

    calls = [0]
    real_run_step = rp.run_step

    def counting(argv, timeout_seconds, cwd=None):
        calls[0] += 1
        return {"outcome": "pass", "returncode": 0, "stdout": "", "stderr": "",
                "duration_seconds": 0.0}

    rp.run_step = counting
    res, _, _ = rp.run([DOC], execute=False, strict_catalog=False)
    check("1. по умолчанию статус DRY_RUN", res["status"] == "DRY_RUN", res["status"])
    check("2. dry-run не запустил ни одного процесса", calls[0] == 0, calls[0])
    check("2b. dry-run не создал артефактов", res["artifacts_path"] is None)

    calls[0] = 0
    res, _, _ = rp.run([DOC], execute=True, strict_catalog=False, artifacts=False)
    check("3. с --execute шаги действительно выполняются", calls[0] >= 1, calls[0])
    rp.run_step = real_run_step

    check("35. DRY_RUN не равен PASS и не имеет выполненных шагов",
          rp.DRY_RUN != rp.PASS and rp.EXIT[rp.DRY_RUN] == 0)

    # ── 2. Никакой оболочки и никаких произвольных команд ────────────────────
    sec("2. Команды нельзя подменить")

    SRC_TXT = io.open(RP_PATH, encoding="utf-8").read()
    SRC = ast.parse(SRC_TXT)
    shell_true, popen_calls = [], []
    for node in ast.walk(SRC):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == "subprocess":
            popen_calls.append(f.attr)
        for kw in node.keywords:
            if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant)
                                          and kw.value.value is False):
                shell_true.append(ast.dump(kw.value)[:60])
    check("4. shell=True не используется нигде в исполнителе", not shell_true, shell_true)
    check("4b. subprocess вызывается только как Popen/run",
          set(popen_calls) <= {"Popen", "run"}, popen_calls)

    bad_reg = os.path.join(TMP, "bad_registry.json")
    io.open(bad_reg, "w", encoding="utf-8").write(json.dumps({
        "schema_version": "3diwell-command-registry-v1",
        "commands": [{"command_id": "evil", "argv": ["{python}", "-c",
                                                     "import os; os.system('dir')"],
                      "allowed_profiles": ["FAST"], "timeout_seconds": 5}]},
        ensure_ascii=False))
    err = None
    try:
        rp.load_registry(bad_reg)
    except rp.ConfigError as e:
        err = str(e)
    check("5. произвольная команда из JSON отклоняется реестром", err is not None, err)

    err = None
    try:
        rp.resolve_argv("no.such.command", DOC, REGISTRY, CATALOG, sel, NODE)
    except rp.ConfigError as e:
        err = str(e)
    check("6. неизвестный command_id отклоняется", err is not None, err)

    for bad_path, label in ((u"../outside/evil.py", "путь наружу"),
                            (u"C:\\Windows\\System32\\cmd.exe", "внешний исполняемый файл")):
        err = None
        try:
            rp.resolve_argv("fast.py_compile", bad_path, REGISTRY, CATALOG, sel, NODE)
        except Exception as e:
            err = str(e)
        check("%s. %s блокируется" % (7 if "outside" in bad_path else 8, label),
              err is not None, err)

    err = None
    try:
        rp.resolve_argv("fast.py_compile", DOC, REGISTRY, CATALOG, sel, NODE)
    except rp.ConfigError as e:
        err = str(e)
    check("8b. чужое расширение для команды отклоняется", err is not None, err)

    check("40. негативный самотест: детектор литералов ловит опасный аргумент",
          not rp.SAFE_LITERAL.match("os.system('dir')")
          and not rp.SAFE_LITERAL.match("a && b")
          and not rp.SAFE_LITERAL.match("x > y")
          and bool(rp.SAFE_LITERAL.match("py_compile")))

    neg = ast.parse("import subprocess\nsubprocess.run(['x'], shell=True)\n")
    found = [1 for n in ast.walk(neg) if isinstance(n, ast.Call)
             for kw in n.keywords if kw.arg == "shell"
             and isinstance(kw.value, ast.Constant) and kw.value.value is True]
    check("40b. негативный самотест: тот же разбор видит shell=True в примере", found == [1])

    # ── 3. FAST ─────────────────────────────────────────────────────────────
    sec("3. FAST — только изменённые файлы")

    st = steps_for(mk("FAST", "R0", changed=["tools/validation/run_profile.py"]))
    ex = [s for s in st if s["kind"] == "execute"]
    check("9. FAST для .py — только py_compile этого файла",
          len(ex) == 1 and ex[0]["argv"][1:] == ["-m", "py_compile",
                                                 "tools/validation/run_profile.py"]
          and ex[0]["argv"][0] == sys.executable, ex and ex[0]["argv"])

    st = steps_for(mk("FAST", "R0", changed=["web/app.js"]))
    ex = [s for s in st if s["kind"] == "execute"]
    if NODE:
        check("10. FAST для .js — только node --check этого файла",
              len(ex) == 1 and ex[0]["argv"][1:] == ["--check", "web/app.js"],
              ex and ex[0]["argv"])
    else:
        check("10. без node шаг откладывается, а не падает",
              not ex and any(s["kind"] == "deferred" for s in st))

    st = steps_for(mk("FAST", "R0", changed=["web/app.css", "web/index.html"]))
    check("10b. css и html откладываются: исполняемой команды нет",
          all(s["kind"] == "deferred" for s in st) and len(st) == 2,
          [(s["id"], s["kind"]) for s in st])

    st = steps_for(mk("FAST", "R0", changed=["tools/validation/risk_map.json"]))
    ex = [s for s in st if s["kind"] == "execute"]
    check("10c. FAST для .json — проверка разбора стандартной библиотекой",
          len(ex) == 1 and ex[0]["command_id"] == "fast.json_check")

    st = steps_for(mk("FAST", "R0", changed=["app/no_such_deleted_file.py"]))
    check("10d. удалённый файл пропускается, а не роняет запуск",
          len(st) == 1 and st[0]["kind"] == "skipped", [(s["id"], s["kind"]) for s in st])

    a = steps_for(mk("FAST", "R0", changed=[u"web/app.js"]))
    b = steps_for(mk("FAST", "R0", changed=[u"web\\app.js"]))
    check("32. windows- и posix-путь дают одинаковый шаг",
          [s["argv"] for s in a] == [s["argv"] for s in b])

    st = steps_for(mk("FAST", "R0", changed=["web/app.js", "web/app.js", "web\\app.js"]))
    check("27. дубликаты не превращаются в два запуска",
          len([s for s in st if s["kind"] == "execute"]) <= 1,
          [s["id"] for s in st])

    # ── 4. TARGETED / SUBSYSTEM и каталог безопасности ──────────────────────
    sec("4. Запускается только доказанно безопасное")

    ST = safe_test()
    check("11a. в каталоге есть хотя бы один безопасный тест", ST is not None)
    st = steps_for(mk("TARGETED", "R1", targeted=[ST]))
    ex = [s for s in st if s["kind"] == "execute"]
    check("11. TARGETED запускает разрешённый безопасный тест",
          len(ex) == 1 and ex[0]["command_id"] == "targeted.python_test"
          and ex[0]["argv"] == [sys.executable, ST], ex and ex[0]["argv"])

    CAPS = (("browser", 12), ("mutation", 13), ("local_server", 14), ("network", 15),
            ("build", 16), ("unknown_capability", 17))
    for cap, num in CAPS:
        p = pick(cap)
        if p is None:
            check("%d. тест со способностью %s откладывается" % (num, cap), True,
                  "в каталоге нет такого теста — проверка неприменима")
            continue
        st = steps_for(mk("TARGETED", "R1", targeted=[p]))
        d = [s for s in st if s["kind"] == "deferred"]
        check("%d. %s-тест не запускается, а откладывается" % (num, cap),
              len(d) == 1 and d[0]["mandatory"] and not [s for s in st
                                                         if s["kind"] == "execute"],
              [(s["id"], s["kind"]) for s in st])

    st = steps_for(mk("TARGETED", "R1", targeted=["tools/test_no_such_file_at_all.py"]))
    check("17b. теста нет в каталоге -> откладывается как недоказуемый",
          [s["kind"] for s in st] == ["deferred"], [(s["id"], s["kind"]) for s in st])

    # ── 5. Статусы ──────────────────────────────────────────────────────────
    sec("5. Статусы и коды возврата")

    unsafe = pick("browser") or pick("network")
    rp.run_step = counting
    calls[0] = 0
    res, _, _ = rp.run([], execute=True, strict_catalog=False, artifacts=False)
    check("28. пустой список изменений -> NO_CHANGES", res["status"] == "NO_CHANGES",
          res["status"])
    rp.run_step = real_run_step

    def run_synth(s, execute=True):
        """Прогнать синтетический результат селектора через тот же исполнитель."""
        saved = sel.select
        sel.select = lambda paths, m: s
        rp_sel = rp._load
        rp._load = lambda name, fn: sel if fn == "select_profile.py" else rp_sel(name, fn)
        try:
            return rp.run(["placeholder"], execute=execute, strict_catalog=False,
                          artifacts=False)
        finally:
            sel.select = saved
            rp._load = rp_sel

    res, _, _ = run_synth(mk("SUBSYSTEM", "R2", changed=[DOC], targeted=[unsafe],
                             subsystem=[unsafe]))
    check("18. SUBSYSTEM с небезопасным обязательным тестом -> PARTIAL",
          res["status"] == "PARTIAL", res["status"])
    check("18b. безопасная часть при этом действительно выполнена",
          res["pass_count"] >= 1, res["pass_count"])

    res, _, _ = run_synth(mk("TARGETED", "R1", changed=[DOC], ui=True))
    check("19. ui_required -> PARTIAL, выше PARTIAL не поднимается",
          res["status"] == "PARTIAL" and res["ui_pending"] is True, res["status"])

    res, _, _ = run_synth(mk("RELEASE", "R3", changed=[DOC]))
    check("20. RELEASE -> BLOCKED", res["status"] == "BLOCKED", res["status"])
    check("36. RELEASE не выполняется даже с --execute",
          not res["executed_steps"] and res["release_pending"] is True)
    check("20b. причина RELEASE названа явно",
          res["blocked_reason"] == "release profile requires explicit future release executor",
          res["blocked_reason"])

    res, _, _ = run_synth(mk("HARDWARE", "R4", changed=[DOC]))
    check("21. HARDWARE -> BLOCKED", res["status"] == "BLOCKED", res["status"])
    check("37. HARDWARE не выполняется даже с --execute",
          not res["executed_steps"] and res["hardware_pending"] is True)
    check("21b. причина HARDWARE названа явно",
          res["blocked_reason"] == "manual hardware verification required",
          res["blocked_reason"])

    check("34. PARTIAL имеет ненулевой код возврата", rp.EXIT["PARTIAL"] == 4)
    check("34b. коды возврата зафиксированы",
          rp.EXIT["PASS"] == 0 and rp.EXIT["FAIL"] == 2 and rp.EXIT["BLOCKED"] == 3
          and rp.EXIT_CONFIG == 5 and rp.EXIT_TIMEOUT == 6)

    # Красный шаг обязан остановить остальные обязательные шаги.
    seq = []

    def failing(argv, timeout_seconds, cwd=None):
        seq.append(argv)
        return {"outcome": "fail", "returncode": 1, "stdout": "", "stderr": "",
                "duration_seconds": 0.0}

    rp.run_step = failing
    res, _, _ = run_synth(mk("FAST", "R0", changed=[DOC, "tools/validation/run_profile.py",
                                                    "tools/validation/risk_map.json"]))
    check("22. первый красный обязательный шаг останавливает остальные",
          res["status"] == "FAIL" and len(seq) == 1 and len(res["skipped_steps"]) >= 2,
          "выполнено %d, пропущено %d" % (len(seq), len(res["skipped_steps"])))

    def timing_out(argv, timeout_seconds, cwd=None):
        return {"outcome": "timeout", "returncode": None, "stdout": "", "stderr": "ТАЙМАУТ",
                "duration_seconds": 1.0}

    rp.run_step = timing_out
    res, _, _ = run_synth(mk("FAST", "R0", changed=[DOC]))
    check("23. таймаут считается красным и попадает в счётчик",
          res["status"] == "FAIL" and res["timeout_count"] == 1, res["status"])

    def exploding(argv, timeout_seconds, cwd=None):
        return {"outcome": "error", "returncode": None, "stdout": "", "stderr": "исключение",
                "duration_seconds": 0.0}

    rp.run_step = exploding
    res, _, _ = run_synth(mk("FAST", "R0", changed=[DOC]))
    check("24. неизвестная ошибка не превращается в PASS",
          res["status"] == "FAIL" and res["pass_count"] == 0, res["status"])
    rp.run_step = real_run_step

    # ── 6. Настоящий запуск процесса — на своих фиктивных скриптах ──────────
    sec("6. Запуск процесса: временные скрипты, не продуктовые тесты")

    ok_py = os.path.join(TMP, "ok.py")
    io.open(ok_py, "w", encoding="utf-8").write(u"print('fake ok')\n")
    r = rp.run_step([sys.executable, ok_py], 30, cwd=TMP)
    check("6a. зелёный скрипт даёт outcome=pass и stdout",
          r["outcome"] == "pass" and "fake ok" in r["stdout"], r["outcome"])

    bad_py = os.path.join(TMP, "bad.py")
    io.open(bad_py, "w", encoding="utf-8").write(u"import sys\nsys.exit(3)\n")
    r = rp.run_step([sys.executable, bad_py], 30, cwd=TMP)
    check("6b. ненулевой код даёт outcome=fail",
          r["outcome"] == "fail" and r["returncode"] == 3, r)

    slow_py = os.path.join(TMP, "slow.py")
    io.open(slow_py, "w", encoding="utf-8").write(u"import time\ntime.sleep(20)\n")
    r = rp.run_step([sys.executable, slow_py], 2, cwd=TMP)
    check("23b. настоящий таймаут завершается сам и помечается timeout",
          r["outcome"] == "timeout" and r["duration_seconds"] < 15, r["outcome"])

    r = rp.run_step([os.path.join(TMP, "no_such_program.exe")], 10, cwd=TMP)
    check("24b. несуществующая программа -> error, не pass", r["outcome"] == "error",
          r["outcome"])

    os.environ["FM_FAKE_SECRET_TOKEN"] = "sekret-value-must-not-leak"
    env = rp.child_env()
    check("26a. секрет не попадает в окружение дочернего процесса",
          "FM_FAKE_SECRET_TOKEN" not in env and "PATH" in env, sorted(env)[:6])

    # ── 7. Артефакты ────────────────────────────────────────────────────────
    sec("7. Артефакты")

    before = set(os.listdir(rp.RUNS_DIR)) if os.path.isdir(rp.RUNS_DIR) else set()
    rp.run([DOC], execute=False, strict_catalog=False)
    after = set(os.listdir(rp.RUNS_DIR)) if os.path.isdir(rp.RUNS_DIR) else set()
    check("39. dry-run не создаёт артефактов", before == after, after - before)

    prod = ["server.py", "web/app.js", "tools/release_gate.py", DOC]
    import hashlib
    h0 = dict((p, hashlib.sha256(io.open(os.path.join(REPO, p), "rb").read()).hexdigest())
              for p in prod)
    res, s_res, steps = rp.run([DOC], execute=True, strict_catalog=False)
    rp.write_artifacts(res, s_res, steps)
    h1 = dict((p, hashlib.sha256(io.open(os.path.join(REPO, p), "rb").read()).hexdigest())
              for p in prod)
    check("38. реальный запуск не изменил ни одного продуктового файла", h0 == h1,
          [p for p in prod if h0[p] != h1[p]])

    art = os.path.join(REPO, res["artifacts_path"])
    for name in ("summary.json", "summary.txt", "selector_result.json",
                 "execution_plan.json", "durations.json", "environment.json"):
        check("25a. артефакт %s создан" % name, os.path.isfile(os.path.join(art, name)))
    outs = [f for f in os.listdir(os.path.join(art, "steps")) if f.endswith(".stdout.txt")]
    errs = [f for f in os.listdir(os.path.join(art, "steps")) if f.endswith(".stderr.txt")]
    check("25. stdout и stderr каждого шага сохранены", len(outs) >= 1 and len(errs) >= 1,
          "%d/%d" % (len(outs), len(errs)))

    envtxt = io.open(os.path.join(art, "environment.json"), encoding="utf-8").read()
    check("26. environment.json не содержит секретов и полного окружения",
          "sekret-value-must-not-leak" not in envtxt
          and "FM_FAKE_SECRET_TOKEN" not in envtxt and len(envtxt) < 4000)

    summary = json.load(io.open(os.path.join(art, "summary.json"), encoding="utf-8"))
    REQ = ("run_id", "started_at", "finished_at", "duration_seconds", "changed_files",
           "risk", "requested_profile", "executed_profile", "status", "executed_steps",
           "skipped_steps", "deferred_steps", "ui_pending", "release_pending",
           "hardware_pending", "pass_count", "fail_count", "timeout_count", "warnings",
           "artifacts_path")
    missing = [k for k in REQ if k not in summary]
    check("33. summary.json содержит все обязательные поля", not missing, missing)
    check("33b. результат сериализуем и статус известен",
          summary["status"] in (rp.PASS, rp.FAIL, rp.PARTIAL, rp.BLOCKED, rp.DRY_RUN,
                                rp.NO_CHANGES), summary["status"])
    os.environ.pop("FM_FAKE_SECRET_TOKEN", None)

    # ── 8. Конфигурация ─────────────────────────────────────────────────────
    sec("8. Повреждённая конфигурация останавливает запуск")

    broken = os.path.join(TMP, "broken.json")
    io.open(broken, "w", encoding="utf-8").write(u'{"schema_version": "x", ')
    for label, fn, num in (("реестр", rp.load_registry, 29), ("каталог", rp.load_catalog, 30)):
        err = None
        try:
            fn(broken)
        except rp.ConfigError as e:
            err = str(e)
        check("%d. повреждённый %s блокирует запуск" % (num, label), err is not None, err)

    stale = os.path.join(TMP, "stale_catalog.json")
    real_cat = json.load(io.open(os.path.join(VALDIR, "test_catalog.json"),
                                 encoding="utf-8"))
    shrunk = copy.deepcopy(real_cat)
    shrunk["tests"] = shrunk["tests"][:-1]
    io.open(stale, "w", encoding="utf-8").write(json.dumps(shrunk, ensure_ascii=False))
    err = None
    try:
        rp.load_catalog(stale, strict=True)
    except rp.ConfigError as e:
        err = str(e)
    check("31. устаревший каталог блокирует запуск", err is not None and "устарел" in (err or ""),
          err)
    check("31b. тот же каталог без строгой сверки читается (сверка — отдельное решение)",
          isinstance(rp.load_catalog(stale, strict=False), dict))

    # ── 9. Контракт CLI ─────────────────────────────────────────────────────
    sec("9. Коды возврата CLI")

    def cli(args):
        p = subprocess.run([sys.executable, RP_PATH] + args, cwd=REPO, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return p.returncode, p.stdout, p.stderr

    rc, out, _ = cli(["--files", DOC, "--json"])
    check("1b. CLI по умолчанию -> DRY_RUN и rc=0",
          rc == 0 and json.loads(out)["status"] == "DRY_RUN", "rc=%d" % rc)

    rc, out, _ = cli(["--files", "app/project_orchestrator.py", "--execute", "--json"])
    d = json.loads(out)
    check("21c. CLI: печать/железо -> BLOCKED, rc=3, ничего не выполнено",
          rc == 3 and d["status"] == "BLOCKED" and not d["executed_steps"], "rc=%d" % rc)

    rc, out, _ = cli(["--files", "web/app.css", "--execute", "--json"])
    check("19b. CLI: ui_required -> PARTIAL, rc=4",
          rc == 4 and json.loads(out)["status"] == "PARTIAL", "rc=%d" % rc)

    rc, _, _ = cli(["--files", DOC, "--registry", broken])
    check("29b. CLI с повреждённым реестром -> rc=5", rc == 5, "rc=%d" % rc)

    rc, _, _ = cli([])
    check("29c. CLI без источника изменений -> rc=5", rc == 5, "rc=%d" % rc)

    # ── 10. UI-гейт (этап 3D) ────────────────────────────────────────────────
    sec("10. UI-гейт: закрывается только доказательствами")

    def sel_stub(**over):
        base = {"ui_required": True, "ui_qualification_status": "VALID",
                "ui_coverage_status": "COVERED",
                "required_ui_scenarios": ["settings_panel_open_close",
                                          "settings_panel_open_close_isolated"],
                "ui_coverage_units": ["settings_panel_shell"], "uncovered_ui_hunks": []}
        base.update(over)
        return base

    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(ui_required=False), True)
    check("100. изменение без UI -> UI_NOT_REQUIRED", st_ == rp.UI_NOT_REQUIRED, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(), False)
    check("101. без --with-ui UI не запускается",
          st_ == rp.UI_NOT_REQUESTED and not sc_, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(ui_qualification_status="STALE_TOOLING"),
                                       True)
    check("102. устаревшая квалификация -> UI не запускается",
          st_ == rp.UI_QUALIFICATION_STALE and not sc_, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(ui_coverage_status="UNKNOWN"), True)
    check("103. неизвестное покрытие -> UI не запускается",
          st_ == rp.UI_COVERAGE_UNKNOWN and not sc_, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(ui_coverage_status="PARTIALLY_COVERED"),
                                       True)
    check("104. частичное покрытие -> UI не запускается",
          st_ == rp.UI_PARTIALLY_COVERED and not sc_, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(ui_coverage_status="UNCOVERED"), True)
    check("105. непокрытое изменение -> UI не запускается",
          st_ == rp.UI_UNCOVERED and not sc_, st_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(), True)
    check("106. покрыто и квалифицировано -> ровно два сценария, static первым",
          st_ == rp.UI_RUNNING and sc_ == ["settings_panel_open_close",
                                           "settings_panel_open_close_isolated"], sc_)
    st_, sc_, why_ = rp.ui_gate_decide(sel_stub(required_ui_scenarios=[]), True)
    check("107. карта не назвала сценариев -> UI не запускается",
          st_ == rp.UI_COVERAGE_UNKNOWN, st_)

    opts = [n.args[0].value for n in ast.walk(SRC)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_argument" and n.args
            and isinstance(n.args[0], ast.Constant)]
    check("108. сценарий нельзя выбрать аргументом командной строки",
          not any(o in ("--ui-scenario", "--scenario", "--url", "--ui-url")
                  for o in opts), opts)
    check("109. пользователь не может передать URL исполнителю",
          not any("url" in (o or "").lower() for o in opts), opts)

    calls = []
    FAKE = {"fail_static": False, "fail_isolated": False, "console": 0, "external": 0,
            "blocked": 0, "cleanup": "clean", "port": True, "remaining": []}

    def fake_ui(cmd, **kw):
        sid = cmd[cmd.index("--scenario") + 1]
        calls.append(sid)
        iso = sid.endswith("_isolated")
        ok = not (iso and FAKE["fail_isolated"]) and not (not iso and FAKE["fail_static"])
        out = {"status": "PASS" if ok else "FAIL", "run_id": "r-" + sid,
               "application_mode": "isolated_farm_manager" if iso else "static_harness",
               "artifacts_path": "logs/ui_runs/r-" + sid, "duration_seconds": 1.0,
               "console_error_count": FAKE["console"],
               "external_network_attempt_count": FAKE["external"],
               "blocked_network_attempts": FAKE["blocked"],
               "cleanup_status": FAKE["cleanup"], "port_released": FAKE["port"],
               "remaining_owned_processes": FAKE["remaining"]}

        class R(object):
            returncode = 0 if ok else 2
            stdout = json.dumps(out)
            stderr = ""
        return R()

    real_sub = rp.subprocess.run
    rp.subprocess.run = fake_ui
    try:
        two = ["settings_panel_open_close", "settings_panel_open_close_isolated"]
        calls[:] = []
        res_, ok_ = rp.run_ui_scenarios(two)
        check("110. оба сценария зелёные -> UI-гейт зелёный", ok_ and calls == two, calls)
        check("111. прогоны последовательны и имеют разные run-id",
              len(set(r["run_id"] for r in res_)) == 2)

        FAKE["fail_static"] = True
        calls[:] = []
        res_, ok_ = rp.run_ui_scenarios(two)
        check("112. красный static останавливает isolated",
              not ok_ and calls == two[:1] and res_[1]["status"] == "SKIPPED",
              (calls, res_[1]["status"]))
        FAKE["fail_static"] = False

        FAKE["fail_isolated"] = True
        calls[:] = []
        res_, ok_ = rp.run_ui_scenarios(two)
        check("113. красный isolated делает UI-гейт красным", not ok_ and calls == two)
        FAKE["fail_isolated"] = False

        DEF = {"console": 0, "external": 0, "blocked": 0, "cleanup": "clean",
               "port": True, "remaining": []}
        for num, key, val, label in ((114, "console", 1, "ошибка консоли"),
                                     (115, "external", 1, "внешний запрос браузера"),
                                     (116, "blocked", 1, "заблокированное обращение"),
                                     (117, "cleanup", "dirty", "грязная уборка"),
                                     (118, "port", False, "порт не освобождён"),
                                     (119, "remaining", [{"pid": 1}],
                                      "остаточный процесс")):
            FAKE[key] = val
            _, ok_ = rp.run_ui_scenarios(two)
            check("%d. %s -> UI-гейт красный" % (num, label), not ok_)
            FAKE[key] = DEF[key]

        calls[:] = []
        res_, ok_ = rp.run_ui_scenarios(two)
        check("120. автоматических повторов нет: ровно два запуска",
              len(calls) == 2 and calls == two, calls)
    finally:
        rp.subprocess.run = real_sub

    check("121. UI закрывает только признак ui_required",
          "ui_pending" in SRC_TXT and "закрывается ТОЛЬКО настоящим зелёным" in SRC_TXT)
    check("122. RELEASE и HARDWARE остаются недоступными для выполнения",
          rp.NEVER_EXECUTE == ("RELEASE", "HARDWARE"))
    check("123. в артефакты пишутся ссылки, а не копии снимков",
          "ui_results.json" in SRC_TXT and "снимки не копируются" in SRC_TXT)
    check("124. все UI-подстатусы объявлены",
          set([rp.UI_NOT_REQUIRED, rp.UI_NOT_REQUESTED, rp.UI_QUALIFICATION_STALE,
               rp.UI_COVERAGE_UNKNOWN, rp.UI_UNCOVERED, rp.UI_PARTIALLY_COVERED,
               rp.UI_RUNNING, rp.UI_PASS, rp.UI_FAIL]) ==
          set(["UI_NOT_REQUIRED", "UI_NOT_REQUESTED", "UI_QUALIFICATION_STALE",
               "UI_COVERAGE_UNKNOWN", "UI_UNCOVERED", "UI_PARTIALLY_COVERED",
               "UI_RUNNING", "UI_PASS", "UI_FAIL"]))
    check("125. smoke имеет отдельные статусы и не равен общему PASS",
          rp.UI_SMOKE_PASS == "UI_INTEGRATION_SMOKE_PASS"
          and rp.UI_SMOKE_FAIL == "UI_INTEGRATION_SMOKE_FAIL"
          and rp.UI_SMOKE_PASS != rp.PASS)
    check("126. smoke не принимает путей, сценариев и URL",
          "SMOKE_SCENARIOS" in SRC_TXT
          and "ns.ui_maintenance_smoke else selector.collect(ns)" in SRC_TXT)

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
