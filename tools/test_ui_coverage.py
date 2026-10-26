# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — КАРТА UI-ПОКРЫТИЯ: что сценарий настроек доказывает, а что нет.
#
#  ЗАЧЕМ. Соблазн простой: раз файл `web/app.js` изменён и сценарий настроек зелёный —
#  значит UI проверен. Это неправда: в том же файле живут очередь печати, верхняя панель
#  и менеджер оверлеев. Покрытие решается по СОДЕРЖИМОМУ изменённых участков diff, и
#  здесь закрепляется, что расширить его случайно нельзя.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. Не запускает Edge, server.py и UI-сценарии; подпроцессов не создаёт.
#
#  Запуск:  python tools/test_ui_coverage.py       (0 = покрытие не размывается)
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
COV_PATH = os.path.join(UIDIR, "select_ui_coverage.py")
MAP_PATH = os.path.join(UIDIR, "ui_coverage_map.json")

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
check("0a. select_ui_coverage.py существует", os.path.isfile(COV_PATH))
check("0b. карта покрытия существует", os.path.isfile(MAP_PATH))
if FAILED:
    print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("fm_cov", COV_PATH)
cov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cov)
CMAP = cov.load_map()
UNIT = CMAP["coverage_units"][0]
TMP = tempfile.mkdtemp(prefix="fm_cov_")


def D(body):
    return body


# Настоящие фрагменты продукта: маркеры взяты из реального кода, а не придуманы.
SETTINGS_OPEN = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -2876,6 +2876,6 @@
     const openSettings = (ev) => {
         if (showDiag.value) closeDiagnostics();
-        showSettings.value = true;
+        showSettings.value = true;   // 2.842
     };
