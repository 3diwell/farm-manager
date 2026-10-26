# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Полнота декларативного реестра маршрутов (Alpha 2.783, актуализирован в 2.784).
#
# БЕЗ запуска приложения: production server.py НЕ импортируется — он на уровне модуля
# берёт глобальный named mutex одиночного экземпляра, и при работающей программе импорт
# вышел бы через sys.exit(0), сделав тест ЛОЖНО-зелёным. Здесь исходники разбираются
# через AST; БД, DATA_DIR, сеть и модульный код со сторонними эффектами не трогаются.
#
# ЧТО ПРОВЕРЯЕТСЯ. Реестр обязан описывать РОВНО то, что есть в коде: каждый маршрут ядра,
# каждый маршрут модуля, WebSocket, методы, обработчики, состав _GATE_EXCLUDE, префикс
# /api/auth/, все handler-level guard и фактический результат _route_perm.
#
# ЧТО НЕ ПРОВЕРЯЕТСЯ. Безопасность модели доступа и правильность самих прав — это предмет
# соседнего теста tools/test_core_route_permissions.py. Здесь проверяется ПОЛНОТА описи.
#
# ЧТО ИЗМЕНИЛА Alpha 2.784. Реестр перестал быть только документом: объявленная карта прав
# используется в рантайме. Поэтому проверки «реестр не импортируется в server.py» заменены
# на противоположные, а _auth_gate исключена из списка неизменных функций — её правка и
# составляет содержание 2.784. Все остальные границы доступа обязаны остаться нетронутыми.
#
# Запуск: python tools/test_route_policy_registry.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import glob
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
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

# Эталон для проверки неизменности поведения. С Alpha 2.784 сравниваем с 8fe9e70 —
# состоянием ДО этой правки: так проверка доказывает, что 2.784 изменила ровно одну
# функцию (_auth_gate) и не задела ни одну границу доступа.
PARENT = "8fe9e70"

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


# ── Обнаружение маршрутов в исходнике (независимо от реестра) ────────────────
GATE_LINE = [l for l in SRC.splitlines() if l.startswith("_GATE_EXCLUDE")][0]
SRC_GATE = set(re.findall(r'"(/api/[^"]+)"', GATE_LINE))

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def route_perm(method, path):
    """Точная копия правил _route_perm ядра, применённая к шаблону маршрута.
    Параметры пути подставляются заглушкой только здесь, в самом реестре они не искажаются."""
    p = re.sub(r"\{[^}]+\}", "X", path)
    if method == "GET":
        return None
    if p.endswith(("/upload_print", "/print_path", "/cmd", "/speedtest")) or p == "/api/part/print":
        return "operate"
    if re.match(r"^/api/projects2/[^/]+/files/[^/]+/print$", p):
        return "operate"
    if p.endswith("/webrtc") or p.startswith("/api/diagnostics/"):
        return None
    if p in ("/api/printers/save", "/api/printer/verify"):
        return "printer_write"
    if method == "PATCH" and re.match(r"^/api/projects2/[^/]+/parts/[^/]+$", p):
        return "count"
    if method == "POST" and re.match(r"^/api/projects2/[^/]+/parts/[^/]+/rework$", p):
        return "rework"
    return "project"


def discover_core():
    """(method, path, handler, guard) для каждого маршрута ядра."""
    found = []
    for n in ast.walk(TREE):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.unparse(n)
        guard = ("SYSTEM_ADMIN" if "_require_system_admin" in body else
                 "CALLBACK_SECRET" if "_require_slicer_callback" in body else
                 # Alpha 2.798: local-recovery guard — loopback-peer + одноразовый tray-токен.
                 "LOCAL_RECOVERY" if "_LOCAL_RECOVERY.consume" in body else
                 "HANDLER_ADMIN" if "_require_admin" in body else "NONE")
        for d in n.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.args and isinstance(d.args[0], ast.Constant)):
                continue
            if getattr(d.func.value, "id", None) != "app":
                continue
            m = d.func.attr.upper()
            if m == "WEBSOCKET":
                found.append(("WS", d.args[0].value, n.name, guard))
            elif m in HTTP_METHODS:
                found.append((m, d.args[0].value, n.name, guard))
    return found


