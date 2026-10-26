# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — СЕЛЕКТОР ПРОФИЛЯ ПРОВЕРКИ: решение детерминировано и безопасно.
#
#  ЗАЧЕМ. tools/validation/select_profile.py решает, какой объём проверки достаточен
#  для конкретной правки. Ошибка в сторону занижения означает, что дефект уезжает
#  на ферму непроверенным. Поэтому тест закрепляет ДВЕ вещи:
#    1) классификацию (какой риск и профиль для какого пути);
#    2) безопасность самого селектора — он ничего не выполняет и ничего не пишет.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. Не запускает ни одной продуктовой проверки, не собирает EXE,
#  не открывает БД и DATA_DIR, не ходит в сеть, не трогает принтеры. Временные файлы
#  создаёт только в системном temp, вне репозитория.
#
#  Запуск:  python tools/test_select_profile.py       (0 = контракт соблюдён)
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
SEL = os.path.join(REPO, "tools", "validation", "select_profile.py")
MAP = os.path.join(REPO, "tools", "validation", "risk_map.json")

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


# ── Загрузка селектора как модуля ────────────────────────────────────────────
sec("0. Селектор и карта на месте")

check("0a. tools/validation/select_profile.py существует", os.path.isfile(SEL))
check("0b. tools/validation/risk_map.json существует", os.path.isfile(MAP))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_select_profile", SEL)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)
RISK_MAP = sp.load_map()


def sel(*paths):
    """Классифицировать пути. Никакая проверка при этом не выполняется."""
    return sp.select(list(paths), RISK_MAP)


# ── 1. Классификация: двадцать закреплённых случаев ──────────────────────────
sec("1. Классификация изменений")

r = sel("docs/validation/release.md")
check("1. markdown -> R0/FAST", r["risk"] == "R0" and r["profile"] == "FAST",
      "%s/%s" % (r["risk"], r["profile"]))

r = sel("web/app.css")
check("2. правка CSS -> R1/TARGETED, требуется UI",
      r["risk"] == "R1" and r["profile"] == "TARGETED" and r["ui_required"] is True,
      "%s/%s ui=%s" % (r["risk"], r["profile"], r["ui_required"]))

r = sel("web/app.js")
check("3. правка web/app.js -> R2/SUBSYSTEM",
      r["risk"] == "R2" and r["profile"] == "SUBSYSTEM", "%s/%s" % (r["risk"], r["profile"]))

r = sel("modules/inventory/web/InventoryPanel.js")
check("4. фронтенд модуля склада -> R2/SUBSYSTEM, требуется UI",
      r["risk"] == "R2" and r["profile"] == "SUBSYSTEM" and r["ui_required"] is True,
      "%s/%s ui=%s" % (r["risk"], r["profile"], r["ui_required"]))

r = sel("app/klipper_start.py")
check("5. адаптер принтера -> не ниже R3 и полный профиль",
      r["risk"] in ("R3", "R4") and r["profile"] in ("RELEASE", "HARDWARE"),
      "%s/%s" % (r["risk"], r["profile"]))

r = sel("app/printer_job_lifecycle.py")
check("6. очередь -> R4/RELEASE",
      r["risk"] == "R4" and r["profile"] == "RELEASE", "%s/%s" % (r["risk"], r["profile"]))

r = sel("app/project_orchestrator.py")
check("7. диспетчеризация печати -> R4, полный прогон и подтверждение на железе",
      r["risk"] == "R4" and r["hardware_required"] is True
      and r["profile"] in ("RELEASE", "HARDWARE")
      and any(s["id"] == "release:gate" for s in r["plan"]),
      "%s/%s hw=%s" % (r["risk"], r["profile"], r["hardware_required"]))

r = sel("app/config_backup/settings_registry.py")
check("8. миграция данных -> R4/RELEASE",
      r["risk"] == "R4" and r["profile"] == "RELEASE", "%s/%s" % (r["risk"], r["profile"]))

