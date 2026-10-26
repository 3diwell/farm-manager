# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 2B: безопасный исполнитель профиля проверки.

РАЗДЕЛЕНИЕ. Планирование и выполнение остаются раздельными. Что проверять — решает
`select_profile.py`; здесь эта логика НЕ повторяется, селектор вызывается как модуль.
Исполнитель отвечает только на второй вопрос: что из запланированного разрешено запустить.

ЧТО ЗАПУСКАЕТ. Только FAST и доказанно безопасные TARGETED/SUBSYSTEM-тесты.
RELEASE, HARDWARE, браузер, mutation proof, сборку, установщик и что-либо, связанное
с реальными принтерами, не запускает никогда — даже с `--execute`.

КАК ЗАЩИЩЁН. Строка `command` из плана не исполняется. Исполнитель берёт command_id из
`command_registry.json`, подставляет проверенный путь в argv-МАССИВ и запускает его без
оболочки: `shell=True` не используется, поэтому пайпы, `&&`, `>` и подстановки невозможны
в принципе. Программа (argv[0]) всегда своя — интерпретатор или найденный node; из ввода
она не берётся никогда.

    python tools/validation/run_profile.py --files web/app.css        # dry-run
    python tools/validation/run_profile.py --working-tree --execute
    python tools/validation/run_profile.py --files a.py --json

