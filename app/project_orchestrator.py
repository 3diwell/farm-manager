# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Оркестратор «Печатать весь проект» — БЕЗОПАСНЫЙ ФУНДАМЕНТ (этапы 1-4 + 5A1 + 5A2a, Alpha 2.742).

ЭТА ВЕРСИЯ НИЧЕГО НЕ ПЕЧАТАЕТ. Здесь только: аддитивные таблицы, планировщик покрытия,
одноразовые подтверждения «Стол очищен», dry-run state machine, recovery-диагностика, удержание
принтера (5A1) и ПОСТРОЕНИЕ ПЛАНА ПОДАЧИ (5A2a — чистое вычисление + запись в свою колонку).
Реальная отправка (reservation + вызов существующей точки печати) — ОТДЕЛЬНАЯ задача, этап 5B.

Предохранитель: DISPATCH_ENABLED = False. Модуль НЕ импортирует и не вызывает ничего из печатного
пути (_do_project2_file_print / _send_file_to_printer / _PrintSendManager / MQTT / FTP) — ни прямо,
ни косвенно. Всё, что понадобится оркестратору от ядра, приходит через init() как ЧИТАЮЩИЕ пробы.
Inventory/Quality/Cost не импортируются и их БД не читаются: складские данные приходят ТОЛЬКО через
generic-снимки ядра (§10.1 AGENTS.md), а сверка с отчётом принтера считается здесь по generic
core-геттеру reported filament — ни строчки про конкретный модуль.