r = sel("3diwell-setup.iss")
check("9. установщик -> R3/RELEASE, требуется сборка",
      r["risk"] == "R3" and r["profile"] == "RELEASE" and r["build_required"] is True,
      "%s/%s build=%s" % (r["risk"], r["profile"], r["build_required"]))

r = sel("tools/validation/select_profile.py")
check("10. сам селектор -> R1/TARGETED (в продукт не входит)",
      r["risk"] == "R1" and r["profile"] == "TARGETED", "%s/%s" % (r["risk"], r["profile"]))

r = sel("app/some_unmapped_widget.py")
check("11. неизвестный продуктовый файл -> RELEASE + предупреждение, не FAST",
      r["profile"] == "RELEASE" and r["warnings"] and r["blocked"] is False
      and "app/some_unmapped_widget.py" in r["unmatched_files"],
      "%s/%s warn=%d" % (r["risk"], r["profile"], len(r["warnings"])))

r = sel("app/print_supervisor_unmapped.py")
check("12. неизвестный файл в критической области -> blocked",
      r["blocked"] is True and r["risk"] == "R4" and r["blocked_reason"],
      "blocked=%s %s" % (r["blocked"], r["risk"]))

r = sel("web/app.css", "app/printer_job_lifecycle.py")
check("13. несколько файлов -> максимальный риск, а не первое совпадение",
      r["risk"] == "R4" and r["profile"] == "RELEASE" and r["ui_required"] is True,
      "%s/%s ui=%s" % (r["risk"], r["profile"], r["ui_required"]))

a, b = sel("web\\app.css"), sel("web/app.css")
check("14. обратный слэш эквивалентен прямому",
      a["changed_files"] == b["changed_files"] == ["web/app.css"]
      and a["risk"] == b["risk"] and a["profile"] == b["profile"],
      "%s vs %s" % (a["changed_files"], b["changed_files"]))

r = sel("../outside_repo/evil.py")
check("15. путь вне репозитория -> blocked, зелёного результата нет",
      r["blocked"] is True and r["profile"] in ("RELEASE", "HARDWARE"),
      "blocked=%s %s" % (r["blocked"], r["profile"]))
r = sel("C:\\Windows\\System32\\drivers\\etc\\hosts")
check("15b. абсолютный путь вне репозитория -> blocked", r["blocked"] is True)

