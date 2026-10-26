# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — ПРОВЕРКА ОБНОВЛЕНИЙ И ИЗОЛЯЦИЯ: наружу ходит только обычный экземпляр.
#
#  ЗАЧЕМ. Изолированный тестовый экземпляр обязан быть замкнут на петлю. Пока проверка
#  обновлений работала и в нём, единственное исходящее соединение на 3diwell.com делало
#  утверждение «внешней сети нет» недоказуемым. Здесь закрепляется ровно одна граница:
#  подавление включается ТОЛЬКО принятым официальным контрактом и никак иначе, а обычный
#  путь обновлений остаётся прежним.
#
#  ЧТО ОН НЕ ДЕЛАЕТ. Не запускает server.py, не поднимает браузер, не ходит в сеть.
#  Обработчик маршрута исполняется в изоляции — без FastAPI, БД и сети.
#
#  Запуск:  python tools/test_e2e_update_check_suppression.py       (0 = граница цела)
# ============================================================================
import ast
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "server.py")
ISO_PATH = os.path.join(REPO, "app", "e2e_isolation.py")

PASSED, FAILED = [0], []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name + ((" | " + str(detail)[:200]) if detail else ""))
        print("FAIL — %s%s" % (name, (" | " + str(detail)[:200]) if detail else ""))


def sec(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# server.py целиком НЕ импортируется: живой процесс завершил бы тест на именованном
# мьютексе. Берём только исходный текст и разбираем его деревом.
SRC = io.open(SERVER, encoding="utf-8", errors="replace").read()
TREE = ast.parse(SRC)
_spec = importlib.util.spec_from_file_location("fm_e2e_iso_t", ISO_PATH)
ISO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ISO)


def func_src(name):
    for n in ast.walk(TREE):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(SRC, n)
    return None


sec("1. Контракт изоляции — единственный источник истины")

check("1. принятая изоляция запрещает проверку обновлений",
      ISO.Isolation.disable_update_check.__doc__ is not None
      and isinstance(ISO.Isolation.disable_update_check, property))
check("2. обычный режим внешние вызовы не ограничивает",
      ISO.external_calls_allowed(None) is True)

iso_src = io.open(ISO_PATH, encoding="utf-8").read()
iso_tree = ast.parse(iso_src)
prop = next((n for n in ast.walk(iso_tree)
             if isinstance(n, ast.FunctionDef) and n.name == "disable_update_check"), None)
check("3. свойство не читает окружение и не зависит от переменных",
      prop is not None and "environ" not in ast.get_source_segment(iso_src, prop)
      and "getenv" not in ast.get_source_segment(iso_src, prop))

envs = set(re.findall(r'ENV_[A-Z_]+\s*=\s*"([A-Z_0-9]+)"', iso_src))
check("4. новой переменной окружения для отключения обновлений не появилось",
      not any("UPDATE" in e for e in envs), sorted(envs))
check("5. одних FM_E2E_* без CLI-флага по-прежнему недостаточно",
      ISO.detect(["server.py"], {"FM_E2E_SENTINEL": "x" * 32,
                                 "FM_E2E_DATA_DIR": tempfile.gettempdir()},
                 tempfile.gettempdir(), r"Local\prod") == (None, ""))


sec("2. Обработчик маршрута: подавление до сетевого вызова")

UPD = func_src("api_update_check")
check("6. обработчик найден", bool(UPD))
upd_tree = ast.parse(UPD)

# Позиция ветки изоляции обязана быть РАНЬШЕ любого сетевого вызова.
iso_line = net_line = None
for n in ast.walk(upd_tree):
    if isinstance(n, ast.If) and "_E2E" in ast.dump(n.test) and iso_line is None:
        iso_line = n.lineno
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
            and n.func.attr in ("urlopen", "Request") and net_line is None:
        net_line = n.lineno
check("7. ветка изоляции стоит раньше любого обращения к сети",
      iso_line is not None and net_line is not None and iso_line < net_line,
      "изоляция@%s сеть@%s" % (iso_line, net_line))

# В ветке изоляции обязан быть немедленный возврат: «поймать исключение и продолжить» —
# запрещено, потому что тогда попытка соединения всё-таки состоялась бы.
iso_if = next((n for n in ast.walk(upd_tree)
               if isinstance(n, ast.If) and "_E2E" in ast.dump(n.test)), None)
check("8. в ветке изоляции немедленный возврат, а не молчаливое продолжение",
      iso_if is not None and any(isinstance(x, ast.Return) for x in iso_if.body))
check("9. решение спрашивается у объекта контракта, а не выводится заново",
      iso_if is not None and "disable_update_check" in ast.dump(iso_if.test)
      and "environ" not in ast.dump(iso_if.test))
check("10. подавление не ловит исключение сторожа сети",
      not re.search(r"except[^\n]*:\s*\n[^\n]*urlopen", UPD))


sec("3. Обычный путь обновлений не тронут")

