# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.830 — mutation proof: ≥18 порч self-restore/validation/safe-error/compat обязаны
краснить целевые тесты. Точечная порча -> целевой тест -> НЕ-ноль -> побайтовое восстановление
(SHA-256). PYTHONDONTWRITEBYTECODE; production data не трогается."""
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
acquire_or_die('test_config_backup_2830_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ENV = dict(os.environ); ENV["PYTHONIOENCODING"] = "utf-8"; ENV["PYTHONDONTWRITEBYTECODE"] = "1"

MPV = os.path.join(ROOT, "app", "config_backup", "module_providers.py")
SELF = os.path.join(ROOT, "app", "config_backup", "self_check.py")
ERR = os.path.join(ROOT, "app", "config_backup", "errors.py")
MIG = os.path.join(ROOT, "app", "config_backup", "migrations", "__init__.py")
MULTI = os.path.join(ROOT, "app", "config_backup", "multistore.py")
SRV = os.path.join(ROOT, "server.py")
APP = os.path.join(ROOT, "web", "app.js")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")
FX = os.path.join(ROOT, "tools", "fixtures", "config_backup")


def b(x):
    return x.encode("utf-8")


# (file, find, replace, test, replace_all, label)
MUT = [
    # 1. validator снова строг к висячей внутренней ссылке (root cause 2.829 возвращается)
    (MPV, "        return snapshot\n\n    def unresolved_internal_refs(self, snapshot):",
     "        for _sp in self.table_specs:\n            for _c, _t in _sp.refs.items():\n                for _r in tables.get(_sp.name) or []:\n                    if str(_r.get(_c) or '') and str(_r.get(_c)) not in keysets.get(_t, set()):\n                        raise BackupError(VALIDATION_FAILED, 'strict')\n        return snapshot\n\n    def unresolved_internal_refs(self, snapshot):",
     "test_config_backup_alpha_2829_compat", False, "validator снова отвергает висячую ссылку (2.829 root cause)"),
    # 2. структурная проверка дубликата ключа отключена
    (MPV, b('                if k in seen:\n                    raise BackupError(VALIDATION_FAILED, "duplicate key in %s" % spec.name)'),
     b('                if k in seen:\n                    pass'),
     "test_inventory_backup_provider", False, "структурный дубликат ключа больше не фатален"),
    # 3. apply обнуляет висячие ссылки (запрещённая коэрция дефолтом)
    (MPV, b("            store.upsert_rows(spec.name, [{c: r.get(c) for c in spec.columns} for r in rows], spec.key)"),
     b("            store.upsert_rows(spec.name, [{c: (None if c.endswith('_id') and c != spec.key else r.get(c)) for c in spec.columns} for r in rows], spec.key)"),
     "test_config_backup_alpha_2829_compat", False, "apply обнуляет висячую location_id (коэрция)"),
    # 4. self_check делают no-op (невалидная копия «проходит»)
    (SELF, b("    # 1-2. Round-trip decode + migrate + validate теми же production-функциями, что и restore."),
     b("    return {\"ok\": True, \"neutered\": True}\n    # 1-2. Round-trip decode + migrate + validate теми же production-функциями, что и restore."),
     "test_config_backup_self_restore", False, "self_check no-op (невалидная копия проходит)"),
    # 5. план перестаёт помечать висячую ссылку предупреждением
    (MPV, b('            plan["warnings"].append({"code": "dangling_internal_ref", "table": ur["table"],'),
     b('            _drop = ({"code": "dangling_internal_ref", "table": ur["table"],'),
     "test_config_backup_alpha_2829_compat", False, "dangling_internal_ref warning исчез из плана"),
    # 6. safe_structured протекает detail наружу
    (ERR, b('    out = {"status": "error", "reason": safe_reason(reason)}'),
     b('    out = {"status": "error", "reason": safe_reason(reason), "detail": str(getattr(err, "detail", ""))}'),
     "test_config_backup_validation_errors", False, "safe_structured протекает detail (значения наружу)"),
    # 7. http_status_for теряет 409-класс
    (ERR, b("    if r in _HTTP_409:\n        return 409"),
     b("    if False:\n        return 409"),
     "test_config_backup_validation_errors", False, "http_status теряет 409 (manual_resolution/active_prints)"),
    # 8. plan-ошибка перестаёт быть структурной (stage сломан)
    (SRV, b('        return JSONResponse(_cfgbackup_safe_structured(e, stage="plan"), status_code=_cfgbackup_http_status(e.reason))'),
     b('        return JSONResponse({"x": 1}, status_code=500)'),
     "test_config_backup_validation_errors", False, "plan-ошибка снова не структурная (unhandled-подобно)"),
    # 9. self-validation вызов удалён из маршрута экспорта
    # Alpha 2.869: окончания строк из якоря УБРАНЫ. Стояло \r\n — server.py был CRLF, но с 2.863
    # лежит с LF, и якорь не находился ни разу: порча молча превращалась в SETUP FAIL.
    # Окончания строк в проекте не гарантированы (.gitattributes: * -text) — не вписывать их в якорь.
    (SRV, b("        _cfgbackup_self_check.verify_exported_blob("),
     b("        _cfgbackup_self_check_REMOVED("),
     "test_config_backup_self_restore", False, "self-validation убрана из экспорта"),
    # 10. авто-план вызывает apply
    (APP, b("            const req = { mode: 'plan', backup_b64: cbImportB64.value };"),
     b("            const req = { mode: 'apply', backup_b64: cbImportB64.value };"),
     "test_config_backup_validation_errors", False, "авто-план вызывает apply"),
    # 11. cbErrorText теряет модульное сообщение (единственный текст возвращается)
    (APP, b("Резервная копия не прошла проверку данных модуля «"),
     b("XXX убрано «"),
     "test_config_backup_validation_errors", False, "cbErrorText теряет понятное RU-сообщение"),
    # 12. миграция v1->v2 создаёт пустой список вместо None (старая копия «очищает» модули)
    (MIG, b('    raw["module_data"] = None                       # absent, НЕ пустой список'),
     b('    raw["module_data"] = {"section_schema_version": 1, "modules": []}'),
     "test_config_backup_alpha_2829_compat", False, "старая копия считается пустой, а не отсутствующей"),
    # 13. immutable guard проектов/задач отключён
    (MULTI, b("            immutable_violated = (fp_fn() != fp_before)"),
     b("            immutable_violated = False"),
     "test_config_backup_project_task_immutability", False, "project/task fingerprint не проверяется"),
    # 14. DISPATCH включается
    (ORCH, b("\nDISPATCH_ENABLED = False"),
     b("\nDISPATCH_ENABLED = True"),
     "test_external_reprint_sync", False, "DISPATCH включён по умолчанию"),
    # 15. multistore не проставляет section/module_id (structured error теряет привязку)
    (MULTI, b("            if e.section is None:\n                e.section = \"modules\""),
     b("            if False:\n                e.section = \"modules\""),
     "test_config_backup_validation_errors", False, "structured error модуля теряет section"),
]

# Байтовые порчи замороженных фикстур (SHA обязан ловиться compat-тестами).
FIXFLIP = [
    (os.path.join(FX, "v1", "sample.3diwell-backup"), "test_config_backup_compatibility_forever",
     "frozen v1 fixture изменён"),
    (os.path.join(FX, "v2", "passwordless_v2.3diwell-backup"), "test_config_backup_compatibility_forever",
     "frozen v2 fixture изменён"),
    (os.path.join(FX, "module_data", "moduledata_v2.3diwell-backup"), "test_config_backup_compatibility_forever",
     "frozen module-data fixture изменён"),
    (os.path.join(FX, "regressions", "alpha_2_829_validation_failed", "dangling_ref_v2.3diwell-backup"),
     "test_config_backup_alpha_2829_compat", "frozen regression fixture изменён"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(name):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", name + ".py")], env=ENV,
                       capture_output=True, timeout=300)
    return r.returncode


def main():
    targets = sorted({m[3] for m in MUT} | {f[1] for f in FIXFLIP})
    for t in targets:
        if run_test(t) != 0:
            print("BASELINE FAIL:", t); return 1
    print("baseline: целевые тесты зелёные\n")

    for path, find, repl, test, all_, label in MUT:
        if isinstance(find, str): find = find.encode("utf-8")
        if isinstance(repl, str): repl = repl.encode("utf-8")
        orig = open(path, "rb").read(); sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s] в %s" % (label, os.path.basename(path)))
            # Alpha 2.841: порча НЕ внесена (устаревший якорь). Считаем ОТДЕЛЬНО:
            # иначе executed == declared тождественно и mutation_not_applied мёртв.
            _n["miss"] += 1; _n["not_applied"] += 1; continue
        mutated = orig.replace(find, repl) if all_ else orig.replace(find, repl, 1)
        try:
            open(path, "wb").write(mutated); rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-52s] %-38s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_config_backup_", "").replace("test_", ""),
                 rc, reverted))

    for path, test, label in FIXFLIP:
        orig = open(path, "rb").read(); sha0 = hashlib.sha256(orig).hexdigest()
        mid = len(orig) // 2
        mutated = orig[:mid] + bytes([orig[mid] ^ 0x01]) + orig[mid + 1:]
        try:
            open(path, "wb").write(mutated); rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-52s] %-38s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_config_backup_", "").replace("test_", ""),
                 rc, reverted))

    total = len(MUT) + len(FIXFLIP)
    print("\n" + "=" * 78)
    print("Mutation proof 2830: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], total))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    # Знаменатель — total: набор портит ДВЕ группы (MUT и FIXFLIP), а счётчик общий.
    _executed = _n["caught"] + _n["miss"]
    if _executed != total:
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, total))
    # Alpha 2.841: машиночитаемый итог для релизного гейта — печатается ПОСЛЕ
    # человекочитаемой сводки и не заменяет её. Прежнее условие выхода сохранено
    # как _rc_prev; ненулевым итог становится от любого из двух источников.
    # Отдельных счётчиков таймаута и несостоявшегося отката у набора нет: превышение
    # времени проверки поднимает исключение наружу, а revert=False уже учтён в miss.
    _rc_prev = 0 if (not _n["miss"] and _executed == total) else 1
    _summary = _mut_build(declared=total, executed=_executed - _n["not_applied"], caught=_n["caught"],
                          timeouts=0, restore_failures=0, cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