Владелец данных — farm_parts.db (там же projects/project_parts/project_files/project_print_jobs),
работаем через переданные conn/lock ядра. Существующие таблицы, строки и учёт НЕ ТРОГАЕМ.
"""
import json
import math
import time
import uuid

# ── ЖЁСТКИЙ ПРЕДОХРАНИТЕЛЬ ЭТАПА 1-4 ──────────────────────────────────────────────────────────
# Пока False, автоматическая отправка на принтер запрещена. Проверяется И на API-уровне (роуты
# server.py), И здесь, непосредственно перед будущей точкой dispatch — defense in depth.
DISPATCH_ENABLED = False
DISPATCH_DISABLED_REASON = "project_orchestrator_dispatch_disabled"

# ── ВТОРОЙ И ТРЕТИЙ ПРЕДОХРАНИТЕЛИ (Alpha 2.747, этап 5B1) ────────────────────────────────────
# Это СЕРВЕРНАЯ конфигурация и только она. Ни API, ни тело запроса, ни query, ни cookie, ни
# frontend изменить их не могут — иначе «выключено по умолчанию» ничего не стоило бы.
# Допуск к настоящему транспорту требует ОДНОВРЕМЕННО: DISPATCH_ENABLED и TRANSPORT_ENABLED, и
# printer_id в allowlist, и явного confirmed is True. Любое одно «нет» -> отказ до транспорта.
TRANSPORT_ENABLED = False
# Пустое НЕИЗМЕНЯЕМОЕ множество: пока сюда руками не впишут принтер, реальная отправка недостижима
# даже при включённых флагах. frozenset выбран намеренно — случайный .add() в рантайме невозможен.
ALLOWED_PRINTER_IDS = frozenset()
TRANSPORT_DISABLED_REASON = "project_orchestrator_transport_disabled"
PRINTER_NOT_ALLOWED_REASON = "printer_not_allowlisted"

# ── Состояния ─────────────────────────────────────────────────────────────────────────────────
RUN_DRAFT, RUN_RUNNING, RUN_PAUSED = "draft", "running", "paused"
RUN_WAIT_PRINTER, RUN_WAIT_CLEAR = "waiting_for_printer", "waiting_for_plate_clear"
RUN_ATTENTION, RUN_COMPLETED, RUN_CANCELLED = "attention_required", "completed", "cancelled"
RUN_ACTIVE_STATES = (RUN_DRAFT, RUN_RUNNING, RUN_PAUSED, RUN_WAIT_PRINTER, RUN_WAIT_CLEAR, RUN_ATTENTION)
RUN_STATES = RUN_ACTIVE_STATES + (RUN_COMPLETED, RUN_CANCELLED)

IT_PENDING, IT_ELIGIBLE, IT_BLOCKED = "pending", "eligible", "blocked"
IT_SUPERSEDED = "superseded_by_external_progress"
IT_FAILED_BEFORE, IT_AMBIGUOUS = "failed_before_dispatch", "ambiguous_after_dispatch"
IT_CANCELLED, IT_COMPLETED = "cancelled", "completed"
# Будущие (этап 5): валидатор их ЗНАЕТ, но production-код этой версии в них не переводит.
IT_LEASED, IT_SENDING = "leased", "sending"
IT_WAIT_START, IT_PRINTING, IT_WAIT_CLEAR = "waiting_start_confirmation", "printing", "waiting_plate_clear"
IT_FUTURE_STATES = (IT_LEASED, IT_SENDING, IT_WAIT_START, IT_PRINTING, IT_WAIT_CLEAR)
IT_STATES_NOW = (IT_PENDING, IT_ELIGIBLE, IT_BLOCKED, IT_SUPERSEDED, IT_FAILED_BEFORE,
                 IT_AMBIGUOUS, IT_CANCELLED, IT_COMPLETED)
IT_STATES = IT_STATES_NOW + IT_FUTURE_STATES

BLOCK_NO_PRINTER = "no_compatible_printer"
BLOCK_OVERPRODUCTION = "overproduction_not_allowed"
BLOCK_FILE_MISSING = "file_missing"

PLAN_EXACT, PLAN_APPROX = "exact", "approximate"
PLANNER_NODE_LIMIT = 100000
PLANNER_TIME_LIMIT_MS = 300

_ctx = {"conn": None, "lock": None, "uid": None, "boot": "", "now": time.time,
        "printer_status": None, "compat_pids": None, "printers": None, "send_reserved": None,
        "file_ok": None, "safety": None, "holds": None, "set_hold": None, "clear_hold": None,
        "file_requirements": None, "filament_snapshot": None, "reported_filament": None}


def init(conn, lock, uid_fn, boot_id, printer_status_fn=None, compat_pids_fn=None,
         printers_fn=None, send_reserved_fn=None, now_fn=None, file_ok_fn=None, safety_fn=None,
         holds_fn=None, set_hold_fn=None, clear_hold_fn=None, file_requirements_fn=None,
         filament_snapshot_fn=None, reported_filament_fn=None):
    """Подключение к ядру. Все пробы — ТОЛЬКО ЧИТАЮЩИЕ; ни одна не умеет печатать:
      printer_status_fn(pid) -> (STATUS_UPPER, fresh)         — существующий _send_printer_status (UI-статус!)
      safety_fn(pid) -> dict                                  — БЕЗОПАСНОСТНЫЙ снимок (_get_printer_safety_snapshot):
          {status, status_raw, fresh, user_stopped_pending, printing_active, safe_idle, unsafe_reason, transport}
          Именно он, а НЕ printer_status_fn, решает «можно ли печатать»: UI-статус после веб-«Стоп»
          намеренно показывает Bambu как IDLE, пока идёт цикл отмены. Пробы нет -> всё небезопасно.
      compat_pids_fn(file_row) -> [printer_id, ...]           — существующая проверка совместимости
      printers_fn() -> [{id, name, type}]                     — список парка
      send_reserved_fn() -> set(printer_id)                   — принтеры с активной send-reservation (только чтение)
      file_ok_fn(file_row) -> bool                            — файл реально есть на диске (иначе плита непечатаема)
      holds_fn() -> {printer_id: {...}}                       — снимок удержаний принтеров (только чтение)
      set_hold_fn(pid, owner_type, owner_id, reason) -> (ok, hold)   — поставить удержание (in-memory ядра)
      clear_hold_fn(pid, owner_type, owner_id) -> bool               — снять СВОЁ удержание
    Удержание принтера — единственное, чем оркестратор воздействует на ядро, и оно НЕ печатает:
    это запрет чужого старта, а не команда принтеру.
    Пробы плана подачи (Alpha 2.742) — тоже ТОЛЬКО ЧИТАЮЩИЕ:
      file_requirements_fn(file_row) -> dict   — ядро читает 3mf и сверяет хеш (_file_filament_requirements)
      filament_snapshot_fn(pid) -> dict        — generic-снимок привязанного филамента (§10.1: провайдеры
          модулей, ядро про склад не знает; модуля нет -> {} -> источник недоказуем)
      reported_filament_fn(pid) -> dict        — generic отчётная телеметрия филамента (_printer_reported_filament)
    """
    _ctx["conn"], _ctx["lock"], _ctx["uid"], _ctx["boot"] = conn, lock, uid_fn, str(boot_id or "")
    _ctx["printer_status"] = printer_status_fn
    _ctx["compat_pids"] = compat_pids_fn
    _ctx["printers"] = printers_fn
    _ctx["send_reserved"] = send_reserved_fn
    _ctx["file_ok"] = file_ok_fn
    _ctx["safety"] = safety_fn
    _ctx["holds"] = holds_fn
    _ctx["set_hold"] = set_hold_fn
    _ctx["clear_hold"] = clear_hold_fn
    _ctx["file_requirements"] = file_requirements_fn
    _ctx["filament_snapshot"] = filament_snapshot_fn
    _ctx["reported_filament"] = reported_filament_fn
    if now_fn:
        _ctx["now"] = now_fn


_SAFETY_UNKNOWN = {"transport": "unknown", "status": "", "status_raw": "", "fresh": False,
                   "user_stopped_pending": False, "printing_active": True, "safe_idle": False}


def safety(printer_id):
    """Безопасностный снимок принтера. FAIL-CLOSED: нет пробы, проба упала или вернула не dict ->
    принтер считается небезопасным И «возможно печатающим» (printing_active=True). Догадок нет."""
    fn = _ctx.get("safety")
    if not fn:
        return dict(_SAFETY_UNKNOWN, printer_id=printer_id, unsafe_reason="no_safety_probe")
    try:
        s = fn(printer_id)
    except Exception:
        s = None
    if not isinstance(s, dict):
        return dict(_SAFETY_UNKNOWN, printer_id=printer_id, unsafe_reason="safety_probe_failed")
    out = dict(_SAFETY_UNKNOWN, printer_id=printer_id, unsafe_reason="")
    out.update(s)
    out["safe_idle"] = bool(out.get("safe_idle"))          # любое «почти правда» -> строгий bool
    out["printing_active"] = bool(out.get("printing_active"))
    return out


def _now():
    return float(_ctx["now"]())


def _uid(prefix):
    fn = _ctx.get("uid")
    return fn(prefix) if fn else (prefix + uuid.uuid4().hex[:12])


def _jdump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _jload(s, default):
    try:
        v = json.loads(s or "")
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. СХЕМА — ТОЛЬКО АДДИТИВНО
# ══════════════════════════════════════════════════════════════════════════════════════════════
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS project_runs (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, state TEXT NOT NULL,
        allow_overproduction INTEGER NOT NULL DEFAULT 0, plan_quality TEXT NOT NULL,
        print_opts_json TEXT NOT NULL DEFAULT '{}', blocked_json TEXT NOT NULL DEFAULT '[]',
        created_by TEXT DEFAULT '', boot_id TEXT NOT NULL, note TEXT DEFAULT '',
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        started_at REAL, finished_at REAL, cancelled_at REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_pruns_project ON project_runs(project_id, state)",
    # Не более ОДНОГО активного run на проект — структурный запрет уровня БД, а не проверка в коде.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pruns_active ON project_runs(project_id) WHERE state IN "
    "('draft','running','paused','waiting_for_printer','waiting_for_plate_clear','attention_required')",

    """CREATE TABLE IF NOT EXISTS project_run_items (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL, file_id TEXT NOT NULL,
        file_content_hash TEXT DEFAULT '', seq INTEGER NOT NULL, state TEXT NOT NULL,
        block_reason TEXT DEFAULT '',
        planned_parts_json TEXT NOT NULL DEFAULT '{}',
        planned_overproduction_json TEXT NOT NULL DEFAULT '{}',
        feed_plan_json TEXT NOT NULL DEFAULT '{}',
        assigned_printer_id TEXT DEFAULT '', lease_nonce TEXT DEFAULT '', lease_boot_id TEXT DEFAULT '',
        lease_acquired_at REAL, lease_expires_at REAL,
        clearance_id TEXT DEFAULT '', project_print_job_id TEXT DEFAULT '', send_job_id TEXT DEFAULT '',
        command_sent INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 0,
        last_error TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
        started_at REAL, finished_at REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_pri_run ON project_run_items(run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_pri_project ON project_run_items(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_pri_printer ON project_run_items(assigned_printer_id)",
    # Одно проектное задание — максимум одному item'у (готовим этап 5).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pri_pjob ON project_run_items(project_print_job_id) "
    "WHERE project_print_job_id != ''",
    # Два item'а на одном принтере в активных (будущих) состояниях невозможны — уровень БД.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pri_active_printer ON project_run_items(assigned_printer_id) "
    "WHERE assigned_printer_id != '' AND state IN "
    "('leased','sending','waiting_start_confirmation','printing','waiting_plate_clear')",

    """CREATE TABLE IF NOT EXISTS plate_clearances (
        id TEXT PRIMARY KEY, printer_id TEXT NOT NULL, finished_job_id TEXT NOT NULL DEFAULT '',
        confirmed_by TEXT DEFAULT '', confirmed_at REAL NOT NULL, nonce TEXT NOT NULL,
        boot_id TEXT NOT NULL, state_snapshot_json TEXT NOT NULL DEFAULT '{}',
        consumed_at REAL, consumed_by_item_id TEXT DEFAULT '',
        invalidated_at REAL, invalid_reason TEXT DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_clr_printer ON plate_clearances(printer_id, consumed_at)",
    # Живой токен на принтер ровно один: двойной клик «Стол очищен» второй токен не создаст.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_clr_active ON plate_clearances(printer_id) "
    "WHERE consumed_at IS NULL AND invalidated_at IS NULL",
]


# Аддитивные колонки СОБСТВЕННЫХ таблиц оркестратора: (таблица, колонка, DDL-тип с DEFAULT).
# Только ADD COLUMN и только по своим таблицам — чужие таблицы не ALTER'ятся никогда (см. init_db).
_MIGRATIONS = [
    ("project_run_items", "feed_plan_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def _migrate():
    """Идемпотентная аддитивная миграция СВОИХ таблиц: колонка добавляется, только если её нет.
    Разрушающих операций нет: ни DROP, ни переписывания DDL, ни UPDATE существующих строк —
    старые строки получают DEFAULT '{}' самим SQLite. Повторный вызов ничего не меняет."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    added = []
    with lock:
        for table, col, decl in _MIGRATIONS:
            have = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
            if col not in have:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
                added.append("%s.%s" % (table, col))
        if added:
            conn.commit()
    return added


def init_db():
    """Идемпотентно создаёт ТРИ новые таблицы и индексы, затем аддитивно мигрирует СВОИ таблицы.
    Существующие ЧУЖИЕ таблицы/строки не трогаются: ни ALTER, ни DELETE, ни UPDATE чужих данных.
    Затем инвалидирует токены прошлого запуска."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        for q in _SCHEMA:
            conn.execute(q)
        conn.commit()
    _migrate()                       # БД Alpha 2.740 без feed_plan_json -> ADD COLUMN (идемпотентно)
    invalidate_stale_boot_clearances()


def invalidate_stale_boot_clearances():
    """Токены чужого boot_id недействительны: после перезапуска доказательств пустого стола нет.
    Атомарно, идемпотентно. -> сколько погашено."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        cur = conn.execute(
            "UPDATE plate_clearances SET invalidated_at=?, invalid_reason='server_restart' "
            "WHERE consumed_at IS NULL AND invalidated_at IS NULL AND boot_id!=?",
            (_now(), _ctx["boot"]))
        conn.commit()
        return cur.rowcount


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. СНИМОК ПРОЕКТА (canonical remaining)
# ══════════════════════════════════════════════════════════════════════════════════════════════
def project_snapshot(project_id):
    """Вход планировщика. Остаток детали — по СУЩЕСТВУЮЩЕЙ семантике проекта (см. server.py
    finish_project_print_job): основной план max(0, required_qty - printed_qty) ПЛЮС открытая
    перепечатка max(0, rework_qty - rework_done). Ручные/экранные печати уже учтены ядром в
    printed_qty, поэтому отдельно их вычитать НЕ нужно — остаток и так уменьшается.
    -> {project_id, parts, files, links, active_jobs, version}"""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        parts = [dict(r) for r in conn.execute(
            "SELECT id, part_name, required_qty, printed_qty, rework_qty, rework_done, order_idx "
            "FROM project_parts WHERE project_id=? AND is_deleted=0 ORDER BY order_idx, id", (project_id,)).fetchall()]
        files = [dict(r) for r in conn.execute(
            "SELECT id, filename, content_hash, target_model, target_nozzles, is_printable, "
            "stored_path, src_path, order_idx FROM project_files WHERE project_id=? ORDER BY order_idx, id",
            (project_id,)).fetchall()]
        links = [dict(r) for r in conn.execute(
            "SELECT file_id, part_id, on_plate_qty FROM project_file_parts WHERE project_id=?", (project_id,)).fetchall()]
        active = [dict(r) for r in conn.execute(
            "SELECT id, printer_id, file_id FROM project_print_jobs "
            "WHERE project_id=? AND status='dispatched' AND counted_at=''", (project_id,)).fetchall()]
    if _ctx.get("file_ok"):
        for f in files:      # файла нет на диске -> плита непечатаема (planner даст честную причину file_missing)
            if not _ctx["file_ok"](f):
                f["is_printable"] = 0
    out_parts = []
    for p in parts:
        main_rem = max(0, int(p["required_qty"] or 0) - int(p["printed_qty"] or 0))
        rw_rem = max(0, int(p["rework_qty"] or 0) - int(p["rework_done"] or 0))
        out_parts.append({"part_id": p["id"], "part_name": p["part_name"],
                          "required_qty": int(p["required_qty"] or 0), "printed_qty": int(p["printed_qty"] or 0),
                          "rework_qty": int(p["rework_qty"] or 0), "rework_done": int(p["rework_done"] or 0),
                          "remaining": main_rem + rw_rem, "order_idx": int(p["order_idx"] or 0)})
    return {"project_id": project_id, "parts": out_parts, "files": files, "links": links,
            "active_jobs": active, "version": _snapshot_version(out_parts, files, links)}


def _snapshot_version(parts, files, links):
    """Отпечаток входных данных плана: если состав/остатки/файлы изменились между preflight и
    create — план устарел (project_plan_stale). Детерминирован."""
    import hashlib
    h = hashlib.sha256()
    for p in sorted(parts, key=lambda x: x["part_id"]):
        h.update(("%s:%d;" % (p["part_id"], p["remaining"])).encode())
    for f in sorted(files, key=lambda x: x["id"]):
        h.update(("%s:%s:%d;" % (f["id"], f.get("content_hash") or "", int(f.get("is_printable") or 0))).encode())
    for l in sorted(links, key=lambda x: (x["file_id"], x["part_id"])):
        h.update(("%s>%s:%d;" % (l["file_id"], l["part_id"], int(l["on_plate_qty"] or 0))).encode())
    return h.hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. ПЛАНИРОВЩИК: целочисленное многократное покрытие
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Задача NP-трудна (multi-set multi-cover), поэтому:
#   • разбиваем на независимые компоненты связности (в типовом проекте деталь лежит на одной плите
#     -> компоненты тривиальны и решаются точно закрытой формулой);
#   • связанные компоненты — branch-and-bound с лимитами узлов/времени;
#   • превышение лимита -> детерминированный greedy + ЧЕСТНАЯ пометка plan_quality='approximate'.
# Цель лексикографическая: (непокрытое, перепроизводство, число запусков), tie-break по (order_idx, file_id).
# Никаких внешних solver-зависимостей.

def _cover_of(choice, fmap):
    cov = {}
    for fid, n in choice.items():
        if n <= 0:
            continue
        for pid, q in fmap[fid].items():
            cov[pid] = cov.get(pid, 0) + q * n
    return cov


def _score(choice, fmap, deficits):
    cov = _cover_of(choice, fmap)
    unc = sum(max(0, d - cov.get(p, 0)) for p, d in deficits.items())
    over = sum(max(0, cov.get(p, 0) - deficits.get(p, 0)) for p in cov)
    runs = sum(choice.values())
    return (unc, over, runs)


def _max_useful(fid, fmap, deficits):
    """Больше этого числа повторов плиты смысла нет никогда (дефицит уже перекрыт)."""
    best = 0
    for pid, q in fmap[fid].items():
        d = deficits.get(pid, 0)
        if q > 0 and d > 0:
            best = max(best, -(-d // q))       # ceil
    return best


def _solve_component(fids, fmap, deficits, allow_over, node_limit, time_limit_ms):
    """-> (choice, exact) для ОДНОЙ компоненты. exact=False, если сработал лимит (greedy fallback)."""
    fids = list(fids)
    maxx = {f: _max_useful(f, fmap, deficits) for f in fids}
    if not any(maxx.values()):
        return ({f: 0 for f in fids}, True)
    # Тривиальная компонента (одна плита) -> точная закрытая формула, поиск не нужен.
    if len(fids) == 1:
        f = fids[0]
        n = maxx[f]
        ch = {f: n}
        if not allow_over and _score(ch, fmap, deficits)[1] > 0:
            # перепроизводство запрещено: берём максимум повторов без единой лишней детали
            best = 0
            for k in range(n, -1, -1):
                if _score({f: k}, fmap, deficits)[1] == 0:
                    best = k
                    break
            ch = {f: best}
        return (ch, True)
    deadline = _now() + (time_limit_ms / 1000.0)
    nodes = [0]
    best = {"choice": None, "key": None}
    order = sorted(fids)                        # стабильный детерминированный порядок ветвления
    cur = {}
    hit_limit = [False]

    def rec(i):
        if hit_limit[0]:
            return
        nodes[0] += 1
        if nodes[0] > node_limit or _now() > deadline:
            hit_limit[0] = True
            return
        if i == len(order):
            key = _score(cur, fmap, deficits)
            if not allow_over and key[1] > 0:
                return
            if best["key"] is None or key < best["key"]:
                best["key"] = key
                best["choice"] = dict(cur)
            return
        f = order[i]
        for n in range(0, maxx[f] + 1):
            cur[f] = n
            partial = _score(cur, fmap, deficits)
            # Добавление повторов НИКОГДА не уменьшает ни перепроизводство, ни число запусков,
            # поэтому по n эти величины монотонны -> можно рвать ветвь (break), а не пропускать.
            if not allow_over and partial[1] > 0:
                break                            # перепроизводство запрещено: всё поддерево нежизнеспособно
            # Нижняя граница ЛЮБОГО продолжения: непокрытое >= 0, перепроизводство >= текущего,
            # запусков >= текущего. Сравнивать нужно ПОЛНЫЙ лексикографический ключ: раньше здесь
            # сравнивались только (over, runs), и полное покрытие (0,0,2) проигрывало (1,0,1).
            if best["key"] is not None and (0, partial[1], partial[2]) >= best["key"]:
                break
            rec(i + 1)
            if hit_limit[0]:
                return
        cur.pop(f, None)

    rec(0)
    if hit_limit[0] or best["choice"] is None:
        return (_greedy_component(order, fmap, deficits, allow_over), not hit_limit[0] and best["choice"] is not None)
    return (best["choice"], True)


def _greedy_component(fids, fmap, deficits, allow_over):
    """Детерминированный fallback: пока есть дефицит, берём плиту с лучшим (свежее покрытие,
    минимум лишнего). Оптимальность НЕ гарантируется — поэтому план помечается approximate."""
    choice = {f: 0 for f in fids}
    rem = dict(deficits)
    guard = 0
    while any(v > 0 for v in rem.values()) and guard < 10000:
        guard += 1
        best_f, best_k = None, None
        for f in sorted(fids):
            fresh = sum(min(rem.get(p, 0), q) for p, q in fmap[f].items())
            if fresh <= 0:
                continue
            over = sum(max(0, q - rem.get(p, 0)) for p, q in fmap[f].items())
            if not allow_over and over > 0:
                continue
            k = (-fresh, over, f)
            if best_k is None or k < best_k:
                best_f, best_k = f, k
        if best_f is None:
            break
        choice[best_f] += 1
        for p, q in fmap[best_f].items():
            rem[p] = max(0, rem.get(p, 0) - q)
    return choice


def plan_project(snap, allow_overproduction=False, compat_fn=None,
                 node_limit=PLANNER_NODE_LIMIT, time_limit_ms=PLANNER_TIME_LIMIT_MS):
    """Детерминированный план. Один и тот же вход -> байт-в-байт один и тот же выход.
    compat_fn(file_row) -> список совместимых printer_id (существующая проверка ядра; None -> не знаем)."""
    parts = {p["part_id"]: p for p in snap["parts"]}
    deficits = {p["part_id"]: p["remaining"] for p in snap["parts"] if p["remaining"] > 0}
    files = {f["id"]: f for f in snap["files"]}
    order_of = {f["id"]: (int(f.get("order_idx") or 0), f["id"]) for f in snap["files"]}

    # Плита пригодна, только если печатаема, файл на месте и есть совместимый принтер.
    usable, blocked_files = {}, {}
    compat_map = {}
    for f in snap["files"]:
        pids = list(compat_fn(f)) if compat_fn else []
        compat_map[f["id"]] = pids
        if not int(f.get("is_printable") or 0):
            blocked_files[f["id"]] = BLOCK_FILE_MISSING
        elif not pids:
            blocked_files[f["id"]] = BLOCK_NO_PRINTER
        else:
            usable[f["id"]] = True

    fmap = {}
    for l in snap["links"]:
        fid, pid, q = l["file_id"], l["part_id"], int(l["on_plate_qty"] or 0)
        if fid not in files or pid not in parts or q <= 0:
            continue
        fmap.setdefault(fid, {})[pid] = fmap.get(fid, {}).get(pid, 0) + q
    plan_fmap = {fid: m for fid, m in fmap.items() if fid in usable}

    # ── компоненты связности (детали ↔ плиты) ──
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for fid, m in plan_fmap.items():
        parent.setdefault("F" + fid, "F" + fid)
        for pid in m:
            parent.setdefault("P" + pid, "P" + pid)
            union("F" + fid, "P" + pid)
    comps = {}
    for fid in plan_fmap:
        comps.setdefault(find("F" + fid), []).append(fid)

    choice, quality = {}, PLAN_EXACT
    for root in sorted(comps):
        cfids = sorted(comps[root], key=lambda f: order_of[f])
        cdef = {p: d for p, d in deficits.items() if any(p in plan_fmap[f] for f in cfids)}
        if not cdef:
            continue
        ch, exact = _solve_component(cfids, plan_fmap, cdef, bool(allow_overproduction), node_limit, time_limit_ms)
        if not exact:
            quality = PLAN_APPROX
        for f, n in ch.items():
            if n > 0:
                choice[f] = n

    # ── материализация items (снимок плана), стабильный порядок ──
    items, total_over = [], {}
    rem = dict(deficits)
    seq = 0
    for fid in sorted(choice, key=lambda f: order_of[f]):
        for _ in range(choice[fid]):
            pp, po = {}, {}
            for pid, q in sorted(fmap[fid].items()):
                take = min(rem.get(pid, 0), q)
                if take > 0:
                    pp[pid] = take
                    rem[pid] = rem.get(pid, 0) - take
                extra = q - take
                if extra > 0:
                    po[pid] = extra
                    total_over[pid] = total_over.get(pid, 0) + extra
            seq += 1
            items.append({"seq": seq, "file_id": fid, "filename": files[fid]["filename"],
                          "file_content_hash": files[fid].get("content_hash") or "",
                          "planned_parts": pp, "planned_overproduction": po,
                          "compatible_pids": compat_map.get(fid, [])})

    # ── непокрытый остаток и причины ──
    uncovered, blocked = {}, []
    for pid, d in deficits.items():
        left = rem.get(pid, 0)
        if left > 0:
            uncovered[pid] = left
            on_files = [l["file_id"] for l in snap["links"] if l["part_id"] == pid and int(l["on_plate_qty"] or 0) > 0]
            if not on_files:
                reason = BLOCK_FILE_MISSING
            elif all(f in blocked_files for f in on_files):
                reason = blocked_files[on_files[0]]
            else:
                reason = BLOCK_OVERPRODUCTION if not allow_overproduction else BLOCK_NO_PRINTER
            blocked.append({"part_id": pid, "part_name": parts[pid]["part_name"], "qty": left, "reason": reason})

    # Требуется ли отдельное согласие: без разрешения точное покрытие недостижимо.
    requires_approval = False
    if not allow_overproduction and uncovered:
        probe = plan_project(snap, True, compat_fn, node_limit, time_limit_ms)
        if len(probe["uncovered"]) < len(uncovered) or sum(probe["uncovered"].values()) < sum(uncovered.values()):
            requires_approval = True

    return {"project_id": snap["project_id"], "snapshot_version": snap["version"],
            "deficits": deficits, "chosen_files": dict(sorted(choice.items())), "items": items,
            "overproduction_total": dict(sorted(total_over.items())),
            "overproduction_count": sum(total_over.values()),
            "uncovered": dict(sorted(uncovered.items())), "blocked": sorted(blocked, key=lambda b: b["part_id"]),
            "plan_quality": quality, "requires_overproduction_approval": requires_approval,
            "allow_overproduction": bool(allow_overproduction)}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. PREFLIGHT (только диагностика; ничего не назначает и не отправляет)
# ══════════════════════════════════════════════════════════════════════════════════════════════
IDLE_NOT_PROOF = ("IDLE/FINISH не доказывают, что стол пуст: подтверждение снятия деталей "
                  "даёт только оператор кнопкой «Стол очищен».")


def printer_availability():
    """Диагностика парка. НЕ назначает и не резервирует. Alpha 2.741: пригодность считается по
    БЕЗОПАСНОСТНОМУ снимку (safety), а не по UI-статусу. Белый список безопасных raw-состояний живёт
    в ядре — здесь мы принимаем ТОЛЬКО доказанный safe_idle. Прежний чёрный список
    ("RUNNING","PREPARE","PAUSED","FAILED") пропускал, например, паузу Bambu: она приходит строкой
    'PAUSE', а не 'PAUSED', и в список не попадала."""
    out = []
    reserved = set(_ctx["send_reserved"]() if _ctx["send_reserved"] else ())
    busy_run = _printers_in_active_runs()
    holds = dict(_ctx["holds"]() if _ctx.get("holds") else {})
    for p in (_ctx["printers"]() if _ctx["printers"] else []):
        pid = p["id"]
        s = safety(pid)
        status, fresh = s.get("status") or "", bool(s.get("fresh"))
        reasons = []
        if not fresh:
            reasons.append("offline_or_stale")
        if not s.get("safe_idle"):
            reasons.append("unsafe_state:" + (s.get("unsafe_reason") or "unknown"))
        if pid in reserved:
            reasons.append("send_reservation")
        if pid in busy_run:
            reasons.append("in_other_project_run")
        if pid in holds:
            reasons.append("printer_held")
        out.append({"printer_id": pid, "name": p.get("name") or pid, "status": status or "OFFLINE",
                    "telemetry_fresh": bool(fresh), "has_send_reservation": pid in reserved,
                    "safe_idle": bool(s.get("safe_idle")), "unsafe_reason": s.get("unsafe_reason") or "",
                    "hold": (dict(holds[pid]) if pid in holds else None),
                    "available": not reasons, "unavailable_reasons": reasons,
                    # clearance — ТОЛЬКО действующее разрешение (active), семантика не менялась:
                    # consumed/revoked/invalidated/никогда-не-было -> null. Потребитель, пишущий
                    # `if (printer.clearance)`, обязан продолжать работать без правок.
                    "clearance": clearance_public(active_clearance(pid)),
                    # last_clearance — история/причина для оператора. Разрешением НЕ является.
                    "last_clearance": clearance_public(last_clearance(pid))})
    return out


# ── УДЕРЖАНИЕ ПРИНТЕРА: кто им владеет и почему ────────────────────────────────────────────────
HOLD_OWNER_TYPE = "project_run"
# Состояния item'а, при которых принтер ОБЯЗАН оставаться за планом. Смысл: либо файл уже отправлен
# (или отправляется), либо печать идёт, либо печать кончилась, но детали ещё НА СТОЛЕ, либо после
# рестарта мы не знаем правды. Во всех этих случаях чужой старт запрещён.
# ambiguous_after_dispatch — тоже владение: пока человек не разобрал ситуацию, считать принтер
# свободным нельзя (возможно, там идёт печать или лежат детали).
HOLD_ITEM_STATES = (IT_LEASED, IT_SENDING, IT_WAIT_START, IT_PRINTING, IT_WAIT_CLEAR, IT_AMBIGUOUS)
# Явно НЕ удерживают: pending/eligible/blocked (ещё ничего не отправляли), completed/superseded/
# cancelled (владение закончено), failed_before_dispatch (доказано, что команда не ушла).


def active_holds():
    """READ-ONLY: какие принтеры должны быть удержаны прямо сейчас -> {printer_id: {owner_id, reason}}.
    Ничего не пишет, не резервирует, не печатает и не трогает send-manager. Источник истины — БД,
    поэтому после рестарта удержания восстанавливаются без чьей-либо памяти."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:                       # короткое чтение; ни сети, ни send-manager lock здесь нет
        rows = [dict(r) for r in conn.execute(
            "SELECT i.assigned_printer_id AS pid, i.run_id AS run_id, i.state AS state, i.id AS item_id "
            "FROM project_run_items i JOIN project_runs r ON r.id=i.run_id "
            "WHERE i.assigned_printer_id!='' AND i.state IN (%s) "
            "ORDER BY i.assigned_printer_id, i.updated_at DESC, i.id" % ",".join("?" * len(HOLD_ITEM_STATES)),
            HOLD_ITEM_STATES).fetchall()]
    out = {}
    for r in rows:
        # На принтер может смотреть только один активный item (idx_pri_active_printer), но ambiguous
        # в этот partial-UNIQUE не входит — поэтому берём первый по стабильному порядку и не падаем.
        out.setdefault(r["pid"], {"owner_type": HOLD_OWNER_TYPE, "owner_id": r["run_id"],
                                  "reason": "project_run_item:" + r["state"], "item_id": r["item_id"]})
    return out


def holds_to_rebuild():
    """Псевдоним active_holds() для точки восстановления при старте (читается в server.py)."""
    return active_holds()


def _printers_in_active_runs():
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        rows = conn.execute(
            "SELECT DISTINCT i.assigned_printer_id AS pid FROM project_run_items i "
            "JOIN project_runs r ON r.id=i.run_id WHERE i.assigned_printer_id!='' "
            "AND r.state IN (%s) AND i.state IN (%s)" %
            (",".join("?" * len(RUN_ACTIVE_STATES)), ",".join("?" * len(IT_FUTURE_STATES))),
            RUN_ACTIVE_STATES + IT_FUTURE_STATES).fetchall()
    return {r["pid"] for r in rows}


def preflight(project_id, allow_overproduction=False, compat_fn=None):
    snap = project_snapshot(project_id)
    plan = plan_project(snap, allow_overproduction, compat_fn)
    parts_by_id = {p["part_id"]: p for p in snap["parts"]}
    for b in plan["blocked"]:
        b.setdefault("part_name", parts_by_id.get(b["part_id"], {}).get("part_name", ""))
    return {"project_id": project_id, "plan": plan,
            "remaining": {p["part_id"]: p["remaining"] for p in snap["parts"] if p["remaining"] > 0},
            "parts": snap["parts"], "printers": printer_availability(),
            "existing_run": run_public(active_run_for_project(project_id)),
            "requires_initial_clearance": True, "dispatch_enabled": DISPATCH_ENABLED,
            "idle_is_not_proof": IDLE_NOT_PROOF}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 5. DRAFT-RUN
# ══════════════════════════════════════════════════════════════════════════════════════════════
def active_run_for_project(project_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_runs WHERE project_id=? AND state IN (%s)" %
                         ",".join("?" * len(RUN_ACTIVE_STATES)), (project_id,) + RUN_ACTIVE_STATES).fetchone()
    return dict(r) if r else None


def run_public(run):
    if not run:
        return None
    return {"run_id": run["id"], "project_id": run["project_id"], "state": run["state"],
            "allow_overproduction": bool(run["allow_overproduction"]), "plan_quality": run["plan_quality"],
            "blocked": _jload(run["blocked_json"], []), "created_at": run["created_at"],
            "updated_at": run["updated_at"], "boot_id": run["boot_id"], "note": run["note"] or "",
            "dispatch_enabled": DISPATCH_ENABLED}


def list_active_runs():
    """READ-ONLY список активных run'ов для восстановления панели после перезагрузки страницы.
    Единственный источник состояний — canonical RUN_ACTIVE_STATES (в server.py он НЕ дублируется).
    Модель та же, что у run_public, плюс аддитивное project_name; второй несовместимой модели нет.
    LEFT JOIN: persisted run НЕ исчезает из UI, если строка проекта пропала -> project_name = None
    (UI подписывает такой run нейтрально). Порядок стабильный: created_at ASC, id ASC.
    Ничего не пишет, не запускает recovery, не создаёт clearance, не резервирует и не печатает."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:   # короткое чтение; сети и долгого кода под lock нет
        # Alpha 2.761: ПЛЮС планы, которые ВСЁ ЕЩЁ УДЕРЖИВАЮТ принтер (item в HOLD_ITEM_STATES),
        # даже если сам план уже терминальный. Иначе получается ловушка: отменённый план с
        # неразрешённой ambiguous-деталью держит принтер, в список не попадает — и разрешить её
        # из интерфейса НЕГДЕ, принтер заблокирован навсегда (поймано на живой ферме).
        rows = [dict(r) for r in conn.execute(
            "SELECT r.*, p.name AS project_name FROM project_runs r "
            "LEFT JOIN projects p ON p.id = r.project_id "
            "WHERE r.state IN (%s) OR r.id IN ("
            "  SELECT DISTINCT i.run_id FROM project_run_items i"
            "  WHERE i.assigned_printer_id!='' AND i.state IN (%s)) "
            "ORDER BY r.created_at ASC, r.id ASC"
            % (",".join("?" * len(RUN_ACTIVE_STATES)), ",".join("?" * len(HOLD_ITEM_STATES))),
            RUN_ACTIVE_STATES + HOLD_ITEM_STATES).fetchall()]
    out = []
    for r in rows:
        pub = run_public(r)                       # та же безопасная сериализация, что и везде
        pub["project_name"] = r.get("project_name")   # None -> проект удалён, UI покажет нейтральную подпись
        out.append(pub)
    return out


def create_run(project_id, allow_overproduction=False, print_opts=None, created_by="",
               expected_snapshot_version=None, compat_fn=None):
    """Создать draft-run + материализовать items. План ПЕРЕСЧИТЫВАЕТСЯ здесь заново — присланному
    фронтом плану не доверяем. Scheduler не запускается: dispatch в этой версии выключен."""
    if active_run_for_project(project_id):
        ex = active_run_for_project(project_id)
        return {"status": "error", "reason": "project_run_exists", "existing_run_id": ex["id"]}
    snap = project_snapshot(project_id)
    if expected_snapshot_version and expected_snapshot_version != snap["version"]:
        return {"status": "error", "reason": "project_plan_stale",
                "expected": expected_snapshot_version, "actual": snap["version"]}
    plan = plan_project(snap, allow_overproduction, compat_fn)
    if plan["requires_overproduction_approval"] and not allow_overproduction:
        return {"status": "error", "reason": "overproduction_approval_required",
                "overproduction": plan["overproduction_total"]}
    conn, lock = _ctx["conn"], _ctx["lock"]
    rid, now = _uid("prun_"), _now()
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO project_runs (id, project_id, state, allow_overproduction, plan_quality, "
                "print_opts_json, blocked_json, created_by, boot_id, note, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, project_id, RUN_DRAFT, 1 if allow_overproduction else 0, plan["plan_quality"],
                 _jdump(print_opts or {}), _jdump(plan["blocked"]), str(created_by or ""), _ctx["boot"],
                 "dry-run: автозапуск отключён (этап 1-4)", now, now))
            for it in plan["items"]:
                conn.execute(
                    "INSERT INTO project_run_items (id, run_id, project_id, file_id, file_content_hash, seq, "
                    "state, planned_parts_json, planned_overproduction_json, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (_uid("pitem_"), rid, project_id, it["file_id"], it["file_content_hash"], it["seq"],
                     IT_PENDING, _jdump(it["planned_parts"]), _jdump(it["planned_overproduction"]), now, now))
            for b in plan["blocked"]:
                conn.execute(
                    "INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, block_reason, "
                    "planned_parts_json, planned_overproduction_json, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (_uid("pitem_"), rid, project_id, "", 0, IT_BLOCKED, b["reason"],
                     _jdump({b["part_id"]: b["qty"]}), _jdump({}), now, now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"status": "ok", "run_id": rid, "plan": plan}


def get_run(run_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_runs WHERE id=?", (run_id,)).fetchone()
        if not r:
            return None
        items = [dict(x) for x in conn.execute(
            "SELECT * FROM project_run_items WHERE run_id=? ORDER BY seq, id", (run_id,)).fetchall()]
        # Alpha 2.754 (аддитивно, read-only): человеческие имена для UI. На первом уровне интерфейса
        # запрещены pfile_/pitem_-идентификаторы, а canonical-имена уже есть в project_files и
        # project_parts — отдаём их вместе со снимком, чтобы фронт ничего не выдумывал.
        fids = sorted({i["file_id"] for i in items if i["file_id"]})
        fnames = {}
        if fids:
            fnames = {x["id"]: (x["filename"] or "") for x in conn.execute(
                "SELECT id, filename FROM project_files WHERE id IN (%s)"
                % ",".join("?" * len(fids)), fids).fetchall()}
        pids = sorted({pid for i in items for pid in _jload(i["planned_parts_json"], {})})
        pnames = {}
        if pids:
            pnames = {x["id"]: (x["part_name"] or "") for x in conn.execute(
                "SELECT id, part_name FROM project_parts WHERE id IN (%s)"
                % ",".join("?" * len(pids)), pids).fetchall()}
    pub = run_public(dict(r))
    pub["items"] = [dict(item_public(i), filename=fnames.get(i["file_id"], "")) for i in items]
    pub["part_names"] = pnames
    counts = {}
    for i in items:
        counts[i["state"]] = counts.get(i["state"], 0) + 1
    pub["counts"] = counts
    pub["printers"] = printer_availability()
    return pub


def item_public(i):
    # feed_plan (Alpha 2.742) — аддитивное поле: нет плана -> null (модель ОДНА, пустого объекта не
    # изобретаем); битый JSON -> attention_required/feed_plan_corrupt, API не падает.
    # updated_at (Alpha 2.749) — canonical версия строки item'а. Аддитивно и ОБЯЗАТЕЛЬНО: без него
    # UI не мог собрать expected_item_updated_at, слал undefined, и optimistic-lock молча
    # пропускался (fail-open). Значение — РОВНО колонка project_run_items.updated_at: не created_at,
    # не run.updated_at, не feed_plan.built_at и не время ответа. Второго timestamp не заводим.
    return {"item_id": i["id"], "seq": i["seq"], "file_id": i["file_id"], "state": i["state"],
            "updated_at": i["updated_at"],
            "block_reason": i["block_reason"] or "", "planned_parts": _jload(i["planned_parts_json"], {}),
            "planned_overproduction": _jload(i["planned_overproduction_json"], {}),
            "assigned_printer_id": i["assigned_printer_id"] or "",
            "project_print_job_id": i["project_print_job_id"] or "",
            "command_sent": bool(i["command_sent"]), "attempt": int(i["attempt"] or 0),
            "last_error": i["last_error"] or "",
            "feed_plan": _feed_from_raw(i.get("feed_plan_json") or "", i["id"])}


def _set_run_state(run_id, new_state, only_if=None):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            if only_if:
                cur = conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE id=? AND state IN (%s)" %
                                   ",".join("?" * len(only_if)), (new_state, _now(), run_id) + tuple(only_if))
            else:
                cur = conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE id=?",
                                   (new_state, _now(), run_id))
            ok = cur.rowcount == 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return ok


def pause_run(run_id):
    return {"status": "ok"} if _set_run_state(run_id, RUN_PAUSED, (RUN_DRAFT, RUN_RUNNING, RUN_WAIT_PRINTER, RUN_WAIT_CLEAR)) \
        else {"status": "error", "reason": "bad_state"}


def resume_run(run_id):
    """dry-run: paused -> draft. В running не переводим — running обязано означать работающий
    scheduler, а его в этой версии нет."""
    return {"status": "ok", "state": RUN_DRAFT} if _set_run_state(run_id, RUN_DRAFT, (RUN_PAUSED,)) \
        else {"status": "error", "reason": "bad_state"}


def cancel_run(run_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE project_runs SET state=?, cancelled_at=?, updated_at=? WHERE id=? AND state IN (%s)" %
                               ",".join("?" * len(RUN_ACTIVE_STATES)),
                               (RUN_CANCELLED, _now(), _now(), run_id) + RUN_ACTIVE_STATES)
            ok = cur.rowcount == 1
            if ok:
                # Отменяем только НЕ начатые item'ы; печатающие никогда не отменяем автоматически.
                conn.execute("UPDATE project_run_items SET state=?, updated_at=? WHERE run_id=? AND state IN (?,?,?)",
                             (IT_CANCELLED, _now(), run_id, IT_PENDING, IT_ELIGIBLE, IT_BLOCKED))
                conn.execute("UPDATE plate_clearances SET invalidated_at=?, invalid_reason='run_cancelled' "
                             "WHERE consumed_at IS NULL AND invalidated_at IS NULL AND printer_id IN "
                             "(SELECT assigned_printer_id FROM project_run_items WHERE run_id=? AND assigned_printer_id!='')",
                             (_now(), run_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"status": "ok"} if ok else {"status": "error", "reason": "bad_state"}


def start_run(run_id):
    """Этап 5. Сейчас — контролируемый отказ, БЕЗ изменения БД (defense in depth: тот же отказ
    дублируется на API-уровне)."""
    if not DISPATCH_ENABLED:
        return {"status": "error", "reason": DISPATCH_DISABLED_REASON}
    raise NotImplementedError("dispatch is implemented in stage 5 only")   # pragma: no cover


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6. CLEARANCE — одноразовое подтверждение «Стол очищен»
# ══════════════════════════════════════════════════════════════════════════════════════════════
def active_clearance(printer_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM plate_clearances WHERE printer_id=? AND consumed_at IS NULL "
                         "AND invalidated_at IS NULL", (printer_id,)).fetchone()
    return dict(r) if r else None


# Фактическое значение, которым revoke_clearance() помечает штатный пользовательский отзыв
# (см. её сигнатуру ниже и server.py -> _orch.revoke_clearance(printer_id) без reason).
# Новых значений здесь не изобретаем: любое ДРУГОЕ -> "invalidated".
CLR_REASON_USER_REVOKE = "user_revoked"
# Канонические причины автоматического гашения токена (Alpha 2.741). Все они -> статус "invalidated"
# (пользовательским отзывом не являются). Токен — разовое подтверждение ТЕКУЩЕГО состояния стола:
# как только состояние принтера доказанно изменилось, подтверждение больше ничего не доказывает.
CLR_REASON_PRINT_STARTED = "print_started"
CLR_REASON_PRINTER_OFFLINE = "printer_offline"
CLR_REASON_PRINTER_ERROR = "printer_error"
CLR_REASON_STATE_CHANGED = "state_changed"


def last_clearance(printer_id):
    """ПОСЛЕДНИЙ токен принтера в ЛЮБОМ состоянии — read-only, ТОЛЬКО для объяснения оператору.
    Разрешением НЕ является и в gate'ах не используется: там остаётся active_clearance()."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM plate_clearances WHERE printer_id=? "
                         "ORDER BY confirmed_at DESC, id DESC LIMIT 1", (printer_id,)).fetchone()
    return dict(r) if r else None


def clearance_status(c):
    """Статус строки токена по её ФАКТИЧЕСКИМ полям, без догадок по телеметрии.
    Приоритет безопасный: аномалия consumed+invalidated -> invalidated (запрещающее сильнее)."""
    if c["invalidated_at"] is not None:
        return "revoked" if (c["invalid_reason"] or "") == CLR_REASON_USER_REVOKE else "invalidated"
    if c["consumed_at"] is not None:
        return "consumed"
    return "active"


def clearance_public(c):
    """Метаданные токена (активного ИЛИ исторического). Секретов/credentials/путей здесь нет и быть
    не может: nonce и state_snapshot_json наружу не выходят."""
    if not c:
        return None
    return {"clearance_id": c["id"], "printer_id": c["printer_id"], "finished_job_id": c["finished_job_id"] or "",
            "confirmed_by": c["confirmed_by"] or "", "confirmed_at": c["confirmed_at"],
            "boot_id": c["boot_id"], "is_initial": not (c["finished_job_id"] or ""),
            "status": clearance_status(c), "invalid_reason": c["invalid_reason"] or "",
            "consumed_at": c["consumed_at"], "invalidated_at": c["invalidated_at"]}


def printer_suits_run(run_id, printer_id, compat_fn=None):
    """Подходит ли принтер хотя бы ОДНОМУ ещё не выполненному item'у этого run. Токен для принтера,
    которому нечего дать, бессмыслен и не должен создаваться."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        rows = conn.execute(
            "SELECT DISTINCT i.file_id AS fid FROM project_run_items i WHERE i.run_id=? AND i.file_id!='' "
            "AND i.state IN (?,?)", (run_id, IT_PENDING, IT_ELIGIBLE)).fetchall()
        fids = [r["fid"] for r in rows]
        if not fids:
            return False
        files = [dict(r) for r in conn.execute(
            "SELECT * FROM project_files WHERE id IN (%s)" % ",".join("?" * len(fids)), fids).fetchall()]
    for f in files:
        if printer_id in list(compat_fn(f) if compat_fn else []):
            return True
    return False


def _job_belongs_to_run(run_id, finished_job_id):
    """finished_job_id должен относиться к ЭТОМУ run: чужой завершённый job подтверждением не является."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT 1 FROM project_run_items WHERE run_id=? AND project_print_job_id=?",
                         (run_id, finished_job_id)).fetchone()
    return bool(r)


# Состояния item'а, которые ещё НЕ терминальны: пока такой есть, run не завершён.
# blocked/ambiguous сюда входят намеренно — они требуют человека, а не «сами рассосутся».
IT_TERMINAL_STATES = (IT_COMPLETED, IT_CANCELLED, IT_SUPERSEDED, IT_FAILED_BEFORE)
# Состояния, из которых run ещё может продолжиться САМ (после включения планировщика).
IT_RUNNABLE_STATES = (IT_PENDING, IT_ELIGIBLE)


def _completion_context(conn, run_id, printer_id, finished_job_id):
    """Доказательства для завершения item по подтверждению «Стол очищен» (вызывать ВНУТРИ транзакции).
    Ничего не пишет. -> (ok, reason, item_row)."""
    j = conn.execute("SELECT id, status, counted_at, printer_id, project_id FROM project_print_jobs WHERE id=?",
                     (str(finished_job_id),)).fetchone()
    if not j:
        return (False, "job_not_found", None)
    it = conn.execute("SELECT * FROM project_run_items WHERE run_id=? AND project_print_job_id=?",
                      (run_id, str(finished_job_id))).fetchone()
    if not it:
        return (False, "job_not_in_run", None)          # чужое задание подтверждением не является
    it = dict(it)
    if (it["assigned_printer_id"] or "") != printer_id or (j["printer_id"] or "") != printer_id:
        return (False, "job_printer_mismatch", None)    # подтверждают не тот принтер
    if it["state"] == IT_AMBIGUOUS:
        # Неоднозначность закрывает ТОЛЬКО человек через resolve: очистка стола её не разрешает.
        return (False, "item_ambiguous", None)
    if it["state"] != IT_WAIT_CLEAR:
        return (False, "item_not_waiting_plate_clear", None)
    if not (j["counted_at"] or ""):
        # FINISH не подтверждён учётом ядра -> завершать нечего (печать могла и не кончиться).
        return (False, "job_not_counted", None)
    return (True, "", it)


def _remaining_items(conn, run_id, done_item_id):
    """Что осталось в run КРОМЕ завершаемого item. -> (нетерминальных, из них продолжаемых сами)."""
    rows = conn.execute("SELECT state FROM project_run_items WHERE run_id=? AND id!=?",
                        (run_id, done_item_id)).fetchall()
    alive = [r["state"] for r in rows if r["state"] not in IT_TERMINAL_STATES]
    return (len(alive), len([s for s in alive if s in IT_RUNNABLE_STATES]))


def create_clearance(printer_id, confirmed=False, finished_job_id="", confirmed_by="",
                     run_id=None, compat_fn=None, post_print=False, finished_raw=()):
    """Токен создаётся ТОЛЬКО по явному действию пользователя. Телеметрия НИКОГДА не создаёт его
    сама: IDLE/FINISH/RUNNING не означают пустой стол. Токен привязан к ОДНОМУ принтеру и является
    разовым подтверждением текущего состояния, а НЕ разрешением на будущие задания.

    Alpha 2.746 (этап 5A4): подтверждение с finished_job_id ЗАВЕРШАЕТ жизненный цикл предыдущего
    item — в ОДНОЙ транзакции с созданием токена. До 2.746 цепочка обрывалась: оператор жал «Стол
    очищен», и не происходило НИЧЕГО — item навсегда оставался waiting_plate_clear, run не
    завершался, а принтер оставался удержан планом НАВСЕГДА.
    ИНВАРИАНТ НЕ МЕНЯЕТСЯ: FINISH сам по себе принтер не освобождает. Освобождает только человек,
    и только этим подтверждением."""
    if confirmed is not True:
        return {"status": "error", "reason": "confirmation_required"}
    # Alpha 2.741: гейт — по БЕЗОПАСНОСТНОМУ снимку, а не по UI-статусу. Требовать здесь safe_idle
    # НЕЛЬЗЯ: главный сценарий подтверждения — ровно FINISH («печать кончилась, снимите детали»),
    # а FINISH по определению не safe_idle. Поэтому запрещаем только ДОКАЗАННО идущее задание
    # (printing_active), включая цикл отмены после веб-«Стоп»: там UI рисует IDLE, а принтер ещё
    # физически работает — прежняя проверка по UI-статусу это пропускала и позволяла подтвердить
    # «стол очищен» на печатающем принтере.
    s = safety(printer_id)
    if not s.get("fresh"):
        return {"status": "error", "reason": "telemetry_stale"}
    if s.get("printing_active"):
        return {"status": "error", "reason": "printer_busy",
                "printer_status": s.get("status_raw") or s.get("status") or "",
                "unsafe_reason": s.get("unsafe_reason") or ""}
    # Alpha 2.752: ПЕРВИЧНОЕ подтверждение (стол пуст ДО первой печати, finished_job_id='') строже
    # постпечатного: принтер обязан быть в safe_idle. Для подтверждения ПОСЛЕ печати safe_idle
    # требовать НЕЛЬЗЯ — главный сценарий там ровно FINISH, а FINISH по определению не safe_idle
    # (см. комментарий выше). Требование авторитетно ЗДЕСЬ, а не только в UI-подсказке.
    #  16.09.2026 (автозапуск очереди ожидания): ТРЕТИЙ вид подтверждения — «после печати», вне
    #  проектного запуска. Принтер, который только что закончил, safe_idle НЕ является (см. выше),
    #  поэтому требовать его здесь нельзя: иначе главный сценарий фермы — «закончил → снял деталь →
    #  подтвердил → пошла следующая» — не проходит вовсе. Вместо safe_idle требуем ДОКАЗАННОЕ
    #  завершение: сырой статус прошивки из списка, который передаёт ядро (там же он используется
    #  для очереди). Обойти проверку подставным finished_job_id было бы подлогом мимо предохранителя,
    #  поэтому для этого случая заведён явный параметр, а не «пустое поле сойдёт».
    #  ИНВАРИАНТ ПРЕЖНИЙ: доказанно идущая печать (printing_active) запрещает подтверждение ВСЕГДА —
    #  проверка выше, до этой ветки.
    if post_print and not finished_job_id:
        _fin = (str(s.get("status") or "").upper() == "FINISH"
                or str(s.get("status_raw") or "") in tuple(finished_raw or ()))
        if not _fin:
            return {"status": "error", "reason": "printer_not_finished",
                    "printer_status": s.get("status_raw") or s.get("status") or "",
                    "unsafe_reason": s.get("unsafe_reason") or ""}
    elif not finished_job_id and not s.get("safe_idle"):
        return {"status": "error", "reason": "printer_unsafe",
                "printer_status": s.get("status_raw") or s.get("status") or "",
                "unsafe_reason": s.get("unsafe_reason") or ""}
    status = s.get("status") or ""
    if run_id is not None:
        if finished_job_id and not _job_belongs_to_run(run_id, finished_job_id):
            return {"status": "error", "reason": "job_not_in_run"}
        # printer_suits_run спрашивает «есть ли ЕЩЁ что дать этому принтеру» и нужен только для
        # ПЕРВИЧНОГО подтверждения (стол пуст до первой печати). Для подтверждения ПОСЛЕ печати он
        # неприменим и был прямым багом: у ПОСЛЕДНЕГО item'а pending/eligible уже нет, и оператор
        # физически не мог подтвердить очистку — run зависал навсегда. Здесь доказательством связи
        # принтера с run служит само завершённое задание (проверяется в транзакции ниже).
        if not finished_job_id and not printer_suits_run(run_id, printer_id, compat_fn):
            return {"status": "error", "reason": "printer_not_used_by_run"}
    if active_clearance(printer_id):
        return {"status": "error", "reason": "clearance_exists"}
    conn, lock = _ctx["conn"], _ctx["lock"]
    cid, now = _uid("clr_"), _now()
    #  16.10.2026 (R-118): и СЫРОЙ статус прошивки. После отмены Bambu статус карточки IDLE, а сырой
    #  FAILED; по одному статусу карточки сторож ядра решал, что принтер стал FAILED уже после
    #  подтверждения, и гасил только что данный жетон.
    snapshot = {"status": status, "status_raw": str(s.get("status_raw") or ""), "confirmed_at": now}
    done = {"item_id": "", "run_state": "", "released": False}
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            # ── Всё, на чём стоит решение, перечитываем ВНУТРИ транзакции ──
            it, keep_active, new_rs, alive = None, True, None, None
            if run_id is not None and finished_job_id:
                r = conn.execute("SELECT state FROM project_runs WHERE id=?", (run_id,)).fetchone()
                if not r:
                    conn.rollback()
                    return {"status": "error", "reason": "run_not_found"}
                ok, why, it = _completion_context(conn, run_id, printer_id, finished_job_id)
                if not ok:
                    conn.rollback()
                    return {"status": "error", "reason": why}
                alive, runnable = _remaining_items(conn, run_id, it["id"])
                # Разрешение оставляем ДЕЙСТВУЮЩИМ, только если этому же run реально есть что
                # печатать дальше. Иначе оно становится чистым аудитом: сразу consumed. Так «стол
                # подтверждён» не превращается в разрешение на постороннюю будущую печать.
                keep_active = runnable > 0
                # ── Состояние run по ФАКТИЧЕСКОМУ остатку ──
                rs = r["state"]
                if alive == 0:
                    new_rs = RUN_COMPLETED if rs != RUN_CANCELLED else RUN_CANCELLED
                elif rs in (RUN_PAUSED, RUN_CANCELLED):
                    new_rs = rs                         # подтверждение стола планом не управляет
                elif runnable > 0:
                    new_rs = RUN_WAIT_PRINTER           # есть что печатать дальше — ждём принтер
                else:
                    new_rs = RUN_ATTENTION              # остались только blocked/ambiguous — нужен человек
            # ЕДИНСТВЕННАЯ точка создания токена на ВСЕ пути (и первичный, и после печати):
            # второго способа завести разрешение в системе нет и быть не должно.
            conn.execute(
                "INSERT INTO plate_clearances (id, printer_id, finished_job_id, confirmed_by, confirmed_at, "
                "nonce, boot_id, state_snapshot_json, consumed_at, consumed_by_item_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, printer_id, (str(finished_job_id) if it else ""), str(confirmed_by or ""), now,
                 uuid.uuid4().hex, _ctx["boot"], _jdump(snapshot),
                 (None if keep_active else now), ("" if keep_active else it["id"])))
            if it is not None:
                cur = conn.execute(
                    "UPDATE project_run_items SET state=?, finished_at=?, updated_at=?, last_error='' "
                    "WHERE id=? AND state=?", (IT_COMPLETED, now, now, it["id"], IT_WAIT_CLEAR))
                if cur.rowcount != 1:
                    conn.rollback()
                    return {"status": "error", "reason": "item_state_changed"}
                if new_rs != rs:
                    conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE id=?", (new_rs, now, run_id))
                if new_rs == RUN_COMPLETED:
                    conn.execute("UPDATE project_runs SET finished_at=? WHERE id=? AND finished_at IS NULL",
                                 (now, run_id))
                done.update({"item_id": it["id"], "run_state": new_rs,
                             # Принтер отпускаем, только когда run доказанно закончил с ним работать.
                             "released": (alive == 0)})
            conn.commit()
        except Exception as e:
            conn.rollback()
            if type(e).__name__ == "IntegrityError":
                return {"status": "error", "reason": "clearance_exists"}   # гонка на UNIQUE-индексе
            raise
    # ── ПОСЛЕ COMMIT: удержание. Под lock_p send-manager не трогаем никогда. ──
    # Завершённый run принтером больше не владеет — иначе ручной старт был бы заблокирован вечно.
    # Снимаем строго по owner-match: чужое удержание не наше дело.
    if done["released"] and run_id is not None:
        fn = _ctx.get("clear_hold")
        if fn:
            try:
                fn(printer_id, HOLD_OWNER_TYPE, run_id)
            except Exception:
                # БД уже зафиксирована — откатывать завершение нельзя. Удержание не должно остаться
                # висеть навсегда: его снимет ближайший rebuild (источник истины — БД, а там уже
                # completed), а факт сбоя обязан быть видимым.
                done["hold_release_failed"] = True
    out = {"status": "ok", "clearance": clearance_public(_clearance_row(cid))}
    if done["item_id"]:
        out["item"] = item_public(_item_row(done["item_id"]))
        out["run"] = run_public(_run_row(run_id))
        out["printer_released"] = bool(done["released"])
        if done.get("hold_release_failed"):
            out["hold_release_failed"] = True
    return out


def _clearance_row(cid):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM plate_clearances WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


def _item_row(item_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_run_items WHERE id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def _run_row(run_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_runs WHERE id=?", (run_id,)).fetchone()
    return dict(r) if r else None


def revoke_clearance(printer_id, reason="user_revoked"):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE plate_clearances SET invalidated_at=?, invalid_reason=? "
                               "WHERE printer_id=? AND consumed_at IS NULL AND invalidated_at IS NULL",
                               (_now(), reason, printer_id))
            ok = cur.rowcount == 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"status": "ok"} if ok else {"status": "error", "reason": "no_active_clearance"}


def consume_clearance(clearance_id, item_id):
    """Одноразовое расходование (готовится к этапу 5). Условный UPDATE + проверка rowcount:
    повторное consume отказывает БЕЗ побочных эффектов."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE plate_clearances SET consumed_at=?, consumed_by_item_id=? "
                "WHERE id=? AND consumed_at IS NULL AND invalidated_at IS NULL AND boot_id=?",
                (_now(), str(item_id or ""), clearance_id, _ctx["boot"]))
            ok = cur.rowcount == 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return ok