Статусы: PASS · FAIL · BLOCKED · PARTIAL · DRY_RUN · NO_CHANGES.
Коды: 0 PASS/NO_CHANGES/DRY_RUN · 2 FAIL · 3 BLOCKED · 4 PARTIAL · 5 конфигурация · 6 таймаут.
"""
import argparse
import datetime
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALDIR = os.path.join(REPO, "tools", "validation")
RUNS_DIR = os.path.join(REPO, "logs", "validation_runs")

SCHEMA = "3diwell-profile-run-v1"
REGISTRY_SCHEMA = "3diwell-command-registry-v1"
CATALOG_SCHEMA = "3diwell-test-catalog-v1"

PASS, FAIL, BLOCKED, PARTIAL, DRY_RUN, NO_CHANGES = (
    "PASS", "FAIL", "BLOCKED", "PARTIAL", "DRY_RUN", "NO_CHANGES")
EXIT = {PASS: 0, NO_CHANGES: 0, DRY_RUN: 0, FAIL: 2, BLOCKED: 3, PARTIAL: 4}
EXIT_CONFIG, EXIT_TIMEOUT = 5, 6

# Профили, которые исполнителю запрещено выполнять на этом этапе — жёстко, а не по данным.
NEVER_EXECUTE = ("RELEASE", "HARDWARE")

# Литерал argv допускается только из этого алфавита: ни пробела, ни кавычки, ни
# метасимвола оболочки сюда не попадёт, даже если реестр кто-то отредактирует.
SAFE_LITERAL = re.compile(r"^[A-Za-z0-9._/\-]+$")

# Переменные окружения, которые передаются дочернему процессу. Всё остальное отбрасывается:
# так в артефакты физически не может попасть токен, ключ или личный путь владельца.
ENV_ALLOW = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "COMSPEC",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL")

FAST_BY_EXT = {".py": "fast.py_compile", ".js": "fast.node_check", ".mjs": "fast.node_check",
               ".json": "fast.json_check", ".md": "fast.doc_check"}
# Расширения, для которых проверка нужна, но исполняемой команды в реестре нет.
DEFER_BY_EXT = {
    ".css": "баланс скобок в CSS: команды в реестре нет, файл читается только через "
            "surrogateescape — см. docs/validation/frontend.md",
    ".html": "баланс тегов шаблона: команды в реестре нет — см. docs/validation/frontend.md",
}


class ConfigError(Exception):
    """Неверная конфигурация или ввод: запуск не начинается вовсе."""


# ── Загрузка соседних модулей ────────────────────────────────────────────────
def _load(name, filename):
    path = os.path.join(VALDIR, filename)
    if not os.path.isfile(path):
        raise ConfigError("нет обязательного модуля: %s" % path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_registry(path=None):
    p = path or os.path.join(VALDIR, "command_registry.json")
    if not os.path.isfile(p):
        raise ConfigError("реестр команд не найден: %s" % p)
    try:
        data = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        raise ConfigError("реестр команд не читается: %s" % e)
    if not isinstance(data, dict) or data.get("schema_version") != REGISTRY_SCHEMA:
        raise ConfigError("несовместимая схема реестра команд")
    cmds = {}
    for c in data.get("commands", []):
        for k in ("command_id", "argv", "allowed_profiles", "timeout_seconds"):
            if k not in c:
                raise ConfigError("команда %r без поля %r" % (c.get("command_id"), k))
        if not isinstance(c["argv"], list) or not c["argv"]:
            raise ConfigError("команда %r: argv должен быть непустым массивом"
                              % c["command_id"])
        for tok in c["argv"]:
            if not isinstance(tok, str):
                raise ConfigError("команда %r: аргумент не строка" % c["command_id"])
            if tok.startswith("{") and tok.endswith("}"):
                continue
            if not SAFE_LITERAL.match(tok):
                raise ConfigError("команда %r: недопустимый аргумент %r "
                                  "(пробелы и метасимволы оболочки запрещены)"
                                  % (c["command_id"], tok))
        cmds[c["command_id"]] = c
    if not cmds:
        raise ConfigError("реестр команд пуст")
    return cmds


def load_catalog(path=None, strict=True):
    p = path or os.path.join(VALDIR, "test_catalog.json")
    if not os.path.isfile(p):
        raise ConfigError("каталог тестов не найден: %s" % p)
    try:
        data = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        raise ConfigError("каталог тестов не читается: %s" % e)
    if not isinstance(data, dict) or data.get("schema_version") != CATALOG_SCHEMA:
        raise ConfigError("несовместимая схема каталога тестов")
    if strict:
        builder = _load("fm_build_test_catalog", "build_test_catalog.py")
        diffs, _ = builder.freshness(p)
        if diffs:
            raise ConfigError("каталог тестов устарел (%d расхождений, первое: %s). "
                              "Перестроить: python tools/validation/"
                              "build_test_catalog.py --write" % (len(diffs), diffs[0]))
    return dict((t["path"], t) for t in data.get("tests", []) if isinstance(t, dict))


# ── Проверка подставляемых значений ──────────────────────────────────────────
def validate_param(value, cmd, catalog, selector):
    """Путь, который попадёт в argv. Любое сомнение — отказ, а не догадка."""
    rel = selector.normalize(value)                     # Win/POSIX -> один вид, `..` отсечён
    full = os.path.realpath(os.path.join(REPO, rel))
    root = os.path.realpath(REPO)
    if not (full == root or full.startswith(root + os.sep)):
        raise ConfigError("путь вне репозитория: %s" % value)
    if not os.path.isfile(full):
        raise ConfigError("файл не существует: %s" % rel)
    exts = cmd.get("param_extensions") or []
    if exts and os.path.splitext(rel)[1].lower() not in exts:
        raise ConfigError("расширение %s не разрешено для команды %s"
                          % (os.path.splitext(rel)[1], cmd["command_id"]))
    flag = cmd.get("requires_catalog_flag")
    if flag:
        entry = catalog.get(rel)
        if entry is None:
            raise ConfigError("тест %s отсутствует в каталоге безопасности" % rel)
        if not entry.get(flag):
            raise ConfigError("тест %s не признан безопасным (%s)"
                              % (rel, ", ".join(entry.get("reasons") or ["без причины"])))
    return rel


def resolve_argv(command_id, value, registry, catalog, selector, node_path=None):
    """command_id + одно проверенное значение -> готовый argv-массив.

    Единственный путь, которым команда может стать исполняемой. Строка из плана,
    JSON или ввода сюда не попадает.
    """
    cmd = registry.get(command_id)
    if cmd is None:
        raise ConfigError("неизвестная команда: %r" % command_id)
    rel = validate_param(value, cmd, catalog, selector) if value is not None else None
    argv = []
    for tok in cmd["argv"]:
        if tok == "{python}":
            argv.append(sys.executable)
        elif tok == "{node}":
            if not node_path:
                raise ConfigError("node не найден: команда %s недоступна" % command_id)
            argv.append(node_path)
        elif tok in ("{file}", "{test}"):
            if rel is None:
                raise ConfigError("команда %s требует параметр" % command_id)
            argv.append(rel)
        elif tok.startswith("{") and tok.endswith("}"):
            raise ConfigError("неизвестная подстановка %r в команде %s" % (tok, command_id))
        else:
            if not SAFE_LITERAL.match(tok):
                raise ConfigError("недопустимый литерал %r в команде %s" % (tok, command_id))
            argv.append(tok)
    return argv, cmd


def find_node():
    p = shutil.which("node")
    if p:
        return p
    for cand in (r"C:\Program Files\nodejs\node.exe",
                 r"C:\Program Files (x86)\nodejs\node.exe"):
        if os.path.isfile(cand):
            return cand
    return None


def child_env():
    env = dict((k, os.environ[k]) for k in ENV_ALLOW if k in os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ── Выполнение одного шага ───────────────────────────────────────────────────
def _kill_tree(proc):
    """Только собственный процесс и его дети, только по PID. Убийство по имени запрещено:
    оно снесло бы браузер и рабочие процессы владельца."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, shell=False, timeout=20)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_step(argv, timeout_seconds, cwd=None):
    """Запустить argv БЕЗ оболочки. Возвращает словарь результата.

    Ни при каких обстоятельствах не возвращает «зелено» по исключению: неизвестная
    ошибка — это красный результат, а не отсутствие результата.
    """
    kw = dict(cwd=cwd or REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
              shell=False, env=child_env())
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True

    started = time.time()
    out = err = ""
    try:
        proc = subprocess.Popen(argv, **kw)
    except Exception as e:
        return {"outcome": "error", "returncode": None, "stdout": "",
                "stderr": "процесс не запущен: %s" % e,
                "duration_seconds": round(time.time() - started, 3)}
    try:
        raw_o, raw_e = proc.communicate(timeout=timeout_seconds)
        out = (raw_o or b"").decode("utf-8", "replace")
        err = (raw_e or b"").decode("utf-8", "replace")
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            raw_o, raw_e = proc.communicate(timeout=10)
            out = (raw_o or b"").decode("utf-8", "replace")
            err = (raw_e or b"").decode("utf-8", "replace")
        except Exception:
            pass
        return {"outcome": "timeout", "returncode": None, "stdout": out,
                "stderr": err + "\nТАЙМАУТ: превышен бюджет %d c" % timeout_seconds,
                "duration_seconds": round(time.time() - started, 3)}
    except Exception as e:
        _kill_tree(proc)
        return {"outcome": "error", "returncode": None, "stdout": out,
                "stderr": "%s\nисключение при выполнении: %s" % (err, e),
                "duration_seconds": round(time.time() - started, 3)}

    if rc == 0:
        outcome = "pass"
    elif isinstance(rc, int):
        outcome = "fail"
    else:
        outcome = "error"
    return {"outcome": outcome, "returncode": rc, "stdout": out, "stderr": err,
            "duration_seconds": round(time.time() - started, 3)}


