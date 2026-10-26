# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.832 — mutation proof: ≥18 порч boot/сортировки/копирования/fallback обязаны краснить
тесты. SHA-revert; PYTHONDONTWRITEBYTECODE; boot-тест гоняется с FM_SKIP_BROWSER=1 (source-гварды
ловят порчи быстро). Production data не трогается."""
import hashlib
import io
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(ROOT, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
# Alpha 2.841: машиночитаемый итог набора — гейт считает нули напрямую, а не разбирает прозу.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_frontend_boot_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
BASE_ENV = dict(os.environ); BASE_ENV["PYTHONIOENCODING"] = "utf-8"; BASE_ENV["PYTHONDONTWRITEBYTECODE"] = "1"

APP = os.path.join(ROOT, "web", "app.js")
IDX = os.path.join(ROOT, "web", "index.html")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")
REG = os.path.join(ROOT, "app", "config_backup", "settings_registry.py")

BOOT = "test_frontend_boot_and_printer_sort"
SORT = "test_printer_sort_and_copy"


def b(x):
    return x.encode("utf-8")


# Якорь root cause 2.831 строится ПО ФАЙЛУ: от последнего «modelHeaderLabel,» в setup-return до
# «enterSpotlight,». Между ними — комментарий, который правится вместе с кодом; вписывать его
# текстом в якорь нельзя, иначе порча перестаёт применяться молча (проверено в 2.866).
_APP_SRC = io.open(APP, "rb").read()
_rc_i = _APP_SRC.rindex(b"modelHeaderLabel,")
_rc_j = _APP_SRC.index(b"enterSpotlight,", _rc_i) + len(b"enterSpotlight,")
assert 0 < (_rc_j - _rc_i) < 400, "якорь root cause 2.831 устарел: setup-return изменился"
_RC831_FIND = _APP_SRC[_rc_i:_rc_j]
_RC831_REPL = b"modelHeaderLabel,   // comment eats the rest enterSpotlight,"

# (file, find, replace, test, skip_browser, label)
MUT = [
    (APP, b("const raw = String((p && p.model) || '').trim();"),
     b("const raw = String(p.model).trim();"),
     SORT, False, "null-модель снова бросает исключение"),
    (APP, b("if (ua !== ub) return ua ? 1 : -1;"),
     b("if (ua !== ub) return ua ? -1 : 1;"),
     SORT, False, "неизвестные модели идут ПЕРЕД известными"),
    (APP, b("const _byPrinterName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true, sensitivity: 'base' });"),
     b("const _byPrinterName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: false, sensitivity: 'base' });"),
     SORT, False, "natural sort заменён lexical (X10 перед X2)"),
    (APP, b("        return String(a.id || '').localeCompare(String(b.id || ''));   // стабильный tie-break по ID"),
     b("        return 0;   // стабильный tie-break по ID"),
     SORT, False, "стабильный tie-break убран"),
    # ROOT CAUSE 2.831 воспроизведён: комментарий снова «съедает» продолжение return.
    # Alpha 2.869: якорь берётся ИЗ ФАЙЛА (_RC831_FIND), а не пишется текстом. Прежде здесь стоял
    # дословный комментарий строки setup-return; его правка в 2.866 сделала якорь ненаходимым,
    # и порча молча превращалась в SETUP FAIL — набор краснел на исправном коде.
    (APP, _RC831_FIND, _RC831_REPL,
     BOOT, True, "root cause 2.831: '//' снова съедает биндинги setup-return"),
    (IDX, b('<div id="fm-boot-fallback"'),
     b('<div id="fm-boot-fallback-REMOVED"'),
     BOOT, True, "аварийный boot-fallback удалён"),
    (APP, b("window.__fmBooted = true"),
     b("window.__fmBooted = false"),
     BOOT, True, "сигнал успешного монтирования (__fmBooted) не ставится"),
    (APP, b("const loadPrinterSortMode = async () => {\n        try { const r = await fetch('/api/printer-sort-mode'"),
     b("const loadPrinterSortMode = async () => {\n        { const r = await fetch('/api/printer-sort-mode'"),
     BOOT, True, "loadPrinterSortMode без try/catch (отказ endpoint может ломать)"),
    (IDX, b("if(shown) return; shown=true;"),
     b("shown=true;"),
     BOOT, True, "fallback shown-guard (reload-loop guard) удалён"),
    (IDX, b("show();                                             // пусто спустя bounded timeout"),
     b("void 0;                                             // пусто спустя bounded timeout"),
     BOOT, True, "fallback не раскрывается по timeout (show() убран)"),
    # copy / save-copy
    (APP, b("        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     b("        newPrinter.value = { id: p.id, name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     SORT, False, "stable ID источника копируется в черновик"),
    (APP, b("            if (keepOpen) {\n                // «Сохранить копию»: форма НЕ закрывается"),
     b("            if (false) {\n                // «Сохранить копию»: форма НЕ закрывается"),
     SORT, False, "save-copy закрывает форму (keep-open отключён)"),
    (APP, b("        if (printerAddBusy.value) return;   // запрос уже идёт"),
     b("        if (false) return;   // запрос уже идёт"),
     SORT, False, "double-click guard снят"),
    (IDX, b('@keydown.enter.prevent="addPrinterNode(false)"'),
     b('@keydown.enter.prevent="addPrinterNode(true)"'),
     SORT, False, "Enter вызывает save-copy вместо обычного Add", True),
    (APP, b("{ label: tr('Create copy'), icon: 'copy', action: () => openCopyPrinter(p) }"),
     b("{ label: tr('Create copyX'), icon: 'copy', action: () => openCopyPrinter(p) }"),
     SORT, False, "пункт «Создать копию» переименован/пропал"),
    (ORCH, b("\nDISPATCH_ENABLED = False"),
     b("\nDISPATCH_ENABLED = True"),
     BOOT, True, "DISPATCH включён"),
    (ORCH, b("\nTRANSPORT_ENABLED = False"),
     b("\nTRANSPORT_ENABLED = True"),
     BOOT, True, "TRANSPORT включён"),
    (REG, b('RB_RESTORE, SENS_NORMAL, False, "manual", 1,'),
     b('RB_RESTORE, SENS_NORMAL, False, "model", 1,'),
     SORT, False, "default сортировки становится model"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(name, skip_browser):
    env = dict(BASE_ENV)
    if skip_browser:
        env["FM_SKIP_BROWSER"] = "1"
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", name + ".py")],
                          env=env, capture_output=True, timeout=300).returncode


def main():
    # baseline
    for name, sb in sorted({(m[3], m[4]) for m in MUT}):
        if run_test(name, sb) != 0:
            print("BASELINE FAIL:", name, "(skip_browser=%s)" % sb); return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, sb, label, *rest in MUT:
        all_ = rest[0] if rest else False
        orig = open(path, "rb").read(); sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s]" % label); _n["miss"] += 1; _n["not_applied"] += 1; continue
        try:
            open(path, "wb").write(orig.replace(find, repl) if all_ else orig.replace(find, repl, 1)); rc = run_test(test, sb)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-54s] %-30s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_", ""), rc, reverted))
    print("\n" + "=" * 80)
    print("Mutation proof 2832: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))
    # Прежнее условие выхода сохранено дословно; ниже к нему добавляется process_rc из сводки.
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    # declared — объявлено поломок (len(MUT)); executed — реально исполнено (_executed, сумма
    # исходов итераций); caught — поломки, покрасневшие целевой тест (_n["caught"]).
    # Отдельных счётчиков таймаута, несостоявшегося отката и уборки в наборе НЕТ:
    # TimeoutExpired из run_test не ловится (набор падает с ненулевым кодом), а revert=False
    # уже учтён в _n["miss"] → timeouts/restore_failures/cleanup_failures = 0.
    _summary = _mut_build(declared=len(MUT),
                          executed=_executed - _n["not_applied"],
                          caught=_n["caught"],
                          timeouts=0,
                          restore_failures=0,
                          cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
