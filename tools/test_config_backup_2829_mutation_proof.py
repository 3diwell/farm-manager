# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — mutation proof: 24 порчи module-backup/атомарности/UX обязаны краснить тесты.

Для каждой мутации: точечная порча -> целевой тест -> НЕ-ноль -> побайтовое восстановление
(SHA-256). PYTHONDONTWRITEBYTECODE: без устаревших .pyc. Production data не трогается.
"""
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
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_config_backup_2829_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ENV = dict(os.environ)
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONDONTWRITEBYTECODE"] = "1"

CB = os.path.join(ROOT, "app", "config_backup")
T = os.path.join(ROOT, "tools")
WEB = os.path.join(ROOT, "web")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")


def _b(x):
    return x.encode("utf-8")


# (file, find, replace, test, replace_all, label)
MUT = [
    # 1. Старый backup «очищает» module data (absent -> пустой список)
    (f"{CB}/migrations/__init__.py", _b('raw["module_data"] = None                       # absent, НЕ пустой список'),
     _b('raw["module_data"] = {"section_schema_version": 1, "modules": []}'),
     "test_config_backup_v1", False, "старый backup считается пустым, а не отсутствующим"),
    # 2. Persistent module без provider пропускается
    (f"{CB}/module_providers.py", _b("        if p is None:\n            problems.append(mid)"),
     _b("        if p is None:\n            continue"),
     "test_module_backup_contract", False, "модуль без provider молча пропускается"),
    # 3. Inventory spool не экспортируется
    (f"{CB}/module_providers.py", _b('TableSpec("inv_spools", "id",'),
     _b('TableSpec("inv_spools_MISSING", "id",'),
     "test_inventory_backup_provider", False, "inventory spools не экспортируются"),
    # 4. Printer binding теряется
    (f"{CB}/module_providers.py", _b('"ams_printer_id", "ams_slot", "notes", "order_idx", "is_deleted",'),
     _b('"notes", "order_idx", "is_deleted",'),
     "test_inventory_backup_provider", False, "привязка к принтеру теряется"),
    # 5. Stable module ID заменяется display name
    (f"{CB}/module_providers.py", _b('    module_id = "inventory"'),
     _b('    module_id = "Складской учёт"'),
     "test_config_backup_module_data", False, "identity = display name вместо stable id"),
    # 6. Raw dump вместо canonical модели
    (f"{CB}/module_providers.py", _b('"domain_data": {"tables": tables}, "attachments_manifest": [], "extensions": {}}'),
     _b('"domain_data": {"raw_sql_dump": str(tables)}, "attachments_manifest": [], "extensions": {}}'),
     "test_inventory_backup_provider", False, "raw dump становится canonical backup"),
    # 7. Projects попадают в backup
    (f"{CB}/models.py", _b('"module_data": self.module_data,           # None сохраняется как null (absent-маркер)'),
     _b('"module_data": self.module_data,\n            "projects": [{"id": "leak"}], "parts_catalog": [],'),
     "test_config_backup_project_task_immutability", False, "projects попадают в backup"),
    # 8. Tasks попадают в backup
    (f"{CB}/models.py", _b('"module_data": self.module_data,           # None сохраняется как null (absent-маркер)'),
     _b('"module_data": self.module_data,\n            "staging_files": [{"filename": "leak"}], "staging_part_counts": [],'),
     "test_config_backup_project_task_immutability", False, "tasks попадают в backup"),
    # 9. Restore перестаёт защищать project-таблицы
    (f"{CB}/multistore.py", _b("            immutable_violated = (fp_fn() != fp_before)"),
     _b("            immutable_violated = False"),
     "test_config_backup_project_task_immutability", False, "изменение project table не ловится"),
    # 10. Failure module не откатывает core
    (f"{CB}/multistore.py", _b('            gateway.restore_full(pre["core"])'),
     _b('            _ = pre["core"]'),
     "test_config_backup_multistore_atomicity", False, "сбой модуля не откатывает core"),
    # 11. Модули не откатываются вовсе
    (f"{CB}/multistore.py", _b('                module_stores[mid].restore_full(pre["modules"][mid])'),
     _b('                _ = pre["modules"][mid]'),
     "test_config_backup_multistore_atomicity", False, "сбой не откатывает модули"),
    # 12. Rollback в прямом порядке
    (f"{CB}/multistore.py", _b("for mid in reversed([m for m, _p, _s in mod_snaps]):"),
     _b("for mid in [m for m, _p, _s in mod_snaps]:"),
     "test_config_backup_multistore_atomicity", False, "rollback в прямом порядке"),
    # 13. Verification модулей отключена
    (f"{CB}/multistore.py", _b("                if not prov.verify_restore(module_stores[mid], snap):"),
     _b("                if False:"),
     "test_config_backup_multistore_atomicity", False, "verification модулей отключена"),
    # 14. Missing module silently ignored
    (f"{CB}/multistore.py", _b("    if strict and missing:"),
     _b("    if False and missing:"),
     "test_config_backup_module_data", False, "missing module молча игнорируется"),
    # 15. Module newer schema угадывается
    (f"{CB}/module_providers.py", _b("        if v > self.backup_schema_version:"),
     _b("        if False:"),
     "test_module_backup_contract", False, "newer module schema угадывается"),
    # 16. Auto plan требует старую кнопку
    (f"{WEB}/app.js", _b("else { await cbInspect(token); }             // авто-план без пароля"),
     _b("else { /* ручная кнопка */ }"),
     "test_config_backup_auto_plan_ui", False, "auto plan отключён (нужна кнопка)"),
    # 17. Новый файл не очищает старый plan
    (f"{WEB}/app.js", _b("        cbPlan.value = null; cbInfo.value = null; cbMsg.value = null; cbDone.value = null;\n        cbImportRequiresPw.value = false; cbImportPw.value = ''; cbPhase.value = 'idle';"),
     _b("        cbImportRequiresPw.value = false; cbPhase.value = 'idle';"),
     "test_config_backup_auto_plan_ui", False, "новый файл не очищает старый план"),
    # 18. Restart overlay не снимается (reload выключен)
    (f"{WEB}/app.js", _b("hardReloadOnce(probe.bootId); return;"),
     _b("continue;"),
     "test_restore_restart_reconnect", True, "overlay не снимается (reload выключен)"),
    # 19. Новый процесс не проверяется
    (f"{WEB}/app.js", _b("if (probe.bootId && oldBoot && probe.bootId !== oldBoot)"),
     _b("if (false)"),
     "test_restore_restart_reconnect", False, "новый процесс не проверяется"),
    # 20. Hard reload зацикливается (guard снят)
    (f"{WEB}/app.js", _b("            if (sessionStorage.getItem(key) === String(newBootId)) return false;"),
     _b("            ;"),
     "test_restore_restart_reconnect", False, "hard reload зацикливается"),
    # 21. Timeout оставляет blocking overlay
    (f"{WEB}/app.js", _b("        restartPhase.value = 'timeout';"),
     _b("        restartPhase.value = 'waiting';"),
     "test_restore_restart_reconnect", True, "timeout не наступает (вечный overlay)"),
    # 22. Pending restart очищается до нового процесса
    (f"{WEB}/app.js", _b("const cbRestartLater = () => { cbDone.value = null; };"),
     _b("const cbRestartLater = () => { cbDone.value = null; try { localStorage.removeItem('fm_pending_restart_boot'); } catch (e) {} };"),
     "test_restore_restart_reconnect", False, "«Позже» стирает pending-маркер"),
    # 23. Active print разрешает restore
    (os.path.join(ROOT, "server.py"), _b("    if _cfgbackup_any_active_print():"),
     _b("    if False:"),
     "test_config_backup_module_data", False, "активная печать разрешает restore"),
    # 24. DISPATCH включается
    (ORCH, _b("\nDISPATCH_ENABLED = False"),
     _b("\nDISPATCH_ENABLED = True"),
     "test_external_reprint_sync", False, "DISPATCH включён по умолчанию"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(name):
    r = subprocess.run([sys.executable, os.path.join(T, name + ".py")], env=ENV,
                       capture_output=True, timeout=300)
    return r.returncode


def main():
    for t in sorted({m[3] for m in MUT}):
        if run_test(t) != 0:
            print("BASELINE FAIL:", t)
            return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, all_, label in MUT:
        orig = open(path, "rb").read()
        sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s] в %s" % (label, os.path.basename(path)))
            # Alpha 2.841: порча НЕ внесена (устаревший якорь). Считаем ОТДЕЛЬНО:
            # иначе executed == declared тождественно и mutation_not_applied мёртв.
            _n["miss"] += 1; _n["not_applied"] += 1
            continue
        mutated = orig.replace(find, repl) if all_ else orig.replace(find, repl, 1)
        try:
            open(path, "wb").write(mutated)
            rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-46s] %s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label,
                 test.replace("test_config_backup_", "").replace("test_", ""), rc, reverted))
    print("\n" + "=" * 74)
    print("Mutation proof 2829: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))
    # Alpha 2.841: машиночитаемый итог для релизного гейта — те же счётчики, что в сводке выше.
    # Отдельных счётчиков таймаутов, несостоявшегося отката и уборки в этом наборе НЕТ:
    # TimeoutExpired не ловится вовсе, а revert=False уже учтён как MISS → все три поля 0.
    _summary = _mut_build(declared=len(MUT),
                          executed=_executed - _n["not_applied"],
                          caught=_n["caught"],
                          timeouts=0,
                          restore_failures=0,
                          cleanup_failures=0)
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