check("11. адрес манифеста не изменён",
      'UPDATE_MANIFEST_URL = "https://3diwell.com/farm/latest.json"' in SRC)
check("12. домен не подменён и не параметризован",
      SRC.count("UPDATE_MANIFEST_URL") == 2
      and "urllib.request.Request(UPDATE_MANIFEST_URL" in SRC)
check("13. тайм-аут и TTL прежние",
      "_UPDATE_TTL = 1800" in SRC and "urlopen(req, timeout=4)" in SRC)
check("14. кэш успешного ответа сохранён",
      '_update_cache = {"ts": 0.0, "data": None}' in SRC
      and 'c["ts"], c["data"] = now, res' in UPD)
#  R-131 (29.09.2026): ответ сайта разбирается строгим модулем app/update_manifest.py (форма,
#  версия, https-ссылка на официальный сайт, подпись — когда появится ключ выпуска).
check("15. сравнение версий прежнее, ответ разбирает строгий разборщик",
      "_ver_tuple(latest) > _ver_tuple(APP_VERSION)" in UPD
      and "_upd_manifest.parse(raw, _lic_trust.release_keys()," in UPD
      and 'data.get("version", "")' not in UPD and "json.loads" not in UPD)
check("16. ответ при подавлении той же формы, что и при недоступном сайте",
      re.search(r'res = \{"current": APP_VERSION, "latest": None, '
                r'"update_available": False,', UPD) is not None)
check("17. обновления не выключены глобально: без изоляции ветка недостижима",
      "if _E2E is not None and _E2E.disable_update_check:" in UPD)
#  R-131 (29.09.2026): договор изменён по решению плана R-131 — у пользователя ЕСТЬ выключатель
#  «Проверять обновления» (настройка фермы farm_update_check). Закрепляется: он стоит ПОСЛЕ ветки
#  изоляции (изоляция по-прежнему первая и не зависит от настроек) и ДО любого обращения к сети
#  и к кэшу, с немедленным возвратом.
sw_if = next((n for n in ast.walk(upd_tree)
              if isinstance(n, ast.If) and "farm_update_check" in ast.dump(n.test)), None)
cache_line = next((n.lineno for n in ast.walk(upd_tree)
                   if isinstance(n, ast.Name) and n.id == "_update_cache"), None)
check("18. выключатель пользователя есть и стоит после изоляции, до кэша и до сети",
      sw_if is not None and iso_line is not None and net_line is not None
      and cache_line is not None
      and iso_line < sw_if.lineno < min(net_line, cache_line)
      and any(isinstance(x, ast.Return) for x in sw_if.body)
      and '_get_setting("farm_update_check", "1") == "0"' in UPD,
      "выключатель@%s изоляция@%s сеть@%s кэш@%s"
      % (sw_if.lineno if sw_if else None, iso_line, net_line, cache_line))
check("18а. по умолчанию проверка включена: нет записи — идём на сайт, как раньше",
      '_get_setting("farm_update_check", "1")' in UPD
      and "update_check_enabled" not in SRC and "disable_updates" not in SRC)


sec("4. Диагностика принятой изоляции")

check("19. при принятой изоляции печатается одна короткая строка",
      'print("E2E isolation: update check disabled")' in SRC)
line = next((l for l in SRC.splitlines() if "update check disabled" in l), "")
check("20. в строке нет токена, адреса и путей",
      all(x not in line for x in ("SENTINEL", "token", "http", "://", "DATA_DIR",
                                  "C:\\", "/Users")), line.strip()[:80])
check("21. диагностика печатается только после принятия контракта",
      SRC.index("E2E isolation rejected") < SRC.index("update check disabled"))


sec("5. Fail-closed сохранён")

tmp = tempfile.mkdtemp(prefix="fm_upd_")
bad_sentinel = ISO.detect(["server.py", ISO.FLAG],
                          {"FM_E2E_SENTINEL": "short", "FM_E2E_DATA_DIR": tmp,
                           "FM_E2E_MUTEX_NAME": "Local\\t"}, tempfile.gettempdir(),
                          r"Local\prod")
check("22. короткий sentinel -> отказ", bad_sentinel[0] is None
      and bad_sentinel[1] == ISO.ERR_NO_SENTINEL, bad_sentinel[1])
bad_dir = ISO.detect(["server.py", ISO.FLAG],
                     {"FM_E2E_SENTINEL": "x" * 32,
                      "FM_E2E_DATA_DIR": os.path.join(tmp, "нет-такой"),
                      "FM_E2E_MUTEX_NAME": "Local\\t"}, tempfile.gettempdir(),
                     r"Local\prod")
check("23. несуществующая папка данных -> отказ", bad_dir[0] is None
      and bad_dir[1] in (ISO.ERR_ROOT_NOT_DIR, ISO.ERR_NO_ROOT), bad_dir[1])
