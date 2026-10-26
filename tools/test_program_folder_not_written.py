# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Программа не пишет в собственную папку установки (Alpha 2.940).
#
# ЗАЧЕМ ЭТОТ НАБОР СУЩЕСТВУЕТ. Два дефекта подряд с одним корнем:
#   · 2.938 — журнал писался в BASE_DIR/logs, у клиента он молча замер на семь дней;
#   · 2.939 — кэш превью создавался в BASE_DIR/thumb_cache, и сервер ПАДАЛ ЦЕЛИКОМ.
# Второй измерен 02.09.2026 на чистой установке: server.py:769,
# PermissionError [WinError 5] на 'C:\\Program Files\\3DIWELL Farm Manager\\thumb_cache';
# сервер умирал, не дойдя ни до баз, ни до модулей, ни до HTTP, в журнале оставалась одна
# строка, а окно показывало «Локальный Farm Manager не найден».
#
# ПОЧЕМУ ЭТО НЕ ЛОВИЛОСЬ РАНЬШЕ. При запуске из исходников и при сборке в обычной папке
# BASE_DIR доступен на запись, и всё проходит. Дефект виден ТОЛЬКО там, где программа
# установлена в Program Files и запущена обычным пользователем, — то есть у владельца и у
# бета-тестера, а не на машине разработки.
#
# ЧТО ПРОВЕРЯЕТСЯ: каждая папка, которую сервер создаёт при старте, считается от DATA_DIR,
# а не от папки программы; ни один os.makedirs верхнего уровня не смотрит внутрь BASE_DIR.
#
# Ни сервера, ни сети, ни файлов: server.py разбирается как текст (AST).
#
# Запуск:  python tools/test_program_folder_not_written.py      (0 = всё в порядке)
# ============================================================================
import ast
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "server.py")
SENTINEL = "PROGRAM_FOLDER_NOT_WRITTEN_SENTINEL_2_940"

#  Папки, которые сервер создаёт или наполняет при старте. Все обязаны жить в DATA_DIR:
#  папка данных пишется всегда, независимо от способа запуска, и переживает обновления.
MUST_BE_IN_DATA_DIR = ("THUMB_CACHE_DIR", "UPLOAD_DIR", "TEMP_FILES_DIR", "LOG_DIR")

#  Единственное разрешённое обращение к самой папке программы: os.makedirs(BASE_DIR).
#  Оно безвредно — папка программы к этому моменту заведомо существует, и exist_ok=True
#  ничего не пишет. Любой ПОДПУТЬ внутри неё — уже дефект.
ALLOWED_MAKEDIRS_ROOTS = ("DATA_DIR", "BASE_DIR_ITSELF")

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def roots_of(src_text):
    """-> {имя переменной: имя корневой переменной}, для присваиваний вида
    NAME = os.path.join(ROOT, ...) на верхнем уровне модуля."""
    out = {}
    for node in ast.parse(src_text).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        v = node.value
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "join":
            if v.args and isinstance(v.args[0], ast.Name):
                out[tgt.id] = v.args[0].id
        elif isinstance(v, ast.Name):
            out[tgt.id] = out.get(v.id, v.id)
    return out


def makedirs_targets(src_text):
    """-> [(имя аргумента os.makedirs, строка)] для вызовов НА ВЕРХНЕМ УРОВНЕ модуля."""
    out = []
    for node in ast.parse(src_text).body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        c = node.value
        if isinstance(c.func, ast.Attribute) and c.func.attr == "makedirs" and c.args:
            a = c.args[0]
            if isinstance(a, ast.Name):
                out.append((a.id, node.lineno))
            elif isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "join":
                base = a.args[0].id if (a.args and isinstance(a.args[0], ast.Name)) else "<выражение>"
                out.append(("join:" + base, node.lineno))
    return out