# ── Построение шагов из СТРУКТУРЫ результата селектора ───────────────────────
def build_steps(sel_result, registry, catalog, selector, node_path):
    """Шаги строятся из полей changed_files / targeted_tests / subsystem_tests,
    а не из строк `command` в плане селектора: исполняемое не берётся из текста."""
    profile = sel_result["profile"]
    steps, seen = [], set()

    def add(sid, kind, profile_of_step, mandatory, reason, command_id=None, value=None,
            argv=None, timeout=60):
        key = (command_id, value) if command_id else ("_", sid)
        if key in seen:
            return
        seen.add(key)
        steps.append({"id": sid, "kind": kind, "profile": profile_of_step,
                      "mandatory": bool(mandatory), "reason": reason,
                      "command_id": command_id, "value": value, "argv": argv,
                      "timeout_seconds": timeout})

    # FAST — по изменённым файлам. Путь нормализуется здесь ещё раз: build_steps не
    # полагается на то, что вход уже прошёл селектор.
    for raw in sel_result["changed_files"]:
        try:
            rel = selector.normalize(raw)
        except Exception as e:
            add("fast:badpath:%s" % raw, "skipped", "FAST", False,
                "путь не поддаётся нормализации: %s" % e)
            continue
        ext = os.path.splitext(rel)[1].lower()
        if not os.path.isfile(os.path.join(REPO, rel)):
            add("fast:missing:%s" % rel, "skipped", "FAST", False,
                "файл отсутствует на диске (удалён или переименован) — синтаксис не проверяется")
            continue
        if ext in DEFER_BY_EXT:
            add("fast:defer:%s" % rel, "deferred", "FAST", False, DEFER_BY_EXT[ext])
            continue
        cid = FAST_BY_EXT.get(ext)
        if not cid:
            continue
        try:
            argv, cmd = resolve_argv(cid, rel, registry, catalog, selector, node_path)
        except ConfigError as e:
            add("fast:blocked:%s" % rel, "deferred", "FAST", False,
                "команда %s недоступна: %s" % (cid, e))
            continue
        add("fast:%s:%s" % (cid.split(".")[1], rel), "execute", "FAST", True,
            "синтаксическая или структурная проверка изменённого файла",
            cid, rel, argv, cmd["timeout_seconds"])

    if profile in NEVER_EXECUTE or sel_result["blocked"]:
        return steps

    def add_test(rel, cid_py, cid_mjs, step_profile):
        ext = os.path.splitext(rel)[1].lower()
        cid = cid_mjs if ext == ".mjs" else cid_py
        entry = catalog.get(rel)
        if entry is None:
            add("test:unknown:%s" % rel, "deferred", step_profile, True,
                "теста нет в каталоге безопасности — доказать безопасность нечем")
            return
        try:
            argv, cmd = resolve_argv(cid, rel, registry, catalog, selector, node_path)
        except ConfigError as e:
            add("test:defer:%s" % rel, "deferred", step_profile, True, str(e))
            return
        add("test:%s" % rel, "execute", step_profile, True,
            "тест признан безопасным: %s" % (", ".join(entry.get("components") or []) or "-"),
            cid, rel, argv, min(cmd["timeout_seconds"], entry.get("expected_max_seconds", 120)))

    if profile in ("TARGETED", "SUBSYSTEM"):
        for rel in sel_result["targeted_tests"]:
            add_test(rel, "targeted.python_test", "targeted.node_test", "TARGETED")
    if profile == "SUBSYSTEM":
        for rel in sel_result["subsystem_tests"]:
            add_test(rel, "subsystem.python_test", "targeted.node_test", "SUBSYSTEM")

    if sel_result["ui_required"]:
        add("ui:visual", "deferred", "TARGETED", True,
            "затронут интерфейс: браузер и UI harness исполнителю запрещены — "
            "проверяет человек, см. docs/validation/frontend.md")
    return steps