def invalidate_clearance_on_event(printer_id, reason):
    """Любая новая печать/смена состояния/offline/alert гасит токен. Идемпотентно: повторный вызов
    обновляет 0 строк (условие consumed IS NULL AND invalidated IS NULL). -> сколько погашено."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        cur = conn.execute("UPDATE plate_clearances SET invalidated_at=?, invalid_reason=? "
                           "WHERE printer_id=? AND consumed_at IS NULL AND invalidated_at IS NULL",
                           (_now(), str(reason or CLR_REASON_STATE_CHANGED), printer_id))
        conn.commit()
        return cur.rowcount


def printers_with_active_clearance():
    """READ-ONLY: принтеры с живым токеном. Нужен сторожевому тику ядра, чтобы гасить токены
    принтеров, которым больше нельзя верить (offline/ошибка/началась печать)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        rows = conn.execute("SELECT printer_id FROM plate_clearances "
                            "WHERE consumed_at IS NULL AND invalidated_at IS NULL").fetchall()
    return [r["printer_id"] for r in rows]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6b. ТЕЛЕМЕТРИЯ -> СОСТОЯНИЕ ПЛАНА (Alpha 2.741). НИ ОДНОЙ КОМАНДЫ ПРИНТЕРУ ОТСЮДА НЕ УХОДИТ.