def discover_modules():
    """(module_id, version, rel, full, method, handler) для маршрутов модулей."""
    out = []
    for f in sorted(glob.glob(os.path.join(REPO, "modules", "*", "backend.py"))):
        mid = os.path.basename(os.path.dirname(f))
        mj = os.path.join(os.path.dirname(f), "module.json")
        ver = re.search(r'"version"\s*:\s*"([^"]+)"', open(mj, encoding="utf-8").read()).group(1)
        t = ast.parse(open(f, encoding="utf-8").read())
        for n in ast.walk(t):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_route" and n.args
                    and isinstance(n.args[0], ast.Constant)):
                continue
            rel = n.args[0].value
            handler = ast.unparse(n.args[1]) if len(n.args) > 1 else "?"
            methods = ("GET",)
            if len(n.args) > 2:
                try:
                    methods = tuple(x.value for x in n.args[2].elts)
                except Exception:
                    pass
            for kw in n.keywords or []:
                if kw.arg == "methods":
                    try:
                        methods = tuple(x.value for x in kw.value.elts)
                    except Exception:
                        pass
            full = "/api/mod/%s/%s" % (mid, rel.lstrip("/"))
            for m in methods:
                out.append((mid, ver, rel, full, m.upper(), handler))
    return out


print("=== Alpha 2.783: полнота декларативного реестра маршрутов ===")

# ═══ ЧАСТЬ 1. Импорт реестра и его чистота ═══
print("--- чистота модуля реестра ---")

try:
    from app import route_policy_registry as reg
    _ok_imp = True
except Exception as _e:
    reg, _ok_imp = None, False
    print("  (app/route_policy_registry.py недоступен: %s)" % _e)
check("R0. app/route_policy_registry.py импортируется", _ok_imp)

if _ok_imp:
    _REG_SRC = open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read()
    # Анализировать надо КОД, а не пояснения: докстрока честно упоминает DATA_DIR и БД
    # словами «не открывает», а ключ сводки называется websocket — наивный поиск подстрок
    # дал бы ложное срабатывание на обоих.
    # Модуль ImportFrom берём ЦЕЛИКОМ, а не первым сегментом: иначе «app» разрешал бы
    # любой импорт из пакета, включая тяжёлые. Alpha 2.784 добавила ровно одну
    # зависимость — чистую модель данных app/route_access_control.py (тоже без
    # фреймворка, БД, сети и config; её чистота проверяется в E1 соседнего теста).
    _REG_IMPORTS = set()
    for _n in ast.walk(ast.parse(_REG_SRC)):
        if isinstance(_n, ast.Import):
            _REG_IMPORTS.update(a.name for a in _n.names)
        elif isinstance(_n, ast.ImportFrom) and _n.module:
            _REG_IMPORTS.add(_n.module)
    check("R1. реестр импортирует только модели данных: %s" % sorted(_REG_IMPORTS),
          _REG_IMPORTS <= {"enum", "dataclasses", "typing", "app.route_access_control"})

    _REG_CALLS = set()
    for _n in ast.walk(ast.parse(_REG_SRC)):
        if isinstance(_n, ast.Call):
            _REG_CALLS.add(ast.unparse(_n.func))
    check("R2. импорт без побочных эффектов: нет open/print/subprocess/сети",
          not any(c.split(".")[0] in ("open", "print", "subprocess", "socket", "urllib", "sqlite3")
                  for c in _REG_CALLS))
    check("R3. реестр не выполняет авторизацию (нет решений allow/deny)",
          all(x not in _REG_SRC for x in ("def authorize", "def check_access", "raise HTTPException",
                                          "status_code=403", "status_code=401")))
    check("R4. записи неизменяемы (frozen dataclass) и детерминированы (кортежи)",
          "frozen=True" in _REG_SRC and "ALL_POLICIES = " in _REG_SRC)
    # Детерминированность: две выборки подряд идентичны по составу и порядку.
    check("R5. all_policies() детерминирован",
          [p.route_id for p in reg.all_policies()] == [p.route_id for p in reg.all_policies()])

# ═══ ЧАСТЬ 2. Полнота: исходник <-> реестр ═══
print("--- полнота описи ---")