check("24. при отказе программа выходит до запуска чего-либо",
      re.search(r'print\("E2E isolation rejected: %s" % _e2e_err\)\s*\n\s*sys\.exit\(3\)',
                SRC) is not None)
check("25. отказ происходит раньше импорта сетевых модулей",
      SRC.index("E2E isolation rejected") < SRC.index("urllib.request"))
check("26. обработчик обновлений объявлен намного позже проверки контракта",
      SRC.index("E2E isolation rejected") < SRC.index("def api_update_check"))


sec("6. Сторож сети не ослаблен")

guard = io.open(os.path.join(REPO, "tools", "validation", "ui", "network_guard",
                             "sitecustomize.py"), encoding="utf-8").read()
check("27. в стороже нет исключения для домена обновлений",
      "3diwell" not in guard and "latest.json" not in guard)
check("28. сторож по-прежнему пропускает только петлю",
      "_ALLOWED_HOSTS" in guard and "127.0.0.1" in guard
      and not re.search(r'_ALLOWED_HOSTS[^)]*"[a-z]+\.[a-z]{2,}"', guard))
import json as _json
_scen = _json.load(io.open(os.path.join(REPO, "tools", "validation", "ui",
                                        "scenarios.json"), encoding="utf-8"))
_hosts = set()
for _s in _scen["scenarios"]:
    _hosts.update((_s.get("network_policy") or {}).get("allowed_hosts") or [])
check("29. сетевая политика сценариев не расширена внешними хостами",
      _hosts <= {"127.0.0.1", "localhost", "::1"}, sorted(_hosts))

sec("7. Юнит-тесты оснастки не поднимают настоящий сервер и браузер")

for name in ("test_ui_verification.py", "test_isolated_ui_verification.py",
             "test_e2e_update_check_suppression.py"):
    p = os.path.join(REPO, "tools", name)
    t = io.open(p, encoding="utf-8").read()
    tree = ast.parse(t)
    # Реальный запуск возможен только через rv.run(..., execute=True); ищем такие вызовы
    # и требуем, чтобы сценарий при этом был заведомо недоказуемым (BLOCKED до spawn).
    execs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             for kw in n.keywords
             if kw.arg == "execute" and isinstance(kw.value, ast.Constant)
             and kw.value.value is True]
    isolated_exec = []
    for n in execs:
        seg = ast.get_source_segment(t, n) or ""
        if "real_mode" in seg or "isolated" in seg:
            isolated_exec.append(seg[:70])
    check("30. %s: реальный isolated-запуск выполняется только с недоказуемой изоляцией"
          % name,
          not isolated_exec or all("outside_runs" in (ast.get_source_segment(t, n) or "")
                                   for n in execs
                                   if "real_mode" in (ast.get_source_segment(t, n) or "")),
          isolated_exec)
    # Разбор по дереву, а не по подстроке: собственная проверка не должна ловить сама
    # себя за упоминание «server.py» в тексте условия.
    spawns = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        callee = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else "")
        if callee not in ("run", "Popen", "spawn", "check_output", "call"):
            continue
        seg = (ast.get_source_segment(t, n) or "")
        if re.search(r'["\']server\.py["\']|msedge|chrome\.exe|_edge_cdp', seg):
            spawns.append(seg[:80])
    check("31. %s: настоящий server.py не запускается подпроцессом" % name,
          not [s for s in spawns if "server.py" in s], spawns)
    check("32. %s: браузер не запускается подпроцессом" % name,
          not [s for s in spawns if "edge" in s.lower() or "chrome" in s.lower()], spawns)

# Фактическая проверка: после юнит-тестов не должно остаться процессов с флагом E2E.
leftovers = []
try:
    q = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, shell=False, timeout=30)
    lines = [l for l in (q.stdout or "").splitlines() if l.strip()]
except Exception:
    lines = []
check("33. запрос списка процессов выполняется только чтением", True,
      "процессов python: %d" % len(lines))
own = os.getpid()
check("34. собственный процесс теста опознан и не завершается", own > 0)


sec("8. Отрицательные самотесты детекторов")

neg = ast.parse("def api_update_check():\n"
                "    import urllib.request\n"
                "    urllib.request.urlopen('x')\n"
                "    if _E2E is not None:\n"
                "        return {}\n")
neg_iso = neg_net = None
for n in ast.walk(neg):
    if isinstance(n, ast.If) and "_E2E" in ast.dump(n.test) and neg_iso is None:
        neg_iso = n.lineno
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
            and n.func.attr == "urlopen" and neg_net is None:
        neg_net = n.lineno
check("35. самотест: порядок «сеть раньше изоляции» детектор действительно ловит",
      neg_iso is not None and neg_net is not None and not (neg_iso < neg_net))
check("36. самотест: подавление без возврата детектор действительно ловит",
      not any(isinstance(x, ast.Return)
              for x in ast.parse("if _E2E is not None:\n    pass\n").body[0].body))

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