# Это НЕ scheduler и не dispatch: колбэки только записывают в БД то, что УЖЕ произошло на принтере,
# и удерживают принтер за планом. Вызываются из существующего handle_state ядра (fail-open).
# В этой версии в производстве они инертны: item получает project_print_job_id только при dispatch,
# а dispatch выключен -> совпадений не будет. Это намеренно: фундамент кладём и проверяем тестами
# на фикстурах ДО того, как появится отправка.
# ══════════════════════════════════════════════════════════════════════════════════════════════
def _hold_set(printer_id, run_id, reason):
    """Удержать принтер за run. Fail-open: нет пробы/ошибка -> состояние плана всё равно пишем
    (потерять запись хуже, чем потерять удержание; удержание восстановит rebuild при следующем старте)."""
    fn = _ctx.get("set_hold")
    if not fn or not printer_id:
        return False
    try:
        ok, _h = fn(printer_id, HOLD_OWNER_TYPE, run_id, reason)
        return bool(ok)
    except Exception:
        return False


def _set_item_state(item_id, new_state, only_if=None, err=None):
    """Условный переход item'а. Идемпотентен: повторный кадр телеметрии, когда item уже в целевом
    состоянии, обязан входить в only_if и просто обновляет updated_at. -> True, если строка изменена."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            if only_if:
                cur = conn.execute(
                    "UPDATE project_run_items SET state=?, last_error=?, updated_at=? WHERE id=? AND state IN (%s)" %
                    ",".join("?" * len(only_if)),
                    (new_state, str(err or ""), _now(), item_id) + tuple(only_if))
            else:
                cur = conn.execute("UPDATE project_run_items SET state=?, last_error=?, updated_at=? WHERE id=?",
                                   (new_state, str(err or ""), _now(), item_id))
            ok = cur.rowcount == 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return ok


def _item_by_pjob(job_id):
    """Item, которому принадлежит ЭТО проектное задание. Связь строгая: project_print_job_id уникален
    (idx_pri_pjob), поэтому одно задание не может достаться двум item'ам. Сопоставление по имени файла
    уже выполнено ядром (_match_project_job) ДО вызова — сюда приходит доказанный job_id."""
    if not job_id:
        return None
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_run_items WHERE project_print_job_id=? "
                         "AND project_print_job_id!=''", (str(job_id),)).fetchone()
    return dict(r) if r else None


# Состояния item'а, из которых он может стать «печатается» / «стол ждёт очистки» / «неоднозначность».
_ST_OWNED = (IT_LEASED, IT_SENDING, IT_WAIT_START, IT_PRINTING)


def on_printer_started(printer_id, filename="", project_print_job_id="", reason=CLR_REASON_PRINT_STARTED):
    """Принтер ДОКАЗАННО начал печать (PREPARE/RUNNING). Ничего не отправляет.
    Токен «Стол очищен» гасится ВСЕГДА — даже если печать чужая: началась печать, значит прежнее
    подтверждение пустого стола больше ничего не доказывает."""
    inv = invalidate_clearance_on_event(printer_id, reason)
    it = _item_by_pjob(project_print_job_id)
    if not it:
        return {"matched": False, "clearances_invalidated": inv}   # чужая/ручная печать — план не трогаем
    ok = _set_item_state(it["id"], IT_PRINTING, only_if=_ST_OWNED + (IT_PRINTING,))
    _set_run_state(it["run_id"], RUN_RUNNING, only_if=(RUN_DRAFT, RUN_RUNNING, RUN_WAIT_PRINTER, RUN_WAIT_CLEAR))
    _hold_set(printer_id, it["run_id"], "project_run_item:" + IT_PRINTING)
    return {"matched": True, "item_id": it["id"], "state": IT_PRINTING if ok else it["state"],
            "clearances_invalidated": inv}


def on_printer_finished(printer_id, filename="", project_print_job_id=""):
    """FINISH. printed_qty к этому моменту УЖЕ засчитан ядром (finish_project_print_job, exactly-once
    по counted_at) — здесь про учёт ни слова, только владение принтером.
    ИНВАРИАНТ: FINISH НЕ создаёт разрешение на следующий запуск и НЕ освобождает принтер. Стол пуст
    ровно тогда, когда это подтвердил оператор кнопкой, и никак иначе."""
    it = _item_by_pjob(project_print_job_id)
    if not it:
        return {"matched": False}
    ok = _set_item_state(it["id"], IT_WAIT_CLEAR, only_if=_ST_OWNED + (IT_WAIT_CLEAR,))
    _set_run_state(it["run_id"], RUN_WAIT_CLEAR, only_if=(RUN_DRAFT, RUN_RUNNING, RUN_WAIT_PRINTER, RUN_WAIT_CLEAR))
    _hold_set(printer_id, it["run_id"], "project_run_item:" + IT_WAIT_CLEAR)   # принтер ОСТАЁТСЯ за планом
    return {"matched": True, "item_id": it["id"], "state": IT_WAIT_CLEAR if ok else it["state"]}


def on_printer_failed(printer_id, filename="", project_print_job_id="", reason=""):
    """FAILED / остановка пользователем / простой после печати. Автоповтора нет и не будет: сбой почти
    всегда означает брак НА СТОЛЕ, и решить, что с ним делать, может только человек.
    Отдельного attention_required у item'а в перечне НЕТ, и выдумывать его нельзя — используем
    существующее каноническое ambiguous_after_dispatch (ровно тот же смысл: «сама система решить не
    вправе»), а внимание поднимаем на уровень run -> attention_required. Ту же модель уже применяет
    recovery (_classify_recovered), так что второго способа сказать одно и то же не появляется.
    Токен гасим: после сбоя стол недостоверен. Принтер остаётся удержан."""
    inv = invalidate_clearance_on_event(printer_id, CLR_REASON_PRINTER_ERROR)
    it = _item_by_pjob(project_print_job_id)
    if not it:
        return {"matched": False, "clearances_invalidated": inv}
    ok = _set_item_state(it["id"], IT_AMBIGUOUS, only_if=_ST_OWNED + (IT_AMBIGUOUS,),
                         err=str(reason or "terminal_without_finish"))
    _set_run_state(it["run_id"], RUN_ATTENTION, only_if=RUN_ACTIVE_STATES)
    _hold_set(printer_id, it["run_id"], "project_run_item:" + IT_AMBIGUOUS)
    return {"matched": True, "item_id": it["id"], "state": IT_AMBIGUOUS if ok else it["state"],
            "clearances_invalidated": inv}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6c. ПЛАН ПОДАЧИ ФИЛАМЕНТА (Alpha 2.742, этап 5A2a). ЧИСТОЕ ВЫЧИСЛЕНИЕ + ЗАПИСЬ В СВОЮ КОЛОНКУ.
# Здесь нет ни отправки, ни резервации, ни consume clearance, ни scheduler'а — только ответ на
# вопрос «чем и из какого слота это печатать и доказано ли это».
# ГЛАВНЫЙ ИНВАРИАНТ: источник подачи должен быть ДОКАЗАН. Нечем доказать -> не ready. Auto/None в
# план не попадает никогда: builder всегда называет явный ams_slot.
# ══════════════════════════════════════════════════════════════════════════════════════════════
FEED_VERSION = 1
FEED_READY, FEED_APPROVAL = "ready", "approval_required"
FEED_ATTENTION, FEED_BLOCKED = "attention_required", "blocked"

# Причины (канонические; UI показывает их дословно).
FR_FILE_MISSING = "file_missing"
FR_FILE_HASH_CHANGED = "file_hash_changed"
FR_FILE_UNREADABLE = "file_unreadable"
FR_COUNT_UNKNOWN = "filament_count_unknown"
FR_MULTI = "multi_filament_not_supported"
FR_MAT_UNKNOWN_FILE = "file_material_unknown"
FR_COLOR_UNKNOWN_FILE = "file_color_unknown"
FR_INV_UNAVAILABLE = "inventory_source_unavailable"
FR_MAT_MISMATCH = "material_mismatch"
FR_MAT_UNKNOWN = "material_unknown"
FR_COLOR_MISMATCH = "color_mismatch"
FR_COLOR_UNKNOWN = "color_unknown"
FR_SLOT_EMPTY = "slot_empty"
FR_TELEMETRY_STALE = "telemetry_stale"
FR_REPORTED_MISMATCH = "reported_material_mismatch"
FR_CLOSE_COLOR = "close_color"
FR_INV_DECLARED = "inventory_declared"
FR_MANUAL_EXTERNAL = "manual_external"
FR_CORRUPT = "feed_plan_corrupt"

VERIFY_TELEMETRY, VERIFY_DECLARED = "telemetry_confirmed", "inventory_declared"
VERIFY_MANUAL = "manual_external"
REL_EXACT, REL_CLOSE, REL_MISMATCH, REL_UNKNOWN = "exact", "close", "mismatch", "unknown"
COLOR_CLOSE_DE = 5.0                     # ΔE00 <= 5 -> «близкий»; сам по себе запуск НЕ разрешает
APPROVABLE_REASONS = (FR_CLOSE_COLOR, FR_INV_DECLARED, FR_MANUAL_EXTERNAL)
MODE_EXTERNAL, MODE_AMS = "external", "ams"
EXTERNAL_SLOT = -1                       # внешняя катушка — ОТДЕЛЬНАЯ позиция, это НЕ слот AMS 0


# ── Нормализация (буквальная; алиасы запрещены) ────────────────────────────────────────────────
def norm_material(v):
    """Материал для СРАВНЕНИЯ: trim + схлопывание пробелов + casefold. Алиасы и «базовый материал»
    НЕ угадываем: «My PETG» != «PETG», «PETG-CF» != «PETG», «Generic PETG» не сокращаем.
    Показывать пользователю нужно ИСХОДНОЕ значение, а не это. None/пусто -> ''."""
    if v is None:
        return ""
    return " ".join(str(v).split()).strip().casefold()


def norm_hex(v):
    """Валидный HEX -> '#RRGGBB' (upper). Принимает 'RRGGBB'/'RRGGBBAA'/'#…'; alpha отбрасывается.
    Не-HEX/пусто/None -> None (такая сторона в сравнении цвета не участвует)."""
    if v is None:
        return None
    s = str(v).strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) not in (6, 8):
        return None
    s = s[:6]
    try:
        int(s, 16)
    except Exception:
        return None
    return "#" + s.upper()


# ── CIEDE2000 (локальная чистая реализация; ни склада, ни зависимостей) ────────────────────────
# CIEDE2000 легко реализовать «почти верно», поэтому реализация проверяется эталонным набором
# Sharma/Wu/Dalal (2005) Table 1 — 34 пары, точность 1e-4 (см. tools/test_project_feed_plan.py).
def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_lab(h):
    """'#RRGGBB' -> (L, a, b). sRGB -> linear RGB -> XYZ (D65) -> CIELAB (белая точка D65)."""
    h = norm_hex(h)
    if not h:
        return None
    r, g, b = (_srgb_to_linear(int(h[1:3], 16)), _srgb_to_linear(int(h[3:5], 16)), _srgb_to_linear(int(h[5:7], 16)))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.00000, 1.08883          # D65
    def f(t):
        return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (841.0 / 108.0) * t + 4.0 / 29.0
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def ciede2000(lab1, lab2):
    """ΔE00 между двумя Lab. Реализация по Sharma/Wu/Dalal (2005)."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    kL = kC = kH = 1.0
    C1 = math.sqrt(a1 * a1 + b1 * b1)
    C2 = math.sqrt(a2 * a2 + b2 * b2)
    Cbar = (C1 + C2) / 2.0
    C7 = Cbar ** 7
    G = 0.5 * (1.0 - math.sqrt(C7 / (C7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + G) * a1, (1.0 + G) * a2
    C1p = math.sqrt(a1p * a1p + b1 * b1)
    C2p = math.sqrt(a2p * a2p + b2 * b2)
    h1p = 0.0 if (b1 == 0 and a1p == 0) else math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = 0.0 if (b2 == 0 and a2p == 0) else math.degrees(math.atan2(b2, a2p)) % 360.0
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2.0)
    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hbp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hbp = (h1p + h2p + 360.0) / 2.0
    else:
        hbp = (h1p + h2p - 360.0) / 2.0
    T = (1.0 - 0.17 * math.cos(math.radians(hbp - 30.0)) + 0.24 * math.cos(math.radians(2.0 * hbp))
         + 0.32 * math.cos(math.radians(3.0 * hbp + 6.0)) - 0.20 * math.cos(math.radians(4.0 * hbp - 63.0)))
    dtheta = 30.0 * math.exp(-(((hbp - 275.0) / 25.0) ** 2))
    Cbp7 = Cbp ** 7
    Rc = 2.0 * math.sqrt(Cbp7 / (Cbp7 + 25.0 ** 7))
    Lbp2 = (Lbp - 50.0) ** 2
    Sl = 1.0 + (0.015 * Lbp2) / math.sqrt(20.0 + Lbp2)
    Sc = 1.0 + 0.045 * Cbp
    Sh = 1.0 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2.0 * dtheta)) * Rc
    return math.sqrt((dLp / (kL * Sl)) ** 2 + (dCp / (kC * Sc)) ** 2 + (dHp / (kH * Sh)) ** 2
                     + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh)))


def color_relation(hex_a, hex_b):
    """-> (relation, distance). Точный HEX -> ('exact', 0.0). Любая невалидная сторона ->
    ('unknown', None) — цвет НЕ сравнивается и близким не объявляется."""
    a, b = norm_hex(hex_a), norm_hex(hex_b)
    if not a or not b:
        return (REL_UNKNOWN, None)
    if a == b:
        return (REL_EXACT, 0.0)
    d = ciede2000(hex_to_lab(a), hex_to_lab(b))
    return ((REL_CLOSE if d <= COLOR_CLOSE_DE else REL_MISMATCH), round(d, 4))


# ── Требования файла ───────────────────────────────────────────────────────────────────────────
def file_requirements(file_row):
    """Требования плиты к филаменту через ЧИТАЮЩУЮ пробу ядра (та читает файл и сверяет хеш).
    -> {"status":"ok"|"error", "reason", "filament_count", "filaments":[...], "plate","nozzle","source"}
    Fail-closed: пробы нет/упала -> error. Имя файла источником материала/цвета НЕ является."""
    fn = _ctx.get("file_requirements")
    if not fn:
        return {"status": "error", "reason": FR_FILE_UNREADABLE, "filament_count": 0, "filaments": []}
    try:
        r = fn(dict(file_row or {}))
    except Exception:
        r = None
    if not isinstance(r, dict):
        return {"status": "error", "reason": FR_FILE_UNREADABLE, "filament_count": 0, "filaments": []}
    return r


def _requirements_problem(req):
    """Что мешает вообще строить план по этому файлу. -> (status, reason) либо None."""
    if req.get("status") != "ok":
        return (FEED_BLOCKED, req.get("reason") or FR_FILE_UNREADABLE)
    n = int(req.get("filament_count") or 0)
    if n <= 0:
        return (FEED_BLOCKED, FR_COUNT_UNKNOWN)
    if n > 1:
        # Пофиламентной карты в UI и в плане пока нет — угадывать соответствие нельзя (отдельная задача).
        return (FEED_BLOCKED, FR_MULTI)
    f0 = (req.get("filaments") or [{}])[0]
    if not norm_material(f0.get("material")):
        return (FEED_BLOCKED, FR_MAT_UNKNOWN_FILE)
    if not norm_hex(f0.get("color_hex")):
        return (FEED_BLOCKED, FR_COLOR_UNKNOWN_FILE)
    return None


# ── Складские кандидаты (ТОЛЬКО через generic-снимок ядра) ─────────────────────────────────────
def _inventory_rows(printer_id):
    """Строки привязанного филамента принтера из generic-снимка ядра. Складская катушка — ТОЛЬКО
    строка с явным inventory_bound/source=inventory И настоящим spool.id: строка одной телеметрии
    катушкой НЕ является (принтер сообщает, что в слоте что-то есть, — это не запись склада)."""
    fn = _ctx.get("filament_snapshot")
    if not fn:
        return []
    try:
        snap = fn(printer_id) or {}
    except Exception:
        return []
    if not isinstance(snap, dict):
        return []
    out = []
    for s in (snap.get("slots") or []):
        if not isinstance(s, dict):
            continue
        bound = bool(s.get("inventory_bound")) or (str(s.get("source") or "") == "inventory")
        spool = s.get("spool") if isinstance(s.get("spool"), dict) else None
        if not bound or not spool or not str(spool.get("id") or ""):
            continue                       # telemetry-only строка -> НЕ кандидат
        # 16.10.2026 (R-137): левая внешняя катушка H2D (склад: ext_side 'left', позиция -2). План подачи
        # знает только одну внешнюю позицию -1 и сверял бы левую катушку с ПРАВОЙ подачей принтера.
        # Пока план не умеет -2, левая катушка кандидатом не считается: решает человек.
        if s.get("external") and (s.get("ext_side") == "left" or s.get("index") == -2):
            continue
        out.append(s)
    return out


def _reported_positions(printer_id):
    """Отчётная телеметрия филамента (generic core-геттер). -> (fresh, available, {ключ: позиция}).
    Ключ external-позиции — строка 'external', а НЕ индекс: у отчёта ядра external приходит с
    index=None, а у склада — с index=-1; сопоставлять их по индексу нельзя."""
    fn = _ctx.get("reported_filament")
    if not fn:
        return (False, False, {})
    try:
        r = fn(printer_id) or {}
    except Exception:
        return (False, False, {})
    if not isinstance(r, dict):
        return (False, False, {})
    pos = {}
    for p in (r.get("positions") or []):
        if not isinstance(p, dict):
            continue
        if p.get("external"):
            pos["external"] = p
        elif p.get("index") is not None:
            pos[int(p["index"])] = p
    return (bool(r.get("telemetry_fresh")), bool(r.get("telemetry_available")), pos)