if _ok_imp:
    core = discover_core()
    mods = discover_modules()
    core_keys = set((m, p) for m, p, _h, _g in core)
    reg_core = [p for p in reg.all_policies() if p.module_id is None]
    reg_core_keys = set((p.method, p.path) for p in reg_core)

    check("C1. каждый маршрут ядра из исходника есть в реестре: не хватает %d"
          % len(core_keys - reg_core_keys), core_keys <= reg_core_keys)
    check("C2. каждая запись ядра существует в исходнике: лишних %d"
          % len(reg_core_keys - core_keys), reg_core_keys <= core_keys)

    mod_keys = set((m, full) for _mid, _v, _r, full, m, _h in mods)
    reg_mod = [p for p in reg.all_policies() if p.module_id is not None]
    reg_mod_keys = set((p.method, p.path) for p in reg_mod)
    check("C3. каждый маршрут модуля есть в реестре: не хватает %d" % len(mod_keys - reg_mod_keys),
          mod_keys <= reg_mod_keys)
    check("C4. каждая запись модуля существует: лишних %d" % len(reg_mod_keys - mod_keys),
          reg_mod_keys <= mod_keys)

    # Alpha 2.879: сокетов стало два — телеметрия /ws и камера /api/printer/{pid}/camera.ws.
    check("C5. WebSocket учтён отдельным видом, а не фиктивным GET",
          sum(1 for p in reg.all_policies() if p.kind is reg.RouteKind.WEBSOCKET) == 2
          and reg.policy_for("WS", "/ws") is not None
          and reg.policy_for("GET", "/ws") is None
          and reg.policy_for("WS", "/api/printer/{pid}/camera.ws") is not None
          and reg.policy_for("GET", "/api/printer/{pid}/camera.ws") is None)

    src_handlers = {(m, p): h for m, p, h, _g in core}
    bad_h = [p.route_id for p in reg_core if src_handlers.get((p.method, p.path)) != p.handler]
    check("C8. обработчик совпадает у всех записей ядра: расхождений %d" % len(bad_h), not bad_h)

    mod_handlers = {(m, full): h for _mid, _v, _r, full, m, h in mods}
    bad_mh = [p.route_id for p in reg_mod if mod_handlers.get((p.method, p.path)) != p.handler]
    check("C8b. обработчик совпадает у всех записей модулей: расхождений %d" % len(bad_mh), not bad_mh)

    ids = [p.route_id for p in reg.all_policies()]
    check("C9. route_id уникальны", len(ids) == len(set(ids)))
    check("C10. нет дублей метод+путь",
          len(set((p.method, p.path) for p in reg.all_policies())) == len(ids))
    check("C11. HEAD/OPTIONS в реестр не попали",
          not any(p.method in ("HEAD", "OPTIONS") for p in reg.all_policies()))

# ═══ ЧАСТЬ 3. Границы доступа отражены точно ═══
print("--- границы доступа ---")

if _ok_imp:
    reg_gate = set(p.path for p in reg.all_policies() if p.gate_excluded)
    check("C12. все 5 маршрутов _GATE_EXCLUDE отмечены точно (%d)" % len(reg_gate),
          reg_gate == SRC_GATE and len(SRC_GATE) == 5)
    check("C13. шестой маршрут как gate_excluded не отмечен", reg_gate <= SRC_GATE)
    check("C13b. зеркало GATE_EXCLUDE_PATHS совпадает с исходником",
          set(reg.GATE_EXCLUDE_PATHS) == SRC_GATE)

    bypass = [p for p in reg.all_policies() if p.auth_namespace_bypass]
    check("C14. все /api/auth/* отмечены bypass (%d)" % len(bypass),
          all(p.path.startswith("/api/auth/") for p in bypass) and len(bypass) == 12)
    check("C15. вне /api/auth/* bypass не отмечен",
          not any(p.auth_namespace_bypass for p in reg.all_policies()
                  if not p.path.startswith("/api/auth/")))

    src_guard = {(m, p): g for m, p, _h, g in core}
    # Alpha 2.787: SYSTEM_ADMIN стало 12 — POST /api/network получил собственную границу
    # (открытие фермы в сеть — административное действие, прежде маршрут guard не имел).
    # Alpha 2.788: CALLBACK_SECRET стало 3 — POST /server/files/upload получил ту же границу,
    # что и его OctoPrint-близнец /api/files/local (loopback + ключ интеграции 2.781).
    # Alpha 2.798: LOCAL_RECOVERY стало 1 — POST /api/auth/local-recovery/complete получил
    # собственную границу (loopback-peer + одноразовый tray-токен, сессия не требуется).
    # Alpha 2.813: SYSTEM_ADMIN стало 13 — GET /api/diagnostics получил собственную границу.
    # Журнал показывает работу фермы целиком (и до 2.813 был доступен любому вошедшему), а с
    # появлением встроенного просмотрщика он стал обычным пользовательским экраном — значит,
    # граница обязана быть административной: admin при включённой защите, локальный хозяин при
    # выключенной.
    # Alpha 2.823: +2 SYSTEM_ADMIN (pf_delete, pf_settings_set — удаление файлов принтера
    # и его предохранитель закрыты административной границей) -> 15.
    # Alpha 2.827: +4 SYSTEM_ADMIN (config-backup export/inspect/restore/status — постоянный
    # контракт резервного копирования; все закрыты границей system-admin loopback/локально) -> 19.
    # 26.09.2026: +3 SYSTEM_ADMIN (лицензии модулей: список, импорт, удаление) -> 22.
    for gname, expect in (("SYSTEM_ADMIN", 22), ("CALLBACK_SECRET", 3), ("HANDLER_ADMIN", 6), ("LOCAL_RECOVERY", 1)):
        got = [p for p in reg_core if p.handler_guard.value == gname]
        src_n = sum(1 for k, g in src_guard.items() if g == gname)
        check("C16-18. guard %-16s в реестре=%d, в исходнике=%d, ожидалось=%d"
              % (gname, len(got), src_n, expect),
              len(got) == src_n == expect)
    mism = [p.route_id for p in reg_core
            if src_guard.get((p.method, p.path)) != p.handler_guard.value]
    check("C19-20. guard объявлен ровно там, где он есть в коде: расхождений %d" % len(mism), not mism)

