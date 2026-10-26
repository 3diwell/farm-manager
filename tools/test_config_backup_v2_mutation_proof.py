# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.828 — mutation proof v2: каждая порча контракта v2/совместимости краснит тест.

Для каждой мутации: точечная порча -> прогон целевого теста -> требуем НЕ-ноль (поймана) ->
ВОССТАНОВЛЕНИЕ байтов + сверка SHA-256. Работает и с бинарной frozen-фикстурой, и с текстом.
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
acquire_or_die('test_config_backup_v2_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ENV = dict(os.environ); ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONDONTWRITEBYTECODE"] = "1"   # не писать .pyc: мутация+revert не оставляют устаревший кэш
CB = os.path.join(ROOT, "app", "config_backup")
T = os.path.join(ROOT, "tools")
WEB = os.path.join(ROOT, "web")
FIXV1 = os.path.join(ROOT, "tools", "fixtures", "config_backup", "v1", "sample.3diwell-backup")
DOCV1 = os.path.join(ROOT, "docs", "BACKUP_FORMAT_V1.md")

def _b(s): return s.encode("utf-8")

# (file, find_bytes, replace_bytes, test, all, label)
MUT = [
    (FIXV1, b"PK", b"ZZ", "test_config_backup_compatibility_forever", False, "v1 fixture байты изменены"),
    (f"{CB}/serializer.py", _b("header_bytes, header, ciphertext = container_v1.read_container(container_bytes)"),
     _b("header_bytes, header, ciphertext = container_v2.read_container_v2(container_bytes)"),
     "test_config_backup_compatibility_forever", False, "v1 reader обойдён (misroute на v2)"),
    (f"{CB}/schemas.py", _b('DEFAULT_PROTECTION_MODE = PROTECTION_MODE_NONE'),
     _b('DEFAULT_PROTECTION_MODE = PROTECTION_MODE_PASSWORD'), "test_config_backup_v2", False,
     "default export снова требует пароль"),
    (f"{CB}/repository.py", _b('credentials={"token": str(row.get("token") or "")},'),
     _b('credentials={},'), "test_config_backup_v2", False, "passwordless omits credentials"),
    (f"{WEB}/index.html", _b("Храните файл в защищённом месте"), _b("Xploaded"),
     "test_config_backup_v2", False, "passwordless UI прячет предупреждение"),
    (f"{CB}/container_v2.py", _b('    h["payload_encoding"] = schemas.PAYLOAD_ENCODING_CANONICAL_JSON'),
     _b('    h["payload_encoding"] = schemas.PAYLOAD_ENCODING_CANONICAL_JSON\n    h["leak"] = payload_plaintext.decode("utf-8", "ignore")'),
     "test_config_backup_v2", False, "header содержит credential (leak)"),
    (f"{CB}/container_v2.py", _b('    h["payload_sha256"] = _sha256_hex(payload_plaintext)'),
     _b('    h["payload_sha256"] = "0" * 64'), "test_config_backup_v2", False,
     "payload SHA-256 не вычисляется корректно (integrity)"),
    (f"{CB}/container_v2.py", _b('plaintext = crypto.decrypt(body, passphrase, salt, nonce, aad=header_bytes_raw, n=n, r=r, p=pp)'),
     _b('plaintext = crypto.decrypt(body, passphrase, salt, nonce, aad=b"", n=n, r=r, p=pp)'),
     "test_config_backup_compatibility_forever", False, "protected mode не использует AAD"),
    (f"{CB}/crypto.py", _b('raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "auth tag mismatch")'),
     _b('raise BackupError(BACKUP_INVALID, "auth tag mismatch")'), "test_config_backup_v2", False,
     "wrong password раскрывает oracle"),
    (f"{WEB}/index.html", _b("Создать резервную копию"), _b("Скачать копию"),
     "test_config_backup_v2", False, "UI снова пишет 'Скачать копию'"),
    (f"{WEB}/index.html", _b("относятся к этому компьютеру"), _b("machine-bound stuff"),
     "test_config_backup_v2", False, "пояснение путей снова непонятное"),
    (f"{WEB}/index.html", _b("Перезапустить Farm Manager"), _b("XX"),
     "test_config_backup_v2", False, "кнопка перезапуска отсутствует"),
    (f"{WEB}/index.html", _b("Конфигурация восстановлена"), _b("XX"),
     "test_config_backup_v2", False, "success panel отсутствует"),
    (f"{CB}/restore_engine.py", _b('    journal.complete()\n    restart = _restart_required(mutation)'),
     _b('    restart = _restart_required(mutation)'), "test_config_backup_restore_atomicity", False,
     "restart-путь: журнал не завершается (complete) до возврата"),
    (f"{CB}/container_v2.py", _b('    h["container_format_version"] = schemas.CONTAINER_FORMAT_VERSION_2'),
     _b('    h["container_format_version"] = 1'), "test_config_backup_v2", False,
     "v2 header подделывает версию (container_format_version=1)"),
    (f"{CB}/container_v2.py", _b('if mode not in schemas.PROTECTION_MODES:'), _b('if False:'),
     "test_config_backup_v2", False, "unknown protection mode принимается"),
    (f"{CB}/serializer.py", _b('if apply_machine_bound:'), _b('if True:'),
     "test_config_backup_contract", False, "machine-bound применяется молча"),
    (f"{CB}/settings_registry.py", _b('RB_IMPORT_AS_OFF, SENS_SECURITY,'), _b('RB_RESTORE, SENS_SECURITY,'),
     "test_config_backup_contract", False, "delete flag импортируется ON"),
    (f"{CB}/schemas.py", _b('MAX_CONTAINER_FORMAT_VERSION = 2'), _b('MAX_CONTAINER_FORMAT_VERSION = 1'),
     "test_config_backup_v2", False, "reader v2 отрезан (max=1)"),
    (DOCV1, _b("AES-256-GCM"), _b("ROT13-CIPHER"), "test_config_backup_v2", True,
     "v1 docs semantics изменены"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}
def run_test(name):
    r = subprocess.run([sys.executable, os.path.join(T, name + ".py")], env=ENV, capture_output=True, timeout=120)
    return r.returncode

def main():
    for t in sorted({m[3] for m in MUT}):
        if run_test(t) != 0:
            print("BASELINE FAIL:", t); return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, all_, label in MUT:
        orig = open(path, "rb").read()
        sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s] в %s" % (label, os.path.basename(path))); _n["miss"] += 1; _n["not_applied"] += 1; continue
        mutated = orig.replace(find, repl) if all_ else orig.replace(find, repl, 1)
        try:
            open(path, "wb").write(mutated); rc = run_test(test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-42s] %s rc=%d revert=%s" % ("CAUGHT" if ok else "MISS  ", label,
              test.replace("test_config_backup_", ""), rc, reverted))
    print("\n" + "=" * 70)
    print("Mutation proof v2: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
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
