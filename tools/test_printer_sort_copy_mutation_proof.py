# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.831 — mutation proof: ≥18 порч сортировки/копирования обязаны краснить тесты.
Точечная порча -> целевой тест -> НЕ-ноль -> побайтовое восстановление (SHA-256).
PYTHONDONTWRITEBYTECODE; production data не трогается."""
import hashlib
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
# Alpha 2.841: машиночитаемый итог набора — гейт обязан читать нули напрямую, а не из прозы.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_printer_sort_copy_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ENV = dict(os.environ); ENV["PYTHONIOENCODING"] = "utf-8"; ENV["PYTHONDONTWRITEBYTECODE"] = "1"

REG = os.path.join(ROOT, "app", "config_backup", "settings_registry.py")
APP = os.path.join(ROOT, "web", "app.js")
IDX = os.path.join(ROOT, "web", "index.html")
SRV = os.path.join(ROOT, "server.py")
RPR = os.path.join(ROOT, "app", "route_policy_registry.py")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")


def b(x):
    return x.encode("utf-8")


T = "test_printer_sort_and_copy"
# (file, find, replace, test, replace_all, label)
MUT = [
    (REG, b('RB_RESTORE, SENS_NORMAL, False, "manual", 1,'),
     b('RB_RESTORE, SENS_NORMAL, False, "model", 1,'),
     T, False, "default sort становится model"),
    (REG, b('_s("printer_sort_mode", STORE_CONFIG_JSON, T_STR, PORT_PORTABLE,'),
     b('_s("printer_sort_mode", STORE_CONFIG_JSON, T_STR, PORT_OPERATIONAL,'),
     T, False, "настройка не переносится в backup (operational)"),
    (REG, b('       RB_RESTORE, SENS_NORMAL, False, "manual", 1,\n       "режим сортировки'),
     b('       RB_EXCLUDE, SENS_NORMAL, False, "manual", 1,\n       "режим сортировки'),
     T, False, "настройка исключена из snapshot (restore=exclude)"),
    (APP, b("const _byPrinterName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true, sensitivity: 'base' });"),
     b("const _byPrinterName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: false, sensitivity: 'base' });"),
     T, False, "natural sort заменён lexical (X10 перед X2)"),
    (APP, b("if (ua !== ub) return ua ? 1 : -1;"),
     b("if (ua !== ub) return ua ? -1 : 1;"),
     T, False, "unknown-модели идут ПЕРЕД известными (теряют место)"),
    (APP, b("        return String(a.id || '').localeCompare(String(b.id || ''));   // стабильный tie-break по ID"),
     b("        return 0;   // стабильный tie-break по ID"),
     T, False, "tie-break по id убран (нестабильный порядок)"),
    # Якорь УНИКАЛЕН для openCopyPrinter (двухстрочная форма + copyBaseName ниже) — не openEditPrinter.
    (APP, b("        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     b("        newPrinter.value = { id: p.id, name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     T, False, "stable ID источника копируется в черновик"),
    (APP, b("        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     b("        newPrinter.value = { name: p.name, type: p.type, ip: p.ip, port: p.port, token: '', token2: 'LEAK',\n                             gen: p.gen || 'auto', serial: p.serial || '', model: p.model || '' };\n        copyBaseName.value = String(p.name || '');"),
     T, False, "в копию просачивается лишнее поле (не 8 editable)"),
    (APP, b("            if (keepOpen) {\n                // «Сохранить копию»: форма НЕ закрывается"),
     b("            if (false) {\n                // «Сохранить копию»: форма НЕ закрывается"),
     T, False, "save-copy больше не keep-open (форма закрывается)"),
    (APP, b("                _editedId = _newPrinterId();   // всегда НОВЫЙ уникальный id; id источника не наследуется"),
     b("                _editedId = 'node_src1';   // всегда НОВЫЙ уникальный id; id источника не наследуется"),
     T, False, "новый принтер переиспользует stable id (перезапись источника)"),
    (APP, b("        if (printerAddBusy.value) return;   // запрос уже идёт"),
     b("        if (false) return;   // запрос уже идёт"),
     T, False, "double-click guard снят (два принтера за клик)"),
    (IDX, b('<button v-if="!editingPrinterId && can(\'printer_write\')" data-help="pf-save-copy"'),
     b('<button v-if="can(\'printer_write\')" data-help="pf-save-copy"'),
     T, False, "«Сохранить копию» показывается и в edit mode"),
    (IDX, b('@keydown.enter.prevent="addPrinterNode(false)"'),
     b('@keydown.enter.prevent="addPrinterNode(true)"'),
     T, True, "Enter вызывает save-copy вместо обычного Add"),
    (APP, b("{ label: tr('Create copy'), icon: 'copy', action: () => openCopyPrinter(p) }"),
     b("{ label: tr('Create copyX'), icon: 'copy', action: () => openCopyPrinter(p) }"),
     T, False, "пункт «Создать копию» переименован/пропал"),
    (SRV, b("    if mode not in _PRINTER_SORT_MODES:"),
     b("    if False:"),
     T, False, "сервер принимает неизвестный режим сортировки"),
    (ORCH, b("\nDISPATCH_ENABLED = False"),
     b("\nDISPATCH_ENABLED = True"),
     T, False, "DISPATCH включён"),
    (ORCH, b("\nTRANSPORT_ENABLED = False"),
     b("\nTRANSPORT_ENABLED = True"),
     T, False, "TRANSPORT включён"),
    (RPR, b("    ('GET', '/api/printer-sort-mode', 'get_printer_sort_mode', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),"),
     b("    "),
     "test_route_policy_registry", False, "маршрут printer-sort-mode выпал из реестра политик"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(name):
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", name + ".py")],
                          env=ENV, capture_output=True, timeout=300).returncode


def main():
    for t in sorted({m[3] for m in MUT}):
        if run_test(t) != 0:
            print("BASELINE FAIL:", t); return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, all_, label in MUT:
        orig = open(path, "rb").read(); sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s]" % label); _n["miss"] += 1; _n["not_applied"] += 1; continue
        mutated = orig.replace(find, repl) if all_ else orig.replace(find, repl, 1)
        try:
            open(path, "wb").write(mutated); rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-52s] %-26s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_", ""), rc, reverted))
    print("\n" + "=" * 76)
    print("Mutation proof 2831: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))
    # Alpha 2.841: ОДНА машиночитаемая строка итога для релизного гейта. Человекочитаемая
    # сводка выше остаётся без изменений. Прежнее условие успеха сохранено как есть (_rc_prev);
    # итоговый код ненулевой, если ненулевой ЛИБО он, ЛИБО process_rc из сводки.
    # Счётчиков таймаутов и несостоявшегося отката в этом наборе нет (TimeoutExpired не ловится,
    # revert=False учитывается как MISS) — поэтому 0.
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    _summary = _mut_build(declared=len(MUT), executed=_executed - _n["not_applied"], caught=_n["caught"],
                          timeouts=0, restore_failures=0, cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