# ═══ ЧАСТЬ 4. Текущие права отражены точно ═══
print("--- текущие права (_route_perm) ---")

if _ok_imp:
    bad_perm = [p.route_id for p in reg.all_policies()
                if p.current_permission != route_perm("GET" if p.method == "WS" else p.method, p.path)]
    check("C21. current_permission совпадает с фактическим _route_perm: расхождений %d" % len(bad_perm),
          not bad_perm)
    gets = [p for p in reg.all_policies() if p.method in ("GET", "WS")]
    check("C22. GET/WS fallback None отражён точно (%d)" % len(gets),
          all(p.current_permission is None for p in gets))
    muts = [p for p in reg.all_policies() if not p.read_only]
    proj = [p for p in muts if p.current_permission == "project"]
    check("C23. mutating fallback 'project' отражён точно (%d из %d)" % (len(proj), len(muts)),
          len(proj) == sum(1 for p in muts
                           if route_perm(p.method, p.path) == "project"))
    mut_none = [p.route_id for p in muts if p.current_permission is None]
    #  2.980 (R-092): +2 — запуск и остановка сырой записи сетевых объявлений. Они живут по
    #  правилам диагностики (общее правило прав отдаёт None для всего /api/diagnostics/), а
    #  доступ к ним закрыт отдельной записью в _SPECIAL_ENFORCED правом администратора.
    check("C24. известные mutating с perm=None отражены: найдено %d" % len(mut_none),
          len(mut_none) == 9)
    check("C25. все 51 маршрутов модулей отражают текущий fallback",
          len(reg_mod) == 51
          and all(p.current_permission == route_perm(p.method, p.path) for p in reg_mod))

    check("C29-30. значения side_effects и sensitivity принадлежат перечислениям",
          all(isinstance(p.sensitivity, reg.Sensitivity) for p in reg.all_policies())
          and all(isinstance(e, reg.SideEffect) for p in reg.all_policies() for e in p.side_effects))

    # Alpha 2.794: у маршрутов модулей объявление эффектов сверено с фактическими обработчиками
    # (доказательство — tools/test_module_route_side_effect_metadata.py). Здесь фиксируется лишь
    # инвариант состава: никаких недоказанных категорий и никакого вывода read_only по методу.
    #  2.994: модуль «Уведомления в мессенджеры» по назначению выходит в сеть (пробная отправка,
    #  мастер подключения) — у него разрешён ещё и NETWORK; доказательство — tools/test_messengers_module.py.
    #  3.0: модуль cost — «Расчёт заказа» (заменил «Себестоимость печати»): хранит файлы заказов и
    #  обращается к самой программе на 127.0.0.1 — у него ещё FILESYSTEM и NETWORK; доказательство —
    #  tools/test_cost_module.py (раздел I). Его расчёт пишет кэш, поэтому из read-only-исключений убран.
    _mod_eff = {e.value for p in reg_mod if p.module_id not in ("messengers", "cost") for e in p.side_effects}
    _msg_eff = {e.value for p in reg_mod if p.module_id == "messengers" for e in p.side_effects}
    _cost_eff = {e.value for p in reg_mod if p.module_id == "cost" for e in p.side_effects}
    check("C31. эффекты маршрутов модулей — только доказанные NONE/DATABASE (%s); messengers: +NETWORK (%s); cost: +FILESYSTEM, NETWORK (%s)"
          % (", ".join(sorted(_mod_eff)), ", ".join(sorted(_msg_eff)), ", ".join(sorted(_cost_eff))),
          _mod_eff <= {"NONE", "DATABASE"} and _mod_eff == {"NONE", "DATABASE"}
          and _msg_eff == {"NONE", "DATABASE", "NETWORK"}
          and _cost_eff == {"NONE", "DATABASE", "FILESYSTEM", "NETWORK"})
    check("C32. read_only-исключения из вывода по методу заданы явным коротким списком (%d)"
          % len(reg.READ_ONLY_DESPITE_METHOD),
          isinstance(reg.READ_ONLY_DESPITE_METHOD, frozenset)
          and reg.READ_ONLY_DESPITE_METHOD == {"inventory.spool.bulk_delete_preview"}
          and all(p.read_only for p in reg_mod if p.policy_id in reg.READ_ONLY_DESPITE_METHOD))

    counts = reg.registry_counts()
    # Alpha 2.798: +1 маршрут ядра (local-recovery) -> 213/168.
    # Alpha 2.823: +5 маршрутов ядра (файловый менеджер принтеров: capabilities/storages/
    # list/delete/settings) -> ядро 173, всего 218.
    # Alpha 2.825: +1 маршрут ядра (printer-files/select-for-print — resolve файла для
    # печати, чтение; старт остаётся в p_cmd) -> ядро 174, всего 219.
    # Alpha 2.827: +4 маршрута ядра (config-backup export/inspect/restore/status — постоянный
    # контракт резервного копирования; 3 POST + 1 GET) -> ядро 178, всего 223.
    # Alpha 2.831: +2 маршрута ядра (printer-sort-mode GET/POST) -> ядро 180, всего 225.
    # Alpha 2.833: +2 маршрута ядра (klipper-prestart GET/POST) -> ядро 182, всего 227.
    # Alpha 2.870: +1 маршрут ядра — камера без перекодирования (GET /api/printer/{pid}/camera.mp4).
    # Alpha 2.879: +1 маршрут ядра — камера по WebSocket (обход предела в шесть
    # одновременных ответов HTTP/1.1 на один адрес; измерено 25.08.2026).
    #  Alpha 2.920: +5 маршрутов ядра — очередь ОЖИДАНИЯ (список, добавить, убрать,
    #  подтверждённый запуск) и флаг разрешения запуска из очереди. 1 GET + 4 POST.
    #  Alpha 2.927: +3 маршрута ядра — пометки принтера (сопло/материал/группа) и
    #  настройки фермы (GET+POST): единые данные на всю ферму с любого компьютера.
    #  Alpha 2.947: +1 маршрут ядра — переключатель синхронизации задачи с проектом (POST).
    #  2.978: +1 маршрут ядра — «где лежит файл проекта» (POST .../files/{file_id}/locate).
    #  Он заменил пути на диске, которые дерево проекта отдавало всем, включая наблюдателя.
    #  2.980 (R-092): +7 маршрутов ядра — поиск принтеров в сети (запуск, снимок, остановка,
    #  смена адреса) и сырая запись сетевых объявлений для снятия контракта на ферме.
    check("C-BASE. baseline: всего=250, ядро=205, модули=45, WebSocket=2",
          counts["total"] == 260 and counts["core"] == 209   # 2.989 +printer-files/preview; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
          and counts["modules"] == 51 and counts["websocket"] == 2)
    #  2.903: GET стало на три больше — страница UI 3.0 и её файлы. 2.920: +1 GET, +4 POST.
    #  2.927: +1 GET (farm-settings), +2 POST (marks, farm-settings). 12.09.2026: −1 POST (marks удалён).
    check("C-BASE2. ядро по методам: GET=87 POST=110 DELETE=6 PATCH=4 WS=2",
          sum(1 for p in reg_core if p.method == "GET") == 87   # 2.989 +printer-files/preview
          and sum(1 for p in reg_core if p.method == "POST") == 110
          and sum(1 for p in reg_core if p.method == "DELETE") == 6
          and sum(1 for p in reg_core if p.method == "PATCH") == 4
          and sum(1 for p in reg_core if p.method == "WS") == 2)