def _candidate_from_row(row, req_mat, req_color, transport, reported, tele_fresh, tele_avail):
    """Один кандидат подачи из складской строки. Чистая функция: ничего не пишет и не отправляет."""
    spool = row.get("spool") or {}
    external = bool(row.get("external"))
    # Слот: external -> ОТДЕЛЬНАЯ позиция -1; иначе РЕАЛЬНЫЙ индекс склада (0, 5, 512 — мульти-AMS
    # и AMS HT дают именно такие; в порядковый слот их превращать нельзя).
    if external:
        slot, mode = EXTERNAL_SLOT, MODE_EXTERNAL
    else:
        try:
            slot = int(row.get("index"))
        except Exception:
            slot = None
        mode = MODE_AMS
    inv_mat = spool.get("material")
    inv_color = norm_hex(spool.get("color_hex"))
    c = {"ams_slot": slot, "mode": mode, "spool_id": str(spool.get("id") or ""),
         "inventory_bound": True, "external": external,
         "inventory_material": inv_mat, "inventory_color": inv_color,
         "reported_material": None, "reported_color": None,
         "color_relation": REL_UNKNOWN, "color_distance": None,
         "verification": VERIFY_DECLARED, "status": FEED_ATTENTION, "reason": "",
         "required_approval_reasons": []}     # blocked/attention согласием не лечатся -> список пуст
    if slot is None:
        c.update({"status": FEED_BLOCKED, "reason": FR_SLOT_EMPTY})
        return c

    # 1) Материал файла vs материал СКЛАДСКОЙ катушки — буквально, без алиасов.
    if not norm_material(inv_mat):
        c.update({"status": FEED_ATTENTION, "reason": FR_MAT_UNKNOWN})
        return c
    if norm_material(inv_mat) != norm_material(req_mat):
        c.update({"status": FEED_BLOCKED, "reason": FR_MAT_MISMATCH})
        return c

    # 2) Цвет файла vs цвет складской катушки.
    rel, dist = color_relation(req_color, inv_color)
    c["color_relation"], c["color_distance"] = rel, dist
    if rel == REL_UNKNOWN:
        c.update({"status": FEED_ATTENTION, "reason": FR_COLOR_UNKNOWN})
        return c
    if rel == REL_MISMATCH:
        c.update({"status": FEED_BLOCKED, "reason": FR_COLOR_MISMATCH})
        return c

    # 3) Подтверждение датчиком. Отчётный филамент есть ТОЛЬКО у Bambu; у Klipper/FlashForge его нет
    #    в принципе, поэтому складская привязка там — ЗАЯВЛЕНИЕ ОПЕРАТОРА, а не доказательство.
    rp = reported.get("external" if external else slot)
    #  16.09.2026. Внешняя позиция Bambu — это ВЫБОР НА ЭКРАНЕ принтера, а не показание датчика:
    #  датчика наличия у внешней подачи нет, и выбранный тип остаётся, когда катушка кончилась или
    #  её сняли. Считать это подтверждением нельзя: план уходил бы в ready и запускался бы без
    #  человека на пустую подачу, а списание ушло бы с катушки, лежащей на полке. Поэтому такой
    #  источник идёт как ЗАЯВЛЕНИЕ СКЛАДА (approval_required) — как было до того, как программа
    #  научилась читать внешнюю катушку. По той же причине пустая внешняя позиция здесь НЕ
    #  блокирует запуск: «на экране не задан материал» не доказывает, что подачи нет.
    #  Ровно то же правило у склада (modules/inventory/backend.py, 1.7.29).
    _setting_only = bool(external and isinstance(rp, dict)
                         and str(rp.get("presence") or "") != "sensor")
    if _setting_only:
        c["reported_material"] = rp.get("reported_material")
        c["reported_color"] = norm_hex(rp.get("reported_color"))
    if transport != "bambu" or not tele_avail or _setting_only:
        c["verification"] = VERIFY_DECLARED
    elif not tele_fresh:
        c.update({"status": FEED_ATTENTION, "reason": FR_TELEMETRY_STALE})
        return c
    elif rp is None:
        c.update({"status": FEED_ATTENTION, "reason": FR_TELEMETRY_STALE})
        return c
    elif not rp.get("present"):
        c.update({"status": FEED_BLOCKED, "reason": FR_SLOT_EMPTY})
        return c
    else:
        c["reported_material"] = rp.get("reported_material")
        c["reported_color"] = norm_hex(rp.get("reported_color"))
        if not norm_material(c["reported_material"]):
            c.update({"status": FEED_ATTENTION, "reason": FR_TELEMETRY_STALE})
            return c
        if norm_material(c["reported_material"]) != norm_material(inv_mat):
            # Принтер сообщает НЕ ТО, что записано в складе: физической правде верим больше.
            c.update({"status": FEED_BLOCKED, "reason": FR_REPORTED_MISMATCH})
            return c
        r_rel, r_dist = color_relation(req_color, c["reported_color"])
        if r_rel == REL_MISMATCH:
            c.update({"status": FEED_BLOCKED, "reason": FR_COLOR_MISMATCH})
            return c
        if r_rel == REL_UNKNOWN:
            c.update({"status": FEED_ATTENTION, "reason": FR_COLOR_UNKNOWN})
            return c
        # Итоговое отношение цвета — ХУДШЕЕ из складского и отчётного (безопасная сторона).
        if r_rel == REL_CLOSE and rel == REL_EXACT:
            c["color_relation"], c["color_distance"] = REL_CLOSE, r_dist
        c["verification"] = VERIFY_TELEMETRY

    # 4) Итог. ready — только доказанный датчиком точный цвет. Близкий цвет и «заявлено складом»
    #    сами по себе автозапуск НЕ разрешают: нужно явное согласие человека.
    #    Alpha 2.744: причин может быть СРАЗУ ДВЕ и это надо сказать вслух. Раньше здесь стоял elif,
    #    и у Klipper/FlashForge (или Bambu external без vt_tray) с близким цветом записывалась только
    #    close_color — вторая причина (датчик не подтверждал) молча терялась, а оператор, соглашаясь
    #    на «близкий цвет», не глядя соглашался и на неподтверждённый источник. Это два разных риска,
    #    и согласие должно покрывать оба. Порядок списка канонический и стабильный.
    reasons = []
    if c["color_relation"] == REL_CLOSE:
        reasons.append(FR_CLOSE_COLOR)
    if c["verification"] == VERIFY_DECLARED:
        reasons.append(FR_INV_DECLARED)
    c["required_approval_reasons"] = reasons
    if reasons:
        # reason остаётся ПЕРВОЙ причиной — как краткая подпись для UI и совместимости; полный
        # перечень требований живёт в required_approval_reasons и именно он решает допуск.
        c.update({"status": FEED_APPROVAL, "reason": reasons[0]})
    else:
        c.update({"status": FEED_READY, "reason": ""})
    return c


def _manual_external_candidate(req_mat, req_color):
    """FlashForge без складской привязки: физическая подача всегда внешняя, а материал принтер
    не сообщает. Это НЕ ready по догадке — только отдельный approval_required, где оператор явно
    подтверждает реальную катушку. Для Bambu/AMS и Klipper этот обход не используется."""
    return {"ams_slot": EXTERNAL_SLOT, "mode": MODE_EXTERNAL, "spool_id": "",
            "inventory_bound": False, "external": True,
            "inventory_material": None, "inventory_color": None,
            "reported_material": None, "reported_color": None,
            "color_relation": REL_UNKNOWN, "color_distance": None,
            "verification": VERIFY_MANUAL, "status": FEED_APPROVAL,
            "reason": FR_MANUAL_EXTERNAL,
            "required_approval_reasons": [FR_MANUAL_EXTERNAL]}


_STATUS_RANK = {FEED_READY: 0, FEED_APPROVAL: 1, FEED_ATTENTION: 2, FEED_BLOCKED: 3}
_REL_RANK = {REL_EXACT: 0, REL_CLOSE: 1, REL_UNKNOWN: 2, REL_MISMATCH: 3}
_VER_RANK = {VERIFY_TELEMETRY: 0, VERIFY_DECLARED: 1, VERIFY_MANUAL: 2}


def _cand_key(c):
    """Лексикографический порядок кандидатов. Полностью детерминирован: последним ключом идёт
    spool_id, поэтому порядок словарей/строк БД на результат не влияет."""
    return (_STATUS_RANK.get(c["status"], 9), _REL_RANK.get(c["color_relation"], 9),
            _VER_RANK.get(c["verification"], 9),
            (0 if c["ams_slot"] is not None else 1), (c["ams_slot"] if c["ams_slot"] is not None else 0),
            str(c["spool_id"]))


def build_feed_plan(run_id, item_id, printer_id, now=None):
    """Построить план подачи для пары item+printer. ЧИСТОЕ ВЫЧИСЛЕНИЕ: ничего не пишет, не резервирует,
    не потребляет clearance и не печатает. -> feed plan (см. FEED_VERSION) + 'candidates' для UI/диагностики.
    Никогда не отдаёт Auto/None: ready-план всегда называет явный ams_slot."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        it = conn.execute("SELECT * FROM project_run_items WHERE id=? AND run_id=?", (item_id, run_id)).fetchone()
        it = dict(it) if it else None
        fr = conn.execute("SELECT * FROM project_files WHERE id=?", (it["file_id"],)).fetchone() if (it and it["file_id"]) else None
        fr = dict(fr) if fr else None
    plan = {"version": FEED_VERSION, "status": FEED_BLOCKED, "reason": "", "project_id": "",
            "run_id": str(run_id), "item_id": str(item_id), "file_id": "", "file_hash": "",
            "printer_id": str(printer_id), "transport": "", "filament_count": 0,
            "ams_slot": None, "mode": "", "spool_id": "", "inventory_bound": False,
            "required_material": None, "inventory_material": None, "reported_material": None,
            "required_color": None, "inventory_color": None, "reported_color": None,
            "color_distance": None, "color_relation": REL_UNKNOWN, "verification": VERIFY_DECLARED,
            "requires_approval": False, "approval": None, "built_at": float(now if now is not None else _now()),
            "candidates": []}
    if not it:
        plan["reason"] = "item_not_found"
        return plan
    plan["project_id"] = it["project_id"]
    plan["file_id"] = it["file_id"] or ""
    if not fr:
        plan["reason"] = FR_FILE_MISSING
        return plan

    req = file_requirements(fr)
    plan["file_hash"] = str(req.get("file_hash") or fr.get("content_hash") or "")
    plan["filament_count"] = int(req.get("filament_count") or 0)
    prob = _requirements_problem(req)
    if prob:
        plan["status"], plan["reason"] = prob
        return plan
    f0 = req["filaments"][0]
    plan["required_material"] = f0.get("material")
    plan["required_color"] = norm_hex(f0.get("color_hex"))

    s = safety(printer_id)
    plan["transport"] = s.get("transport") or "unknown"
    rows = _inventory_rows(printer_id)
    if not rows:
        if plan["transport"] == "flashforge":
            # Adventurer 5M не имеет AMS/датчика материала и штатно работает с внешней катушкой
            # без записи склада. Назначаем только ФИЗИЧЕСКИ однозначную позицию -1, но требуем
            # отдельное согласие человека на материал/цвет из файла. Никакого Auto и ready здесь нет.
            c = _manual_external_candidate(plan["required_material"], plan["required_color"])
            plan["candidates"] = [c]
            return _plan_with_candidate(plan, c)
        # Либо модуль склада не установлен, либо у принтера нет ни одной привязанной катушки.
        # В обоих случаях источник подачи недоказуем -> человек. Импортировать склад нельзя и не нужно.
        plan.update({"status": FEED_ATTENTION, "reason": FR_INV_UNAVAILABLE})
        return plan
    tele_fresh, tele_avail, reported = _reported_positions(printer_id)
    cands = [_candidate_from_row(r, plan["required_material"], plan["required_color"],
                                 plan["transport"], reported, tele_fresh, tele_avail) for r in rows]
    cands.sort(key=_cand_key)
    plan["candidates"] = cands
    best = cands[0]
    if best["status"] in (FEED_READY, FEED_APPROVAL):
        # Общий helper с API выбора: план «лучшего» и план «выбранного вручную» строятся ОДНИМ кодом
        # и разъехаться не могут (candidates при этом остаются — они уже в plan).
        plan = _plan_with_candidate(plan, best)
    else:
        # Ни одного пригодного кандидата: blocked/attention НЕ выбираются как selected — план
        # объясняет причину, но подачу не назначает (ams_slot остаётся None).
        plan.update({"status": best["status"], "reason": best["reason"],
                     "inventory_material": best["inventory_material"], "inventory_color": best["inventory_color"],
                     "reported_material": best["reported_material"], "reported_color": best["reported_color"],
                     "color_relation": best["color_relation"], "color_distance": best["color_distance"]})
    return plan


# ── Согласие оператора (service-функция; API/UI появятся отдельной задачей) ────────────────────
def feed_fingerprint(plan):
    """Отпечаток ФАКТОВ, на которых стоит согласие. Любое их изменение обязано обесценить согласие:
    другая катушка, другой слот, другой файл, другой материал/цвет — это уже другое решение."""
    p = plan or {}
    parts = [p.get("item_id"), p.get("file_hash"), p.get("printer_id"), p.get("ams_slot"), p.get("spool_id"),
             norm_material(p.get("required_material")), norm_material(p.get("inventory_material")),
             norm_material(p.get("reported_material")),
             norm_hex(p.get("required_color")) or "", norm_hex(p.get("inventory_color")) or "",
             norm_hex(p.get("reported_color")) or ""]
    return "|".join("" if x is None else str(x) for x in parts)


def _norm_reasons(v):
    """Причины согласия -> СТАБИЛЬНЫЙ канонический список. Порядок фиксирован (APPROVABLE_REASONS),
    дубликаты схлопываются, произвольный текст НЕ принимается. -> (list, unknown_list)."""
    got = [str(x) for x in (v or [])] if isinstance(v, (list, tuple, set)) else []
    unknown = sorted({x for x in got if x not in APPROVABLE_REASONS})
    return ([r for r in APPROVABLE_REASONS if r in got], unknown)


def feed_required_reasons(plan):
    """Какие причины ОБЯЗАНО покрыть согласие. Стабильный список.
    Legacy-запас: у планов Alpha 2.742/2.743 поля ещё нет — тогда берём одиночный reason (в тех
    планах требование и было одно). Пересчитанный план всегда несёт полный список."""
    p = plan or {}
    v = p.get("required_approval_reasons")
    if isinstance(v, (list, tuple)):
        return _norm_reasons(v)[0]
    if p.get("status") == FEED_APPROVAL and p.get("reason") in APPROVABLE_REASONS:
        return [p["reason"]]
    return []


def feed_approved_reasons(plan):
    """Какие причины человек РЕАЛЬНО подтвердил. Legacy: одиночный approved_reason."""
    a = (plan or {}).get("approval")
    if not isinstance(a, dict):
        return []
    v = a.get("approved_reasons")
    if isinstance(v, (list, tuple)):
        return _norm_reasons(v)[0]
    if a.get("approved_reason") in APPROVABLE_REASONS:
        return [a["approved_reason"]]
    return []


def approve_feed_plan(plan, approved_by="", now=None, reasons=None):
    """Явное согласие человека на подачу, которую система сама разрешить не вправе.
    Разрешено ТОЛЬКО для close_color, inventory_declared и ручной внешней подачи FlashForge.
    Всё остальное (несовпадение материала,
    ΔE00 > 5, устаревшая телеметрия Bambu, пустой слот, multi-filament, пропавший/изменённый файл,
    неизвестный материал/цвет) согласием не лечится — это отказ по факту, а не по осторожности.
    reasons=None -> согласие на ВЕСЬ требуемый перечень (совместимость с вызовами 5A2a/5A2b).
    Неполный перечень -> approval_incomplete: у кандидата может быть СРАЗУ ДВЕ причины (близкий цвет
    И неподтверждённый датчиком источник), и согласие обязано покрыть обе — это разные риски.
    Идемпотентно. Ничего не пишет ни в БД, ни в склад/качество/себестоимость."""
    p = dict(plan or {})
    req = feed_required_reasons(p)
    if p.get("status") != FEED_APPROVAL or not req:
        return {"status": "error", "reason": "not_approvable", "plan_status": p.get("status"),
                "plan_reason": p.get("reason")}
    if reasons is None:
        given, unknown = list(req), []
    else:
        given, unknown = _norm_reasons(reasons)
    if unknown:
        return {"status": "error", "reason": "unknown_approval_reason", "unknown": unknown,
                "required_approval_reasons": req}
    if set(given) != set(req):
        # И неполный, и «лишний» перечень — отказ: согласие должно быть ровно на то, что требуется.
        return {"status": "error", "reason": "approval_incomplete",
                "required_approval_reasons": req, "approved_reasons": given}
    fp = feed_fingerprint(p)
    ex = p.get("approval")
    if isinstance(ex, dict) and ex.get("fingerprint") == fp and set(feed_approved_reasons(p)) == set(req):
        return {"status": "ok", "plan": p, "idempotent": True}     # повтор — тот же ответ
    p["approval"] = {"approved_by": str(approved_by or "")[:64],
                     "approved_at": float(now if now is not None else _now()),
                     "approved_reasons": given,
                     # approved_reason — LEGACY-производное (первая причина): старые читатели не
                     # ломаются, но допуск считается ТОЛЬКО по approved_reasons.
                     "approved_reason": given[0] if given else "",
                     "fingerprint": fp}
    return {"status": "ok", "plan": p, "idempotent": False}


def feed_plan_effective_status(plan):
    """Итоговый статус С УЧЁТОМ согласия. Исходные status/reason/relation/verification НЕ переписываются —
    почему решение было спорным, обязано остаться видно и в UI, и в журнале.
    ready — только если согласие покрывает ВЕСЬ требуемый перечень И отпечаток совпал: факты
    изменились -> решение недействительно. Наличие approval-объекта само по себе ничего не значит."""
    p = plan or {}
    st = p.get("status")
    if st != FEED_APPROVAL:
        return st
    a = p.get("approval")
    if not isinstance(a, dict):
        return FEED_APPROVAL
    req = feed_required_reasons(p)
    if not req or set(feed_approved_reasons(p)) != set(req):
        return FEED_APPROVAL                       # согласие не покрывает требуемое
    if a.get("fingerprint") != feed_fingerprint(p):
        return FEED_APPROVAL                       # отпечаток разъехался -> согласие обесценено
    return FEED_READY


# ── Сериализация и запись ──────────────────────────────────────────────────────────────────────
# Наружу и в БД идут ТОЛЬКО поля модели: ни путей, ни байтов файла, ни токенов принтера, ни данных
# MQTT/FTP, ни nonce подтверждения. 'candidates' — диагностика для UI, секретов там тоже нет.
_FEED_KEYS = ("version", "status", "reason", "project_id", "run_id", "item_id", "file_id", "file_hash",
              "printer_id", "transport", "filament_count", "ams_slot", "mode", "spool_id",
              "inventory_bound", "required_material", "inventory_material", "reported_material",
              "required_color", "inventory_color", "reported_color", "color_distance",
              "color_relation", "verification", "required_approval_reasons", "requires_approval",
              "approval", "built_at", "candidates")


def feed_plan_public(plan):
    """Безопасный снимок плана: whitelist полей + вычисленные производные. Единственный источник
    истины — сам план; производные считаются здесь и в БД не хранятся."""
    if not plan:
        return None
    out = {k: plan.get(k) for k in _FEED_KEYS if k in plan}
    out["effective_status"] = feed_plan_effective_status(plan)
    out["required_approval_reasons"] = feed_required_reasons(plan)
    out["approved_reasons"] = feed_approved_reasons(plan)
    # Наличие approval-объекта НЕ означает, что он действует: сверяем покрытие и отпечаток.
    out["approval_valid"] = bool(plan.get("approval")) and out["effective_status"] == FEED_READY
    out["fingerprint"] = feed_fingerprint(plan)
    return out


def _plan_with_candidate(plan, c):
    """План для КОНКРЕТНОГО кандидата (не обязательно лучшего) — общая точка для build_feed_plan и
    для API выбора: так план из «выбрать этот слот» не может разъехаться с планом планировщика."""
    out = dict(plan)
    out.update({"status": c["status"], "reason": c["reason"], "ams_slot": c["ams_slot"],
                "mode": c["mode"], "spool_id": c["spool_id"],
                "inventory_bound": bool(c.get("inventory_bound")),
                "inventory_material": c["inventory_material"], "inventory_color": c["inventory_color"],
                "reported_material": c["reported_material"], "reported_color": c["reported_color"],
                "color_relation": c["color_relation"], "color_distance": c["color_distance"],
                "verification": c["verification"],
                "required_approval_reasons": list(c.get("required_approval_reasons") or []),
                "requires_approval": c["status"] == FEED_APPROVAL})
    return out


def _feed_dump(plan):
    """Canonical JSON (sorted, без пробельных различий): повторная запись того же плана даёт
    байт-в-байт ту же строку, поэтому идемпотентность проверяется сравнением строк."""
    return json.dumps({k: plan.get(k) for k in _FEED_KEYS if k in plan},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# Поля, которые НЕ являются решением и потому не должны ломать идемпотентность. built_at — отметка
# времени пересчёта: builder ставит её при КАЖДОМ вызове, и без этого исключения повторный
# «выбрать то же самое» каждый раз переписывал бы строку и дёргал updated_at на пустом месте.
_FEED_VOLATILE = ("built_at",)


def _feed_dump_stable(plan):
    """Canonical JSON БЕЗ волатильных полей — им сравниваем «то же самое решение или нет»."""
    return json.dumps({k: plan.get(k) for k in _FEED_KEYS if k in plan and k not in _FEED_VOLATILE},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# Состояния item'а, в которых план подачи ещё можно переписать. Активные (отправляется/печатает/
# ждёт стол) переписывать НЕЛЬЗЯ: план уже применён к физической печати.
FEED_WRITABLE_STATES = (IT_PENDING, IT_ELIGIBLE, IT_BLOCKED, IT_AMBIGUOUS)


def persist_feed_plan(item_id, expected_run_id, feed_plan):
    """Записать план в СВОЮ колонку project_run_items.feed_plan_json. Больше не меняется ничего:
    ни другие колонки, ни другие таблицы, ни reservation/clearance/dispatch.
    Условный UPDATE + rowcount: item обязан принадлежать run и быть в переписываемом состоянии."""
    payload = _feed_dump(feed_plan or {})
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT run_id, state, feed_plan_json FROM project_run_items WHERE id=?",
                               (item_id,)).fetchone()
            if not row:
                conn.rollback()
                return {"status": "error", "reason": "item_not_found"}
            if row["run_id"] != str(expected_run_id):
                conn.rollback()
                return {"status": "error", "reason": "item_not_in_run"}
            if row["state"] not in FEED_WRITABLE_STATES:
                conn.rollback()
                return {"status": "error", "reason": "item_state_locked", "state": row["state"]}
            # «Тот же план» — по СУЩЕСТВУ решения, а не побайтово: built_at меняется при каждом
            # пересчёте и решением не является. Совпало -> не трогаем строку вовсе (и updated_at).
            _cur = _feed_from_raw(row["feed_plan_json"], item_id)
            if (row["feed_plan_json"] or "") == payload or (
                    _cur and _feed_dump_stable(_cur) == _feed_dump_stable(feed_plan or {})):
                conn.rollback()
                return {"status": "ok", "written": False, "idempotent": True}
            cur = conn.execute("UPDATE project_run_items SET feed_plan_json=?, updated_at=? "
                               "WHERE id=? AND run_id=? AND state IN (%s)" % ",".join("?" * len(FEED_WRITABLE_STATES)),
                               (payload, _now(), item_id, str(expected_run_id)) + FEED_WRITABLE_STATES)
            ok = cur.rowcount == 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"status": "ok", "written": True} if ok else {"status": "error", "reason": "race_lost"}


def read_feed_plan(item_id):
    """Прочитать сохранённый план. Fail-open: пусто/'{}' -> None; битый JSON -> план со статусом
    attention_required/feed_plan_corrupt (API не падает, сырое содержимое наружу не идёт)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT feed_plan_json FROM project_run_items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return None
    return _feed_from_raw(r["feed_plan_json"], item_id)


