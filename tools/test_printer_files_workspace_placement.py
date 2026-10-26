# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.824 — регрессия дефекта «пустой workspace файлов принтера + FlashForge».
#
#  Быстрый СТАТИЧЕСКИЙ страж (без сети/Edge/Node/сервера) для конкретного дефекта
#  Alpha 2.823→2.824: при выборе «Файлы принтера» у FlashForge правая рабочая
#  область оставалась ПУСТОЙ, потому что секция workspace стояла ВНЕ контейнера
#  .main-cols (была соседом, а не ребёнком, как settings/diagnostics/projects), и
#  чтение списка FlashForge дублировалось отдельной реализацией. Здесь проверяется:
#    • секция файлов вложена в .main-cols, как остальные рабочие экраны;
#    • header (.pfw-head) виден всегда, тело покрывает все состояния;
#    • чтение FlashForge идёт через ЕДИНЫЙ низкоуровневый чтец /gcodeList (тот же,
#      что выпадашка выбора файла) — нет двух расходящихся реализаций;
#    • не тронуты чужие адаптеры и выключенный по умолчанию предохранитель удаления.
#  Тяжёлый рендер в реальном движке — в tools/test_printer_file_manager.py.
#
#  Запуск:  python tools/test_printer_files_workspace_placement.py   (0 = ок)
# ============================================================================
import ast
import io
import os
import sys
from html.parser import HTMLParser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
FF = io.open(os.path.join(REPO, "app", "printer_files", "flashforge.py"), encoding="utf-8").read()
BB = io.open(os.path.join(REPO, "app", "printer_files", "bambu.py"), encoding="utf-8").read()
MR = io.open(os.path.join(REPO, "app", "printer_files", "moonraker.py"), encoding="utf-8").read()
SEC = io.open(os.path.join(REPO, "app", "printer_files", "security.py"), encoding="utf-8").read()

FAILED = []
PASSED = [0]


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:180]) if detail else ""))


def section(t):
    print("\n--- %s ---" % t)


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


print("=== Alpha 2.824: регрессия workspace-placement + FlashForge shared read ===")

# ── Родители workspace-секций в шаблоне (#app) ──────────────────────────────
section("PLACEMENT: секция файлов принтеров внутри .main-cols")

_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "col", "use",
         "path", "circle", "rect", "line", "polyline", "polygon", "stop", "ellipse"}


def _parents():
    s = INDEX.find('<div id="app"')
    depth = 0
    end = -1
    i = s
    import re as _re
    for m in _re.finditer(r"<div\b|</div>", INDEX[s:]):
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                end = s + m.end()
                break
        else:
            depth += 1
    tpl = INDEX[s:end]

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []
            self.parents = {}

        def handle_starttag(self, tag, attrs):
            cls = dict(attrs).get("class", "") or ""
            for t in ("projects-pane", "fm-settings-workspace", "fm-diagnostics-workspace",
                      "fm-printer-files-workspace"):
                if t in cls and t not in self.parents:
                    self.parents[t] = " ".join(x[1] for x in self.stack[-1:])
            if tag not in _VOID:
                self.stack.append((tag, cls))

        def handle_endtag(self, tag):
            for j in range(len(self.stack) - 1, -1, -1):
                if self.stack[j][0] == tag:
                    del self.stack[j:]
                    break

    p = _P()
    p.feed(tpl)
    return p.parents


PAR = _parents()
check("1. секция .fm-printer-files-workspace вложена в .main-cols (тот самый дефект)",
      "main-cols" in PAR.get("fm-printer-files-workspace", ""), PAR)
check("2. она в ТОМ ЖЕ контейнере, что settings/diagnostics/projects (единый flex-слот)",
      all("main-cols" in PAR.get(k, "") for k in
          ("fm-settings-workspace", "fm-diagnostics-workspace", "projects-pane"))
      and len(set((v or "").split()[0] for v in PAR.values())) == 1
      and (list(PAR.values())[0] or "").split()[0] == "main-cols", PAR)