def verdict(src_text):
    """-> список претензий. Пустой список = всё в порядке. Одна и та же функция служит и
    проверкой настоящего файла, и доказательством непустоты на изменённом."""
    bad = []
    roots = roots_of(src_text)
    for name in MUST_BE_IN_DATA_DIR:
        r = roots.get(name)
        if r is None:
            bad.append("%s: не найдена или собрана не через os.path.join" % name)
        elif r != "DATA_DIR":
            bad.append("%s считается от %s, а не от DATA_DIR" % (name, r))
    for arg, line in makedirs_targets(src_text):
        if arg == "BASE_DIR":
            continue                      # сама папка программы — см. ALLOWED_MAKEDIRS_ROOTS
        root = arg[5:] if arg.startswith("join:") else roots.get(arg, arg)
        if root == "DATA_DIR" or arg == "DATA_DIR":
            continue
        bad.append("os.makedirs(%s) в строке %d смотрит в %s" % (arg, line, root))
    return bad


SRC = io.open(SERVER, encoding="utf-8").read()

print("--- 1. Папки старта живут в папке данных, а не в папке программы ---")
roots = roots_of(SRC)
for name in MUST_BE_IN_DATA_DIR:
    check("%s считается от DATA_DIR" % name, roots.get(name) == "DATA_DIR",
          "корень: %s" % roots.get(name))

print("--- 2. Ни один os.makedirs при старте не смотрит внутрь папки программы ---")
targets = makedirs_targets(SRC)
print("   вызовов os.makedirs на верхнем уровне: %d — %s"
      % (len(targets), ", ".join("%s:%d" % t for t in targets)))
check("5. os.makedirs есть и они разобраны", bool(targets), targets)
inside = [t for t in targets if t[0] != "BASE_DIR" and roots.get(t[0], t[0]) not in ("DATA_DIR",)]
check("6. КОРЕНЬ ДЕФЕКТА 2.939: ни одного os.makedirs в подпапку программы", not inside, inside)

print("--- 3. Старые места переносятся, а не бросаются ---")
check("7. кэш превью переносится из папки программы",
      '_migrate_dir(os.path.join(BASE_DIR, "thumb_cache"), THUMB_CACHE_DIR)' in SRC)
check("8. журнал переносится из папки программы (2.938)", "_migrate_log_files" in SRC)

print("--- 4. Общий вердикт по нынешнему файлу ---")
now = verdict(SRC)
check("9. претензий к server.py нет", not now, now[:4])

print("--- 5. НЕ ВАКУУМ: проверка ловит именно то, что описано ---")
#  Возвращаем дефект 2.939 ровно в том виде, в каком он был, и требуем красного.
_old_2939 = SRC.replace('THUMB_CACHE_DIR = os.path.join(DATA_DIR, "thumb_cache")',
                        'THUMB_CACHE_DIR = os.path.join(BASE_DIR, "thumb_cache")', 1)
check("10. дефект 2.939 (кэш превью в папке программы) был бы пойман",
      _old_2939 != SRC and bool(verdict(_old_2939)), verdict(_old_2939)[:2])

#  И дефект 2.938 — журнал в папке программы.
_old_2938 = SRC.replace('LOG_DIR = os.path.join(DATA_DIR, "logs")',
                        'LOG_DIR = os.path.join(BASE_DIR, "logs")', 1)
check("11. дефект 2.938 (журнал в папке программы) был бы пойман",
      _old_2938 != SRC and bool(verdict(_old_2938)), verdict(_old_2938)[:2])

#  И прямое создание подпапки внутри программы, даже без отдельной переменной.
_direct = SRC.replace("os.makedirs(THUMB_CACHE_DIR, exist_ok=True)",
                      'os.makedirs(os.path.join(BASE_DIR, "cache2"), exist_ok=True)', 1)
check("12. прямой os.makedirs внутрь папки программы был бы пойман",
      _direct != SRC and bool(verdict(_direct)), verdict(_direct)[:2])

#  Обратная сторона: на нынешнем файле проверка молчит — значит она не «всегда красная».
check("13. на исправленном файле проверка молчит", not verdict(SRC), verdict(SRC)[:2])

print("")
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for n in _fail:
        print("  провалено: %s" % n)
sys.exit(1 if _fail else 0)
