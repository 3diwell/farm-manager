# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.857 — журнал «Что нового» не должен молча замолкать.

ЗАЧЕМ. Журнал внутри программы (константа CHANGELOG в server.py) — единственное место, где
владелец, не читая код, видит, что изменилось. 21.08.2026 обнаружилось, что он оборван на
версии Alpha 2.840: пятнадцать выпусков подряд правили программу, а в окне «Что нового» не
появилось ни строчки. Заметить это было нечем — журнал не проверял никто.

Дефект прожил долго ровно по той же причине, что и дефекты подписей на кнопках до 2.847: его
никто не измерял. Этот набор измеряет.

ЧТО ПРОВЕРЯЕТСЯ:
  · журнал разбирается и имеет ожидаемое устройство (список записей «версия + пункты»);
  · версии не повторяются и идут строго по убыванию;
  · журнал НЕ ОТСТАЁТ от текущей версии программы больше чем на CHANGELOG_MAX_LAG выпусков;
  · пункты — человеческие фразы, а не заглушки и не служебные обрывки.

ПОЧЕМУ ДОПУСК, А НЕ «ЗАПИСЬ НА КАЖДУЮ ВЕРСИЮ». Версия в этом проекте поднимается при ЛЮБОЙ
правке кода, включая чисто внутренние (оснастка проверок, тесты). Требовать рассказ владельцу
о каждой такой правке — плодить шум, который он перестанет читать. Небольшая череда внутренних
выпусков без записи — нормально; пятнадцать выпусков молчания — нет. Допуск задан явно и
обоснован здесь же.

3.0 (12.09.2026). Владелец перевёл программу на «Alpha 3.0» и сжал весь журнал с 2.566 по
2.1007 в одну запись. Номер версии теперь разбирается как ПАРА чисел «старшая.младшая»:
«Alpha 2.1007» → (2, 1007), «Alpha 3.0» → (3, 0); сравнение порядка и отставание считаются
по паре. Прежний разбор «последняя группа цифр» прочитал бы 3.0 как ноль. Смена старшей
версии без записи о ней в журнале — то же молчание, и оно тоже ловится.

Ни сервера, ни сети: server.py разбирается как текст (AST).