# ── Header виден всегда + тело покрывает все состояния ──────────────────────
section("STATES: header всегда виден, тело покрывает все состояния")

_si = INDEX.find('<section v-if="showPrinterFiles"')
_sec = INDEX[_si:INDEX.find("</section>", _si)]
_open_end = _sec.find(">") + 1
_hi = _sec.find('<div class="pfw-head"')
_before = _sec[_open_end:_hi]
_head_tag = _sec[_hi:_sec.find(">", _hi) + 1] if _hi >= 0 else ""
check("3. header (.pfw-head) сразу после открытия секции, без промежуточных гейтов",
      _hi > _open_end and _before.strip() == ""
      and "v-if" not in _before and "v-show" not in _before)
check("4. сам тег .pfw-head без v-if/v-show (header не пропадает при loading/error)",
      _head_tag and "v-if" not in _head_tag and "v-show" not in _head_tag, _head_tag)
check("5. тело секции покрывает ВСЕ состояния (loading/idle/unsupported/offline/nostorage/error/empty)",
      all(("pfState==='%s'" % s) in _sec for s in
          ("loading", "idle", "unsupported", "offline", "nostorage", "error", "empty")))
check("6. секция управляется своим workspace-гейтом v-if=\"showPrinterFiles\" (как settings/diag)",
      '<section v-if="showPrinterFiles"' in INDEX)

# ── FlashForge: единый низкоуровневый чтец /gcodeList ───────────────────────
section("FLASHFORGE: единый чтец /gcodeList, без двух реализаций")

_helper = fn_src("_flashforge_gcode_list")
_files = fn_src("_flashforge_files")
_pf = fn_src("_pf_ff_list")
check("7. _flashforge_gcode_list определён РОВНО один раз и делает POST /gcodeList",
      SRV.count("def _flashforge_gcode_list(") == 1 and "/gcodeList" in _helper and "urlopen" in _helper)
check("8. выпадашка выбора файла (_flashforge_files) читает через общий чтец, без своего urlopen",
      "_flashforge_gcode_list(" in _files and "urlopen" not in _files)
check("9. файловый менеджер (_pf_ff_list) читает через ТОТ ЖЕ общий чтец, без своего urlopen",
      "_flashforge_gcode_list(" in _pf and "urlopen" not in _pf)
check("10. запрос /gcodeList формируется РОВНО в одном месте (нет расходящихся реализаций)",
      SRV.count('+ "/gcodeList"') == 1 and SRV.count('"/gcodeList"') == 1)
check("11. _pf_ff_list честно различает ошибки: timeout/malformed/connection-lost (не пустой список)",
      "_PfError" in _pf and "REASON_TIMEOUT" in _pf and "REASON_MALFORMED" in _pf
      and "REASON_CONNECTION_LOST" in _pf)

# ── FlashForge провайдер: list-only, delete недоступно ──────────────────────
section("FLASHFORGE провайдер + границы (чужие адаптеры/предохранитель не тронуты)")

check("12. FlashForge capabilities: supported + list_files, delete_files=False (delete недоступно)",
      "supported=True, list_files=True," in FF and "delete_files=False," in FF)
check("13. предохранитель удаления по умолчанию ВЫКЛЮЧЕН",
      "\nPRINTER_FILE_DELETE_ENABLED_DEFAULT = False" in SEC)
check("14. Bambu-адаптер не тронут (delete_safe_during_print = False — запрет при печати)",
      "delete_safe_during_print = False" in BB)
check("15. Moonraker-адаптер не тронут (учёт места накопителя сохранён)",
      "read_storage_usage" in MR)

# ── Итог ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 76)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), PASSED[0] + len(FAILED)))
    for n in FAILED:
        print("   - " + n)
    sys.exit(1)
print("PASS — регрессия 2.824: workspace-placement + FlashForge shared read — все %d проверок пройдены "
      "(статический страж, без сети/Edge)" % PASSED[0])
sys.exit(0)
