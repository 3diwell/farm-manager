# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — СЕРТИФИКАТ КВАЛИФИКАЦИИ UI: что его выдаёт и что его убивает.
#
#  ЗАЧЕМ. Сертификат — единственное, на что опирается автоматический UI-гейт. Если его
#  можно выписать по неполной серии, оставить действующим после правки оснастки или
#  перенести на другое окружение, гейт превращается в самообман.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. НЕ запускает server.py, Edge и UI-сценарии; подпроцессов не создаёт.
#
#  Запуск:  python tools/test_ui_qualification.py       (0 = сертификат строгий)
# ============================================================================
import ast
import copy
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIDIR = os.path.join(REPO, "tools", "validation", "ui")
VQ_PATH = os.path.join(UIDIR, "verify_qualification.py")
CERT = os.path.join(UIDIR, "qualification.json")

PASSED, FAILED = [0], []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name + ((" | " + str(detail)[:200]) if detail else ""))
        print("FAIL — %s%s" % (name, (" | " + str(detail)[:200]) if detail else ""))


def sec(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


sec("0. Оснастка на месте")
check("0a. verify_qualification.py существует", os.path.isfile(VQ_PATH))
check("0b. сертификат существует", os.path.isfile(CERT))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_vq", VQ_PATH)
vq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vq)
BASE = json.load(io.open(CERT, encoding="utf-8"))
TMP = tempfile.mkdtemp(prefix="fm_uiq_")
ENV_OK = dict(BASE["qualified_environment"])


