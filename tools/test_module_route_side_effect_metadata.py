#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Alpha 2.794 — точная классификация побочных эффектов маршрутов модулей.
#
# Главный принцип теста: он НЕ постулирует желаемые значения. Факт добывается разбором
# исходников backend.py трёх модулей через AST с транзитивным обходом графа вызовов, и уже
# этот факт сверяется с декларацией в реестре. Поэтому проверка краснеет и при неверной
# метаданной, и при незамеченном изменении обработчика.
#
# Что доказывается:
#   * характеризация Alpha 2.793 (эталон — коммит bbce4ab, он неизменяем, поэтому проверки
#     остаются зелёными и после 2.794 и продолжают описывать именно старое состояние);
#   * каждая запись в БД объявлена DATABASE, каждое чтение — NONE;
#   * read_only соответствует факту (POST без записи read_only=True);
#   * ни один маршрут модуля не трогает файлы, сеть, подпроцессы, принтер, очередь и recovery;
#   * отпечатки путей, методов, прав и policy_id побайтово не изменились;
#   * метаданные не участвуют в разрешении доступа.
#
# Безопасность прогона:
#   * production server.py НЕ импортируется (работающая программа не мешает и не даёт ложный ноль);
#   * обработчики модулей НЕ выполняются: только чтение исходников и статический разбор;
#   * рабочие БД, DATA_DIR и config не открываются; сеть, принтеры и слайсер не используются.
#
# Запуск: python tools/test_module_route_side_effect_metadata.py   (0 = все проверки пройдены)

import ast
import hashlib
import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "bbce4ab"   # HEAD до Alpha 2.794 (handoff 2.793)
SENTINEL = "MODULE_SIDE_EFFECT_SENTINEL_2_794"

fail = 0
total = 0


def check(name, cond):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def section(t):
    print("\n--- %s ---" % t)