def _feed_from_raw(raw, item_id=""):
    s = (raw or "").strip()
    if not s or s == "{}":
        return None
    try:
        v = json.loads(s)
    except Exception:
        v = None
    if not isinstance(v, dict) or not v:
        # Битый/чужой JSON: молча «нет плана» показывать нельзя (выглядело бы как «ещё не считали»),
        # поэтому честно говорим, что план испорчен, и требуем человека.
        return {"version": FEED_VERSION, "status": FEED_ATTENTION, "reason": FR_CORRUPT,
                "item_id": str(item_id), "effective_status": FEED_ATTENTION}
    return feed_plan_public(v)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6c-bis. СЕРВИСЫ API ПЛАНА ПОДАЧИ (Alpha 2.744, этап 5A3a). ТОЛЬКО чтение + запись СВОЕЙ колонки.
# Ни reservation, ни lease, ни consume clearance, ни hold, ни project_print_job, ни scheduler.
# Вся арифметика — тот же builder 5A2a, дословно: «выбрать вручную» не может разъехаться с тем, что
# позже посчитает планировщик, потому что план строится одним и тем же кодом.
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Состояния item'а, в которых план подачи ещё можно менять: активный (уже отправляется/печатает/
# ждёт стол) трогать нельзя — план уже применён к физической печати.
FEED_API_STATES = (IT_PENDING, IT_ELIGIBLE, IT_BLOCKED, IT_AMBIGUOUS)


def _feed_ctx(run_id, item_id):
    """Проверка принадлежности и состояния. -> (ok, err_dict, run, item, file_row)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_runs WHERE id=?", (run_id,)).fetchone()
        it = conn.execute("SELECT * FROM project_run_items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return (False, {"status": "error", "reason": "run_not_found", "http": 404}, None, None, None)
    if not it:
        return (False, {"status": "error", "reason": "item_not_found", "http": 404}, None, None, None)
    r, it = dict(r), dict(it)
    if it["run_id"] != run_id:
        return (False, {"status": "error", "reason": "item_not_in_run", "http": 404}, r, it, None)
    if it["project_id"] != r["project_id"]:
        return (False, {"status": "error", "reason": "item_project_mismatch", "http": 409}, r, it, None)
    if it["state"] in IT_FUTURE_STATES:
        # Уже идёт lease/отправка/печать — план менять поздно и опасно.
        return (False, {"status": "error", "reason": "item_already_active", "http": 409,
                        "state": it["state"]}, r, it, None)
    if it["state"] not in FEED_API_STATES:
        return (False, {"status": "error", "reason": "item_state_locked", "http": 409,
                        "state": it["state"]}, r, it, None)
    if not it["file_id"]:
        return (False, {"status": "error", "reason": FR_FILE_MISSING, "http": 409}, r, it, None)
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        f = conn.execute("SELECT * FROM project_files WHERE id=? AND project_id=?",
                         (it["file_id"], it["project_id"])).fetchone()
    if not f:
        return (False, {"status": "error", "reason": FR_FILE_MISSING, "http": 409}, r, it, None)
    return (True, None, r, it, dict(f))


_CAND_PUBLIC = ("printer_id", "printer_name", "transport", "ams_slot", "mode", "spool_id",
                "inventory_bound", "inventory_material", "inventory_color", "reported_material",
                "reported_color", "required_material", "required_color", "color_distance",
                "color_relation", "verification", "status", "effective_status", "reason",
                "required_approval_reasons", "fingerprint")


def feed_candidates(run_id, item_id, compat_fn=None):
    """READ-ONLY: все кандидаты подачи для пары item × совместимые принтеры. Ничего не пишет, не
    резервирует, не потребляет разрешение, не ставит hold и не запускает планировщик.
    Порядок — тот же ranking builder'а 5A2a, довешенный стабильным order_idx принтера: одинаковый
    снимок бэкенда -> байт-в-байт одинаковый порядок и отпечатки."""
    ok, err, run, it, frow = _feed_ctx(run_id, item_id)
    if not ok:
        return err
    req = file_requirements(frow)
    prob = _requirements_problem(req)
    out = {"status": "ok", "run_id": run_id, "item_id": item_id, "file_id": it["file_id"],
           "file_hash": str(req.get("file_hash") or frow.get("content_hash") or ""),
           "filament_count": int(req.get("filament_count") or 0),
           "candidates": [], "selected": None,
           "summary": {FEED_READY: 0, FEED_APPROVAL: 0, FEED_ATTENTION: 0, FEED_BLOCKED: 0}}
    if prob:
        # Файл пропал/изменился/multi-filament/неизвестен материал: кандидатов не бывает в принципе.
        out.update({"status": "ok", "reason": prob[1], "plan_status": prob[0]})
        return out
    fleet = list(_ctx["printers"]() if _ctx["printers"] else [])
    fleet.sort(key=lambda p: (int(p.get("order_idx") or 0), str(p.get("id"))))
    compat = set(compat_fn(frow) or ()) if compat_fn else {p["id"] for p in fleet}
    names = {p["id"]: (p.get("name") or p["id"]) for p in fleet}
    order = {p["id"]: i for i, p in enumerate(fleet)}
    rows = []
    for p in fleet:
        if p["id"] not in compat:
            continue
        plan = build_feed_plan(run_id, item_id, p["id"])     # builder 5A2a — дословно
        for c in (plan.get("candidates") or []):
            cp = _plan_with_candidate({k: v for k, v in plan.items() if k != "candidates"}, c)
            pub = {k: cp.get(k) for k in _CAND_PUBLIC if k in cp}
            pub.update({"printer_id": p["id"], "printer_name": names[p["id"]],
                        "transport": cp.get("transport") or "",
                        "effective_status": feed_plan_effective_status(cp),
                        "required_approval_reasons": feed_required_reasons(cp),
                        "fingerprint": feed_fingerprint(cp)})
            rows.append((_cand_key(c), order[p["id"]], p["id"], pub))
        if not (plan.get("candidates") or []):
            # У принтера нет ни одной привязанной катушки — это тоже ответ оператору.
            rows.append(((_STATUS_RANK[FEED_ATTENTION], 9, 9, 1, 0, ""), order[p["id"]], p["id"],
                         {"printer_id": p["id"], "printer_name": names[p["id"]],
                          "transport": plan.get("transport") or "", "ams_slot": None, "mode": "",
                          "spool_id": "", "inventory_bound": False,
                          "required_material": plan.get("required_material"),
                          "required_color": plan.get("required_color"),
                          "inventory_material": None, "inventory_color": None,
                          "reported_material": None, "reported_color": None,
                          "color_relation": REL_UNKNOWN, "color_distance": None,
                          "verification": VERIFY_DECLARED, "status": FEED_ATTENTION,
                          "effective_status": FEED_ATTENTION, "reason": FR_INV_UNAVAILABLE,
                          "required_approval_reasons": [], "fingerprint": ""}))
    rows.sort(key=lambda x: (x[0], x[1], x[2], str(x[3].get("spool_id") or "")))
    out["candidates"] = [x[3] for x in rows]
    for c in out["candidates"]:
        st = c.get("status")
        if st in out["summary"]:
            out["summary"][st] += 1
    # selected — лучший ПРИГОДНЫЙ; blocked/attention не выбираются никогда.
    for c in out["candidates"]:
        if c.get("status") in (FEED_READY, FEED_APPROVAL):
            out["selected"] = c
            break
    return out


def _find_candidate(run_id, item_id, printer_id, ams_slot, spool_id, compat_fn=None):
    """Найти кандидата ТОЛЬКО по фактическим printer/slot/spool. Материалу/цвету/статусу из тела
    запроса не доверяем ни на грамм — всё пересчитывается здесь. -> (ok, err, plan_for_candidate)."""
    ok, err, run, it, frow = _feed_ctx(run_id, item_id)
    if not ok:
        return (False, err, None)
    if compat_fn is not None and printer_id not in set(compat_fn(frow) or ()):
        return (False, {"status": "error", "reason": "printer_incompatible", "http": 409}, None)
    plan = build_feed_plan(run_id, item_id, printer_id)
    prob = _requirements_problem(file_requirements(frow))
    if prob:
        return (False, {"status": "error", "reason": prob[1], "http": 409}, None)
    for c in (plan.get("candidates") or []):
        if c["ams_slot"] == ams_slot and str(c["spool_id"]) == str(spool_id):
            cp = _plan_with_candidate({k: v for k, v in plan.items() if k != "candidates"}, c)
            # Уже данное согласие переносим на пересчитанный план — ТОЧНО так же, как планировщик
            # (_sched_plan_for), и только при полном совпадении отпечатка. Иначе повторный
            # «подтвердить то же самое» каждый раз создавал бы НОВОЕ согласие с новым временем.
            st = read_feed_plan(item_id)
            if isinstance(st, dict) and isinstance(st.get("approval"), dict) \
                    and feed_fingerprint(st) == feed_fingerprint(cp):
                cp["approval"] = st["approval"]
            return (True, None, cp)
    return (False, {"status": "error", "reason": "candidate_not_found", "http": 409}, None)


def _feed_persist_guarded(run_id, item_id, plan, expected_fingerprint):
    """Запись плана с защитой от гонки: под BEGIN IMMEDIATE перечитываем item, сверяем принадлежность,
    состояние и отпечаток, и только потом пишем СВОЮ колонку. Отпечаток сверяется ДВАЖДЫ: снаружи
    (против устаревшего UI) и здесь (против параллельного изменения плана)."""
    if expected_fingerprint and feed_fingerprint(plan) != str(expected_fingerprint):
        return {"status": "error", "reason": "feed_plan_stale", "http": 409,
                "fingerprint": feed_fingerprint(plan)}
    r = persist_feed_plan(item_id, run_id, plan)          # единственный canonical writer
    if r.get("status") != "ok":
        http = 409 if r.get("reason") in ("item_state_locked", "item_not_in_run", "race_lost") else 404
        return dict(r, http=http)
    return {"status": "ok", "written": bool(r.get("written")), "idempotent": bool(r.get("idempotent"))}


def api_feed_select(run_id, item_id, printer_id, ams_slot, spool_id, expected_fingerprint=None,
                    compat_fn=None):
    """Явный выбор кандидата оператором. Без согласия допустим ТОЛЬКО ready."""
    ok, err, plan = _find_candidate(run_id, item_id, printer_id, ams_slot, spool_id, compat_fn)
    if not ok:
        return err
    eff = feed_plan_effective_status(plan)
    req = feed_required_reasons(plan)
    if expected_fingerprint and feed_fingerprint(plan) != str(expected_fingerprint):
        return {"status": "error", "reason": "feed_plan_stale", "http": 409,
                "fingerprint": feed_fingerprint(plan), "feed_plan": feed_plan_public(plan)}
    if plan["status"] == FEED_APPROVAL and eff != FEED_READY:
        return {"status": "error", "reason": "feed_plan_approval_required", "http": 409,
                "required_approval_reasons": req, "fingerprint": feed_fingerprint(plan),
                "feed_plan": feed_plan_public(plan)}
    if eff != FEED_READY:
        return {"status": "error", "reason": plan.get("reason") or plan["status"], "http": 409,
                "plan_status": plan["status"], "feed_plan": feed_plan_public(plan)}
    if plan.get("ams_slot") is None or int(plan.get("filament_count") or 0) != 1:
        return {"status": "error", "reason": FR_MULTI if int(plan.get("filament_count") or 0) > 1
                else FR_COUNT_UNKNOWN, "http": 409}
    w = _feed_persist_guarded(run_id, item_id, plan, expected_fingerprint)
    if w.get("status") != "ok":
        return w
    return {"status": "ok", "feed_plan": feed_plan_public(plan), "idempotent": bool(w.get("idempotent"))}


def api_feed_approve(run_id, item_id, printer_id, ams_slot, spool_id, approved_reasons,
                     confirmed=False, approved_by="operator", expected_fingerprint=None,
                     compat_fn=None, now=None):
    """Явное согласие оператора на спорную подачу. Кандидат пересчитывается сервером заново."""
    if confirmed is not True:
        return {"status": "error", "reason": "confirmation_required", "http": 400}
    _given, _unknown = _norm_reasons(approved_reasons)
    if _unknown:
        return {"status": "error", "reason": "unknown_approval_reason", "http": 400, "unknown": _unknown}
    ok, err, plan = _find_candidate(run_id, item_id, printer_id, ams_slot, spool_id, compat_fn)
    if not ok:
        return err
    if expected_fingerprint and feed_fingerprint(plan) != str(expected_fingerprint):
        return {"status": "error", "reason": "feed_plan_stale", "http": 409,
                "fingerprint": feed_fingerprint(plan), "feed_plan": feed_plan_public(plan)}
    a = approve_feed_plan(plan, approved_by=approved_by, now=now, reasons=_given)
    if a.get("status") != "ok":
        http = 400 if a.get("reason") == "unknown_approval_reason" else 409
        return dict(a, http=http, feed_plan=feed_plan_public(plan))
    ap = a["plan"]
    w = _feed_persist_guarded(run_id, item_id, ap, expected_fingerprint)
    if w.get("status") != "ok":
        return w
    return {"status": "ok", "feed_plan": feed_plan_public(ap), "idempotent": bool(w.get("idempotent"))}


def api_feed_clear(run_id, item_id, confirmed=False):
    """Отзыв сохранённого плана подачи. Это НЕ отзыв подтверждения «Стол очищен» (revoke_clearance) —
    ни разрешения, ни удержания, ни резервации, ни run это не касается."""
    if confirmed is not True:
        return {"status": "error", "reason": "confirmation_required", "http": 400}
    ok, err, run, it, _f = _feed_ctx(run_id, item_id)
    if not ok:
        return err
    # Пишем ТЕМ ЖЕ единственным canonical writer'ом: пустой план — это тоже план, и он обязан
    # проходить те же проверки (принадлежность run, состояние item, транзакция, rowcount).
    # Отдельного UPDATE у колонки быть не должно — иначе появляется второй путь мимо проверок.
    r = persist_feed_plan(item_id, run_id, {})            # _feed_dump({}) == '{}'
    if r.get("status") != "ok":
        http = 409 if r.get("reason") in ("item_state_locked", "item_not_in_run", "race_lost") else 404
        return dict(r, http=http)
    return {"status": "ok", "cleared": bool(r.get("written")), "idempotent": bool(r.get("idempotent")),
            "feed_plan": None}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6d. АТОМАРНЫЙ LEASE + MOCKED SCHEDULER (Alpha 2.743, этап 5A2b).
# В ПРОДАКШЕНЕ ЭТОТ КОД НИЧЕГО НЕ ПЕЧАТАЕТ И НЕ ЗАПУСКАЕТСЯ САМ.
#
# Разделение намеренное:
#   • scheduler_tick()          — PRODUCTION-вход. Первым делом предохранитель; при False выходит
#                                 ДО reservation/lease/consume/hold и любой правки item/run.
#   • _scheduler_tick_core()    — внутреннее DI-ядро. Не роут, не поток, не таймер; само себя не
#                                 запускает и следующий тик не планирует. Весь внешний мир —
#                                 ТОЛЬКО через явно переданные adapters. Настоящего transport-
#                                 адаптера в 5A2b не существует; тесты передают свои fake.
# Обхода предохранителя ни флагом, ни переменной окружения, ни HTTP-параметром НЕТ и не будет:
# единственный способ выполнить ядро — передать adapters из кода (то есть из тестов).
#
# ПОРЯДОК БЛОКИРОВОК (доказывается тестами, см. tools/test_project_orchestrator_scheduler.py):
#   reserve (send-manager lock) -> BEGIN IMMEDIATE (lock_p) -> COMMIT -> set_hold -> adapter.
#   Под lock_p НЕТ вызовов send-manager; cancel_reserved зовётся ТОЛЬКО после выхода из lock_p;
#   adapter вызывается без единого удержанного лока. Глобальный _orch_lock не вводится: атомарная
#   reservation уже является мьютексом принтера, второй лок только добавил бы риск.
# ══════════════════════════════════════════════════════════════════════════════════════════════
LEASE_TTL_S = 900.0          # срок аренды. В 5A2b его никто не жнёт: истёкший lease разбирает
                             # recovery по boot_id. Поле заполняется, чтобы 5B имел на что опереться.
SCHED_DISABLED = "disabled"

# Причины решений тика (канонические, для лога/диагностики/UI).
SD_RUN_NOT_RUNNING = "run_not_running"
SD_ITEM_NOT_LEASABLE = "item_not_leasable"
SD_NO_PRINTER = "no_candidate_printer"
SD_UNSAFE = "printer_unsafe"
SD_NO_CLEARANCE = "no_active_clearance"


def _expected_ts(v):
    """Ожидаемая версия строки (optimistic-lock) -> float или None, если это НЕ настоящее число.
    Отдельного timestamp не заводим: сравниваем ту же canonical колонку updated_at, что и в БД.
    Отбрасываем именно «похожее на значение»: None/undefined, "", строку (в т.ч. "222.25"),
    bool (True == 1 в Python!), NaN и inf. NaN опасен молча: NaN != NaN, поэтому сравнение
    «устарело?» дало бы stale навсегда, а не отказ по контракту.
    0 специально НЕ запрещаем магией: он просто не совпадёт с реальным updated_at (это _now()),
    а совпал бы — значит это и есть настоящая версия строки."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f