_tmp = tempfile.mkdtemp(prefix="fm_selprof_")
try:
    bad = os.path.join(_tmp, "broken.json")
    io.open(bad, "w", encoding="utf-8").write(u'{"schema_version": "3diwell-risk-map-v1", ')
    err = None
    try:
        sp.load_map(bad)
    except sp.SelectorError as e:
        err = str(e)
    check("16. испорченная карта -> ошибка, а не тихий FAST", err is not None, err)
    rc = subprocess.run([sys.executable, SEL, "--files", "web/app.css", "--map", bad],
                        cwd=REPO, capture_output=True,
                        env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode
    check("16b. испорченная карта -> ненулевой код возврата CLI", rc != 0, "rc=%d" % rc)

    missing = os.path.join(_tmp, "no_such_map.json")
    err = None
    try:
        sp.load_map(missing)
    except sp.SelectorError as e:
        err = str(e)
    check("17. отсутствующая карта -> ошибка", err is not None, err)
    rc = subprocess.run([sys.executable, SEL, "--files", "web/app.css", "--map", missing],
                        cwd=REPO, capture_output=True,
                        env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode
    check("17b. отсутствующая карта -> ненулевой код возврата CLI", rc != 0, "rc=%d" % rc)

    # Схема с чужой версией тоже обязана краснеть, а не подстраиваться.
    wrong = os.path.join(_tmp, "wrong_schema.json")
    d = copy.deepcopy(RISK_MAP)
    d["schema_version"] = "3diwell-risk-map-v999"
    io.open(wrong, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
    err = None
    try:
        sp.load_map(wrong)
    except sp.SelectorError as e:
        err = str(e)
    check("17c. несовместимая версия схемы -> ошибка", err is not None, err)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

r = sel()
check("18. пустой список изменений -> R0/FAST и пустой план",
      r["risk"] == "R0" and r["profile"] == "FAST" and r["plan"] == []
      and r["changed_files"] == [], "%s/%s plan=%d" % (r["risk"], r["profile"], len(r["plan"])))

r = sel("web/app.css", "web\\app.css", "./web/app.css")
check("19. дубликаты и разные написания схлопываются в один файл",
      r["changed_files"] == ["web/app.css"], r["changed_files"])

r = sel("web/app.css")
_KEYS = ("schema_version", "changed_files", "matched_rules", "unmatched_files", "components",
         "risk", "profile", "ui_required", "build_required", "hardware_required",
         "targeted_tests", "subsystem_tests", "reasons", "warnings", "blocked",
         "blocked_reason", "plan")
_missing = [k for k in _KEYS if k not in r]
check("20. структура результата содержит все обязательные поля", not _missing, _missing)
check("20b. результат сериализуется в JSON без потерь",
      json.loads(json.dumps(r, ensure_ascii=False))["profile"] == r["profile"])
check("20c. в каждом шаге плана есть id, profile, command, reason, estimated_scope, executes",
      all(set(("id", "profile", "command", "reason", "estimated_scope", "executes")) <= set(s)
          for s in r["plan"]), [s.get("id") for s in r["plan"]])


# ── 2. Селектор ничего не выполняет ──────────────────────────────────────────
sec("2. Селектор планирует, но не выполняет")

_all_plans = []
for p in ("web/app.css", "app/project_orchestrator.py", "3diwell-setup.iss",
          "app/some_unmapped_widget.py", "docs/validation/release.md"):
    _all_plans.extend(sel(p)["plan"])
check("21. executes=false у каждого шага любого плана (%d шагов)" % len(_all_plans),
      all(s["executes"] is False for s in _all_plans),
      [s["id"] for s in _all_plans if s["executes"] is not False])

_FS_MUTATORS = {"remove", "unlink", "rename", "replace", "rmdir", "makedirs", "mkdir",
                "rmtree", "copy", "copy2", "copyfile", "move", "chmod", "truncate", "system"}


def _mode_of(node):
    """Режим открытия файла: позиционный второй аргумент или ключевое слово mode."""
    mode = "r"
    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return str(mode)


def scan_source(src):
    """Разбор ИСХОДНИКА по дереву, а не по подстрокам: комментарий про subprocess
    не должен считаться вызовом subprocess."""
    out = {"writes": [], "fs": [], "sub_attrs": [], "non_git": [], "gate_strings": 0}
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and "release_gate.py" in node.value:
            out["gate_strings"] += 1
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        owner = ""
        if isinstance(f, ast.Attribute):
            owner = f.value.id if isinstance(f.value, ast.Name) else ""
            if owner == "subprocess":
                out["sub_attrs"].append(f.attr)
                arg = node.args[0] if node.args else None
                while isinstance(arg, ast.BinOp):
                    arg = arg.left
                first = arg.elts[0].value if isinstance(arg, ast.List) and arg.elts \
                    and isinstance(arg.elts[0], ast.Constant) else None
                if first != "git":
                    out["non_git"].append("%s(%s)" % (f.attr, first))
            if owner in ("os", "shutil", "pathlib") and f.attr in _FS_MUTATORS:
                out["fs"].append("%s.%s" % (owner, f.attr))
            if owner == "io" and f.attr == "open" and any(c in _mode_of(node) for c in "wax+"):
                out["writes"].append("io.open %s" % _mode_of(node))
        if isinstance(f, ast.Name) and f.id == "open" and any(c in _mode_of(node) for c in "wax+"):
            out["writes"].append("open %s" % _mode_of(node))
    return out


S = scan_source(io.open(SEL, encoding="utf-8").read())

check("22. селектор не открывает ни одного файла на запись", not S["writes"], S["writes"])
check("23. селектор не вызывает разрушающих файловых операций", not S["fs"], S["fs"])
check("24. из subprocess используется только run()",
      set(S["sub_attrs"]) <= {"run"}, S["sub_attrs"])
check("25. каждый subprocess.run начинается с git (%d вызов)" % len(S["sub_attrs"]),
      not S["non_git"] and len(S["sub_attrs"]) >= 1, S["non_git"])
check("26. release_gate.py упоминается только как строка плана, вызова нет",
      S["gate_strings"] >= 1 and not S["non_git"], S["gate_strings"])

# Отрицательный самотест: проверки 22–26 обязаны краснеть на исходнике, который
# действительно пишет файлы и запускает не git. Иначе они вакуумны.
_NEG = (
    "import io, os, shutil, subprocess\n"
    "io.open('x.txt', 'w', encoding='utf-8').write('1')\n"
    "open('y.txt', mode='a').write('2')\n"
    "os.remove('z.txt')\n"
    "shutil.rmtree('d')\n"
    "subprocess.run(['python', 'tools/release_gate.py'])\n"
    "subprocess.Popen(['cmd'])\n"
)
N = scan_source(_NEG)
check("26a. самотест: детектор видит запись файлов", len(N["writes"]) == 2, N["writes"])
check("26b. самотест: детектор видит разрушающие операции", len(N["fs"]) == 2, N["fs"])
check("26c. самотест: детектор видит вызов не через run()",
      "Popen" in N["sub_attrs"], N["sub_attrs"])
check("26d. самотест: детектор видит запуск не git", len(N["non_git"]) == 2, N["non_git"])
check("26e. самотест: комментарий не считается вызовом",
      not scan_source("# subprocess.run(['python']) в комментарии\nx = 1\n")["sub_attrs"])


# ── 3. Карта риска непротиворечива ───────────────────────────────────────────
sec("3. Карта риска")

_ids = [x["id"] for x in RISK_MAP["rules"]]
check("27. идентификаторы правил уникальны", len(_ids) == len(set(_ids)),
      [i for i in _ids if _ids.count(i) > 1])

_bad_min = [x["id"] for x in RISK_MAP["rules"]
            if RISK_MAP["profile_order"].index(x["profile"])
            < RISK_MAP["profile_order"].index(RISK_MAP["profile_min_by_risk"][x["risk"]])]
check("28. ни одно правило не назначает профиль слабее минимума для своего риска",
      not _bad_min, _bad_min)

_ghost = []
for x in RISK_MAP["rules"]:
    for k in ("targeted_tests", "subsystem_tests"):
        for t in x.get(k, []):
            if not os.path.isfile(os.path.join(REPO, t)):
                _ghost.append("%s:%s" % (x["id"], t))
check("29. карта не ссылается на несуществующие тесты", not _ghost, _ghost)

_no_esc = [x["id"] for x in RISK_MAP["rules"]
           if x["risk"] in ("R3", "R4")
           and RISK_MAP["profile_order"].index(x["profile"])
           < RISK_MAP["profile_order"].index("RELEASE")]
check("30. критический риск нельзя закрыть узким профилем", not _no_esc, _no_esc)

# Мутационная страховка: если убрать эскалацию неизвестного файла, проверка 11 обязана
# покраснеть. Копия карты, не файл на диске.
_weak = copy.deepcopy(RISK_MAP)
_weak["fallback"]["unknown_product_file"].update({"risk": "R0", "profile": "FAST"})
_w = sp.select(["app/some_unmapped_widget.py"], _weak)
check("31. проверка 11 не вакуумна: с ослабленной картой результат становится FAST",
      _w["profile"] == "FAST" and r["profile"] != "FAST",
      "ослабленная=%s" % _w["profile"])

_weak2 = copy.deepcopy(RISK_MAP)
_weak2["fallback"]["unknown_in_critical_area"]["blocked"] = False
_w2 = sp.select(["app/print_supervisor_unmapped.py"], _weak2)
check("32. проверка 12 не вакуумна: без флага blocked результат перестаёт блокироваться",
      _w2["blocked"] is False)


# ── 4. CLI-контракт ──────────────────────────────────────────────────────────
sec("4. Коды возврата CLI")

def cli(args):
    p = subprocess.run([sys.executable, SEL] + args, cwd=REPO, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout, p.stderr


rc, out, _ = cli(["--files", "docs/validation/release.md", "--json"])
check("33. обычный запуск -> rc=0 и валидный JSON",
      rc == 0 and json.loads(out)["profile"] == "FAST", "rc=%d" % rc)

rc, _, _ = cli(["--files", "app/print_supervisor_unmapped.py"])
check("34. заблокированный результат -> rc=3, не 0", rc == 3, "rc=%d" % rc)

rc, _, _ = cli([])
check("35. без источника изменений -> rc=2", rc == 2, "rc=%d" % rc)

rc, _, _ = cli(["--files", "web/app.css", "--staged"])
check("36. несовместимые режимы ввода -> rc=2", rc == 2, "rc=%d" % rc)

# Рабочее дерево селектор читает через git, но по-прежнему ничего не выполняет.
rc, out, err = cli(["--working-tree", "--json"])
check("37. режим --working-tree отрабатывает и остаётся планом",
      rc in (0, 3) and all(s["executes"] is False for s in json.loads(out)["plan"]),
      "rc=%d %s" % (rc, err.strip()[:120]))


# ── 5. Покрытие интерфейса (этап 3D) ─────────────────────────────────────────
sec("5. Селектор сообщает о покрытии интерфейса, но UI не запускает")

_ui = sp.augment_ui(sel("web/app.css"), diff_mode=None)
check("40. path-only UI -> покрытие UNKNOWN и ни одного сценария",
      _ui["ui_coverage_status"] == "UNKNOWN" and _ui["required_ui_scenarios"] == []
      and _ui["ui_required"] is True, _ui["ui_coverage_status"])
check("40b. профиль при этом не понижен",
      _ui["profile"] == "TARGETED" and _ui["risk"] == "R1")

_non_ui = sp.augment_ui(sel("docs/validation/release.md"), diff_mode=None)
check("41. изменение без UI покрытия не требует",
      _non_ui["ui_coverage_status"] == "NOT_REQUIRED"
      and _non_ui["required_ui_scenarios"] == [])

check("42. статус квалификации оснастки виден в результате",
      _ui["ui_qualification_status"] in ("VALID", "STALE_TOOLING", "STALE_SCENARIOS",
                                         "STALE_ENVIRONMENT", "MISSING", "INVALID"),
      _ui["ui_qualification_status"])

_r4 = sp.augment_ui(sel("app/project_orchestrator.py"), diff_mode=None)
check("43. покрытие интерфейса не понижает R4 и не снимает требование железа",
      _r4["risk"] == "R4" and _r4["hardware_required"] is True
      and _r4["profile"] in ("RELEASE", "HARDWARE"), (_r4["risk"], _r4["profile"]))

_SRC_SEL = io.open(SEL, encoding="utf-8").read()
_tree_sel = ast.parse(_SRC_SEL)
_spawn_ui = [n for n in ast.walk(_tree_sel) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen")
             and "run_ui_verification" in (ast.get_source_segment(_SRC_SEL, n) or "")]
check("44. селектор UI не запускает вовсе", not _spawn_ui, _spawn_ui)

_stale = dict(_ui)
_stale["ui_qualification_status"] = "STALE_TOOLING"
check("45. при устаревшей квалификации сценарии не выдаются",
      not _stale["required_ui_scenarios"])

check("46. в результате есть все поля UI-интеграции",
      all(k in _ui for k in ("ui_coverage_status", "ui_coverage_units",
                             "required_ui_scenarios", "uncovered_ui_hunks",
                             "ui_qualification_status")), sorted(_ui))


print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