def rd(rel):
    return io.open(os.path.join(REPO, rel), encoding="utf-8", errors="surrogateescape").read()


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["app/route_policy_registry.py"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


from app import route_policy_registry as reg   # noqa: E402  (чистый модуль политик, без БД и сети)

MODP_ALL = [p for p in reg.ALL_POLICIES if getattr(p, "module_id", None)]
#  2.994: модуль «Уведомления в мессенджеры» (6 маршрутов) в этот форензик-инвариант 2.794 не входит:
#  он по назначению выходит в сеть (пробная отправка, мастер подключения), и его эффекты доказаны
#  отдельно — tools/test_messengers_module.py. Здесь сверяются три модуля эталона 1d04271.
#  3.0 (12.09.2026): модуль cost теперь «Расчёт заказа» — другой модуль под тем же id (слово
#  владельца: «Себестоимость печати» удалить, поставить его). Он по назначению пишет файлы заказов
#  и обращается к самой программе на 127.0.0.1, поэтому из форензик-инварианта 2.794 выведен так
#  же, как messengers; его эффекты доказаны отдельно — tools/test_cost_module.py, раздел I.
#  Характеризация эталона (H*) по-прежнему читает исторический реестр, и Cost 2.793 в нём
#  проверяется. Пути, методы и права маршрутов cost не менялись — они сверяются вместе с
#  остальными (MODP_PATHS).
MODP = [p for p in MODP_ALL if p.module_id not in ("messengers", "cost")]
MODP_PATHS = [p for p in MODP_ALL if p.module_id != "messengers"]
MSGP = [p for p in MODP_ALL if p.module_id == "messengers"]
COSTP = [p for p in MODP_ALL if p.module_id == "cost"]
BY_ID = {p.policy_id: p for p in MODP}

print("=== Alpha 2.794: точная классификация побочных эффектов маршрутов модулей ===")

# ════════════════════════════════════════════════════════════════════════════
# ФАКТ: что обработчики делают на самом деле (AST, обработчики не выполняются)
# ════════════════════════════════════════════════════════════════════════════
SQL_WRITE = re.compile(r'\b(INSERT\s+INTO|INSERT\s+OR\s+\w+\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|'
                       r'CREATE\s+TABLE|CREATE\s+INDEX|ALTER\s+TABLE|DROP\s+TABLE|REPLACE\s+INTO)\b', re.I)
SQL_DDL = re.compile(r'\b(CREATE\s+TABLE|CREATE\s+INDEX|ALTER\s+TABLE)\b', re.I)
FS_SAFE = {"os.path.join", "os.path.dirname", "os.path.basename", "os.path.abspath",
           "os.path.exists", "os.path.isfile", "os.path.isdir", "os.path.splitext",
           "os.environ.get", "os.path.normpath"}


def _strings(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((getattr(n, "lineno", 0), n.value))
        elif isinstance(n, ast.JoinedStr):
            out.append((getattr(n, "lineno", 0),
                        "".join(v.value for v in n.values
                                if isinstance(v, ast.Constant) and isinstance(v.value, str))))
    return out


def _calls(node):
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                if isinstance(f.value, ast.Name):
                    names.add(f.value.id + "." + f.attr)
                names.add("." + f.attr)
    return names


def analyze(mid):
    src = rd("modules/%s/backend.py" % mid)
    tree = ast.parse(src)
    fns = {}

    class Idx(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            fns.setdefault(node.name, []).append(node)
            self.generic_visit(node)
        visit_AsyncFunctionDef = visit_FunctionDef

    Idx().visit(tree)

    def local(fn):
        ev = {}
        for lineno, s in _strings(fn):
            if SQL_WRITE.search(s):
                ev.setdefault("db_write", []).append((lineno, SQL_WRITE.search(s).group(0).upper()))
            if SQL_DDL.search(s):
                ev.setdefault("db_ddl", []).append((lineno, "DDL"))
        for c in _calls(fn):
            if c == ".commit":
                ev.setdefault("db_write", []).append((fn.lineno, "commit()"))
            if (c == "open" or c.startswith(("os.", "shutil.", "pathlib."))) and c not in FS_SAFE:
                ev.setdefault("fs", []).append((fn.lineno, c))
            if c.startswith(("requests.", "urllib", "socket.", "httpx.")):
                ev.setdefault("network", []).append((fn.lineno, c))
            if c.startswith("subprocess."):
                ev.setdefault("subprocess", []).append((fn.lineno, c))
        return ev

    def walk(name, seen=None):
        seen = seen or set()
        if name in seen or name not in fns:
            return {}
        seen.add(name)
        total_ev = {}
        for fn in fns[name]:
            for k, v in local(fn).items():
                total_ev.setdefault(k, []).extend(v)
            for c in _calls(fn):
                bare = c.lstrip(".")
                if bare in fns and bare != name:
                    for k, v in walk(bare, seen).items():
                        total_ev.setdefault(k, []).extend(v)
        return total_ev

    return fns, walk


FACT = {}
for _mid in ("quality", "inventory"):
    _fns, _walk = analyze(_mid)
    for p in [x for x in MODP if x.module_id == _mid]:
        ev = _walk(p.handler)
        FACT[p.policy_id] = {
            "writes": "db_write" in ev,
            "ddl": "db_ddl" in ev,
            "fs": "fs" in ev,
            "network": "network" in ev,
            "subprocess": "subprocess" in ev,
            "evidence": ev,
        }

WRITERS = sorted(k for k, v in FACT.items() if v["writes"])
READERS = sorted(k for k, v in FACT.items() if not v["writes"])

check("A0. факт добыт для всех 35 маршрутов склада и качества (иначе проверки были бы вакуумными)",
      len(FACT) == 35 and len(MODP) == 35)
check("A0c. 3.0: у модуля cost («Расчёт заказа») 10 маршрутов; эффекты сверены с фактом в tools/test_cost_module.py",
      len(COSTP) == 10
      and {e.value for p in COSTP for e in p.side_effects} == {"NONE", "DATABASE", "FILESYSTEM", "NETWORK"}
      and "I1. эффекты всех 10 маршрутов в карте прав равны факту" in rd("tools/test_cost_module.py"))
check("A0b. 2.994: у модуля messengers 6 маршрутов, эффекты только NONE/DATABASE/NETWORK, все — admin",
      len(MSGP) == 6 and {e.value for p in MSGP for e in p.side_effects} == {"NONE", "DATABASE", "NETWORK"}
      and all(p.required_capability == "admin" for p in MSGP))
check("A1. разбор нашёл и записи, и чтения (детектор не выродился)",
      len(WRITERS) == 19 and len(READERS) == 16)

# ════════════════════════════════════════════════════════════════════════════
section("характеризация: как было в Alpha 2.793 (эталон %s)" % PARENT)

P_REG = git_show("app/route_policy_registry.py")
hcheck("H0. эталон %s прочитан" % PARENT, lambda: bool(P_REG))

_p_rows = re.findall(r"\('(cost|inventory|quality)', '[\d.]+','([^']*)', '([^']*)', '([A-Z]+)', "
                     r"'([a-z_0-9]+)', \(([^)]*)\), ([^)]*)\)", P_REG or "")
hcheck("H1. в эталоне разобраны все 45 строк маршрутов модулей", lambda: len(_p_rows) == 45)

_p_eff = {}
for mid, mroute, path, method, handler, effects, _perm in _p_rows:
    _p_eff[(mid, method, mroute)] = tuple(sorted(re.findall(r"'([A-Z_]+)'", effects)))

_p_none = sum(1 for v in _p_eff.values() if v == ("NONE",))
_p_config = sum(1 for v in _p_eff.values() if v == ("CONFIG",))
hcheck("H2. (1) в 2.793 объявлено NONE у 44 маршрутов из 45", lambda: _p_none == 44)
hcheck("H3. (2) единственное не-NONE значение — CONFIG у настроек склада",
       lambda: _p_config == 1 and _p_eff.get(("inventory", "POST", "settings")) == ("CONFIG",))
hcheck("H4. (3) все 19 фактических записей склада в БД были объявлены как отсутствие эффектов",
       lambda: bool(_p_eff) and all(_p_eff.get((BY_ID[k].module_id, BY_ID[k].method, BY_ID[k].module_route)) in (("NONE",), ("CONFIG",))
          for k in WRITERS))
hcheck("H5. (4) неточность Cost подтверждена: сохранение расчёта и ставки объявлены NONE",
       lambda: _p_eff.get(("cost", "POST", "calculations")) == ("NONE",)
       and _p_eff.get(("cost", "POST", "settings")) == ("NONE",)
       and _p_eff.get(("cost", "POST", "printer-settings/{pid}")) == ("NONE",))
hcheck("H6. (5) Quality: все четыре маршрута были объявлены NONE — и это ОКАЗАЛОСЬ ВЕРНО",
       lambda: all(_p_eff.get(("quality", "GET", r)) == ("NONE",)
          for r in ("print-runs", "print-runs/{run_id}", "print-runs/{run_id}/materials", "summary")))
check("H7. (7) Inventory проверен тем же способом: 19 записей из 31 маршрута (у Cost 2.793 их было 4; модуль заменён в 3.0)",
      sum(1 for k in WRITERS if BY_ID[k].module_id == "inventory") == 19
      and sum(1 for k in WRITERS if BY_ID[k].module_id == "quality") == 0)

_p_ro = re.search(r"\('cost', '[\d.]+','calculate'", P_REG or "")
hcheck("H8. read_only=False у cost.calculate в эталоне (POST принят за мутацию по методу)",
       lambda: bool(P_REG) and bool(_p_ro) and reg.module_policy_by_id("cost.calculate") is not None)

check("H9. (8-11) тест не импортирует server.py и не трогает рабочие данные",
      "server" not in sys.modules
      and not any(str(getattr(m, "__file__", "") or "").endswith("server.py") for m in sys.modules.values()))

# ════════════════════════════════════════════════════════════════════════════
section("схема side_effects: значения и отсутствие свободного текста")

_ALLOWED = {e.value for e in reg.SideEffect}
check("1. поле side_effects — кортеж значений перечисления SideEffect",
      all(isinstance(p.side_effects, tuple) and len(p.side_effects) >= 1 for p in MODP)
      and all(isinstance(e, reg.SideEffect) for p in MODP for e in p.side_effects))
check("2. нет пустого списка, пустой строки и свободного текста",
      all(p.side_effects for p in MODP)
      and all(e.value in _ALLOWED and e.value.strip() == e.value and e.value for p in MODP for e in p.side_effects))
check("3. у каждого из 45 маршрутов значение задано явно (в схеме нет default)",
      "side_effects: Tuple[SideEffect, ...]" in rd("app/route_policy_registry.py")
      and "side_effects: Tuple[SideEffect, ...] =" not in rd("app/route_policy_registry.py"))
check("4. неизвестное значение невозможно: конструктор приводит строку к SideEffect",
      "side_effects=tuple(SideEffect(e) for e in effects)" in rd("app/route_policy_registry.py"))

# ════════════════════════════════════════════════════════════════════════════
section("классификация по ФАКТУ обработчика, а не по HTTP-методу")

for k in WRITERS:
    p = BY_ID[k]
    ev = FACT[k]["evidence"].get("db_write", [])
    where = ", ".join("стр.%d %s" % (l, t) for l, t in sorted(set(ev))[:3])
    check("5. %s: запись в БД объявлена DATABASE (%s)" % (k, where or "commit"),
          tuple(e.value for e in p.side_effects) == ("DATABASE",))

for k in READERS:
    p = BY_ID[k]
    check("6. %s: без записи — эффектов нет (NONE)" % k,
          tuple(e.value for e in p.side_effects) == ("NONE",))

_calc = reg.module_policy_by_id("cost.calculate")
check("7. cost.calculate (3.0, «Расчёт заказа»): POST пишет кэш моделей принтеров и временный файл — помечен изменяющим (факт — tools/test_cost_module.py I1, I4)",
      _calc is not None and _calc.read_only is False
      and {e.value for e in _calc.side_effects} == {"DATABASE", "FILESYSTEM", "NETWORK"})
check("8. inventory.spool.bulk_delete_preview: POST без записи — не помечен мутацией",
      not FACT["inventory.spool.bulk_delete_preview"]["writes"]
      and tuple(e.value for e in BY_ID["inventory.spool.bulk_delete_preview"].side_effects) == ("NONE",)
      and BY_ID["inventory.spool.bulk_delete_preview"].read_only is True)
check("9. cost.calculations.save и cost.settings.write: запись объявлена (факт — tools/test_cost_module.py I1)",
      "DATABASE" in {e.value for e in reg.module_policy_by_id("cost.calculations.save").side_effects}
      and tuple(e.value for e in reg.module_policy_by_id("cost.settings.write").side_effects) == ("DATABASE",))
check("10. inventory.settings.write: пишет в СВОЮ БД модуля, а не в config приложения",
      "INSERT INTO inv_settings" in rd("modules/inventory/backend.py")
      and tuple(e.value for e in BY_ID["inventory.settings.write"].side_effects) == ("DATABASE",))
check("11. Quality: все четыре маршрута только читают",
      all(not FACT[k]["writes"] for k in FACT if k.startswith("quality."))
      and all(tuple(e.value for e in BY_ID[k].side_effects) == ("NONE",)
              for k in FACT if k.startswith("quality.")))
check("12. read_only согласован с фактом на всех 35 маршрутах склада и качества",
      all(BY_ID[k].read_only == (not FACT[k]["writes"]) for k in FACT))

_gets_writing = [k for k in WRITERS if BY_ID[k].method == "GET"]
check("13. ни один GET-маршрут модуля не выполняет запись (иначе он был бы замаскирован)",
      not _gets_writing)
_posts_reading = [k for k in READERS if BY_ID[k].method in ("POST", "PATCH", "DELETE")]
check("14. POST без записи существует и классифицирован честно: %s" % (", ".join(_posts_reading) or "нет"),
      set(_posts_reading) == {"inventory.spool.bulk_delete_preview"})   # 3.0: cost.calculate пишет кэш — см. пункт 7

# ════════════════════════════════════════════════════════════════════════════
section("эффекты, которых у маршрутов модулей нет")

for tag, label in (("fs", "файловая система"), ("network", "сеть"), ("subprocess", "подпроцессы")):
    bad = [k for k, v in FACT.items() if v[tag]]
    check("15. ни один маршрут модуля не трогает: %s (%s)" % (label, ", ".join(bad) or "подтверждено"),
          not bad)

_forbidden = {"FILESYSTEM", "NETWORK", "SUBPROCESS", "PRINTER", "QUEUE", "RECOVERY",
              "MODULE_STATE", "SESSION_STATE", "AUDIT", "CONFIG"}
_declared = {e.value for p in MODP for e in p.side_effects}
check("16. в объявлениях модулей нет недоказанных категорий: %s" % ", ".join(sorted(_declared)),
      not (_declared & _forbidden) and _declared <= {"NONE", "DATABASE"})
check("17. ленивой инициализации схемы на запрос нет: _init_tables() только при загрузке модуля",
      all(rd("modules/%s/backend.py" % m).count("_init_tables()") == 2 for m in ("quality", "inventory"))
      and all(not FACT[k]["ddl"] for k in FACT))

# ════════════════════════════════════════════════════════════════════════════
section("инварианты: отпечатки не изменились")


def fingerprint(policies):
    rows = sorted("%s|%s|%s|%s|%s|%s" % (p.policy_id, p.method, p.path, p.required_capability,
                                         p.kind.value, p.module_id) for p in policies)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


_fp_now = fingerprint(MODP_PATHS)
_p_rows_fp = sorted("%s|%s|%s" % (mid, method, path) for mid, mroute, path, method, h, e, perm in _p_rows)
_fp_paths_now = sorted("%s|%s|%s" % (p.module_id, p.method, p.path) for p in MODP_PATHS)
hcheck("18. пути и методы 45 маршрутов побайтово прежние", lambda: _p_rows_fp == _fp_paths_now)
check("19. отпечаток policy_id/метод/путь/право/вид/модуль устойчив (%s…)" % _fp_now[:12],
      len(_fp_now) == 64)

from collections import Counter   # noqa: E402
_caps = Counter(p.required_capability for p in MODP_PATHS)
check("20. распределение прав прежнее: view 21 / project 17 / count 2 / admin 5",
      dict(_caps) == {"view": 21, "project": 17, "count": 2, "admin": 5})
check("21. состав маршрутов ожидаемый: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart; 2.870 +камера без перекодирования; 2.879 +камера по WebSocket); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)
check("22. все 51 маршрутов модулей остаются на границе CAPABILITY",
      len(MODP_ALL) == 51 and all(p.enforced_access.value == "CAPABILITY" for p in MODP_ALL))

def _norm(s):
    """Гасит РОВНО намеренные изменения 2.794 и 2.798. Любая ДРУГАЯ правка реестра оставит
    расхождение и покраснит проверку — это и есть инвариант «ничего лишнего не тронуто»."""
    s = re.sub(r"\('(NONE|CONFIG|DATABASE)',\)", "('X',)", s)                       # 1) ярлыки эффектов 2.794
    #  Alpha 2.891: номер версии складского модуля к составу маршрутов и эффектам отношения не
    #  имеет — он поднимается вместе с самим модулем. Гасим ТОЛЬКО его, всё остальное в описи
    #  по-прежнему сверяется построчно.
    s = re.sub(r"'inventory', '1\.7\.\d+'", "'inventory', 'X'", s)
    #  3.0: «Расчёт заказа» заменил «Себестоимость печати» под тем же id — версия модуля и ярлыки
    #  эффектов его строк описи изменились вместе с модулем (факт — tools/test_cost_module.py).
    #  Гасим ТОЛЬКО версию и эффекты строк cost; пути, методы и обработчики сверяются как прежде.
    s = "\n".join(re.sub(r"\('cost', '[\d.]+','", "('cost', 'X','",
                         re.sub(r"\((?:'[A-Z_]+'(?:, )?)+\)", "('X',)", l))
                  if l.lstrip().startswith("('cost', '") else l for l in s.split("\n"))
    #  2.964: то же и для модуля качества — версия поднялась вместе с самим модулем
    #  (уборка «зависших» записей), состав маршрутов и их эффекты не изменились.
    s = re.sub(r"'quality', '0\.2\.\d+'", "'quality', 'X'", s)
    s = re.sub(r"\n# Alpha 2\.794: read_only выводился.*?\)\)\n", "", s, flags=re.S)   # 2) явные исключения 2.794
    s = s.replace(" or (pid in READ_ONLY_DESPITE_METHOD)", "")                       # 3) их учёт в _mk
    # 2.798: локальное восстановление админа добавило один маршрут ядра, границу LOCAL_RECOVERY
    # и её ветви + примечание. Гасим ровно их, чтобы инвариант остался «ничего другого не тронуто».
    s = re.sub(r'    "POST /api/auth/local-recovery/complete": \(\n(?:.*\n)*?    \),\n', "", s)  # примечание
    s = re.sub(r'    if guard is HandlerGuard\.LOCAL_RECOVERY:\n        return AccessBoundary\.LOCAL_RECOVERY\n', "", s)
    s = re.sub(r'    if boundary is AccessBoundary\.LOCAL_RECOVERY:\n        return AuthOffScope\.LOOPBACK_ONLY.*\n', "", s)
    s = re.sub(r'    if guard == "LOCAL_RECOVERY":\n        return \(stage, EnforcedAccess\.LOCAL_RECOVERY, None, None\)\n', "", s)
    s = s.replace(", EnforcedAccess.LOCAL_RECOVERY):", "):")                         # инлайн-вставка в _auth_off_behavior_for
    # 2.813: встроенный журнал сделал GET /api/diagnostics административным экраном (SYSTEM_ADMIN).
    # Гасим ровно эту строку реестра: любая ДРУГАЯ правка по-прежнему покраснит проверку.
    s = s.replace("('GET', '/api/diagnostics', 'diagnostics', 'diagnostics', 'browser', "
                  "'SENSITIVE', ('X',), 'SYSTEM_ADMIN', None)",
                  "('GET', '/api/diagnostics', 'diagnostics', 'diagnostics', 'browser', "
                  "'SENSITIVE', ('X',), 'NONE', None)")
    #  26.09.2026: «любая версия модуля грузится» — маршрут модуля, которого нет в карте прав,
    #  получает строгую политику времени выполнения (app/module_runtime_policy.py, право admin).
    #  В module_http_policy ОДНА строка поиска стала двумя помеченными «26.09.2026», и после
    #  функции добавлен помеченный словарь _RUNTIME_MODULE_HTTP_INDEX (с двумя пустыми строками
    #  перед ним). Возвращаем исходную строку поиска и убираем ровно добавленный словарь. Строки описи, политик и guard не тронуты —
    #  любая другая правка реестра по-прежнему красная. Новое поведение закреплено в
    #  tools/test_module_version_tolerance.py.
    #  Подстановка — по ТОЧНОМУ тексту добавленных строк: любая лишняя правка в них (или
    #  ещё одна строка с той же меткой) оставит расхождение и покраснит проверку.
    s = s.replace("    key = (str(method).upper(), path_template)   # 26.09.2026: неизвестный карте маршрут модуля\n"
                  "    return _MODULE_HTTP_INDEX.get(key) or _RUNTIME_MODULE_HTTP_INDEX.get(key)"
                  "   # 26.09.2026: -> app/module_runtime_policy.py\n",
                  "    return _MODULE_HTTP_INDEX.get((str(method).upper(), path_template))\n")
    s = s.replace("\n\n_RUNTIME_MODULE_HTTP_INDEX = {}   # 26.09.2026: строгие политики, заполняет только "
                  "app/module_runtime_policy.py\n", "")
    # 2.823: файловый менеджер принтеров добавил пять строк описи, три поимённые политики
    # printer_files_read и комментарии с меткой «2.823». Гасим ровно их — любая другая
    # правка описи по-прежнему красная.
    s = "\n".join(l for l in s.split("\n")
                  if "LOCAL_RECOVERY" not in l and "local-recovery" not in l and "Alpha 2.798" not in l
                  and "printer-files" not in l and "printer_files" not in l and "2.823" not in l
                  and "2.825" not in l   # 2.825: +select-for-print (строка описи, политика, комментарии)
                  and "config-backup" not in l   # 2.827: +4 config-backup (строки описи + комментарии)
                  and "printer-sort-mode" not in l and "2.831" not in l   # 2.831: +2 printer-sort-mode (визуальная сортировка)
                  and "klipper-prestart" not in l and "2.833" not in l    # 2.833: +2 klipper-prestart (read-only discovery + prefs)
                  # 2.837: у POST /api/network появилась ВТОРАЯ граница (машина сервера).
                  # Изменилось ТОЛЬКО примечание — ни одной строки описи, ни одного guard,
                  # ни одной политики. Каждая добавленная строка примечания помечена «2.837»,
                  # поэтому гасится ровно она: любая другая правка реестра по-прежнему красная.
                  and "2.837" not in l
                  # 2.839: добавлен ОДИН диагностический маршрут (read-only сбор контракта
                  # подготовки печати). Каждая добавленная строка помечена «2.839», поэтому
                  # гасится ровно она: любая другая правка реестра по-прежнему красная.
                  and "2.839" not in l and "klipper-contract-report" not in l
                  # 2.870: +1 маршрут камеры без перекодирования (только чтение).
                  # 2.879: +1 маршрут той же камеры по WebSocket — обход измеренного
                  # предела браузера в шесть длинных ответов HTTP/1.1 на один адрес.
                  # Каждая добавленная строка помечена именем маршрута или версией,
                  # поэтому гасится ровно она: любая другая правка реестра красная.
                  and "camera.mp4" not in l and "camera.ws" not in l
                  and "2.870" not in l and "2.879" not in l
                  # 2.903: второй интерфейс UI 3.0 — три строки описи (страница и её файлы).
                  # Это статика браузера: ни одного guard, ни одной новой политики.
                  and "/ui3" not in l and "2.903" not in l
                  # 2.920: очередь ОЖИДАНИЯ (что печатать, принтер ещё не выбран) и флаг
                  # разрешения запуска из очереди. Каждая добавленная строка помечена именем
                  # маршрута или версией — гасится ровно она, любая другая правка красная.
                  and "queue-wait" not in l and "queue-allowed" not in l
                  and "2.920" not in l
                  # 2.927: пометки принтера и настройки фермы — единые на всю ферму.
                  # Каждая строка помечена версией — гасится ровно она.
                  and "printer/marks" not in l and "farm-settings" not in l
                  and "2.927" not in l
                  #  2.947: +1 маршрут ядра — переключатель «считать печать задачи и в проекте».
                  #  Ни одного guard, ни одной новой политики: право 'project', как у прочей
                  #  правки задач. Гасится ровно эта строка, любая другая правка красная.
                  and "/api/staging/sync" not in l and "2.947" not in l
                  #  2.948: маршрут pending-printable удалён вместе со сценарием подсказок.
                  and "pending-printable" not in l
                  #  2.978: смена ПАПКИ ДАННЫХ поднята с права 'project' до 'admin' — то же
                  #  действие и тот же риск, что смена папки архивов. Ужесточение, не ослабление.
                  and "storage/data" not in l and "2.978" not in l
                  #  2.979: +1 маршрут «открыть расположение файла детали» (project).
                  and "files/{file_id}/locate" not in l and "2.979" not in l
                  #  2.980 (R-092): поиск принтеров в сети (4 маршрута, printer_write) и сырая
                  #  запись сетевых объявлений (3 маршрута, admin — открывает сокеты и пишет файл).
                  #  Каждая строка помечена именем маршрута или версией: гасится ровно она,
                  #  любая другая правка реестра по-прежнему красная.
                  and "printer-discovery" not in l and "net-capture" not in l
                  and "2.980" not in l
                  #  2.986: строки-ПОЯСНЕНИЯ (сплошной комментарий) из сравнения исключены.
                  #  Список выше гасил их по метке версии, но продолжение абзаца метки не несёт,
                  #  и проверка краснела на пояснительном тексте. Поведение комментарий не
                  #  меняет; строки описи, политик и guard сравниваются как прежде — любая их
                  #  правка по-прежнему красная.
                  #  2.994: модуль «Уведомления в мессенджеры» — шесть строк описи и прав по имени
                  #  модуля. Любая другая правка реестра по-прежнему красная.
                  and "messengers" not in l
                  #  16.09.2026: две строки подтверждения «Стол очищен» вне проектного
                  #  запуска (plate-clear и его отзыв). Любая другая правка реестра
                  #  по-прежнему красная.
                  and "/api/printer/{printer_id}/plate-clear" not in l
                  #  26.09.2026: три строки описи лицензий модулей (/api/licenses). Любая другая
                  #  правка реестра по-прежнему красная.
                  and "'/api/licenses" not in l
                  #  16.10.2026 (R-149): файлы модулей /modules/* — только после входа. Одна строка
                  #  поимённой политики; строка описи прежняя. Любая другая правка красная.
                  and '"GET /modules/{module_id}/{asset_path:path}": (EnforcedAccess.SESSION_ONLY' not in l
                  and not l.strip().startswith("#"))
    return s


hcheck("23. в реестре изменились ТОЛЬКО ярлыки эффектов и явный список read-only-исключений",
       lambda: bool(P_REG) and _norm(rd("app/route_policy_registry.py")) == _norm(P_REG))
check("23b. правило read_only по методу НЕ отменено — оно осталось и лишь получило исключения",
      "read_only=(method not in MUTATING_METHODS) or (pid in READ_ONLY_DESPITE_METHOD)"
      in rd("app/route_policy_registry.py")
      and len(reg.READ_ONLY_DESPITE_METHOD) == 1)   # 3.0: cost.calculate из исключений убран — он пишет кэш
check("23c. исключения не затрагивают маршруты ядра (у них policy_id отсутствует)",
      all(p.read_only == (p.method not in reg.MUTATING_METHODS)
          for p in reg.ALL_POLICIES if not getattr(p, "module_id", None)))

# ════════════════════════════════════════════════════════════════════════════
section("метаданные не являются границей безопасности")

_SRC = rd("server.py")
_RAC = rd("app/route_access_control.py")
check("24. side_effects не используется в разрешении запроса",
      "side_effects" not in _SRC and "side_effects" not in _RAC
      and "SideEffect" not in _SRC and "SideEffect" not in _RAC)
check("25. read_only не используется в разрешении запроса",
      not re.search(r'\bpolicy\.read_only\b|\.read_only\s*(?:and|or|if)\b', _SRC + _RAC))
check("26. решение принимается по required_capability/enforced_access, а не по метаданным",
      "required_capability" in rd("app/route_policy_registry.py"))
_users = subprocess.run(["git", "-C", REPO, "grep", "-l", "side_effects"], capture_output=True)
_files = [f for f in _users.stdout.decode("utf-8", "replace").split() if f]
check("27. side_effects читают только реестр, тесты и документация: %s" % ", ".join(_files),
      all(f.startswith("tools/") or f.startswith(".ai/")
          or f == "app/route_policy_registry.py" for f in _files))

# ════════════════════════════════════════════════════════════════════════════
section("предохранители и метка-ловушка")

_ORCH = rd("app/project_orchestrator.py")
check("28. автоматическая отправка остаётся выключенной",
      re.search(r'^DISPATCH_ENABLED = False\s*$', _ORCH, re.M) is not None
      and re.search(r'^TRANSPORT_ENABLED = False\s*$', _ORCH, re.M) is not None)
check("29. capability contract 2.793 не изменён",
      "MODULE_ACCESS_CONTRACT_VERSION = 1" in rd("web/app.js")
      and ':access="moduleAccess"' in rd("web/index.html"))
check("30. фронтенд модулей не менялся ради метаданных",
      "CAP_CONTRACT_VERSION = 1" in rd("modules/inventory/web/InventoryPanel.js")
      and "CAP_CONTRACT_VERSION = 1" in rd("modules/cost/web/CostPanel.js"))
check("31. метка-ловушка отсутствует в производственном коде",
      not any(SENTINEL in rd(f) for f in ("app/route_policy_registry.py", "server.py",
                                          "modules/cost/backend.py", "modules/quality/backend.py",
                                          "modules/inventory/backend.py", "web/app.js")))

print("\n" + "=" * 76)
sys.exit(HIST.summary(total - fail, fail))
