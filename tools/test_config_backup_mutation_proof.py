# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — mutation proof: каждая порча ядра config_backup ДОЛЖНА краснить тест.

Доказывает, что тесты контракта НЕ вакуумны. Для каждой мутации: применить точечную порчу
исходника, прогнать целевой тест, потребовать НЕ-ноль (порча поймана), затем ВОССТАНОВИТЬ
байты и сверить SHA-256 (файл вернулся дословно). Любая непойманная мутация -> проф провален.
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
acquire_or_die('test_config_backup_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ENV = dict(os.environ); ENV["PYTHONIOENCODING"] = "utf-8"

CB = os.path.join(ROOT, "app", "config_backup")
T = os.path.join(ROOT, "tools")

# (файл, find, replace, тест, replace_all, метка)
MUT = [
    # ── crypto -> contract ──
    (f"{CB}/crypto.py", "AESGCM(key).decrypt(nonce, bytes(ciphertext), aad)",
     "AESGCM(key).decrypt(nonce, bytes(ciphertext), None)", "test_config_backup_contract", False,
     "decrypt игнорирует AAD"),
    (f"{CB}/crypto.py", 'raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "auth tag mismatch")',
     'raise BackupError(BACKUP_INVALID, "auth tag mismatch")', "test_config_backup_contract", False,
     "oracle: разный код на неверный пароль"),
    (f"{CB}/crypto.py", "KDF_N_MIN = 1 << 14", "KDF_N_MIN = 1 << 2", "test_config_backup_contract", False,
     "ослаблен floor KDF"),
    (f"{CB}/crypto.py", "return os.urandom(NONCE_LEN)", "return bytes(NONCE_LEN)",
     "test_config_backup_contract", False, "детерминированный nonce"),
    (f"{CB}/crypto.py", 'if passphrase is None or passphrase == "":', "if passphrase is None:",
     "test_config_backup_contract", False, "пустой пароль разрешён"),
    # ── container -> contract ──
    (f"{CB}/container_v1.py", "if cfv > schemas.CONTAINER_FORMAT_VERSION:", "if False:",
     "test_config_backup_contract", False, "не отклоняет будущую версию контейнера"),
    (f"{CB}/container_v1.py", "if cap not in schemas.KNOWN_READER_CAPABILITIES:", "if False:",
     "test_config_backup_contract", False, "не отклоняет неизвестную возможность"),
    (f"{CB}/container_v1.py", "json.dumps(obj, sort_keys=True, separators",
     "json.dumps(obj, sort_keys=False, separators", "test_config_backup_contract", False,
     "canonical_json теряет детерминизм (sort_keys)"),
    # ── registry -> contract ──
    (f"{CB}/settings_registry.py", "RB_IMPORT_AS_OFF, SENS_SECURITY,", "RB_RESTORE, SENS_SECURITY,",
     "test_config_backup_contract", False, "delete не импортируется как OFF"),
    (f"{CB}/settings_registry.py", "RB_CURRENT_ONLY, SENS_PATH, True,", "RB_RESTORE, SENS_PATH, True,",
     "test_config_backup_contract", False, "data_dir не current_only"),
    # ── serializer -> contract ──
    (f"{CB}/serializer.py", "value = False   # деструктивная", "value = True   # деструктивная",
     "test_config_backup_contract", False, "import_as_off не форсирует OFF"),
    (f"{CB}/serializer.py", "if apply_machine_bound:", "if True:", "test_config_backup_contract", False,
     "machine_bound применяется по умолчанию"),
    # ── validator -> v1 ──
    (f"{CB}/validator.py", "if psv > schemas.PAYLOAD_SCHEMA_VERSION:", "if False:",
     "test_config_backup_v1", False, "принимает payload из будущего"),
    (f"{CB}/validator.py", "if sv > schemas.CORE_SETTINGS_SCHEMA:", "if False:",
     "test_config_backup_v1", False, "принимает будущую core-схему"),
    (f"{CB}/validator.py", "if known is not None and asv > known:", "if False:",
     "test_config_backup_v1", False, "принимает будущую схему адаптера"),
    (f"{CB}/validator.py", "if snap.stable_id in seen:", "if False:", "test_config_backup_v1", False,
     "принимает дубликат stable_id"),
    (f"{CB}/validator.py", '_need(sid != "", "printer stable_id empty")', '_need(True, "x")',
     "test_config_backup_v1", False, "принимает пустой stable_id"),
    # ── migrations -> v1 ──
    (f"{CB}/migrations/__init__.py", "if v > target:", "if False:", "test_config_backup_v1", False,
     "миграция не отклоняет будущее"),
    # ── restore_engine -> atomicity ──
    (f"{CB}/restore_engine.py", "gateway.restore_full(pre)", "pass", "test_config_backup_restore_atomicity",
     True, "нет отката при сбое применения"),
    (f"{CB}/restore_engine.py", "if e and e.restart_required:", "if e and False:",
     "test_config_backup_restore_atomicity", False, "не сообщает restart_required"),
    # ── restore_plan -> atomicity ──
    (f"{CB}/restore_plan.py", "e.sensitivity == reg.SENS_NETWORK and bool(new_val):",
     "e.sensitivity == reg.SENS_NETWORK and bool(new_val) and False:",
     "test_config_backup_restore_atomicity", False, "нет предупреждения о сети"),
    (f"{CB}/restore_plan.py", '"code": "destructive_off", "key": e.key,',
     '"code": "destructive_OFF_renamed", "key": e.key,',
     "test_config_backup_restore_atomicity", False, "нет предупреждения о деструктиве"),
    (f"{CB}/restore_plan.py", "if not apply_machine_bound and mb_items:", "if False and mb_items:",
     "test_config_backup_restore_atomicity", False, "нет предупреждения machine_bound_kept"),
    # ── recovery -> atomicity ──
    (f"{CB}/recovery.py", '"pre_image": None,', '"pre_image": (self.read() or {}).get("pre_image"),',
     "test_config_backup_restore_atomicity", False, "pre-image не затирается"),
    (f"{CB}/recovery.py", "return bool(j and isinstance(st, str) and st and st != STATE_COMPLETE)",
     "return False",
     "test_config_backup_restore_atomicity", False, "is_pending всегда False"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(name):
    r = subprocess.run([sys.executable, os.path.join(T, name + ".py")], env=ENV,
                       capture_output=True, timeout=120)
    return r.returncode


def main():
    # baseline: все тесты зелёные ДО мутаций
    for t in sorted({m[3] for m in MUT}):
        rc = run_test(t)
        if rc != 0:
            print("BASELINE FAIL: %s (rc=%d) — прекращаю" % (t, rc))
            return 1
    print("baseline: все целевые тесты зелёные\n")

    for path, find, repl, test, all_, label in MUT:
        orig = open(path, "rb").read()
        sha0 = hashlib.sha256(orig).hexdigest()
        fb = find.encode("utf-8")
        if orig.count(fb) < 1:
            print("SETUP FAIL: не найден якорь [%s] в %s" % (label, os.path.basename(path)))
            # Alpha 2.841: порча НЕ внесена (устаревший якорь). Считаем ОТДЕЛЬНО:
            # иначе executed == declared тождественно и mutation_not_applied мёртв.
            _n["miss"] += 1; _n["not_applied"] += 1
            continue
        mutated = orig.replace(fb, repl.encode("utf-8")) if all_ else orig.replace(fb, repl.encode("utf-8"), 1)
        try:
            open(path, "wb").write(mutated)
            rc = run_test(test)
        finally:
            open(path, "wb").write(orig)   # revert
        sha1 = hashlib.sha256(open(path, "rb").read()).hexdigest()
        reverted = (sha1 == sha0)
        caught = (rc != 0)
        ok = caught and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-40s] тест %s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_config_backup_", ""), rc, reverted))

    print("\n" + "=" * 70)
    print("Mutation proof: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))
    # Alpha 2.841: машиночитаемый итог для релизного гейта — печатается ПОСЛЕ
    # человекочитаемой сводки и не заменяет её. Прежнее условие выхода сохранено
    # как _rc_prev; ненулевым итог становится от любого из двух источников.
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    _summary = _mut_build(declared=len(MUT), executed=_executed - _n["not_applied"], caught=_n["caught"],
                          timeouts=0, restore_failures=0, cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