"""
SETTINGS_CLOSE = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -2900,3 +2900,3 @@
-    const closeSettings = () => { showSettings.value = false; };
+    const closeSettings = () => { showSettings.value = false; /* 2.842 */ };
"""
SETTINGS_CSS = """diff --git a/web/app.css b/web/app.css
--- a/web/app.css
+++ b/web/app.css
@@ -100,5 +100,5 @@
 .fm-settings-workspace {
   position: relative;
-  height: 100%;
+  height: calc(100% - 8px);
 }
"""
SETTINGS_ROLE = """diff --git a/web/index.html b/web/index.html
--- a/web/index.html
+++ b/web/index.html
@@ -500,3 +500,3 @@
-<section v-if="showSettings" class="fm-settings-workspace" role="region">
+<section v-if="showSettings" class="fm-settings-workspace" role="region" tabindex="-1">
 <div class="fm-set-title"><span>Settings</span></div>
"""
QUEUE = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -5000,3 +5000,3 @@
     const loadQueue = async () => {
-        const r = await fetch('/api/send-jobs');
+        const r = await fetch('/api/send-jobs?v=2');
"""
TOPBAR = """diff --git a/web/app.css b/web/app.css
--- a/web/app.css
+++ b/web/app.css
@@ -20,3 +20,3 @@
 .fm-header-desktop-v270 {
-  height: 3.5rem;
+  height: 3.75rem;
"""
OVERLAY = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -700,3 +700,3 @@
     const fmCloseNested = () => {
-        fmModalTop().close();
+        fmModalTop().close(true);
"""
ROUTER = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -900,3 +900,3 @@
     const openModule = (id) => {
-        activeModuleId.value = id;
+        activeModuleId.value = String(id);
"""
GLOBAL_CSS = """diff --git a/web/design/palette.css b/web/design/palette.css
--- a/web/design/palette.css
+++ b/web/design/palette.css
@@ -1,3 +1,3 @@
 :root {
-  --fm-accent: #4da6ff;
+  --fm-accent: #3d96ef;
"""
UNKNOWN_JS = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -7000,3 +7000,3 @@
     const recalcSomething = () => {
-        return 1;
+        return 2;
"""
NEW_CONTROL = """diff --git a/web/index.html b/web/index.html
--- a/web/index.html
+++ b/web/index.html
@@ -505,2 +505,3 @@
 <section class="fm-settings-workspace" role="region">
+<button class="fm-set-act" @click="doSomethingNew">New</button>
"""
UNCHECKED_TEXT = """diff --git a/web/index.html b/web/index.html
--- a/web/index.html
+++ b/web/index.html
@@ -520,3 +520,3 @@
 <div class="fm-set-nav">
-<button class="fm-set-nav-item"><span>General</span></button>
+<button class="fm-set-nav-item"><span>Common</span></button>
"""
RENAME = """diff --git a/web/old_panel.js b/web/new_panel.js
similarity index 90%
rename from web/old_panel.js
rename to web/new_panel.js
--- a/web/old_panel.js
+++ b/web/new_panel.js
@@ -1,3 +1,3 @@
-const x = 1;
+const x = 2;
"""
DELETE = """diff --git a/web/index.html b/web/index.html
--- a/web/index.html
+++ b/web/index.html
@@ -500,4 +500,3 @@
 <section class="fm-settings-workspace" role="region">
 <div class="fm-set-title"><span>Settings</span>
-<button class="fm-set-x" @click="closeSettings">x</button>
 </div>
"""
BACKEND = """diff --git a/server.py b/server.py
--- a/server.py
+++ b/server.py
@@ -100,3 +100,3 @@
-x = 1
+x = 2
"""


def an(diff, cmap=None):
    return cov.analyse(diff, cmap or CMAP)


try:
    sec("1. Покрытая оболочка настроек")

    for num, label, diff in ((13, "открытие настроек", SETTINGS_OPEN),
                             (14, "закрытие настроек", SETTINGS_CLOSE),
                             (15, "CSS самой рабочей области настроек", SETTINGS_CSS),
                             (16, "role и заголовок панели", SETTINGS_ROLE)):
        r = an(diff)
        check("%d. %s -> COVERED" % (num, label),
              r["status"] == "COVERED" and r["covered_hunks"] == 1
              and r["required_scenarios"] == ["settings_panel_open_close",
                                              "settings_panel_open_close_isolated"],
              (r["status"], r["required_scenarios"]))

    r = an(SETTINGS_OPEN + SETTINGS_CSS)
    check("23. два участка настроек -> COVERED целиком",
          r["status"] == "COVERED" and r["covered_hunks"] == 2 and r["ui_hunks"] == 2, r)

    sec("2. Непокрытое остаётся непокрытым")

    for num, label, diff in ((17, "очередь печати в том же app.js", QUEUE),
                             (18, "верхняя панель", TOPBAR),
                             (19, "общий менеджер оверлеев", OVERLAY),
                             (20, "навигация между экранами", ROUTER),
                             (24, "неизвестный участок app.js", UNKNOWN_JS),
                             (28, "новый непроверяемый элемент внутри панели", NEW_CONTROL),
                             (28.1, "глобальные CSS-токены", GLOBAL_CSS),
                             (28.2, "текст, который не проверяет ни одна assertion",
                              UNCHECKED_TEXT)):
        r = an(diff)
        check("%s. %s -> UNCOVERED" % (num, label),
              r["status"] == "UNCOVERED" and not r["required_scenarios"],
              (r["status"], r["uncovered"][:1]))

    sec("3. Смешанные изменения не прячут непокрытое")

    r = an(SETTINGS_OPEN + QUEUE)
    check("21. настройки + очередь -> PARTIALLY_COVERED",
          r["status"] == "PARTIALLY_COVERED" and r["covered_hunks"] == 1
          and r["uncovered_hunks"] == 1 and not r["required_scenarios"], r["status"])
    r = an(SETTINGS_CSS + GLOBAL_CSS)
    check("22. настройки + глобальный CSS -> PARTIALLY_COVERED",
          r["status"] == "PARTIALLY_COVERED" and not r["required_scenarios"], r["status"])
    check("21b. при частичном покрытии сценарии НЕ выдаются",
          not r["required_scenarios"])

    sec("4. Переименование, удаление, backend, path-only")

    r = an(RENAME)
    check("26. переименование анализируется по обоим путям",
          r["ui_hunks"] == 1 and r["hunks"][0]["renamed"]
          and r["hunks"][0]["old_path"] == "web/old_panel.js"
          and r["hunks"][0]["new_path"] == "web/new_panel.js", r["hunks"][:1])
    r = an(DELETE)
    check("27. удаление UI-кода анализируется и требует покрытия",
          r["ui_hunks"] == 1 and r["status"] == "COVERED", r["status"])
    r = an(BACKEND)
    check("36. изменение backend покрытия UI не требует",
          r["status"] == "NO_UI_CHANGES" and r["ui_hunks"] == 0, r["status"])
    u = cov.unknown_result("путь без diff")
    check("25. path-only -> UNKNOWN и без сценариев",
          u["status"] == "UNKNOWN" and not u["required_scenarios"])
    check("25b. UNKNOWN не равен COVERED", cov.UNKNOWN != cov.COVERED)

    sec("5. Каждый участок присутствует в результате")

    r = an(SETTINGS_OPEN + QUEUE + TOPBAR + SETTINGS_CSS)
    check("30. в результате перечислены все четыре участка", r["ui_hunks"] == 4
          and len(r["hunks"]) == 4, r["ui_hunks"])
    check("30b. у каждого участка есть диапазоны и файл",
          all(h["old_range"] and h["new_range"] and h["file"] for h in r["hunks"]))
    check("30c. у непокрытых указана причина",
          all(h["unmatched_reason"] for h in r["hunks"]
              if not h["matched_coverage_units"]))
    check("29. изменение проверяемого селектора требует обоих сценариев",
          set(an(SETTINGS_ROLE)["required_scenarios"]) == set(UNIT["required_scenarios"]))

    sec("6. Карта не размыта")

    broad = {"settings", "button", "modal", "app", "display", "div", "class"}
    check("6a. в разрешённых маркерах нет слишком широких",
          not (set(m.lower() for m in UNIT["allowed_hunk_markers"]) & broad),
          UNIT["allowed_hunk_markers"])
    check("6b. каждый разрешённый маркер встречается в реальном коде продукта",
          all(any(m in io.open(os.path.join(REPO, f), encoding="utf-8",
                               errors="surrogateescape").read()
                  for f in ("web/app.js", "web/index.html", "web/app.css"))
              for m in UNIT["allowed_hunk_markers"]),
          [m for m in UNIT["allowed_hunk_markers"]])
    check("6c. содержимое панели явно объявлено непокрытым",
          any("fm-set-nav" in m for m in UNIT["forbidden_hunk_markers"])
          and any("содержимое панели" in x for x in UNIT["unsupported_changes"]))
    check("6d. карта покрытия отделена от карты риска",
          not os.path.samefile(MAP_PATH, os.path.join(REPO, "tools", "validation",
                                                      "risk_map.json")))
    check("6e. карта требует ОБА сценария",
          UNIT["required_scenarios"] == ["settings_panel_open_close",
                                         "settings_panel_open_close_isolated"])

    sec("7. Разбор diff и отказ по-честному")

    err = None
    try:
        cov.parse_diff("@@ мусор @@\n")
    except cov.CoverageError as e:
        err = str(e)
    check("7a. неразбираемый diff -> ошибка, а не молчаливое покрытие", err is not None, err)
    p = os.path.join(TMP, "bad_map.json")
    io.open(p, "w", encoding="utf-8").write('{"schema_version": "чужая"}')
    err = None
    try:
        cov.load_map(p)
    except cov.CoverageError as e:
        err = str(e)
    check("7b. чужая схема карты -> ошибка", err is not None, err)

    SRC = io.open(COV_PATH, encoding="utf-8").read()
    tree = ast.parse(SRC)
    shell_true = [1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                  for kw in n.keywords if kw.arg == "shell"
                  and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)]
    check("71. shell=True в анализаторе отсутствует", not shell_true)
    own = ast.parse(io.open(os.path.join(REPO, "tools", "test_ui_coverage.py"),
                            encoding="utf-8").read())
    spawn = [n for n in ast.walk(own) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen", "check_output")]
    check("73. этот тест не создаёт подпроцессов", not spawn)

    sec("8. Отрицательные самотесты")

    weak = copy.deepcopy(CMAP)
    weak["coverage_units"][0]["forbidden_hunk_markers"] = []
    weak["coverage_units"][0]["allowed_hunk_markers"] += ["fetch", "loadQueue"]
    r = an(QUEUE, weak)
    check("8a. самотест: с размытой картой очередь стала бы «покрытой» — значит "
          "строгость карты и есть то, что держит границу",
          r["status"] == "COVERED", r["status"])
    check("8b. с настоящей картой та же очередь непокрыта",
          an(QUEUE)["status"] == "UNCOVERED")

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