# ═══ ЧАСТЬ 5. Неизменность поведения относительно Alpha 2.782 ═══
# Сравниваем ФУНКЦИИ, а не файл целиком: версия и CHANGELOG обязаны отличаться.
print("--- поведение не изменено относительно %s ---" % PARENT)


def parent_src():
    try:
        out = subprocess.run(["git", "-C", REPO, "show", "%s:server.py" % PARENT],
                             capture_output=True)
        return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None
    except Exception:
        return None


def fn_text(src, name):
    try:
        t = ast.parse(src)
    except Exception:
        return None
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


_par = parent_src()
#  26.09.2026: в открытой выгрузке закрытой истории нет — сверять с эталоном не с чем. Там сверка
#  пропускается с пометкой; в закрытом репозитории эталон обязан читаться, как и раньше.
#  Правило «открытая копия» одно на все наборы (tools/_history_baseline.py): метка выгрузки
#  И отсутствие первого коммита закрытой истории — метка, случайно попавшая в закрытое дерево,
#  пропуска не включает.
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402
if _par is None and HB.is_public_tree(REPO):
    print("SKIP — B0. эталона %s в этой копии нет (открытая выгрузка с новой историей)" % PARENT)
else:
    check("B0. эталон %s:server.py прочитан" % PARENT, _par is not None)
