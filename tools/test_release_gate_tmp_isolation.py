# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.853 — временная папка полного прогона обязана быть изолирована от репозитория.

ЗАЧЕМ ЭТОТ НАБОР СУЩЕСТВУЕТ. На рабочей машине владельца `TEMP` лежит на `C:`, а репозиторий на
`D:`. Пятнадцать наборов из-за этого падали в `os.path.relpath` («path is on mount 'C:', start on
mount 'D:'») ЕЩЁ ДО СВОИХ ПРОВЕРОК: они не выполнялись вовсе, а гейт показывал их красными —
настоящая поломка внутри них осталась бы незамеченной. Полный прогон стал сам выдавать наборам
временную папку на диске репозитория.

ЦЕНА ПЕРВОЙ ПОПЫТКИ. Каталог назвали «<репозиторий>.gate_tmp» — он СОДЕРЖИТ путь репозитория как
подстроку. Наборы-песочницы проверяют собственную изоляцию условиями вида «REPO not in ROOT» и
«not ROOT.startswith(REPO)», и 19.08.2026 полный прогон показал: семь ранее зелёных наборов стали
красными (test_project_name_only_folders 100d, test_canonical_project_task_folders 40a,
test_project_folder_rename_consistency 58a, test_desktop_shell 89c, test_orchestrator_git_adapter 87
и два fixture_v2 «полигон вне рабочего репозитория»). Проверки были ПРАВЫ — ошибка была в имени.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ: каталог лежит на диске репозитория; он НЕ внутри репозитория; путь
репозитория не является его подстрокой и он не начинается с пути репозитория — ровно те условия,
которыми проверяют себя песочницы; при системном TEMP на диске репозитория подмены не происходит;
сбой создания каталога не роняет прогон. Отдельно — НЕ ВАКУУМ: прежнее имя эти условия нарушало.

Ничего не запускает и не печатает: только вызывает gate_tmp_dir и сверяет путь.

Запуск:  python tools/test_release_gate_tmp_isolation.py      (0 = изоляция соблюдена)
"""
import importlib.util
import io
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(REPO, "tools", "release_gate.py")
SENTINEL = "RELEASE_GATE_TMP_ISOLATION_SENTINEL_2_853"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def load_gate():
    spec = importlib.util.spec_from_file_location("release_gate_probe", GATE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gate = load_gate()
check("1. раннер полного прогона загружен и объявляет временную папку",
      hasattr(gate, "gate_tmp_dir") and callable(gate.gate_tmp_dir))

d = gate.gate_tmp_dir()
same_drive = (os.path.splitdrive(tempfile.gettempdir())[0].upper()
              == os.path.splitdrive(gate.ROOT)[0].upper())

print("--- 2. Условия изоляции — те же, которыми проверяют себя песочницы ---")
if same_drive:
    check("2. системный TEMP уже на диске репозитория — подмены не происходит", d == "", d)
    print("     (проверки 3-7 относятся к подставляемому каталогу; здесь он не нужен)")
    cand = os.path.join(os.path.dirname(gate.ROOT), "_3diwell_gate_tmp")
else:
    check("2. системный TEMP на другом диске — каталог подставляется", bool(d), d)
    cand = d

_R = os.path.normcase(os.path.abspath(gate.ROOT))
_C = os.path.normcase(os.path.abspath(cand))
check("3. каталог на ДИСКЕ РЕПОЗИТОРИЯ — иначе os.path.relpath снова упадёт",
      os.path.splitdrive(_C)[0] == os.path.splitdrive(_R)[0], (cand, gate.ROOT))
check("4. каталог НЕ внутри репозитория — временные файлы поймала бы проверка гигиены",
      not _C.startswith(_R + os.sep) and _C != _R, cand)
check("5. путь репозитория НЕ является подстрокой пути каталога "
      "(условие test_project_name_only_folders 100d)", _R not in _C, (cand, gate.ROOT))
check("6. путь каталога НЕ начинается с пути репозитория "
      "(условие test_orchestrator_git_adapter 87 и fixture_v2)", not _C.startswith(_R), cand)
check("7. репозиторий не внутри временного каталога (обратное направление тоже опасно)",
      not _R.startswith(_C + os.sep), (cand, gate.ROOT))

print("--- 3. НЕ ВАКУУМ: прежнее имя эти условия нарушало ---")
_bad = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(gate.ROOT),
                                                     os.path.basename(gate.ROOT) + ".gate_tmp")))
check("8. «<репозиторий>.gate_tmp» СОДЕРЖИТ путь репозитория — проверка меряет разницу, а не себя",
      _R in _bad and _bad.startswith(_R), _bad)
check("9. и нынешний каталог этим свойством не обладает", not (_R in _C or _C.startswith(_R)), _C)

print("--- 4. Прогон не должен падать из-за собственной оснастки ---")
_real = os.makedirs
try:
    os.makedirs = lambda *a, **k: (_ for _ in ()).throw(OSError("нет прав"))
    check("10. каталог создать не удалось — возвращается пусто, прогон идёт как раньше",
          gate.gate_tmp_dir() == "")
finally:
    os.makedirs = _real
check("11. после восстановления функция снова работает",
      (gate.gate_tmp_dir() == "") if same_drive else bool(gate.gate_tmp_dir()))

print("--- 5. Раннер по-прежнему не ослаблен ---")
SRC = io.open(GATE, encoding="utf-8").read()
check("12. манифест по-прежнему без исключений", '"excluded": []' in SRC and "excluded_files" in SRC)
check("13. подстановка идёт ТОЛЬКО в окружение дочерних процессов, а не в сам прогон",
      'env["TEMP"] = env["TMP"] = env["TMPDIR"] = _tmp' in SRC)
check("14. выбранный каталог назван вслух в выводе прогона", "временная папка наборов" in SRC)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
