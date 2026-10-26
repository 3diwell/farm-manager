# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.928 — счёт распечатанного не затирается (жалоба владельца 29.08.2026).

ДЕФЕКТ, КОТОРЫЙ ЗАКРЕПЛЯЕТСЯ НАВСЕГДА. Сохранение задачи писало ВСЕ поля с умолчаниями
для неприсланных: правка одной заметки затирала на сервере счёт удачных печатей
устаревшим экранным значением. Владелец видел «печатаю второй раз — счёт стоит».
Теперь сервер пишет ТОЛЬКО присланные поля.

БЕЗОПАСНОСТЬ — как в test_queue_wait: сервер целиком НЕ импортируется, рабочая база
не открывается. Исполняется ИСХОДНЫЙ ТЕКСТ функции save_staging поверх временной базы.

Запуск:  python tools/test_staging_count.py
"""
import ast
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "STAGING_COUNT_SENTINEL_2_928"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()

print("--- 1. серверный зачёт удачной печати не ограничен планом ---")
#  Сам инкремент: np = printed + 1 без всякого «если меньше плана». Проверяем, что
#  потолка не появилось: рядом с инкрементом нет сравнения с required до записи.
check("1. зачёт печати — безусловный «+1», потолка по плану нет",
      SRC.count('np = (row["printed_qty"] or 0) + 1') == 1
      and SRC.count('np = (r["printed_qty"] or 0) + 1') == 1
      and "if np <= " not in SRC and "np < (row" not in SRC)
check("2. статус строки: план достигнут или превышен -> «done» (2 из 1 — тоже done)",
      SRC.count("'done' if np >= (row[\"required_qty\"] or 1) else 'ready'") == 1
      or SRC.count("'done' if np >= (r[\"required_qty\"] or 1) else 'ready'") >= 1)

print("--- 2. частичное сохранение: НАСТОЯЩИЙ save_staging на временной базе ---")
_tree = ast.parse(SRC)
_fn = None
for node in ast.walk(_tree):
    if isinstance(node, ast.FunctionDef) and node.name == "save_staging":
        _fn = ast.get_source_segment(SRC, node)
check("3. исходник save_staging найден", bool(_fn))
#  Срезаем декоратор маршрута — исполняем чистую функцию.
_fn_body = _fn[_fn.index("def save_staging"):] if _fn else ""

_tmp = tempfile.mkdtemp(prefix="stcnt928_")
conn_p = sqlite3.connect(os.path.join(_tmp, "parts.db"), check_same_thread=False)
conn_p.row_factory = sqlite3.Row
conn_p.execute("CREATE TABLE staging_files (filename TEXT PRIMARY KEY,"
               " required_qty INTEGER DEFAULT 1, printed_qty INTEGER DEFAULT 0,"
               " notes TEXT DEFAULT '')")
conn_p.execute("INSERT INTO staging_files (filename, required_qty, printed_qty, notes)"
               " VALUES ('korpus.gcode.3mf', 1, 2, 'PLA')")
conn_p.commit()
NS = {"os": os, "conn_p": conn_p, "lock_p": threading.RLock()}
exec(_fn_body, NS)          # noqa: S102 — свой исходник в песочнице
save_staging = NS["save_staging"]


def row():
    return dict(conn_p.execute("SELECT * FROM staging_files WHERE filename='korpus.gcode.3mf'")
                .fetchone())


#  СЦЕНАРИЙ ЖАЛОБЫ: на сервере счёт 2 (план 1). Владелец правит ТОЛЬКО заметку.
r = save_staging({"filename": "korpus.gcode.3mf", "notes": "ABS, после смены сопла"})
d = row()
check("4. КОРЕНЬ ЖАЛОБЫ: правка одной заметки НЕ затирает счёт печати и план",
      r.get("status") == "ok" and d["printed_qty"] == 2 and d["required_qty"] == 1
      and d["notes"] == "ABS, после смены сопла", d)

r = save_staging({"filename": "korpus.gcode.3mf", "required_qty": 5})
d = row()
check("5. правка одного плана не трогает счёт и заметку",
      d["required_qty"] == 5 and d["printed_qty"] == 2 and d["notes"] == "ABS, после смены сопла", d)

r = save_staging({"filename": "korpus.gcode.3mf", "printed_qty": 7})
d = row()
check("6. правка одного счёта работает и не трогает остальное",
      d["printed_qty"] == 7 and d["required_qty"] == 5, d)

r = save_staging({"filename": "korpus.gcode.3mf", "required_qty": 3,
                  "printed_qty": 1, "notes": "x"})
d = row()
check("7. прежний вызов со всеми полями работает как раньше",
      d["required_qty"] == 3 and d["printed_qty"] == 1 and d["notes"] == "x", d)

check("8. запрос без единого поля — ошибка, а не тихое затирание умолчаниями",
      save_staging({"filename": "korpus.gcode.3mf"}).get("status") == "error")
check("9. отрицательное число не проходит (пол — ноль)",
      save_staging({"filename": "korpus.gcode.3mf", "printed_qty": -4}).get("status") == "ok"
      and row()["printed_qty"] == 0)

print("--- 3. экран: метки по-полевые, фокус ничего не замораживает ---")
check("10. метка «правится» ставится на ПОЛЕ, а не на всю строку",
      "stagingDirty.value = { ...stagingDirty.value, [f.filename]: cur }" in APPJS
      and "const markStagingDirty = (f, field)" in APPJS)
check("11. опрос сервера подменяет только правящееся поле, остальные — живые",
      "if (df.required_qty) nf.required_qty = old.required_qty;" in APPJS
      and "if (df.printed_qty) nf.printed_qty = old.printed_qty;" in APPJS)
check("12. сохранение шлёт только правившиеся поля",
      "const saveStaging = async (f, fields)" in APPJS
      and "saveStaging(f, [field])" in APPJS)
check("13. ФОКУС в поле больше НЕ ставит метку — клик без правки не морозит счёт",
      '@focus="markStagingDirty' not in IDX)
#  2.951 завела ВТОРУЮ разметку строки задачи — для оформления 3.0. Она включается
#  v-if="ui3Mode", прежняя — v-if="!ui3Mode", то есть на экране всегда ровно одна из двух.
#  Поэтому считать «сколько мест» бессмысленно; важно, что каждое место сохраняет ТОЛЬКО СВОЁ
#  поле, что план и итог идут парой (иначе одну из строк забыли) и что нет вызова без списка.
_n_notes = IDX.count("saveStaging(f, ['notes'])")
_n_req = IDX.count("saveStaging(f, ['required_qty'])")
_n_pri = IDX.count("saveStaging(f, ['printed_qty'])")
check("14. каждое поле в разметке метит и сохраняет только себя",
      _n_notes >= 1 and _n_req >= 1 and _n_req == _n_pri
      and "saveStaging(f)\"" not in IDX,
      (_n_notes, _n_req, _n_pri))

try:
    conn_p.close()
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