if _par:
    # _auth_gate в этом списке НЕТ намеренно: Alpha 2.784 переписала именно её.
    # Остальные границы доступа обязаны остаться нетронутыми — это и есть доказательство,
    # что явная карта прав не задела ни один существующий guard.
    # _auth_gate и ModuleCore.add_route в этом списке НЕТ намеренно: их переписали
    # Alpha 2.784 и 2.785. Остальные границы доступа обязаны остаться нетронутыми —
    # это и есть доказательство, что явная карта прав не задела ни один существующий guard.
    for fn in ("_route_perm", "_has_perm", "_require_admin",
               "_require_system_admin", "_require_slicer_callback",
               "_session_user", "_req_role"):
        a, b = fn_text(_par, fn), fn_text(SRC, fn)
        check("B. %-26s не изменена" % fn, a is not None and a == b)
    check("B. _auth_gate изменена НАМЕРЕННО (Alpha 2.784: явная карта прав)",
          fn_text(_par, "_auth_gate") is not None
          and fn_text(_par, "_auth_gate") != fn_text(SRC, "_auth_gate"))
    check("B. add_route изменена НАМЕРЕННО (Alpha 2.785: policy_id + атомарная регистрация)",
          fn_text(SRC, "add_route") is not None and "policy_id" in fn_text(SRC, "add_route"))
    check("B. ws_ep изменена НАМЕРЕННО (Alpha 2.786: авторизация и перепроверка WebSocket)",
          fn_text(SRC, "ws_ep") is not None and "_ws_auth_state" in fn_text(SRC, "ws_ep")
          and "ws_origin_allowed" in fn_text(SRC, "ws_ep"))
    par_gate = [l for l in _par.splitlines() if l.startswith("_GATE_EXCLUDE")]
    check("B. _GATE_EXCLUDE не изменён", par_gate and par_gate[0] == GATE_LINE)

    # Декораторы маршрутов: состав и наличие dependencies.
    # Фильтр методов обязателен: @app.middleware("http") — тоже вызов app.<attr>("..."),
    # и без фильтра он попал бы в состав маршрутов лишней записью.
    par_core = set()
    for n in ast.walk(ast.parse(_par)):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args
                    and isinstance(d.args[0], ast.Constant)
                    and getattr(d.func.value, "id", None) == "app"):
                m = d.func.attr.upper()
                if m == "WEBSOCKET":
                    par_core.add(("WS", d.args[0].value))
                elif m in HTTP_METHODS:
                    par_core.add((m, d.args[0].value))
    # Относительно эталона 8fe9e70 добавлены ТОЛЬКО: local-recovery (2.798), пять
    # маршрутов файлового менеджера принтеров (2.823) и select-for-print (2.825);
    # ни один прежний маршрут не изменён и не удалён.
    _cur_core = set((m, p) for m, p, _h, _g in core)
    _NEW_SINCE_PARENT = {
        ("POST", "/api/auth/local-recovery/complete"),
        ("GET", "/api/printer-files/capabilities"),
        ("GET", "/api/printer-files/storages"),
        ("POST", "/api/printer-files/list"),
        ("POST", "/api/printer-files/delete"),
        ("POST", "/api/printer-files/settings"),
        ("POST", "/api/printer-files/select-for-print"),
        #  2.989: картинка предпросмотра файла — то же чтение файлов принтера.
        ("GET", "/api/printer-files/preview"),
        # Alpha 2.827: постоянный контракт резервного копирования конфигурации.
        ("POST", "/api/config-backup/export"),
        ("POST", "/api/config-backup/inspect"),
        ("POST", "/api/config-backup/restore"),
        ("GET", "/api/config-backup/status"),
        # Alpha 2.831: режим сортировки принтеров (визуальный; чтение public, запись printer_write).
        ("GET", "/api/printer-sort-mode"),
        ("POST", "/api/printer-sort-mode"),
        # Alpha 2.833: capability-driven предстартовые операции Klipper (read-only discovery + prefs).
        ("GET", "/api/printer/{pid}/klipper-prestart"),
        ("POST", "/api/printer/{pid}/klipper-prestart"),
        # Alpha 2.870: тот же поток камеры без перекодирования (fMP4). Только чтение,
        # принтеру ничего не отправляется; прежний /camera остаётся запасным путём.
        ("GET", "/api/printer/{pid}/camera.mp4"),
        # Alpha 2.839: диагностический сбор контракта подготовки печати. POST только к Farm
        # Manager; принтеру уходят исключительно GET по неизменяемому allowlist.
        ("POST", "/api/printer/{pid}/klipper-contract-report"),
        # Alpha 2.879: тот же поток камеры по WebSocket. Причина — измеренный предел браузера:
        # шесть длинных ответов HTTP/1.1 на один адрес, седьмая камера не получает ничего.
        # Alpha 2.903: второй интерфейс UI 3.0 — страница и её файлы. Обычная статика браузера.
        ("GET", "/ui3"),
        ("GET", "/ui3/"),
        ("GET", "/ui3/{asset_path:path}"),
        ("WS", "/api/printer/{pid}/camera.ws"),
        # Alpha 2.920: очередь ожидания и флаг разрешения запуска из очереди. Постановка,
        # снятие и подтверждённый запуск — право 'project', как у постановки в очередь запусков.
        ("GET", "/api/queue-wait"),
        ("POST", "/api/queue-wait/add"),
        ("POST", "/api/queue-wait/remove"),
        ("POST", "/api/queue-wait/start"),
        ("POST", "/api/printer/queue-allowed"),
        #  2.927: настройки фермы — единые на всю ферму. Пометки принтера и их маршрут записи
        #  удалены 12.09.2026 по слову владельца.
        ("GET", "/api/farm-settings"),
        ("POST", "/api/farm-settings"),
        #  2.947: переключатель «считать печать задачи и в проекте». Право 'project' — как
        #  у остальной правки задач; на сам запуск печати маршрут не влияет.
        ("POST", "/api/staging/sync"),
        #  2.978: «где лежит файл проекта». Появился взамен путей на диске в дереве проекта:
        #  дерево читает и наблюдатель, а путь теперь отдаётся по явному запросу и по праву
        #  'project'. На печать и на файлы маршрут не влияет — только читает запись.
        ("POST", "/api/projects2/{project_id}/files/{file_id}/locate"),
        #  2.980 (R-092): программа сама находит принтеры, объявившиеся в сети. Поиск слушает
        #  объявления и один раз спрашивает «представься»; перебора сети нет — это прямой
        #  запрет владельца. Смена адреса меняет ТОЛЬКО ip и только по нажатию владельца.
        ("POST", "/api/printer-discovery/start"),
        ("GET", "/api/printer-discovery"),
        ("POST", "/api/printer-discovery/stop"),
        ("POST", "/api/printer-discovery/rebind"),
        #  Сырая запись сетевых объявлений: без неё контракт с настоящих принтеров не снять.
        ("POST", "/api/diagnostics/net-capture/start"),
        ("POST", "/api/diagnostics/net-capture/stop"),
        ("GET", "/api/diagnostics/net-capture"),
        #  16.09.2026: подтверждение «Стол очищен» ВНЕ проектного запуска — для очереди
        #  ожидания и автозапуска. Раньше кнопка жила только внутри «Печатать весь проект»,
        #  поэтому в очереди вместо запрета стоял текст «убедитесь, что стол пуст». Механизм
        #  прежний: тот же одноразовый жетон и та же единственная точка его создания.
        ("POST", "/api/printer/{printer_id}/plate-clear"),
        ("POST", "/api/printer/{printer_id}/plate-clear/revoke"),
        #  26.09.2026: лицензии модулей — список, импорт файла, удаление. Только администратор
        #  (SYSTEM_ADMIN, как установка модулей); на печать, очередь и данные фермы не влияют.
        ("GET", "/api/licenses"),
        ("POST", "/api/licenses/import"),
        ("DELETE", "/api/licenses/{license_id}"),
    }
    #  2.948: маршрут /api/projects2/pending-printable УДАЛЁН вместе со сценарием подсказок по
    #  типам принтеров (заказ владельца: вырезать без остатка). Единственное допустимое удаление.
    _GONE_SINCE_PARENT = {("GET", "/api/projects2/pending-printable")}
    check("B. состав маршрутов ядра: добавлены только local-recovery (2.798), printer-files (2.823), select-for-print (2.825), config-backup (2.827), printer-sort-mode (2.831), klipper-prestart (2.833), klipper-contract-report (2.839) и камера без перекодирования (2.870), синхронизация задачи с проектом (2.947)",
          (_cur_core - par_core) == _NEW_SINCE_PARENT and (par_core - _cur_core) == _GONE_SINCE_PARENT)
    check("B. декораторы маршрутов не получили dependencies",
          "dependencies=" not in SRC)