SD_PRINTER_TAKEN = "printer_taken_this_tick"
SD_OTHER_RUN = "printer_in_other_run"
SD_RESERVE_FAILED = "reserve_failed"
SD_FEED_NOT_READY = "feed_plan_not_ready"
SD_CHANGED = "changed_after_reservation"
SD_LEASE_FAILED = "lease_failed"
SD_HOLD_FAILED = "set_hold_failed"
SD_LEASED = "leased"
SD_DISPATCH_ACCEPTED = "dispatch_accepted"
SD_DISPATCH_FAILED = "dispatch_failed_before_command"
SD_DISPATCH_AMBIGUOUS = "dispatch_ambiguous"


def scheduler_tick():
    """PRODUCTION-вход планировщика. Пока предохранитель выключен — контролируемый отказ БЕЗ единого
    побочного эффекта: ни reservation, ни lease, ни consume clearance, ни hold, ни правки item/run.
    Настоящий планировщик (фоновый воркер, пробуждения по телеметрии, fallback-опрос) — этап 5B."""
    if not DISPATCH_ENABLED:
        return {"status": SCHED_DISABLED, "reason": DISPATCH_DISABLED_REASON, "leased": 0, "dispatched": 0}
    raise NotImplementedError("production scheduler ships in stage 5B only")   # pragma: no cover


def _sched_runs():
    """Активные run'ы в СТАБИЛЬНОМ порядке: старый run не обгоняется новым (защита от starvation)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM project_runs WHERE state IN (%s) ORDER BY created_at ASC, id ASC"
            % ",".join("?" * len(RUN_ACTIVE_STATES)), RUN_ACTIVE_STATES).fetchall()]


def _sched_items(run_id):
    """Незапущенные item'ы run'а в стабильном порядке плана."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM project_run_items WHERE run_id=? AND state IN (?,?) AND file_id!='' "
            "ORDER BY seq ASC, id ASC", (run_id, IT_PENDING, IT_ELIGIBLE)).fetchall()]


def _sched_file_row(file_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_files WHERE id=?", (file_id,)).fetchone()
    return dict(r) if r else None


def _sched_plan_for(run_id, item_id, printer_id, adapters):
    """Свежий план подачи + перенесённое согласие. Согласие переносится на пересчитанный план ТОЛЬКО
    при полном совпадении отпечатка: изменились факты — согласие обесценилось (см. 5A2a).
    -> (plan, effective_status)."""
    fresh = adapters["build_feed_plan"](run_id, item_id, printer_id)
    stored = read_feed_plan(item_id)
    if isinstance(stored, dict) and isinstance(stored.get("approval"), dict) \
            and feed_fingerprint(stored) == feed_fingerprint(fresh):
        fresh = dict(fresh, approval=stored["approval"])
    return (fresh, feed_plan_effective_status(fresh))


def _sched_precheck(run, item, printer_id, adapters):
    """Проверка ДО reservation. Дешёвая и заведомо устаревающая: авторитетно всё перепроверяется
    ПОСЛЕ захвата reservation (см. _scheduler_tick_core). -> (ok, reason, plan, clearance_id)."""
    s = adapters["safety_snapshot"](printer_id)
    if not isinstance(s, dict) or not s.get("safe_idle"):
        return (False, SD_UNSAFE, None, None)
    clr = active_clearance(printer_id)
    if not clr:
        # IDLE/FINISH пустой стол не доказывают — разрешение даёт ТОЛЬКО оператор кнопкой.
        return (False, SD_NO_CLEARANCE, None, None)
    if printer_id in _printers_in_active_runs():
        return (False, SD_OTHER_RUN, None, clr["id"])
    plan, eff = _sched_plan_for(run["id"], item["id"], printer_id, adapters)
    adapters["persist_feed_plan"](item["id"], run["id"], plan)     # единственный canonical writer
    if eff != FEED_READY:
        return (False, SD_FEED_NOT_READY, plan, clr["id"])
    if plan.get("ams_slot") is None or int(plan.get("filament_count") or 0) != 1:
        # Auto/None и multi-filament до сюда доходить не должны; это последний барьер.
        return (False, SD_FEED_NOT_READY, plan, clr["id"])
    return (True, "", plan, clr["id"])


def _lease_item_tx(run_id, item_id, printer_id, plan, clearance_id, send_job_id, boot=None,
                   activate_run=False):
    """АТОМАРНЫЙ lease: одна транзакция BEGIN IMMEDIATE под lock_p. Внутри — ПОВТОРНОЕ чтение всего,
    на чём стоит решение, расход разрешения и сам lease. Вызовов send-manager здесь нет и быть
    не может. project_print_job тут НЕ создаётся: его отдаёт adapter (в 5A2b — mock).

    activate_run (Alpha 2.752) — ТОЛЬКО для ручного controlled one-shot: сохранённый план после
    «Сохранить план» остаётся draft, а отдельного корректного перехода draft->running не было.
    True разрешает начать run из draft/waiting_for_printer и переводит его в running В ЭТОЙ ЖЕ
    транзакции, что и успешный lease + consume clearance: любой отказ ниже откатывает ВСЁ разом,
    run остаётся draft, разрешение не тратится. Фоновый scheduler зовёт с default False и
    по-прежнему требует RUN_RUNNING; paused/waiting_plate_clear/attention/терминальные состояния
    закрыты в ОБОИХ режимах.
    -> (ok, reason, nonce)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    nonce = uuid.uuid4().hex
    now = _now()
    fp = feed_fingerprint(plan)
    startable = (RUN_RUNNING, RUN_DRAFT, RUN_WAIT_PRINTER) if activate_run else (RUN_RUNNING,)
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT state FROM project_runs WHERE id=?", (run_id,)).fetchone()
            if not r or r["state"] not in startable:
                conn.rollback()
                return (False, SD_RUN_NOT_RUNNING, None)
            it = conn.execute("SELECT state, feed_plan_json FROM project_run_items WHERE id=? AND run_id=?",
                              (item_id, run_id)).fetchone()
            if not it or it["state"] not in (IT_PENDING, IT_ELIGIBLE):
                conn.rollback()
                return (False, SD_ITEM_NOT_LEASABLE, None)
            # Сохранённый план обязан описывать ТО ЖЕ решение (его только что записал precheck).
            saved = _feed_from_raw(it["feed_plan_json"], item_id)
            if not saved or feed_fingerprint(saved) != fp:
                conn.rollback()
                return (False, SD_CHANGED, None)
            busy = conn.execute(
                "SELECT 1 FROM project_run_items WHERE assigned_printer_id=? AND id!=? AND state IN (%s)"
                % ",".join("?" * len(HOLD_ITEM_STATES)),
                (printer_id, item_id) + HOLD_ITEM_STATES).fetchone()
            if busy:
                conn.rollback()
                return (False, SD_OTHER_RUN, None)
            # Разрешение расходуется РОВНО один раз: условный UPDATE + rowcount.
            cur = conn.execute(
                "UPDATE plate_clearances SET consumed_at=?, consumed_by_item_id=? "
                "WHERE id=? AND consumed_at IS NULL AND invalidated_at IS NULL AND boot_id=?",
                (now, item_id, clearance_id, str(boot if boot is not None else _ctx["boot"])))
            if cur.rowcount != 1:
                conn.rollback()
                return (False, SD_NO_CLEARANCE, None)
            cur = conn.execute(
                "UPDATE project_run_items SET assigned_printer_id=?, lease_nonce=?, lease_boot_id=?, "
                "lease_acquired_at=?, lease_expires_at=?, clearance_id=?, send_job_id=?, "
                "attempt=attempt+1, state=?, last_error='', updated_at=? "
                "WHERE id=? AND run_id=? AND state IN (?,?)",
                (printer_id, nonce, str(boot if boot is not None else _ctx["boot"]), now, now + LEASE_TTL_S,
                 clearance_id, str(send_job_id or ""), IT_LEASED, now, item_id, run_id, IT_PENDING, IT_ELIGIBLE))
            if cur.rowcount != 1:
                conn.rollback()
                return (False, SD_LEASE_FAILED, None)
            if activate_run and r["state"] != RUN_RUNNING:
                # Активация СТРОГО в этой же транзакции и строго условным UPDATE: если состояние
                # run сменил кто-то другой между чтением выше и этой строкой, lease не выживает.
                cur = conn.execute(
                    "UPDATE project_runs SET state=?, updated_at=? WHERE id=? AND state IN (?,?)",
                    (RUN_RUNNING, now, run_id, RUN_DRAFT, RUN_WAIT_PRINTER))
                if cur.rowcount != 1:
                    conn.rollback()
                    return (False, SD_RUN_NOT_RUNNING, None)
            conn.commit()
            return (True, "", nonce)
        except Exception as e:
            conn.rollback()
            # Partial UNIQUE idx_pri_active_printer — ОЖИДАЕМЫЙ исход гонки двух run'ов за принтер,
            # а не поломка: проигравший спокойно уходит, освободив reservation снаружи.
            if type(e).__name__ == "IntegrityError":
                return (False, SD_OTHER_RUN, None)
            raise


def _attach_pjob(item_id, pjob_id, new_state, command_sent):
    """Привязать проектное задание к item'у и перевести состояние. Одно задание — одному item'у:
    чужой/повторный pjob НЕ перезаписывает уже привязанный (это неоднозначность, а не «обновление»).
    -> (ok, reason)."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state, project_print_job_id FROM project_run_items WHERE id=?",
                               (item_id,)).fetchone()
            if not row:
                conn.rollback()
                return (False, "item_not_found")
            cur_pjob = row["project_print_job_id"] or ""
            if cur_pjob and cur_pjob != str(pjob_id or ""):
                conn.rollback()
                return (False, "pjob_mismatch")
            cur = conn.execute(
                "UPDATE project_run_items SET project_print_job_id=?, state=?, command_sent=?, updated_at=? "
                "WHERE id=? AND state=? AND (project_print_job_id='' OR project_print_job_id=?)",
                (str(pjob_id or ""), new_state, 1 if command_sent else 0, _now(), item_id, IT_SENDING,
                 str(pjob_id or "")))
            ok = cur.rowcount == 1
            conn.commit()
        except Exception as e:
            conn.rollback()
            if type(e).__name__ == "IntegrityError":
                return (False, "pjob_taken_by_other_item")     # уровень БД: idx_pri_pjob
            raise
    return (ok, "" if ok else "race_lost")


def reconcile_run_state(run_id):
    """Alpha 2.769 (аудит): ЕДИНЫЙ пересчёт состояния run по ФАКТИЧЕСКИМ состояниям деталей.
    До 2.769 run->completed умели только create_clearance и resolve_item, поэтому любой сценарий,
    завершавший детали мимо них, оставлял run активным НАВСЕГДА (аудит: зависание в
    waiting_for_plate_clear после рестарта; attention_required без выхода после отказа отправки).
    Правила: печать реально идёт (item в IT_FUTURE_STATES) -> run НЕ трогаем (правит телеметрия);
    все детали терминальны -> completed; из waiting_for_plate_clear/attention_required при наличии
    запускаемых деталей и отсутствии ambiguous -> waiting_for_printer (start его принимает);
    paused/cancelled/completed НЕ трогаем никогда (паузу снимает только человек). Идемпотентно."""
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT state FROM project_runs WHERE id=?", (run_id,)).fetchone()
            if not r:
                conn.rollback()
                return ""
            rs = r["state"]
            if rs not in (RUN_DRAFT, RUN_RUNNING, RUN_WAIT_PRINTER, RUN_WAIT_CLEAR, RUN_ATTENTION):
                conn.rollback()
                return rs
            states = [x["state"] for x in conn.execute(
                "SELECT state FROM project_run_items WHERE run_id=?", (run_id,)).fetchall()]
            if any(s in IT_FUTURE_STATES for s in states):
                conn.rollback()
                return rs
            alive = [s for s in states if s not in IT_TERMINAL_STATES]
            new_rs = rs
            if not alive:
                new_rs = RUN_COMPLETED
            elif rs in (RUN_WAIT_CLEAR, RUN_ATTENTION):
                if any(s == IT_AMBIGUOUS for s in alive):
                    new_rs = RUN_ATTENTION
                elif any(s in IT_RUNNABLE_STATES for s in alive):
                    new_rs = RUN_WAIT_PRINTER
            if new_rs != rs:
                conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE id=?",
                             (new_rs, _now(), run_id))
                if new_rs == RUN_COMPLETED:
                    conn.execute("UPDATE project_runs SET finished_at=? WHERE id=? AND finished_at IS NULL",
                                 (_now(), run_id))
            conn.commit()
            return new_rs
        except Exception:
            conn.rollback()
            raise

def _sched_fail(item_id, run_id, printer_id, state, err, adapters, send_job_id, clear_hold):
    """Общий безопасный выход: item -> терминальное безопасное состояние, run -> внимание.
    Автоповтора нет НИГДЕ и никогда: причина сбоя может означать брак на столе.
    Разрешение НЕ восстанавливаем: оно израсходовано, и доказательства пустого стола больше нет —
    оператор подтверждает заново. hold снимаем ТОЛЬКО когда доказано, что печать начаться не могла."""
    # Alpha 2.769 (аудит): ДОКАЗАННЫЙ отказ до отправки (printer_send_busy/printer_held/файла нет
    # и т.п.) — печать НЕ начиналась, деталь всё ещё нужна -> она ВОЗВРАЩАЕТСЯ В ОЧЕРЕДЬ (pending),
    # а run пересчитывается и НЕ заклинивает в attention_required без выхода (прежний тупик:
    # failed_before_dispatch терминален, retry нет, из attention start не принимается, паузу нельзя).
    # Это НЕ автоповтор: диспатч только явной кнопкой человека. Сомнение (ambiguous) — как раньше:
    # run -> attention, разрешает человек.
    if state == IT_FAILED_BEFORE:
        _set_item_state(item_id, IT_PENDING, only_if=(IT_LEASED, IT_SENDING, IT_WAIT_START), err=str(err or ""))
        reconcile_run_state(run_id)
    else:
        _set_item_state(item_id, state, only_if=(IT_LEASED, IT_SENDING, IT_WAIT_START), err=str(err or ""))
        _set_run_state(run_id, RUN_ATTENTION, only_if=RUN_ACTIVE_STATES)
    if send_job_id:
        try:
            adapters["cancel_reserved"](send_job_id)
        except Exception:
            pass
    if clear_hold:
        try:
            adapters["clear_hold"](printer_id, HOLD_OWNER_TYPE, run_id)
        except Exception:
            pass


def _scheduler_tick_core(context, adapters):
    """ВНУТРЕННЕЕ DI-ядро одного тика. Не роут и не воркер: один проход, без ожидания телеметрии,
    без sleep, без busy-loop и без планирования следующего тика (всё это — 5B).
    context: {"now": float|None}. adapters: list_printers, safety_snapshot, compatibility_check,
    build_feed_plan, persist_feed_plan, reserve_printer, cancel_reserved, set_hold, clear_hold,
    mock_dispatch. Настоящего transport-адаптера в этой версии не существует.
    -> {"status","leased","dispatched","decisions":[...]}"""
    A = dict(adapters or {})
    ctx = dict(context or {})
    decisions, leased, dispatched = [], 0, 0
    used_printers, used_items = set(), set()

    def _say(run_id, item_id, printer_id, action, reason=""):
        decisions.append({"run_id": run_id, "item_id": item_id, "printer_id": printer_id,
                          "action": action, "reason": reason})

    # Парк снимается ОДИН раз на тик и в стабильном порядке: одинаковый вход -> одинаковые решения.
    fleet = list(A["list_printers"]() or [])
    fleet.sort(key=lambda p: (int(p.get("order_idx") or 0), str(p.get("id"))))

    for run in _sched_runs():
        if run["state"] != RUN_RUNNING:
            # paused/cancelled/attention/draft: не lease'им НИЧЕГО и принтер не трогаем.
            _say(run["id"], None, None, "skipped", SD_RUN_NOT_RUNNING)
            continue
        for item in _sched_items(run["id"]):
            if item["id"] in used_items:
                continue
            frow = _sched_file_row(item["file_id"])
            if not frow:
                _say(run["id"], item["id"], None, "skipped", FR_FILE_MISSING)
                continue
            compat = set(A["compatibility_check"](frow) or ())
            cands = [p for p in fleet if p["id"] in compat and p["id"] not in used_printers]
            if not cands:
                _say(run["id"], item["id"], None, "skipped", SD_NO_PRINTER)
                continue
            for p in cands:
                pid = p["id"]
                ok, reason, plan, clr_id = _sched_precheck(run, item, pid, A)
                if not ok:
                    _say(run["id"], item["id"], pid, "skipped", reason)
                    continue

                # ── RESERVATION: единственный АТОМАРНЫЙ мьютекс принтера. Берётся ДО lock_p ──
                rok, sjid, rreason = A["reserve_printer"](pid, HOLD_OWNER_TYPE, run["id"])
                if not rok:
                    _say(run["id"], item["id"], pid, "skipped", SD_RESERVE_FAILED + ":" + str(rreason or ""))
                    continue

                # ── ПОВТОРНАЯ ПРОВЕРКА ПО СВЕЖИМ ДАННЫМ. Между precheck и reservation мир мог
                #    измениться: ручная печать, смена катушки, подмена файла, отзыв разрешения.
                ok2, reason2, plan2, clr_id2 = _sched_precheck(run, item, pid, A)
                if not ok2 or clr_id2 != clr_id or feed_fingerprint(plan2) != feed_fingerprint(plan):
                    A["cancel_reserved"](sjid)          # reservation отдаём, БД не трогаем
                    _say(run["id"], item["id"], pid, "skipped", (reason2 or SD_CHANGED) if not ok2 else SD_CHANGED)
                    continue

                # ── АТОМАРНЫЙ LEASE (lock_p). Никаких send-manager вызовов внутри ──
                lok, lreason, nonce = _lease_item_tx(run["id"], item["id"], pid, plan2, clr_id2, sjid)
                if not lok:
                    A["cancel_reserved"](sjid)          # ТОЛЬКО после выхода из lock_p
                    _say(run["id"], item["id"], pid, "skipped", lreason)
                    continue
                leased += 1
                used_printers.add(pid)
                used_items.add(item["id"])

                # ── HOLD после COMMIT. Короткое окно COMMIT->set_hold прикрыто reservation ──
                hok, _h = (False, None)
                try:
                    hok, _h = A["set_hold"](pid, HOLD_OWNER_TYPE, run["id"],
                                            "project_run_item:" + IT_LEASED)
                except Exception:
                    hok = False
                if not hok:
                    # Удержать принтер не удалось -> отправлять НЕЛЬЗЯ: чужой старт не будет закрыт.
                    _sched_fail(item["id"], run["id"], pid, IT_FAILED_BEFORE, SD_HOLD_FAILED, A, sjid, False)
                    _say(run["id"], item["id"], pid, "failed", SD_HOLD_FAILED)
                    continue

                # ── ОТПРАВКА. item -> sending короткой транзакцией, ЗАТЕМ adapter БЕЗ ЛОКОВ ──
                try:
                    _set_item_state(item["id"], IT_SENDING, only_if=(IT_LEASED,))
                except Exception as e:
                    # Исключение ДО входа в adapter: доказано, что отправки не было -> hold можно снять.
                    _sched_fail(item["id"], run["id"], pid, IT_FAILED_BEFORE, "pre_dispatch_error:" + type(e).__name__,
                                A, sjid, True)
                    _say(run["id"], item["id"], pid, "failed", SD_DISPATCH_FAILED)
                    continue
                _say(run["id"], item["id"], pid, SD_LEASED, "")

                payload = {"run_id": run["id"], "item_id": item["id"], "printer_id": pid,
                           "project_id": run["project_id"], "file_id": item["file_id"],
                           "ams_slot": plan2.get("ams_slot"), "mode": plan2.get("mode"),
                           "spool_id": plan2.get("spool_id"), "send_job_id": sjid,
                           "lease_nonce": nonce, "clearance_id": clr_id2}
                try:
                    res = A["mock_dispatch"](payload)
                except Exception as e:
                    # Adapter ВОШЁЛ и упал: мог успеть отправить -> решает человек, hold ОСТАЁТСЯ.
                    _sched_fail(item["id"], run["id"], pid, IT_AMBIGUOUS, "dispatch_exception:" + type(e).__name__,
                                A, sjid, False)
                    _say(run["id"], item["id"], pid, "ambiguous", SD_DISPATCH_AMBIGUOUS)
                    continue
                dispatched += 1 if _apply_dispatch_result(run, item, pid, res, A, sjid, _say) else 0
                break        # item обработан — к следующему
    return {"status": "ok", "leased": leased, "dispatched": dispatched, "decisions": decisions}