# ── Главный сценарий ─────────────────────────────────────────────────────────
def run(paths_source, execute=False, registry_path=None, catalog_path=None,
        map_path=None, strict_catalog=True, artifacts=True, with_ui=False,
        diff_mode=None, base=None, smoke=False):
    selector = _load("fm_select_profile", "select_profile.py")
    risk_map = selector.load_map(map_path)
    registry = load_registry(registry_path)
    catalog = load_catalog(catalog_path, strict=strict_catalog)
    node_path = find_node()

    sel = selector.select(paths_source, risk_map)
    if hasattr(selector, "augment_ui"):
        sel = selector.augment_ui(sel, diff_mode=diff_mode, base=base)
    started = datetime.datetime.now()
    run_id = started.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    root = RUNS_DIR

    res = {
        "schema_version": SCHEMA, "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None, "duration_seconds": 0.0,
        "changed_files": sel["changed_files"], "risk": sel["risk"],
        "requested_profile": sel["profile"], "executed_profile": None,
        "status": None, "executed_steps": [], "skipped_steps": [], "deferred_steps": [],
        "ui_pending": bool(sel["ui_required"]), "release_pending": False,
        "hardware_pending": False, "pass_count": 0, "fail_count": 0, "timeout_count": 0,
        "warnings": list(sel["warnings"]), "artifacts_path": None,
        "blocked_reason": sel["blocked_reason"],
        # ── UI-гейт (этап 3D) ──────────────────────────────────────────────────
        "ui_requested": bool(with_ui or smoke),
        "ui_qualification_status": sel.get("ui_qualification_status"),
        "ui_coverage_status": sel.get("ui_coverage_status"),
        "ui_coverage_units": sel.get("ui_coverage_units") or [],
        "ui_required_scenarios": [], "ui_executed_scenarios": [],
        "ui_passed_scenarios": [], "ui_failed_scenarios": [],
        "ui_uncovered_hunks": sel.get("uncovered_ui_hunks") or [],
        "ui_status": None, "ui_artifact_paths": [],
    }

    if smoke:
        return _ui_maintenance_smoke(res, sel, execute, run_dir_root=root)

    if not sel["changed_files"] and not sel["blocked"]:
        res.update(status=NO_CHANGES, executed_profile="NONE",
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        return res, sel, []

    steps = build_steps(sel, registry, catalog, selector, node_path)
    res["skipped_steps"] = [s for s in steps if s["kind"] == "skipped"]
    res["deferred_steps"] = [s for s in steps if s["kind"] == "deferred"]

    # RELEASE и HARDWARE не выполняются НИКОГДА — проверка стоит выше ветки --execute.
    if sel["profile"] == "RELEASE" or sel["profile"] == "HARDWARE" or sel["blocked"]:
        if sel["profile"] == "RELEASE":
            res["release_pending"] = True
            res["blocked_reason"] = ("release profile requires explicit future release "
                                     "executor")
            res["deferred_steps"].append(
                {"id": "release:gate", "kind": "deferred", "profile": "RELEASE",
                 "mandatory": True, "command_id": None, "value": None, "argv": None,
                 "timeout_seconds": 0,
                 "reason": "полный набор запускает человек: python tools/release_gate.py"})
        if sel["profile"] == "HARDWARE":
            res["release_pending"] = True
            res["hardware_pending"] = True
            res["blocked_reason"] = "manual hardware verification required"
            res["deferred_steps"].append(
                {"id": "hardware:manual", "kind": "deferred", "profile": "HARDWARE",
                 "mandatory": True, "command_id": None, "value": None, "argv": None,
                 "timeout_seconds": 0,
                 "reason": "подтверждение на реальном принтере: только владелец на ферме"})
        res.update(status=BLOCKED, executed_profile="NONE",
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        return res, sel, steps

    runnable = [s for s in steps if s["kind"] == "execute"]
    res["planned_steps"] = [{"id": s["id"], "command_id": s["command_id"],
                             "argv": s["argv"], "profile": s["profile"],
                             "mandatory": s["mandatory"]} for s in runnable]
    if not execute:
        # План показывает, ЧТО было бы запущено, но не запускает ничего.
        ui_st, ui_sc, ui_why = ui_gate_decide(sel, res.get("ui_requested"))
        res["ui_status"] = ui_st
        res["ui_required_scenarios"] = list(ui_sc)
        if ui_why:
            res["warnings"].append("UI: %s" % ui_why)
        res.update(status=DRY_RUN, executed_profile="NONE",
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        return res, sel, steps

    t0 = time.time()
    art = os.path.join(RUNS_DIR, run_id) if artifacts else None
    if art:
        os.makedirs(os.path.join(art, "steps"), exist_ok=True)
        res["artifacts_path"] = os.path.relpath(art, REPO).replace("\\", "/")

    stopped = False
    for i, s in enumerate(runnable):
        if stopped:
            s2 = dict(s, kind="skipped",
                      reason="пропущен: предыдущая обязательная проверка красная")
            res["skipped_steps"].append(s2)
            continue
        r = run_step(s["argv"], s["timeout_seconds"])
        rec = {"id": s["id"], "command_id": s["command_id"], "value": s["value"],
               "argv": s["argv"], "profile": s["profile"], "mandatory": s["mandatory"],
               "outcome": r["outcome"], "returncode": r["returncode"],
               "duration_seconds": r["duration_seconds"]}
        res["executed_steps"].append(rec)
        if art:
            base = os.path.join(art, "steps", "%02d_%s" % (i, re.sub(r"[^A-Za-z0-9._-]", "_",
                                                                    s["id"])[:60]))
            io.open(base + ".stdout.txt", "w", encoding="utf-8",
                    newline="\n").write(r["stdout"])
            io.open(base + ".stderr.txt", "w", encoding="utf-8",
                    newline="\n").write(r["stderr"])
        if r["outcome"] == "pass":
            res["pass_count"] += 1
        elif r["outcome"] == "timeout":
            res["timeout_count"] += 1
            res["fail_count"] += 1
            stopped = s["mandatory"]
        else:
            res["fail_count"] += 1
            stopped = s["mandatory"]

    res["duration_seconds"] = round(time.time() - t0, 3)
    res["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    res["executed_profile"] = sel["profile"]

    # ── UI-гейт: только после обычных шагов и только по доказательствам ─────────
    ui_status, ui_scenarios, ui_reason = ui_gate_decide(sel, res.get("ui_requested"))
    res["ui_required_scenarios"] = list(ui_scenarios)
    if ui_status == UI_RUNNING:
        results, ok = run_ui_scenarios(ui_scenarios)
        res["_ui_results"] = results
        res["ui_executed_scenarios"] = [r["scenario_id"] for r in results
                                        if r.get("status") != "SKIPPED"]
        res["ui_passed_scenarios"] = [r["scenario_id"] for r in results
                                      if r.get("status") == "PASS"
                                      and not r.get("violations")]
        res["ui_failed_scenarios"] = [r["scenario_id"] for r in results
                                      if r.get("status") not in ("PASS", "SKIPPED")
                                      or r.get("violations")]
        res["ui_artifact_paths"] = [r["artifacts_path"] for r in results
                                    if r.get("artifacts_path")]
        ui_status = UI_PASS if ok else UI_FAIL
        if not ok:
            res["warnings"].extend("UI: %s — %s" % (r["scenario_id"],
                                                    "; ".join(r.get("violations") or [])
                                                    or r.get("status"))
                                   for r in results
                                   if r.get("violations") or r.get("status") != "PASS")
    elif ui_reason:
        res["warnings"].append("UI: %s" % ui_reason)
    res["ui_status"] = ui_status
    # ui_pending закрывается ТОЛЬКО настоящим зелёным UI-прогоном.
    if ui_status == UI_PASS:
        res["ui_pending"] = False

    mandatory_deferred = [s for s in res["deferred_steps"] if s.get("mandatory")]
    if res["fail_count"] or ui_status == UI_FAIL:
        res["status"] = FAIL
    elif mandatory_deferred or res["ui_pending"]:
        res["status"] = PARTIAL
    elif not res["executed_steps"]:
        res["status"] = PARTIAL
        res["warnings"].append("ни одна проверка не была применима: зелёным это не считается")
    else:
        res["status"] = PASS
    return res, sel, steps


# ── UI-гейт ──────────────────────────────────────────────────────────────────
# Исполнитель не выбирает сценарии и не принимает их от пользователя: список берётся
# ТОЛЬКО из карты покрытия, и только когда покрыт каждый изменённый участок интерфейса,
# а квалификация оснастки действительна. UI закрывает исключительно признак ui_required
# и не заменяет ни SUBSYSTEM, ни RELEASE, ни HARDWARE, ни проверку на железе.
UI_DIR = os.path.join(VALDIR, "ui")
UI_VERIFIER = os.path.join(UI_DIR, "run_ui_verification.py")

UI_NOT_REQUIRED = "UI_NOT_REQUIRED"
UI_NOT_REQUESTED = "UI_NOT_REQUESTED"
UI_QUALIFICATION_STALE = "UI_QUALIFICATION_STALE"
UI_COVERAGE_UNKNOWN = "UI_COVERAGE_UNKNOWN"
UI_UNCOVERED = "UI_UNCOVERED"
UI_PARTIALLY_COVERED = "UI_PARTIALLY_COVERED"
UI_RUNNING = "UI_RUNNING"
UI_PASS = "UI_PASS"
UI_FAIL = "UI_FAIL"
UI_SMOKE_PASS = "UI_INTEGRATION_SMOKE_PASS"
UI_SMOKE_FAIL = "UI_INTEGRATION_SMOKE_FAIL"

SMOKE_SCENARIOS = ("settings_panel_open_close", "settings_panel_open_close_isolated")


def _ui_module(name):
    import importlib.util
    path = os.path.join(UI_DIR, name)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("fm_x_" + name.split(".")[0], path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod


def ui_gate_decide(sel_result, with_ui):
    """Что делать с UI. Решение принимается ДО запуска и целиком по доказательствам."""
    if not sel_result.get("ui_required"):
        return UI_NOT_REQUIRED, [], "интерфейс изменением не затронут"
    if not with_ui:
        return UI_NOT_REQUESTED, [], "UI-проверка не запрошена (--with-ui)"
    qual = sel_result.get("ui_qualification_status") or "MISSING"
    if qual != "VALID":
        return UI_QUALIFICATION_STALE, [], "квалификация UI-оснастки: %s" % qual
    cov = sel_result.get("ui_coverage_status")
    if cov == "UNKNOWN":
        return UI_COVERAGE_UNKNOWN, [], ("покрытие не доказано: путь без diff "
                                         "доказательством не является")
    if cov == "UNCOVERED":
        return UI_UNCOVERED, [], "ни один изменённый участок интерфейса не покрыт"
    if cov == "PARTIALLY_COVERED":
        return UI_PARTIALLY_COVERED, [], "часть изменённых участков интерфейса не покрыта"
    if cov != "COVERED":
        return UI_COVERAGE_UNKNOWN, [], "покрытие не определено (%s)" % cov
    scenarios = list(sel_result.get("required_ui_scenarios") or [])
    if not scenarios:
        return UI_COVERAGE_UNKNOWN, [], "карта покрытия не назвала ни одного сценария"
    return UI_RUNNING, scenarios, ""


def run_ui_scenarios(scenarios, art_dir=None, timeout_s=900):
    """Строго последовательный запуск. Повторов нет; первый красный останавливает второй."""
    results, failed = [], False
    for sid in scenarios:
        if failed:
            results.append({"scenario_id": sid, "status": "SKIPPED",
                            "reason": "предыдущий сценарий красный — второй не запускается"})
            continue
        pr = subprocess.run([sys.executable, UI_VERIFIER, "--scenario", sid, "--execute",
                             "--json"], cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", shell=False,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                            timeout=timeout_s)
        try:
            summary = json.loads(pr.stdout)
        except Exception:
            results.append({"scenario_id": sid, "status": "NO_RESULT",
                            "reason": (pr.stdout or pr.stderr or "")[:200]})
            failed = True
            continue
        row = {"scenario_id": sid, "status": summary.get("status"),
               "exit_code": pr.returncode, "run_id": summary.get("run_id"),
               "application_mode": summary.get("application_mode"),
               "artifacts_path": summary.get("artifacts_path"),
               "duration_seconds": summary.get("duration_seconds"),
               "console_errors": summary.get("console_error_count"),
               "browser_external": summary.get("external_network_attempt_count"),
               "blocked_network": summary.get("blocked_network_attempts"),
               "cleanup_status": summary.get("cleanup_status"),
               "port_released": summary.get("port_released"),
               "remaining_processes": summary.get("remaining_owned_processes") or []}
        bad = []
        if row["status"] != "PASS":
            bad.append("статус %s" % row["status"])
        if (row["console_errors"] or 0) != 0:
            bad.append("ошибок консоли %s" % row["console_errors"])
        if (row["browser_external"] or 0) != 0:
            bad.append("внешних обращений браузера %s" % row["browser_external"])
        if (row["blocked_network"] or 0) != 0:
            bad.append("заблокированных обращений %s" % row["blocked_network"])
        if row["cleanup_status"] != "clean":
            bad.append("уборка %s" % row["cleanup_status"])
        if row["port_released"] is not True:
            bad.append("порт не освобождён")
        if row["remaining_processes"]:
            bad.append("остались свои процессы")
        row["violations"] = bad
        results.append(row)
        if bad:
            failed = True
    ids = [r.get("run_id") for r in results if r.get("run_id")]
    if len(ids) != len(set(ids)):
        failed = True
        results.append({"scenario_id": "-", "status": "DUPLICATE_RUN_ID",
                        "reason": "повторный run-id: прогоны не независимы"})
    return results, not failed


def _ui_maintenance_smoke(res, sel, execute, run_dir_root):
    """Служебная проверка проводки «исполнитель -> верификатор».

    НЕ является проверкой пользовательской задачи и НИКОГДА не даёт общий PASS: покрытие
    здесь не вычисляется и не симулируется, сценарии жёстко заданы квалифицированной парой.
    """
    res["ui_required_scenarios"] = list(SMOKE_SCENARIOS)
    qual = res.get("ui_qualification_status")
    if qual != "VALID":
        res.update(status=BLOCKED, ui_status=UI_QUALIFICATION_STALE,
                   executed_profile="NONE",
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        res["warnings"].append("квалификация UI-оснастки: %s" % qual)
        return res, sel, None
    if not execute:
        res.update(status=DRY_RUN, ui_status=UI_NOT_REQUESTED, executed_profile="NONE",
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        return res, sel, None

    run_dir = os.path.join(run_dir_root, res["run_id"])
    os.makedirs(run_dir, exist_ok=True)
    res["artifacts_path"] = os.path.relpath(run_dir, REPO).replace("\\", "/")
    t0 = time.time()
    results, ok = run_ui_scenarios(list(SMOKE_SCENARIOS))
    res["ui_executed_scenarios"] = [r["scenario_id"] for r in results
                                    if r.get("status") not in ("SKIPPED",)]
    res["ui_passed_scenarios"] = [r["scenario_id"] for r in results
                                  if r.get("status") == "PASS" and not r.get("violations")]
    res["ui_failed_scenarios"] = [r["scenario_id"] for r in results
                                  if r.get("status") != "PASS" or r.get("violations")]
    res["ui_artifact_paths"] = [r["artifacts_path"] for r in results
                                if r.get("artifacts_path")]
    res["_ui_results"] = results
    res["duration_seconds"] = round(time.time() - t0, 3)
    res["ui_status"] = UI_SMOKE_PASS if ok else UI_SMOKE_FAIL
    # Общим статусом smoke остаётся PARTIAL: он доказывает проводку, а не задачу.
    res.update(status=PARTIAL if ok else FAIL, executed_profile="UI_SMOKE",
               finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
    res["warnings"].append("maintenance smoke доказывает только проводку "
                           "executor -> verifier и НЕ закрывает пользовательскую задачу")
    return res, sel, None


# ── Артефакты и вывод ────────────────────────────────────────────────────────
def write_artifacts(res, sel, steps):
    art = os.path.join(REPO, res["artifacts_path"]) if res.get("artifacts_path") else None
    if not art:
        return
    def w(name, obj):
        io.open(os.path.join(art, name), "w", encoding="utf-8",
                newline="\n").write(json.dumps(obj, ensure_ascii=False, indent=1,
                                               sort_keys=True) + "\n")
    w("summary.json", res)
    w("selector_result.json", sel)
    w("execution_plan.json", steps)
    w("durations.json", dict((s["id"], s["duration_seconds"])
                             for s in res["executed_steps"]))
    if res.get("ui_requested") or res.get("ui_status"):
        vq = _ui_module("verify_qualification.py")
        w("ui_qualification.json", vq.verify() if vq else {"status": "MISSING"})
        w("ui_coverage.json", {"status": res.get("ui_coverage_status"),
                               "units": res.get("ui_coverage_units"),
                               "uncovered_hunks": res.get("ui_uncovered_hunks"),
                               "note": "покрытие считается по содержимому diff, не по пути"})
        w("ui_execution_plan.json", {"required_scenarios": res.get("ui_required_scenarios"),
                                     "sequential": True, "retries": 0,
                                     "note": "сценарии берутся только из карты покрытия"})
        w("ui_results.json", {"results": res.get("_ui_results") or [],
                              "ui_status": res.get("ui_status"),
                              "run_links": res.get("ui_artifact_paths") or [],
                              "note": "снимки не копируются: только относительные ссылки"})
    w("environment.json", {
        "python": sys.version.split()[0], "executable": os.path.basename(sys.executable),
        "platform": sys.platform, "cwd": ".",
        "env_keys_passed_to_children": list(ENV_ALLOW) + ["PYTHONIOENCODING"],
        "note": ("Полное окружение владельца намеренно НЕ сохраняется: дочерние процессы "
                 "получают только перечисленные ключи, поэтому токены, ключи и личные "
                 "пути сюда попасть не могут."),
    })
    io.open(os.path.join(art, "summary.txt"), "w", encoding="utf-8",
            newline="\n").write(render(res) + "\n")


def render(res):
    L = ["=" * 78, "ИСПОЛНЕНИЕ ПРОФИЛЯ ПРОВЕРКИ", "=" * 78,
         "риск: %s   профиль: %s   статус: %s" % (res["risk"], res["requested_profile"],
                                                  res["status"]),
         "файлов изменено: %d" % len(res["changed_files"])]
    if res["status"] == DRY_RUN:
        L.append("НИЧЕГО НЕ ВЫПОЛНЕНО: это план. Для запуска добавьте --execute.")
    if res["blocked_reason"]:
        L.append("причина блокировки: %s" % res["blocked_reason"])
    L.append("")
    if res["executed_steps"]:
        L.append("выполнено (%d):" % len(res["executed_steps"]))
        for s in res["executed_steps"]:
            L.append("   [%-7s] %-52s %.2f c" % (s["outcome"], s["id"][:52],
                                                 s["duration_seconds"]))
    else:
        L.append("выполнено: ничего")
    if res.get("planned_steps") and not res["executed_steps"]:
        L.append("")
        L.append("было бы выполнено (%d) — сейчас НЕ выполнено:" % len(res["planned_steps"]))
        for s in res["planned_steps"]:
            L.append("   [%-9s] %s" % (s["command_id"] or "-", " ".join(
                (os.path.basename(a) if i == 0 else a) for i, a in enumerate(s["argv"] or []))))
    if res["deferred_steps"]:
        L.append("")
        L.append("отложено (%d) — исполнителю запрещено:" % len(res["deferred_steps"]))
        for s in res["deferred_steps"]:
            L.append("   %-52s %s" % (s["id"][:52], ("обязательно"
                                                     if s.get("mandatory") else "не блокирует")))
            L.append("      %s" % s["reason"])
    if res["skipped_steps"]:
        L.append("")
        L.append("пропущено (%d)" % len(res["skipped_steps"]))
    for w in res["warnings"]:
        L.append("   ! %s" % w)
    L.append("")
    if res.get("ui_status"):
        L.append("")
        L.append("UI: %s   покрытие %s   квалификация %s"
                 % (res["ui_status"], res.get("ui_coverage_status"),
                    res.get("ui_qualification_status")))
        if res.get("ui_required_scenarios"):
            L.append("    сценарии: %s" % ", ".join(res["ui_required_scenarios"]))
        for p_ in res.get("ui_artifact_paths") or []:
            L.append("    прогон: %s" % p_)
        for h in (res.get("ui_uncovered_hunks") or [])[:5]:
            L.append("    ! непокрыто: %s @%s — %s"
                     % (h.get("file"), (h.get("new_range") or [0])[0],
                        (h.get("reason") or "")[:70]))
    L.append("зелёных %d · красных %d · таймаутов %d" % (res["pass_count"], res["fail_count"],
                                                         res["timeout_count"]))
    if res["artifacts_path"]:
        L.append("артефакты: %s" % res["artifacts_path"])
    if res["status"] == PARTIAL:
        L.append("PARTIAL — это НЕ зелёный результат: остались обязательные проверки.")
    if res["status"] == BLOCKED:
        L.append("BLOCKED — задача не считается проверенной.")
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Безопасный исполнитель профиля проверки (по умолчанию — только план).")
    ap.add_argument("--files", nargs="+")
    ap.add_argument("--files-from")
    ap.add_argument("--working-tree", action="store_true")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--execute", action="store_true",
                    help="действительно выполнить безопасные шаги (по умолчанию нет)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--registry")
    ap.add_argument("--catalog")
    ap.add_argument("--map")
    ap.add_argument("--allow-stale-catalog", action="store_true",
                    help="служебное: не сверять каталог с состоянием репозитория")
    ap.add_argument("--with-ui", action="store_true",
                    help="выполнить UI-сценарии, если покрытие доказано и оснастка "
                         "квалифицирована; сценарии выбирает карта покрытия, не пользователь")
    ap.add_argument("--ui-maintenance-smoke", action="store_true",
                    help="служебное: доказать проводку executor -> verifier; "
                         "пользовательскую задачу не закрывает никогда")
    ns = ap.parse_args(argv)

    try:
        selector = _load("fm_select_profile", "select_profile.py")
        paths = [] if ns.ui_maintenance_smoke else selector.collect(ns)
        mode = ("working-tree" if ns.working_tree else "staged" if ns.staged
                else "base" if ns.base else None)
        res, sel, steps = run(paths, execute=ns.execute, registry_path=ns.registry,
                              catalog_path=ns.catalog, map_path=ns.map,
                              strict_catalog=not ns.allow_stale_catalog,
                              with_ui=ns.with_ui, diff_mode=mode, base=ns.base,
                              smoke=ns.ui_maintenance_smoke)
    except (ConfigError, Exception) as e:
        if isinstance(e, SystemExit):
            raise
        payload = {"schema_version": SCHEMA, "status": BLOCKED, "error": str(e),
                   "blocked_reason": "конфигурация или ввод не позволяют начать запуск"}
        sys.stderr.write((json.dumps(payload, ensure_ascii=False) if ns.json
                          else "ОШИБКА: %s" % e) + "\n")
        return EXIT_CONFIG

    if (ns.execute or ns.ui_maintenance_smoke) and res.get("artifacts_path"):
        write_artifacts(res, sel, steps)

    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res)) + "\n")
    if res["timeout_count"]:
        return EXIT_TIMEOUT
    return EXIT[res["status"]]


if __name__ == "__main__":
    sys.exit(main())