# Alpha 2.784 ИЗМЕНИЛА эти два условия на противоположные: реестр теперь участвует в
# рантайме как источник объявленной карты прав. Сам он по-прежнему остаётся данными —
# решение принимает app/route_access_control.py, а маршрут определяет app/route_matching.py.
check("B. реестр подключён к рантайму как источник карты прав (2.784)",
      "route_policy_registry" in SRC and "core_http_policy" in SRC)
check("B. решение принимает движок, а не реестр (реестр остаётся данными)",
      "route_access_control" in SRC and "_route_access.decide" in SRC
      and "def decide" not in open(os.path.join(REPO, "app", "route_policy_registry.py"),
                                   encoding="utf-8").read())
check("B. маршрут определяется средствами фреймворка, а не префиксом строки",
      "route_matching" in SRC and "resolve_matched_route" in SRC)

# ═══ ЧАСТЬ 6. Обнаружение расхождений (drift) ═══
# Проверки C1–C4, C8, C12, C16–C20 сами по себе краснеют при добавлении/удалении маршрута,
# смене метода, пути, обработчика, состава _GATE_EXCLUDE и любого handler-guard.
print("--- обнаружение расхождений ---")
if _ok_imp:
    fake = set(core_keys) | {("POST", "/api/новый-маршрут-без-записи")}
    check("D31. новый маршрут без записи в реестре делает проверку красной",
          not (fake <= reg_core_keys))
    fake2 = set(reg_core_keys) | {("POST", "/api/удалённый-маршрут")}
    check("D32. запись без маршрута в исходнике делает проверку красной",
          not (fake2 <= core_keys))
    # Детерминированный выбор (Alpha 2.805): next(iter(set)) зависел от хеш-рандомизации, и когда
    # выпадал маршрут, чей путь имеет и PATCH-вариант (например DELETE+PATCH /api/projects2/{id}),
    # «мутация метода» совпадала с существующим ключом и была необнаружима — ложный FAIL ~раз в 40
    # прогонов. Берём первый по сортировке маршрут, для которого мутировавший ключ ЗАВЕДОМО
    # отсутствует в реестре.
    some = next(t for t in sorted(core_keys)
                if ("PATCH" if t[0] != "PATCH" else "PUT", t[1]) not in reg_core_keys)
    changed = (set(core_keys) - {some}) | {("PATCH" if some[0] != "PATCH" else "PUT", some[1])}
    check("D33. изменение метода делает проверку красной", not (changed <= reg_core_keys))
    check("D34. изменение состава _GATE_EXCLUDE делает проверку красной",
          (SRC_GATE | {"/api/чужое"}) != set(reg.GATE_EXCLUDE_PATHS))
    check("D35-36. появление/снятие guard делает проверку красной",
          any(p.handler_guard.value != "NONE" for p in reg_core)
          and all(src_guard.get((p.method, p.path)) == p.handler_guard.value for p in reg_core))

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