def transport_allowed(printer_id):
    """Допуск к НАСТОЯЩЕМУ транспорту. Три независимых серверных условия, все обязательны.
    -> (ok, reason). Ничего не читает из запроса: это чистая серверная конфигурация."""
    if not DISPATCH_ENABLED:
        return (False, DISPATCH_DISABLED_REASON)
    if not TRANSPORT_ENABLED:
        return (False, TRANSPORT_DISABLED_REASON)
    if str(printer_id or "") not in ALLOWED_PRINTER_IDS:
        return (False, PRINTER_NOT_ALLOWED_REASON)
    return (True, "")


def start_item_controlled(run_id, item_id, confirmed=False, adapters=None,
                          expected_run_updated_at=None, expected_item_updated_at=None,
                          expected_feed_fingerprint=None):
    """ТОЧЕЧНЫЙ one-shot запуск ОДНОГО явно выбранного item на ОДИН принтер (этап 5B1).
    Это НЕ планировщик: второй item не выбирается, следующий не запускается, таймеров/воркеров не
    создаётся, автоповтора нет. Никакой фоновой автоматизации.

    ЧТО АВТОРИТЕТНО. printer_id / ams_slot / spool_id / отпечаток берутся ТОЛЬКО из сохранённого
    feed_plan_json; материал, цвет, путь к файлу и слот из запроса не принимаются вообще — иначе
    «подтверждение» подтверждало бы присланные цифры, а не реальность.
    expected_* — защита от устаревшего экрана: если состояние изменилось, отказ ДО reservation.

    Переиспользует АТОМАРНЫЙ конвейер 5A2b (_sched_precheck -> reserve -> повторная проверка ->
    _lease_item_tx -> set_hold -> adapter), поэтому порядок локов и все гарантии те же."""
    if confirmed is not True:
        return {"status": "error", "reason": "confirmation_required", "http": 400}
    A = dict(adapters or {})
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_runs WHERE id=?", (run_id,)).fetchone()
        it = conn.execute("SELECT * FROM project_run_items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return {"status": "error", "reason": "run_not_found", "http": 404}
    if not it:
        return {"status": "error", "reason": "item_not_found", "http": 404}
    run, item = dict(r), dict(it)
    if item["run_id"] != run_id:
        return {"status": "error", "reason": "item_not_in_run", "http": 404}
    # Устаревший экран не должен запускать печать: сверяем то, что видел оператор.
    # Alpha 2.749 — FAIL-CLOSED. Раньше здесь стояло `is not None`, и пропущенное значение означало
    # «проверку пропустить». UI как раз слал undefined (item.updated_at не сериализовался), ключ
    # выпадал из JSON, сервер видел None — и защита от устаревшего экрана молча не работала.
    # Теперь все три значения ОБЯЗАТЕЛЬНЫ: нет значения -> нет запуска.
    _er, _ei = _expected_ts(expected_run_updated_at), _expected_ts(expected_item_updated_at)
    _ef = str(expected_feed_fingerprint or "").strip()
    if _er is None or _ei is None or not _ef:
        return {"status": "error", "reason": "expected_version_required", "http": 400}
    if _er != float(run["updated_at"]):
        return {"status": "error", "reason": "run_stale", "http": 409}
    if _ei != float(item["updated_at"]):
        return {"status": "error", "reason": "item_stale", "http": 409}
    # Alpha 2.752: ручному controlled one-shot разрешено НАЧАТЬ run из draft/waiting_for_printer —
    # сохранённый план до первой печати ровно draft, и другого корректного перехода в running нет.
    # Сам переход выполняет _lease_item_tx(activate_run=True) в одной транзакции с lease и consume
    # clearance: отказ где угодно ниже оставляет run как был. paused/waiting_plate_clear/
    # attention_required/completed/cancelled закрыты; фоновый scheduler по-прежнему требует running.
    if run["state"] not in (RUN_RUNNING, RUN_DRAFT, RUN_WAIT_PRINTER):
        return {"status": "error", "reason": SD_RUN_NOT_RUNNING, "http": 409, "state": run["state"]}
    if item["state"] not in (IT_PENDING, IT_ELIGIBLE):
        return {"status": "error", "reason": SD_ITEM_NOT_LEASABLE, "http": 409, "state": item["state"]}
    if not item["file_id"]:
        return {"status": "error", "reason": FR_FILE_MISSING, "http": 409}

    # ── Принтер берём ИЗ ПЛАНА, а не из запроса ──
    saved = read_feed_plan(item_id)
    if not isinstance(saved, dict) or saved.get("reason") == FR_CORRUPT:
        return {"status": "error", "reason": "feed_plan_missing", "http": 409}
    pid = str(saved.get("printer_id") or "")
    if not pid:
        return {"status": "error", "reason": "feed_plan_missing", "http": 409}
    if _ef != str(saved.get("fingerprint") or ""):     # _ef уже обязателен и нормализован выше
        return {"status": "error", "reason": "feed_plan_stale", "http": 409}
    ok, why = transport_allowed(pid)
    if not ok:
        # Предохранители проверяются ДО любых побочных эффектов: ни reservation, ни правок БД.
        return {"status": "error", "reason": why, "http": 409}
    # Alpha 2.748: одноразовое вооружение этого запуска. Здесь только ЧИТАЕМ (чужая цель, истёкший
    # срок, уже израсходовано -> отказ ДО reservation). Расходуется оно строго на границе входа в
    # production-адаптер: проверка, которая ничего не отправила, права на запуск не сжигает.
    _armfn = A.get("arm_check")
    if _armfn:
        aok, awhy = _armfn(run_id, item_id, pid)
        if not aok:
            return {"status": "error", "reason": awhy, "http": 409}

    # ── Ранняя проверка (понятный ответ). Авторитетная — после reservation. ──
    ok, why, plan, clr_id = _sched_precheck(run, item, pid, A)
    if not ok:
        return {"status": "error", "reason": why, "http": 409, "printer_id": pid}

    # ── RESERVATION с owner-bypass: атомарный мьютекс принтера, берётся ДО lock_p ──
    rok, sjid, rreason = A["reserve_printer"](pid, HOLD_OWNER_TYPE, run_id)
    if not rok:
        return {"status": "error", "reason": SD_RESERVE_FAILED + ":" + str(rreason or ""), "http": 409}

    # ── ПОВТОРНАЯ проверка по свежим данным: мир мог измениться между precheck и reservation ──
    ok2, why2, plan2, clr_id2 = _sched_precheck(run, item, pid, A)
    if not ok2 or clr_id2 != clr_id or feed_fingerprint(plan2) != feed_fingerprint(plan):
        A["cancel_reserved"](sjid)
        return {"status": "error", "reason": (why2 or SD_CHANGED) if not ok2 else SD_CHANGED, "http": 409}

    # ── АТОМАРНЫЙ LEASE (lock_p). Никаких send-manager вызовов внутри ──
    # activate_run=True: если run ещё draft/waiting_for_printer, он станет running В ЭТОЙ ЖЕ
    # транзакции; любой отказ откатывает и lease, и активацию, и расход разрешения разом.
    lok, lreason, nonce = _lease_item_tx(run_id, item_id, pid, plan2, clr_id2, sjid,
                                         activate_run=True)
    if not lok:
        A["cancel_reserved"](sjid)          # ТОЛЬКО после выхода из lock_p
        return {"status": "error", "reason": lreason, "http": 409}

    # ── HOLD после COMMIT ──
    try:
        hok, _h = A["set_hold"](pid, HOLD_OWNER_TYPE, run_id, "project_run_item:" + IT_LEASED)
    except Exception:
        hok = False
    if not hok:
        _sched_fail(item_id, run_id, pid, IT_FAILED_BEFORE, SD_HOLD_FAILED, A, sjid, False)
        return {"status": "error", "reason": SD_HOLD_FAILED, "http": 409}

    # ── ОТПРАВКА: item -> sending, затем adapter БЕЗ ЕДИНОГО ЛОКА ──
    try:
        _set_item_state(item_id, IT_SENDING, only_if=(IT_LEASED,))
    except Exception as e:
        # Исключение ДО входа в adapter: доказано, что отправки не было -> hold можно снять.
        _sched_fail(item_id, run_id, pid, IT_FAILED_BEFORE, "pre_dispatch_error:" + type(e).__name__, A, sjid, True)
        return {"status": "error", "reason": SD_DISPATCH_FAILED, "http": 409}
    payload = {"run_id": run_id, "item_id": item_id, "printer_id": pid, "project_id": run["project_id"],
               "file_id": item["file_id"], "ams_slot": plan2.get("ams_slot"), "mode": plan2.get("mode"),
               "spool_id": plan2.get("spool_id"), "send_job_id": sjid, "lease_nonce": nonce,
               "clearance_id": clr_id2}
    _say = lambda *a, **k: None
    try:
        res = A["dispatch"](payload)
    except Exception as e:
        # Adapter ВОШЁЛ и упал: мог успеть отправить -> решает человек, hold ОСТАЁТСЯ.
        _sched_fail(item_id, run_id, pid, IT_AMBIGUOUS, "dispatch_exception:" + type(e).__name__, A, sjid, False)
        return {"status": "ok", "accepted": False, "result": "ambiguous", "item_id": item_id,
                "printer_id": pid, "item": item_public(_item_row(item_id)), "run": run_public(_run_row(run_id))}
    accepted = _apply_dispatch_result(run, item, pid, res, A, sjid, _say)
    out = {"status": "ok", "accepted": bool(accepted), "item_id": item_id, "printer_id": pid,
           "ams_slot": plan2.get("ams_slot"),
           "item": item_public(_item_row(item_id)), "run": run_public(_run_row(run_id))}
    # Формулировка намеренно осторожная: команда принята транспортом — это ещё НЕ «печать началась».
    # Печать началась только тогда, когда это подтвердила телеметрия (on_printer_started).
    out["result"] = "accepted_awaiting_start_confirmation" if accepted else "ambiguous_or_failed"
    return out


def _apply_dispatch_result(run, item, pid, res, A, sjid, _say):
    """Разбор ответа adapter'а. -> True, если отправка принята."""
    if not isinstance(res, dict):
        # Неизвестный результат = неизвестно, ушла ли команда -> неоднозначность (hold остаётся).
        _sched_fail(item["id"], run["id"], pid, IT_AMBIGUOUS, "dispatch_unknown_result", A, sjid, False)
        _say(run["id"], item["id"], pid, "ambiguous", SD_DISPATCH_AMBIGUOUS)
        return False
    st = str(res.get("status") or "")
    cmd = res.get("command_sent")
    if st == "accepted":
        if cmd is None:
            _sched_fail(item["id"], run["id"], pid, IT_AMBIGUOUS, "command_sent_unknown", A, sjid, False)
            _say(run["id"], item["id"], pid, "ambiguous", SD_DISPATCH_AMBIGUOUS)
            return False
        pjob = str(res.get("project_print_job_id") or "")
        ok, why = _attach_pjob(item["id"], pjob, IT_WAIT_START, bool(cmd))
        if not ok:
            # Задание уже привязано к другому item'у / гонка -> честная неоднозначность.
            _sched_fail(item["id"], run["id"], pid, IT_AMBIGUOUS, "pjob:" + why, A, sjid, False)
            _say(run["id"], item["id"], pid, "ambiguous", SD_DISPATCH_AMBIGUOUS)
            return False
        # Дальше item двигает ТОЛЬКО телеметрия (on_printer_started/finished/failed). hold остаётся.
        _say(run["id"], item["id"], pid, SD_DISPATCH_ACCEPTED, "command_sent" if cmd else "queued")
        return True
    if st == "failed" and cmd is False:
        # Доказано, что команда НЕ ушла: печать начаться не могла -> hold снимаем по owner-match.
        # Разрешение остаётся израсходованным, автоповтора нет.
        _sched_fail(item["id"], run["id"], pid, IT_FAILED_BEFORE, str(res.get("reason") or "dispatch_failed"),
                    A, sjid, True)
        _say(run["id"], item["id"], pid, "failed", SD_DISPATCH_FAILED)
        return False
    # status=failed с command_sent True/None и любой другой ответ -> неоднозначность.
    _sched_fail(item["id"], run["id"], pid, IT_AMBIGUOUS, str(res.get("reason") or "dispatch_ambiguous"),
                A, sjid, False)
    _say(run["id"], item["id"], pid, "ambiguous", SD_DISPATCH_AMBIGUOUS)
    return False


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 7. RECOVERY (dry-run: только классификация состояний, печать не продолжается)
# ══════════════════════════════════════════════════════════════════════════════════════════════
def recover_on_start():
    """Детерминированно и идемпотентно. Ничего не резервирует и не отправляет.
    Правила: чужой boot -> lease мёртв; доказать завершение/освобождение может ТОЛЬКО свежая
    телеметрия; при сомнении -> ambiguous_after_dispatch (автоповтор запрещён)."""
    invalidated = invalidate_stale_boot_clearances()
    conn, lock = _ctx["conn"], _ctx["lock"]
    decisions = []
    with lock:
        items = [dict(r) for r in conn.execute(
            "SELECT i.* FROM project_run_items i JOIN project_runs r ON r.id=i.run_id "
            "WHERE r.state IN (%s) AND i.state IN (%s)" %
            (",".join("?" * len(RUN_ACTIVE_STATES)), ",".join("?" * len(IT_FUTURE_STATES))),
            RUN_ACTIVE_STATES + IT_FUTURE_STATES).fetchall()]
    for it in items:
        new_state, reason = _classify_recovered(it)
        decisions.append({"item_id": it["id"], "was": it["state"], "now": new_state, "reason": reason})
        with lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE project_run_items SET state=?, last_error=?, lease_nonce='', "
                             "lease_boot_id='', updated_at=? WHERE id=? AND state=?",
                             (new_state, reason, _now(), it["id"], it["state"]))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    # Run с ambiguous item'ами требует человека.
    with lock:
        conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE state IN (%s) AND id IN "
                     "(SELECT run_id FROM project_run_items WHERE state=?)" % ",".join("?" * len(RUN_ACTIVE_STATES)),
                     (RUN_ATTENTION, _now()) + RUN_ACTIVE_STATES + (IT_AMBIGUOUS,))
        conn.commit()
    # Alpha 2.769 (аудит): пересчёт ВСЕХ активных run по фактическим деталям. Закрывает зависание
    # «рестарт при ожидании снятия детали»: item становился completed (counted_before_restart), а
    # run оставался waiting_for_plate_clear навсегда — без item в waiting_plate_clear кнопки «Стол
    # очищен» нет и create_clearance его не завершит. Fail-open: сбой пересчёта не срывает recovery.
    with lock:
        _act_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM project_runs WHERE state IN (%s)" % ",".join("?" * len(RUN_ACTIVE_STATES)),
            RUN_ACTIVE_STATES).fetchall()]
    for _rid in _act_ids:
        try:
            reconcile_run_state(_rid)
        except Exception:
            pass
    return {"clearances_invalidated": invalidated, "items": decisions, "dispatch_enabled": DISPATCH_ENABLED}


def _classify_recovered(it):
    """Таблица решений restart×job×command_sent×telemetry. Без свежей телеметрии item НИКОГДА не
    считается завершённым или освободившим принтер."""
    pjob = _pjob_row(it["project_print_job_id"]) if it["project_print_job_id"] else None
    pid = it["assigned_printer_id"] or ""
    status, fresh = (_ctx["printer_status"](pid) if (pid and _ctx["printer_status"]) else ("", False))
    if it["state"] == IT_LEASED and not pjob and not int(it["command_sent"] or 0):
        return (IT_PENDING, "lease_void_after_restart")          # команда точно не отправлялась
    if pjob and pjob["counted_at"]:
        return (IT_COMPLETED, "counted_before_restart")          # учтено ядром — факт
    if not fresh:
        return (IT_AMBIGUOUS, "no_fresh_telemetry_after_restart")
    if status in ("RUNNING", "PREPARE") and pjob and pjob["status"] == "dispatched":
        return (IT_AMBIGUOUS, "printing_after_restart_needs_operator")
    return (IT_AMBIGUOUS, "dispatch_may_have_happened")


def _pjob_row(job_id):
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT id, status, counted_at, printer_id FROM project_print_jobs WHERE id=?",
                         (job_id,)).fetchone()
    return dict(r) if r else None


def resolve_item(run_id, item_id, resolution):
    """Единственный выход из ambiguous — решение человека. Автоповтор запрещён."""
    if resolution not in ("started", "not_started"):
        return {"status": "error", "reason": "bad_resolution"}
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        r = conn.execute("SELECT * FROM project_run_items WHERE id=? AND run_id=?", (item_id, run_id)).fetchone()
    if not r:
        return {"status": "error", "reason": "item_not_found"}
    it = dict(r)
    if it["state"] != IT_AMBIGUOUS:
        return {"status": "error", "reason": "not_ambiguous", "state": it["state"]}
    if resolution == "started":
        # «Началась» принимаем ТОЛЬКО при подтверждающем проектном задании — на слово не верим.
        if not it["project_print_job_id"] or not _pjob_row(it["project_print_job_id"]):
            return {"status": "error", "reason": "no_project_print_job_to_confirm"}
        new_state, err = IT_COMPLETED, "resolved_started_by_operator"
    else:
        # Alpha 2.766: «печать не начиналась» -> деталь ВОЗВРАЩАЕТСЯ В ОЧЕРЕДЬ (pending), а не
        # хоронится в failed_before_dispatch. Прежнее состояние было ТУПИКОМ: запуск требует
        # pending/eligible, пути из failed нет — оператору приходилось отменять ВЕСЬ план и
        # собирать его заново после каждого сбоя принтера (реальный круг с живой фермы).
        # Это НЕ автоповтор: диспатча отсюда не происходит; повторная отправка потребует ЯВНОГО
        # нажатия человеком + нового подтверждения «Стол очищен» + safe_idle. attempt сохраняется
        # (история попыток), last_error остаётся следом решения. Для НЕактивного run (отменён/
        # завершён) деталь по-прежнему уходит в failed_before_dispatch — историю не воскрешаем.
        new_state, err = IT_PENDING, "resolved_not_started_by_operator"
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            r0 = conn.execute("SELECT state FROM project_runs WHERE id=?", (run_id,)).fetchone()
            run_state = (r0["state"] if r0 else "")
            if resolution == "not_started" and run_state not in RUN_ACTIVE_STATES:
                new_state = IT_FAILED_BEFORE       # исторический (отменённый/завершённый) план
            cur = conn.execute("UPDATE project_run_items SET state=?, last_error=?, updated_at=? "
                               "WHERE id=? AND state=?", (new_state, err, _now(), item_id, IT_AMBIGUOUS))
            ok = cur.rowcount == 1
            # Alpha 2.766: run НЕ должен вечно висеть в «нужно решение человека» ПОСЛЕ решения.
            # Пересчёт по фактическому остатку (та же модель, что у подтверждения стола):
            # есть что печатать -> waiting_for_printer (start_item_controlled его принимает);
            # всё терминально -> completed; остались только blocked/ambiguous -> attention.
            new_rs = run_state
            if ok and run_state == RUN_ATTENTION:
                rows = conn.execute("SELECT state FROM project_run_items WHERE run_id=?", (run_id,)).fetchall()
                alive = [x["state"] for x in rows if x["state"] not in IT_TERMINAL_STATES]
                if not alive:
                    new_rs = RUN_COMPLETED
                elif any(s in IT_RUNNABLE_STATES for s in alive):
                    new_rs = RUN_WAIT_PRINTER
                if new_rs != run_state:
                    conn.execute("UPDATE project_runs SET state=?, updated_at=? WHERE id=?", (new_rs, _now(), run_id))
                    if new_rs == RUN_COMPLETED:
                        conn.execute("UPDATE project_runs SET finished_at=? WHERE id=? AND finished_at IS NULL",
                                     (_now(), run_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return ({"status": "ok", "state": new_state, "run_state": new_rs}
            if ok else {"status": "error", "reason": "race_lost"})


def diagnostics():
    conn, lock = _ctx["conn"], _ctx["lock"]
    with lock:
        runs = conn.execute("SELECT state, COUNT(*) c FROM project_runs GROUP BY state").fetchall()
        items = conn.execute("SELECT state, COUNT(*) c FROM project_run_items GROUP BY state").fetchall()
        clr = conn.execute("SELECT COUNT(*) c FROM plate_clearances WHERE consumed_at IS NULL "
                           "AND invalidated_at IS NULL").fetchone()
    return {"dispatch_enabled": DISPATCH_ENABLED, "boot_id": _ctx["boot"],
            "runs": {r["state"]: r["c"] for r in runs}, "items": {r["state"]: r["c"] for r in items},
            "active_clearances": clr["c"] if clr else 0}