def cert_file(mutate=None, name=None):
    c = copy.deepcopy(BASE)
    if mutate:
        mutate(c)
    p = os.path.join(TMP, (name or "c%d" % len(os.listdir(TMP))) + ".json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(c, ensure_ascii=False))
    return p


try:
    sec("1. Действующий сертификат")

    r = vq.verify(CERT, env=ENV_OK)
    check("1. реальные артефакты этапа 3C дают VALID", r["status"] == "VALID", r)
    check("1b. сертификат выдан по серии QUALIFIED",
          BASE["source_series_status"] == "QUALIFIED")
    check("1c. сертификат называет ровно два квалифицированных сценария",
          BASE["qualified_scenarios"] == ["settings_panel_open_close",
                                          "settings_panel_open_close_isolated"])
    check("1d. сертификат называет единицу покрытия",
          BASE["coverage_units"] == ["settings_panel_shell"])
    check("1e. привязан к отпечатку исходных артефактов",
          len(BASE["source_artifact_digest"]) == 64)

    sec("2. Сертификат нельзя выписать по слабой серии")

    p = cert_file(lambda c: c.update(source_series_status="NOT_QUALIFIED"))
    check("78. серия NOT_QUALIFIED -> сертификат недействителен",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")
    p = cert_file(lambda c: c.update(total_runs=18))
    check("79. неполные 20 прогонов -> недействителен",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")
    p = cert_file(lambda c: c.update(cycles=9))
    check("79b. меньше десяти циклов -> недействителен",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")
    p = cert_file(lambda c: c.update(failed_criteria=[{"id": "x"}]))
    check("80. невыполненные критерии -> недействителен",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")
    p = cert_file(lambda c: c.update(individual_retries=1))
    check("80b. индивидуальные повторы -> недействителен",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")

    sec("3. Повреждение и отсутствие")

    bad = os.path.join(TMP, "broken.json")
    io.open(bad, "w", encoding="utf-8").write('{"schema_version": "x", ')
    check("2b. повреждённый сертификат -> INVALID",
          vq.verify(bad, env=ENV_OK)["status"] == "INVALID")
    check("3. отсутствующий сертификат -> MISSING",
          vq.verify(os.path.join(TMP, "нет.json"), env=ENV_OK)["status"] == "MISSING")
    p = cert_file(lambda c: c.pop("tool_fingerprints"))
    check("2c. сертификат без обязательного поля -> INVALID",
          vq.verify(p, env=ENV_OK)["status"] == "INVALID")
    p = cert_file(lambda c: c.update(schema_version="чужая"))
    check("2d. чужая схема -> INVALID", vq.verify(p, env=ENV_OK)["status"] == "INVALID")

    sec("4. Изменение оснастки убивает квалификацию")

    TOOLS = [("4", "run_ui_verification.py", "tools/validation/ui/run_ui_verification.py"),
             ("5", "_ui_driver.mjs", "tools/validation/ui/_ui_driver.mjs"),
             ("6", "network guard",
              "tools/validation/ui/network_guard/sitecustomize.py"),
             ("6b", "_stage_server.py", "tools/validation/ui/_stage_server.py"),
             ("6c", "анализатор покрытия", "tools/validation/ui/select_ui_coverage.py"),
             ("6d", "карта покрытия", "tools/validation/ui/ui_coverage_map.json")]
    for num, label, rel in TOOLS:
        p = cert_file(lambda c, r=rel: c["tool_fingerprints"].update({r: "0" * 64}))
        res = vq.verify(p, env=ENV_OK)
        check("%s. изменение %s -> STALE_TOOLING" % (num, label),
              res["status"] == "STALE_TOOLING" and rel in res["changed_tools"], res)

    p = cert_file(lambda c: c.update(scenario_registry_fingerprint="0" * 64))
    check("7. изменение реестра сценариев -> STALE_SCENARIOS",
          vq.verify(p, env=ENV_OK)["status"] == "STALE_SCENARIOS")

    check("12. изменение продукта оснастку не устаревает: server.py и web/ не входят "
          "в список отпечатков",
          not any(x.startswith(("server.py", "web/", "app/", "modules/"))
                  for x in BASE["tool_fingerprints"]),
          sorted(BASE["tool_fingerprints"]))

    sec("5. Политика окружения")

    e = dict(ENV_OK, engine_version="151.0.1000.1")
    check("8. мажорная версия движка изменилась -> STALE_ENVIRONMENT",
          vq.verify(CERT, env=e)["status"] == "STALE_ENVIRONMENT")
    major = ENV_OK["engine_version"].split(".")[0]
    e = dict(ENV_OK, engine_version=major + ".0.4078.999")
    r = vq.verify(CERT, env=e)
    check("9. патч движка -> остаётся VALID, но с предупреждением",
          r["status"] == "VALID" and r["warnings"], r)
    e = dict(ENV_OK, python="3.13")
    check("10. другая major.minor Python -> STALE_ENVIRONMENT",
          vq.verify(CERT, env=e)["status"] == "STALE_ENVIRONMENT")
    e = dict(ENV_OK, node_major="22")
    check("11. другая мажорная версия Node -> STALE_ENVIRONMENT",
          vq.verify(CERT, env=e)["status"] == "STALE_ENVIRONMENT")
    e = dict(ENV_OK, windows_build="10.0.22631")
    check("11b. другая сборка Windows -> STALE_ENVIRONMENT",
          vq.verify(CERT, env=e)["status"] == "STALE_ENVIRONMENT")
    check("11c. политика окружения описана в сертификате",
          set(BASE["environment_policy"]) >= {"windows_build", "python", "node",
                                              "engine_major", "engine_patch", "why"})

    sec("6. Два разных понятия разделены")

    check("12b. сертификат прямо говорит, что не аннулируется продуктом",
          any("не отменяют" in x or "не аннулир" in x
              for x in BASE["not_invalidated_by"]), BASE["not_invalidated_by"])
    check("12c. сертификат перечисляет, что его аннулирует",
          len(BASE["invalidated_by"]) >= 6)
    check("12d. ограничения названы прямо",
          any("ИНСТРУМЕНТУ" in x for x in BASE["limitations"]), BASE["limitations"])
    check("12e. файлы, доказанные серией, перечислены отдельно",
          len(BASE.get("series_proven_files") or []) == 5)

    sec("7. Безопасность проверяющего")

    SRC = io.open(VQ_PATH, encoding="utf-8").read()
    tree = ast.parse(SRC)
    shell_true = [1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                  for kw in n.keywords if kw.arg == "shell"
                  and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)]
    check("71. shell=True в проверяющем отсутствует", not shell_true)
    # Подстрокой себя не проверяем: «server.py» есть в пояснении к сертификату.
    spawns = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)                 and n.func.attr in ("run", "Popen", "check_output"):
            seg = ast.get_source_segment(SRC, n) or ""
            if "server.py" in seg or "msedge" in seg:
                spawns.append(seg[:60])
    check("73. настоящий server.py и браузер проверяющим не запускаются", not spawns,
          spawns)
    # Запись в stdout изменением файлов не является — смотрим только файловые операции.
    writes = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        owner = n.func.value.id if isinstance(n.func.value, ast.Name) else ""
        if owner in ("os", "shutil") and n.func.attr in ("remove", "unlink", "rmtree",
                                                         "makedirs", "rename", "replace"):
            writes.append("%s.%s" % (owner, n.func.attr))
        if n.func.attr == "open" and owner == "io":
            mode = n.args[1].value if len(n.args) > 1 and isinstance(
                n.args[1], ast.Constant) else "r"
            if any(c in str(mode) for c in "wax+"):
                writes.append("io.open %s" % mode)
    check("71b. проверяющий не изменяет ни одного файла", not writes, writes)
    own = io.open(os.path.join(REPO, "tools", "test_ui_qualification.py"),
                  encoding="utf-8").read()
    own_tree = ast.parse(own)
    spawn = [n for n in ast.walk(own_tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen", "check_output")]
    check("74. этот тест не создаёт подпроцессов и не может запустить Edge", not spawn)

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