Запуск:  python tools/test_changelog_continuity.py      (0 = журнал в порядке)
"""
import ast
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "server.py")
SENTINEL = "CHANGELOG_CONTINUITY_SENTINEL_2_857"

# Допуск отставания журнала от версии программы, в выпусках. Пять — это несколько подряд
# внутренних правок; больше означает, что владельцу перестали рассказывать об изменениях.
CHANGELOG_MAX_LAG = 5

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def load(src_text):
    """-> (APP_VERSION, [записи журнала]). Разбор AST: подстрочный поиск ловил бы прозу."""
    tree = ast.parse(src_text)
    app_version, changelog = None, None
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_VERSION":
            app_version = ast.literal_eval(n.value)
        elif isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CHANGELOG":
            changelog = ast.literal_eval(n.value)
    return app_version, changelog


def ver_key(v):
    """«Alpha 2.857» -> (2, 857); «Alpha 3.0» -> (3, 0). Не разобралось -> None."""
    m = re.search(r"(\d+)\.(\d+)\s*$", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def lag_between(app_key, top_key):
    """Отставание журнала от программы, в выпусках. Одна старшая версия — разница младших;
    программа ушла на новую старшую версию, а верхняя запись о старой — журнал молчит о целом
    поколении (отставание считается бесконечным); запись новее программы — ошибка порядка."""
    if app_key is None or top_key is None:
        return None
    if app_key[0] == top_key[0]:
        return app_key[1] - top_key[1]
    return 10 ** 6 if app_key[0] > top_key[0] else -1


SRC = io.open(SERVER, encoding="utf-8").read()
APP, LOG = load(SRC)

print("--- 1. Журнал существует и устроен как ожидается ---")
check("1. версия программы прочитана", bool(APP), APP)
check("2. журнал прочитан и не пуст", isinstance(LOG, list) and len(LOG) > 0,
      type(LOG).__name__ if LOG is None else len(LOG))
check("3. каждая запись — это версия и список пунктов",
      all(isinstance(e, dict) and isinstance(e.get("v"), str) and isinstance(e.get("items"), list)
          for e in LOG),
      [e for e in LOG if not (isinstance(e, dict) and isinstance(e.get("items"), list))][:2])
print("   версия программы: %s, записей в журнале: %d, верхняя: %s"
      % (APP, len(LOG), LOG[0]["v"] if LOG else "—"))

print("--- 2. Порядок и отсутствие повторов ---")
vers = [e["v"] for e in LOG]
check("4. версии не повторяются", len(vers) == len(set(vers)),
      [v for v in vers if vers.count(v) > 1][:3])
keys = [ver_key(v) for v in vers]
check("5. все версии разобрались в пару чисел (старшая.младшая)", all(k is not None for k in keys),
      [v for v, k in zip(vers, keys) if k is None][:3])
_desc = [(vers[i], vers[i + 1]) for i in range(len(keys) - 1)
         if keys[i] is not None and keys[i + 1] is not None and keys[i] <= keys[i + 1]]
check("6. записи идут строго от новых к старым", not _desc, _desc[:3])

print("--- 3. Журнал не отстаёт от программы ---")
lag = lag_between(ver_key(APP), keys[0] if keys else None)
check("7. КОРЕНЬ ДЕФЕКТА: журнал отстаёт не больше чем на %d выпусков" % CHANGELOG_MAX_LAG,
      lag is not None and 0 <= lag <= CHANGELOG_MAX_LAG,
      "версия программы %s, верхняя запись %s, отставание %s" % (APP, vers[0] if vers else "—", lag))

print("--- 4. Пункты — человеческие фразы, а не заглушки ---")
_empty = [e["v"] for e in LOG if not e["items"]]
check("8. пустых записей нет", not _empty, _empty[:5])
_short = [(e["v"], it) for e in LOG for it in e["items"]
          if not isinstance(it, str) or len(it.strip()) < 40]
check("9. коротких обрывков и заглушек нет", not _short, _short[:3])
_stub = [(e["v"], it) for e in LOG for it in e["items"]
         if isinstance(it, str) and re.search(r"\b(TODO|FIXME|заглушк|описание позже|xxx)\b", it, re.I)]
check("10. служебных пометок в тексте для владельца нет", not _stub, _stub[:3])

print("--- 5. НЕ ВАКУУМ: проверка ловит именно то, что описано ---")
#  2.995: версия-ловушка СЧИТАЕТСЯ от текущей, а не вписана числом. Вписанная «2.999»
#  устарела сама собой: программа доросла до 2.995, отставание стало 4 — в пределах
#  допустимого, и проверка на вакуум покраснела, хотя журнал в порядке.
_ak = ver_key(APP) or (0, 0)
#  25.10.2026: префикс выпуска (Alpha, с Beta 3.71 — Beta) берётся у текущей версии.
_prefix = (str(APP or "").split() or ["Alpha"])[0]
_broken_gap = SRC.replace('APP_VERSION = "%s"' % APP,
                          'APP_VERSION = "%s %d.%d"' % (_prefix, _ak[0], _ak[1] + CHANGELOG_MAX_LAG + 20), 1)
_a2, _l2 = load(_broken_gap)
_lag2 = lag_between(ver_key(_a2), ver_key(_l2[0]["v"]))
check("11. журнал, отставший на десятки выпусков, признаётся негодным",
      not (0 <= _lag2 <= CHANGELOG_MAX_LAG), _lag2)

#  3.0: программа перешла на новую старшую версию, а журнал остался на старой — тоже молчание.
_lag3 = lag_between((_ak[0] + 1, 0), _ak)
check("11b. смена старшей версии без записи о ней признаётся негодной",
      _lag3 is not None and not (0 <= _lag3 <= CHANGELOG_MAX_LAG), _lag3)

_dup = list(LOG[:1]) + list(LOG)
_v = [e["v"] for e in _dup]
check("12. повтор версии был бы пойман", len(_v) != len(set(_v)))

#  Порядок проверяется по паре чисел, поэтому ловушка не зависит от длины журнала:
#  «2.1007» новее «2.999», а «3.0» новее «2.1007» — разбор «последних цифр» это путал.
_n = [ver_key("Alpha 2.999"), ver_key("Alpha 2.1007")]
check("13. нарушенный порядок был бы пойман (2.999 выше 2.1007 — ошибка)",
      any(_n[i] <= _n[i + 1] for i in range(len(_n) - 1)))
check("13b. пара чисел сравнивается верно: 3.0 > 2.1007 > 2.999",
      ver_key("Alpha 3.0") > ver_key("Alpha 2.1007") > ver_key("Alpha 2.999"))
#  25.10.2026: выпуск «Beta 3.71» встал над «Alpha 3.0». Префикс на порядок не влияет.
check("13c. префикс выпуска не влияет: «Beta 3.71» -> (3, 71), выше «Alpha 3.0», ниже «Beta 3.72»;"
      " Beta 3.71 и Alpha 3.71 — один номер",
      ver_key("Beta 3.71") == (3, 71) and ver_key("Alpha 3.0") < ver_key("Beta 3.71") < ver_key("Beta 3.72")
      and ver_key("Alpha 3.71") == ver_key("Beta 3.71"))
check("13d. журнал Beta 3.71 сверху и Alpha 3.0 под ней — порядок верный, отставание 0",
      lag_between(ver_key("Beta 3.71"), ver_key("Beta 3.71")) == 0
      and ver_key("Beta 3.71") > ver_key("Alpha 3.0")
      and not (0 <= lag_between(ver_key("Beta 3.71"), ver_key("Alpha 3.0")) <= CHANGELOG_MAX_LAG))

check("14. заглушка вместо текста была бы поймана",
      len("TODO") < 40 and bool(re.search(r"\bTODO\b", "TODO", re.I)))

print("--- 6. Верхняя запись описывает именно текущую версию ---")
check("15. верхняя запись журнала — это версия программы либо один из ближайших выпусков",
      vers[0] == APP or (lag is not None and 0 <= lag <= CHANGELOG_MAX_LAG),
      (APP, vers[0] if vers else "—"))

#  16.10.2026 (R-152): английский «Что нового». У записи рядом с русскими items лежит items_en —
#  тот же порядок и то же число пунктов; окно показывает его при языке EN, а при несовпадении
#  длины — русский текст (web/index.html). Верхняя запись обязана нести items_en: иначе английский
#  пользователь снова увидит журнал по-русски, и заметить это некому.
print("--- 7. Английский текст «Что нового» (items_en) ---")


def en_problems(log, top_required=True):
    """-> список нарушений items_en в журнале (пусто — порядок)."""
    out = []
    for k, e in enumerate(log or []):
        en = e.get("items_en")
        if en is None:
            if k == 0 and top_required:
                out.append((e.get("v"), "у верхней записи нет items_en"))
            continue
        if not isinstance(en, list) or len(en) != len(e.get("items") or []):
            out.append((e.get("v"), "items_en другой длины: %s против %s"
                        % (len(en) if isinstance(en, list) else type(en).__name__, len(e.get("items") or []))))
            continue
        for j, it in enumerate(en):
            if not isinstance(it, str) or len(it.strip()) < 40:
                out.append((e.get("v"), "пункт %d: короткий обрывок или не строка" % j))
            elif re.search(u"[Ѐ-ӿ]", it):
                out.append((e.get("v"), "пункт %d: русские буквы в английском тексте" % j))
    return out


_enp = en_problems(LOG)
check("16. у верхней записи есть items_en той же длины, что items (%d)"
      % len((LOG[0] if LOG else {}).get("items") or []),
      bool(LOG) and isinstance(LOG[0].get("items_en"), list)
      and len(LOG[0]["items_en"]) == len(LOG[0]["items"]), (LOG[0].get("v"), len(LOG[0].get("items_en") or [])) if LOG else "")
check("17. английские пункты — фразы не короче 40 знаков, без русских букв, той же длины во всех записях",
      not _enp, _enp[:3])

#  Не вакуум: те же правила на испорченных копиях верхней записи.
_top = dict(LOG[0]) if LOG else {"v": "x", "items": []}
_no_en = [dict(_top)]
_no_en[0].pop("items_en", None)
_short_en = [dict(_top, items_en=list(_top.get("items_en") or [])[:-1])]
_ru_en = [dict(_top, items_en=list(_top.get("items") or []))]
check("18. верхняя запись без items_en была бы поймана", bool(en_problems(_no_en)))
check("18b. items_en короче items был бы пойман", bool(en_problems(_short_en)))
check("18c. русский текст в items_en был бы пойман", bool(en_problems(_ru_en)))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
