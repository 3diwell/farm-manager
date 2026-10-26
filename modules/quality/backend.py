# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Модуль «Аналитика качества» (quality) v0.2.3 — фундамент системы качества.
#
# Модуль ВЛАДЕЕТ журналом print_runs и его БД: farm_quality.db (путь — core.resolve_db,
# физически DATA_DIR\farm_quality.db). Ядро лишь испускает универсальные fail-open события
# print_run_started / print_run_finished — этот backend подписывается на них через core.add_hook
# и ведёт иммутабельную историю всех попыток печати. Отключение/удаление модуля не влияет на
# печать (ядро продолжит испускать события «в пустоту») и НЕ удаляет farm_quality.db.
#
# v0.2.0: на старте печати снимается ИММУТАБЕЛЬНЫЙ снимок использованных материалов/катушек
# (таблица print_run_materials). Данные берутся ТОЛЬКО через generic core.get_printer_filament_snapshot
# — БЕЗ импорта склада, без farm_inventory.db, без HTTP к /api/mod/inventory/*. Снимок
# денормализован: производитель/материал/цвет/партия/остаток фиксируются и не пересчитываются,
# даже если позже катушку переименовать/переместить/удалить.
# v0.2.3: при запуске программы разбираются строки, оставшиеся «печатается» с прошлых запусков
# (см. q_sweep_orphans). Решение принимает сам принтер, а не таймер.
# Статистика, оценки, дефекты, компоненты и рекомендации — в следующих версиях.
import json
import logging
import re
import sqlite3
import threading
import time

log = logging.getLogger("fm.mod.quality")

core = None            # ядро (ModuleCore) — задаётся в register()
conn_q = None          # подключение к СВОЕЙ БД farm_quality.db — создаётся в register()
lock_q = threading.RLock()

SCHEMA_VERSION = 1

DDL = [
    "CREATE TABLE IF NOT EXISTS print_runs ("
    "run_id TEXT PRIMARY KEY, "
    "source TEXT NOT NULL, "                      # project | quick | screen | queue | external | unknown
    "printer_id TEXT NOT NULL, "
    "printer_name TEXT, printer_type TEXT, printer_model TEXT, "
    "project_id INTEGER, task_id INTEGER, file_id INTEGER, "
    "filename TEXT, file_norm TEXT, file_hash TEXT, "
    "batch_id TEXT, queue_id INTEGER, "
    "started_at TEXT NOT NULL, finished_at TEXT, "
    "elapsed_s INTEGER, estimated_s INTEGER, final_percent REAL, "
    "outcome_raw TEXT, "                          # running | finished | failed | cancelled | interrupted | unknown
    "terminal_reason TEXT, "
    "source_payload_json TEXT, profile_snapshot_json TEXT, printer_snapshot_json TEXT, "
    "origin TEXT NOT NULL DEFAULT 'live', "
    "schema_version INTEGER NOT NULL DEFAULT 1, "
    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_printer_started ON print_runs(printer_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_started ON print_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_hash ON print_runs(file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_outcome ON print_runs(outcome_raw)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_source ON print_runs(source)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_project ON print_runs(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_pruns_filename ON print_runs(filename)",
    # ── Алиасы событий ядра (инвариант run_id) ─────────────────────────────────────────
    # persistent run_id строки print_runs — ПОСТОЯННАЯ идентичность физической попытки печати
    # (на неё будут ссылаться материалы/оценки/дефекты/фото/статистика) и НИКОГДА не меняется.
    # После рестарта ядро выдаёт продолжающейся печати НОВЫЙ корреляционный event id — он
    # связывается с прежней строкой записью-алиасом (только INSERT; переживает рестарты).
    "CREATE TABLE IF NOT EXISTS print_run_event_aliases ("
    "event_run_id TEXT PRIMARY KEY, "
    "persistent_run_id TEXT NOT NULL, "
    "created_at TEXT NOT NULL, "
    "reason TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_prea_persistent ON print_run_event_aliases(persistent_run_id)",
    # ── Снимок материалов/катушек печати (v0.2.0) ──────────────────────────────────────
    # Иммутабельный ДЕНОРМАЛИЗОВАННЫЙ снимок на момент старта: значения (производитель, материал,
    # цвет, партия, катушка, остаток) фиксируются и НЕ пересчитываются позже — переименование/
    # перемещение/удаление катушки в складе прошлую печать не меняет. Несколько строк на один
    # persistent_run_id = многоцветная/многоматериальная печать. FOREIGN KEY к складу НЕ ставим:
    # история переживает удаление катушки и самого модуля склада.
    "CREATE TABLE IF NOT EXISTS print_run_materials ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "persistent_run_id TEXT NOT NULL, "
    "spool_id TEXT, filament_id TEXT, vendor_id TEXT, vendor_name TEXT, "
    "material TEXT, color_hex TEXT, diameter REAL, lot TEXT, opened_at TEXT, purchased_at TEXT, "
    "source_type TEXT, "                          # ams | external | manual | unknown
    "printer_id TEXT, ams_unit TEXT, ams_slot INTEGER, position_key TEXT, "
    "remaining_g_at_capture REAL, full_weight_g REAL, planned_g REAL, planned_total_g REAL, "
    "capture_phase TEXT, "                        # start | resume | orphan
    "allocation_confidence TEXT, "                # exact | probable | partial | unknown
    "captured_at TEXT NOT NULL, snapshot_json TEXT, "
    "schema_version INTEGER NOT NULL DEFAULT 1)",
    "CREATE INDEX IF NOT EXISTS idx_prm_run ON print_run_materials(persistent_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_prm_spool ON print_run_materials(spool_id)",
    "CREATE INDEX IF NOT EXISTS idx_prm_filament ON print_run_materials(filament_id)",
    "CREATE INDEX IF NOT EXISTS idx_prm_vendor ON print_run_materials(vendor_name)",
    "CREATE INDEX IF NOT EXISTS idx_prm_material ON print_run_materials(material)",
    "CREATE INDEX IF NOT EXISTS idx_prm_lot ON print_run_materials(lot)",
    "CREATE INDEX IF NOT EXISTS idx_prm_printer ON print_run_materials(printer_id)",
    # Безопасная идемпотентность: повторный started/recovery НЕ создаёт дубль строки того же
    # физического слота в рамках одной попытки печати (вставка — INSERT OR IGNORE).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_prm_run_pos ON print_run_materials(persistent_run_id, position_key)",
]


def _now():
    """Единый формат времени проекта (UTC 'YYYY-MM-DD HH:MM:SS')."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _init_tables():
    """Создаёт (идемпотентно) схему журнала + режимы WAL/busy_timeout — та же политика, что у склада."""
    with lock_q:
        conn_q.execute("PRAGMA journal_mode=WAL;")
        conn_q.execute("PRAGMA synchronous=NORMAL;")
        conn_q.execute("PRAGMA busy_timeout=5000;")
        for q in DDL:
            conn_q.execute(q)
        conn_q.commit()


# ── Обработчики событий ядра (fail-open: любые свои ошибки глотаем и логируем) ──
_ROW_KEYS = ("run_id", "source", "printer_id", "printer_name", "printer_type", "printer_model",
             "project_id", "task_id", "file_id", "filename", "file_norm", "file_hash",
             "batch_id", "queue_id", "started_at", "finished_at", "elapsed_s", "estimated_s",
             "final_percent", "outcome_raw", "terminal_reason")

def _insert_run(snap, outcome=None):
    """INSERT строки журнала из снапшота события ядра. outcome позволяет вставить сразу терминальную
    запись (orphan-finished). Идемпотентность обеспечивает вызывающий."""
    now = _now()
    vals = {k: snap.get(k) for k in _ROW_KEYS}
    if outcome:
        vals["outcome_raw"] = outcome
    vals.setdefault("source", "unknown")
    with lock_q:
        conn_q.execute(
            "INSERT INTO print_runs (run_id, source, printer_id, printer_name, printer_type, printer_model, "
            "project_id, task_id, file_id, filename, file_norm, file_hash, batch_id, queue_id, "
            "started_at, finished_at, elapsed_s, estimated_s, final_percent, outcome_raw, terminal_reason, "
            "source_payload_json, profile_snapshot_json, printer_snapshot_json, origin, schema_version, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (vals["run_id"], str(vals["source"] or "unknown"), str(vals["printer_id"] or ""),
             vals["printer_name"], vals["printer_type"], vals["printer_model"],
             vals["project_id"], vals["task_id"], vals["file_id"],
             vals["filename"], vals["file_norm"], vals["file_hash"],
             vals["batch_id"], vals["queue_id"],
             vals["started_at"] or now, vals["finished_at"], vals["elapsed_s"], vals["estimated_s"],
             vals["final_percent"], vals["outcome_raw"] or "running", vals["terminal_reason"],
             _dumps(snap.get("source_payload") or {}), _dumps(snap.get("profile_snapshot") or {}),
             _dumps(snap.get("printer_snapshot") or {}), str(snap.get("origin") or "live"),
             int(snap.get("schema_version") or SCHEMA_VERSION), now, now))
        conn_q.commit()


def resolve_persistent_run_id(event_run_id):
    """Единый резолвер: event run_id ядра → ПОСТОЯННЫЙ run_id строки print_runs.
    1) прямое совпадение с print_runs.run_id; 2) поиск в print_run_event_aliases;
    3) None — событие-сирота (обработку выбирает вызывающий)."""
    rid = str(event_run_id or "")
    if not rid:
        return None
    with lock_q:
        if conn_q.execute("SELECT 1 FROM print_runs WHERE run_id=?", (rid,)).fetchone():
            return rid
        r = conn_q.execute("SELECT persistent_run_id FROM print_run_event_aliases WHERE event_run_id=?", (rid,)).fetchone()
    return (r["persistent_run_id"] if r else None)


# ── Снимок материалов/катушек (v0.2.0): денормализованный, иммутабельный, fail-open ──
def _f(v):
    """float или None (в БД — NULL; никаких выдуманных нулей)."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _slot_int(v):
    try:
        return int(v)
    except Exception:
        return None


def _unit_str(v):
    return None if v in (None, "") else str(v)


def _position_key(slot):
    """Стабильный ключ физического слота внутри принтера (для идемпотентной вставки)."""
    unit = slot.get("unit")
    idx = slot.get("index")
    return "u%ss%s" % ("" if unit in (None, "") else unit, "" if idx in (None, "") else idx)


def _source_type(has_ams, slot, assignment=None):
    """ams | external | unknown ('manual' — на будущее, ручной ввод). Приоритет — флагу назначения."""
    if (assignment and assignment.get("external")) or slot.get("external"):
        return "external"
    if slot.get("unit") is not None or slot.get("tray") is not None:
        return "ams"
    if has_ams:
        return "ams"
    return "unknown"


def _cap_confidence(conf):
    """После рестарта (resume) исходный стартовый контекст потерян — доверие не выше 'partial'."""
    return conf if conf in ("partial", "unknown") else "partial"


def _capture_materials(persistent_run_id, snap, phase):
    """Иммутабельный снимок материалов, НАЗНАЧЕННЫХ конкретному заданию печати.
    КЛЮЧЕВОЙ ИНВАРИАНТ: пишутся ТОЛЬКО позиции из material_assignments события (реальный ams_mapping
    задания), сопоставленные с привязанной катушкой из generic-снимка ядра. Наличие катушки в AMS
     само по себе НЕ означает её использование — «все непустые слоты» НЕ сохраняются никогда.
    Нет назначения → материалы не пишем вовсе. Источник данных о катушках — ТОЛЬКО
    core.get_printer_filament_snapshot (без зависимости от склада). Всё fail-open; иммутабельность
    recovery: если у run уже есть материалы — не трогаем."""
    try:
        pid = str((snap or {}).get("printer_id") or "")
        if not pid or conn_q is None:
            return
        assignments = [a for a in (snap.get("material_assignments") or []) if isinstance(a, dict)]
        if not assignments:
            return          # назначение задания неизвестно → НЕ выдумываем материалы (никаких «все катушки AMS»)
        with lock_q:        # иммутабельность recovery
            if conn_q.execute("SELECT 1 FROM print_run_materials WHERE persistent_run_id=? LIMIT 1",
                              (persistent_run_id,)).fetchone():
                return
        fil = {}
        if core is not None and hasattr(core, "get_printer_filament_snapshot"):
            try:
                fil = core.get_printer_filament_snapshot(pid) or {}
            except Exception:
                fil = {}    # провайдер упал — печать не блокируем, материал просто не пишем
        prov = {}           # AMS-слот (index) → слот провайдера с ПРИВЯЗАННОЙ катушкой
        for s in (fil.get("slots") or []):
            if isinstance(s, dict) and s.get("spool"):
                try:
                    prov[int(s.get("index"))] = s
                except Exception:
                    pass
        has_ams = bool(fil.get("has_ams"))
        single_job = (len(assignments) == 1)
        now = _now()
        rows = []
        for a in assignments:
            try:
                slot = int(a.get("ams_slot"))
            except Exception:
                continue
            s = prov.get(slot)
            if not s:
                continue    # назначенная позиция без привязанной катушки → строку НЕ создаём (→ status partial)
            sp = s.get("spool") or {}
            pg = _f(a.get("planned_g"))
            if pg is not None:
                conf = "exact"          # позиция задания + катушка на ней + точный вес филамента
            elif single_job:
                conf = "probable"       # доказанно однофиламентное задание, одна назначенная позиция
            else:
                conf = "partial"        # многофиламентное без пофиламентного веса
            if phase == "resume":
                conf = _cap_confidence(conf)
            rows.append({
                "persistent_run_id": persistent_run_id, "spool_id": sp.get("id"),
                "filament_id": sp.get("filament_id"), "vendor_id": sp.get("vendor_id"),
                "vendor_name": sp.get("vendor_name"), "material": sp.get("material"),
                "color_hex": sp.get("color_hex"), "diameter": _f(sp.get("diameter")),
                "lot": sp.get("lot"), "opened_at": sp.get("opened_at"), "purchased_at": sp.get("purchased_at"),
                "source_type": _source_type(has_ams, s, a), "printer_id": pid,
                "ams_unit": _unit_str(s.get("unit")), "ams_slot": _slot_int(s.get("index")),
                "position_key": _position_key(s), "remaining_g_at_capture": _f(sp.get("weight_remaining_g")),
                "full_weight_g": _f(sp.get("weight_total_g")), "planned_g": pg, "planned_total_g": None,
                "capture_phase": phase, "allocation_confidence": conf, "captured_at": now,
                "snapshot_json": _dumps({
                    "assignment": {k: a.get(k) for k in ("filament_index", "ams_slot", "external", "planned_g")},
                    "slot": {k: s.get(k) for k in ("index", "unit", "tray", "external", "offline")}, "spool": sp}),
                "schema_version": SCHEMA_VERSION})
        if not rows:
            return
        # planned_total_g — контекст общего веса; кладём его РОВНО на одну строку (первую по слоту),
        # чтобы суммирование planned_total_g по строкам не задваивало общий вес.
        rows.sort(key=lambda d: (d["ams_slot"] if d["ams_slot"] is not None else 1 << 30))
        rows[0]["planned_total_g"] = _f((snap.get("profile_snapshot") or {}).get("planned_weight_g"))
        cols = ("persistent_run_id", "spool_id", "filament_id", "vendor_id", "vendor_name", "material",
                "color_hex", "diameter", "lot", "opened_at", "purchased_at", "source_type", "printer_id",
                "ams_unit", "ams_slot", "position_key", "remaining_g_at_capture", "full_weight_g", "planned_g",
                "planned_total_g", "capture_phase", "allocation_confidence", "captured_at", "snapshot_json",
                "schema_version")
        batch = [tuple(d[c] for c in cols) for d in rows]
        with lock_q:
            conn_q.executemany(
                "INSERT OR IGNORE INTO print_run_materials (" + ", ".join(cols) + ") "
                "VALUES (" + ",".join(["?"] * len(cols)) + ")", batch)
            conn_q.commit()
        log.info("[quality] captured %d/%d assigned material(s) for run %s (phase=%s)",
                 len(batch), len(assignments), persistent_run_id, phase)
    except Exception:
        log.debug("[quality] capture_materials failed", exc_info=True)


def q_on_run_started(snap):
    """Событие ядра print_run_started. ИНВАРИАНТ: persistent run_id строки НИКОГДА не изменяется
    (PRIMARY KEY не UPDATE-ится). A) активной строки нет → INSERT с run_id = event id;
    B) running того же принтера с ТЕМ ЖЕ file_norm (доказанно продолжающаяся печать после
    рестарта ядра) → строка НЕ трогается (started_at/снапшоты первоначальные), новый event id
    связывается алиасом (INSERT OR IGNORE) — finished найдёт строку через резолвер;
    C) running другого файла → закрывается unknown/superseded_by_new_job, затем INSERT новой."""
    try:
        snap = dict(snap or {})
        event_id = str(snap.get("run_id") or "")
        pid = str(snap.get("printer_id") or "")
        fn = str(snap.get("file_norm") or "")
        if not event_id or not pid:
            return
        if resolve_persistent_run_id(event_id):
            return   # повторное событие того же запуска (напрямую или через алиас) — дубль не создаём
        with lock_q:
            open_row = conn_q.execute(
                "SELECT run_id, file_norm FROM print_runs WHERE printer_id=? AND outcome_raw='running' "
                "ORDER BY started_at DESC LIMIT 1", (pid,)).fetchone()
        if open_row:
            if fn and str(open_row["file_norm"] or "") == fn:
                # рестарт ядра во время ТОЙ ЖЕ печати: persistent id неизменен, event id — алиас.
                # Снапшот после рестарта беднее первоначального (метаданные отправки потеряны) —
                # ничего не дополняем и тем более не перезаписываем.
                with lock_q:
                    conn_q.execute("INSERT OR IGNORE INTO print_run_event_aliases "
                                   "(event_run_id, persistent_run_id, created_at, reason) VALUES (?,?,?,?)",
                                   (event_id, open_row["run_id"], _now(), "core_restart_resume"))
                    conn_q.commit()
                log.info("[quality] run %s resumed after core restart via alias %s (printer=%s)",
                         open_row["run_id"], event_id, pid)
                # если исходный старт был БЕЗ материалов (склад появился позже) — снимем с пометкой
                # 'resume' и пониженным доверием; если материалы уже есть — _capture_materials их не трогает.
                _capture_materials(open_row["run_id"], snap, "resume")
                return
            with lock_q:   # другой файл — прежняя печать закончилась недоказуемо
                conn_q.execute("UPDATE print_runs SET outcome_raw='unknown', terminal_reason='superseded_by_new_job', "
                               "finished_at=?, updated_at=? WHERE run_id=? AND outcome_raw='running'",
                               (_now(), _now(), open_row["run_id"]))
                conn_q.commit()
        _sp = dict(snap.get("source_payload") or {})   # счётчик назначений задания — для диагностики capture в detail
        _sp["material_assignment_count"] = len([a for a in (snap.get("material_assignments") or []) if isinstance(a, dict)])
        snap["source_payload"] = _sp
        _insert_run(snap)
        _capture_materials(event_id, snap, "start")   # новая физическая попытка → свой снимок материалов
    except Exception:
        log.debug("[quality] on_run_started failed", exc_info=True)


def q_on_run_finished(snap):
    """Событие ядра print_run_finished → идемпотентный терминальный UPDATE (только пока running).
    Orphan (started не видели, напр. модуль установлен во время печати): снапшот события полный —
    безопасно создаём сразу терминальную запись; без printer_id — только диагностический лог."""
    try:
        snap = dict(snap or {})
        run_id = str(snap.get("run_id") or "")
        if not run_id:
            return
        persistent = resolve_persistent_run_id(run_id)   # event id после рестарта → постоянный id через алиас
        target = persistent or run_id
        now = _now()
        with lock_q:
            cur = conn_q.execute(
                "UPDATE print_runs SET outcome_raw=?, terminal_reason=?, finished_at=?, elapsed_s=?, "
                "final_percent=?, updated_at=? WHERE run_id=? AND outcome_raw='running'",
                (str(snap.get("outcome_raw") or "unknown"), snap.get("terminal_reason"),
                 snap.get("finished_at") or now, snap.get("elapsed_s"), snap.get("final_percent"), now, target))
            conn_q.commit()
            if cur.rowcount > 0:
                return
            if conn_q.execute("SELECT 1 FROM print_runs WHERE run_id=?", (target,)).fetchone():
                return   # уже терминальная — повторный finished не меняет исход
        if snap.get("printer_id") and (snap.get("filename") or snap.get("file_norm")):
            _insert_run(snap, outcome=str(snap.get("outcome_raw") or "unknown"))   # orphan с полным снапшотом
            log.info("[quality] orphan finished stored as terminal run %s", run_id)
        else:
            log.warning("[quality] orphan finished dropped (insufficient snapshot): %s", run_id)
    except Exception:
        log.debug("[quality] on_run_finished failed", exc_info=True)



# ── Уборка записей, оставшихся «печатается» (v0.2.3, решение владельца по R-043) ─────────
# ОТКУДА БЕРУТСЯ. Строка создаётся на старте печати со словом running, а исход дописывает
# событие print_run_finished. Если программа в этот момент была выключена, дописывать некому:
# после перезапуска ядро не помнит активных печатей (self._active в памяти), и строка висит
# «печатается» вечно. Часть таких строк закрывает q_on_run_started (superseded_by_new_job) —
# но только если на том же принтере позже началась ДРУГАЯ печать. Остальные не закроет никто.
#
# ПРАВИЛО ОДНО, И ОНО ОСТОРОЖНОЕ: закрываем строку, ТОЛЬКО когда принтер на связи и НЕ печатает.
#   • принтер печатает (в любом состоянии печати) — не трогаем. Если он печатает уже другое,
#     строку закроет q_on_run_started, когда придёт событие старта;
#   • принтер молчит (нет состояния или OFFLINE) — не трогаем: доказательств нет, ждём
#     следующего запуска программы;
#   • принтера нет в списке фермы — закрываем: его удалили, доказательству взяться неоткуда.
#
# ИМЯ ФАЙЛА ДЛЯ РЕШЕНИЯ НЕ ИСПОЛЬЗУЕТСЯ, и это не упрощение. В журнале лежит имя, под которым
# файл отправил СЕРВЕР (handle_state: `raw_fn = sp`), а принтер сообщает своё — для одной и той
# же печати они могут отличаться. Сравнение имён закрывало бы живую печать как брошенную.
#
# ВРЕМЯ ТОЖЕ НЕ ИСПОЛЬЗУЕТСЯ: порог в часах пришлось бы выбирать наугад, а печати бывают
# и по сутки. Решение принимает сам принтер.
SWEEP_DELAY_S = 120          # пауза после старта программы: раньше принтеры ещё не ответили
_PRINTING = ("RUNNING", "PREPARE", "PAUSED", "SLICING")


def q_sweep_orphans():
    """Разбирает строки, оставшиеся running с прошлых запусков. Возвращает сводку для журнала и тестов.

    Fail-open: любая беда здесь не должна ничего ломать — журнал просто останется как был."""
    out = {"checked": 0, "closed": 0, "left": 0, "reasons": {}}
    try:
        with lock_q:
            rows = [dict(r) for r in conn_q.execute(
                "SELECT run_id, printer_id FROM print_runs WHERE outcome_raw='running'").fetchall()]
        out["checked"] = len(rows)
        if not rows:
            return out
        try:
            states = dict(core.printer_states() or {})
        except Exception:
            log.warning("[quality] уборка пропущена: живые состояния принтеров недоступны")
            out["left"] = len(rows)
            return out
        try:
            known = {str(p.get("id")) for p in (core.printers() or [])}
        except Exception:
            known = None          # список принтеров не прочитался — удалённые принтеры не ищем
        now = _now()
        for r in rows:
            pid = str(r.get("printer_id") or "")
            status = str((states.get(pid) or {}).get("status") or "").upper()
            if known is not None and pid and pid not in known:
                reason = "printer_removed"
            elif not status or status == "OFFLINE":
                out["left"] += 1
                continue
            elif status in _PRINTING:
                out["left"] += 1
                continue
            else:
                reason = "program_was_off"
            with lock_q:
                cur = conn_q.execute(
                    "UPDATE print_runs SET outcome_raw='unknown', terminal_reason=?, finished_at=?, "
                    "updated_at=? WHERE run_id=? AND outcome_raw='running'",
                    (reason, now, now, r.get("run_id")))
                conn_q.commit()
            if cur.rowcount > 0:
                # finished_at — момент закрытия строки, а не настоящий конец печати: он неизвестен.
                # elapsed_s и final_percent НЕ выставляем — выдумывать их было бы враньём в отчёте.
                out["closed"] += 1
                out["reasons"][reason] = out["reasons"].get(reason, 0) + 1
            else:
                out["left"] += 1
        if out["closed"]:
            log.info("[quality] уборка при запуске: закрыто %d из %d (%s), оставлено %d",
                     out["closed"], out["checked"], out["reasons"], out["left"])
    except Exception:
        log.debug("[quality] sweep_orphans failed", exc_info=True)
    return out


# ── API модуля: /api/mod/quality/* (read-only) ──
def _row_out(r):
    d = dict(r)
    for k in ("source_payload_json", "profile_snapshot_json", "printer_snapshot_json"):
        try:
            d[k[:-5]] = json.loads(d.pop(k) or "{}")
        except Exception:
            d[k[:-5]] = {}
    return d


def q_query(printer_id="", outcome="", source="", date_from="", date_to="", limit=100, offset=0):
    """Выборка журнала. limit жёстко 1..500; сортировка started_at DESC."""
    try:
        try:
            limit = int(limit)
        except Exception:
            limit = 100
        limit = max(1, min(500, limit))
        try:
            offset = max(0, int(offset))
        except Exception:
            offset = 0
        where, args = [], []
        for col, val in (("printer_id", printer_id), ("outcome_raw", outcome), ("source", source)):
            if val:
                where.append(col + "=?"); args.append(str(val))
        if date_from:
            where.append("started_at>=?"); args.append(str(date_from))
        if date_to:
            where.append("started_at<=?"); args.append(str(date_to))
        sql = "SELECT * FROM print_runs" + ((" WHERE " + " AND ".join(where)) if where else "") + \
              " ORDER BY started_at DESC, created_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with lock_q:
            rows = conn_q.execute(sql, args).fetchall()
        return [_row_out(r) for r in rows]
    except Exception:
        log.debug("[quality] query failed", exc_info=True)
        return []


def api_q_print_runs(printer_id: str = "", outcome: str = "", source: str = "", date_from: str = "",
                     date_to: str = "", limit: int = 100, offset: int = 0):
    """GET /api/mod/quality/print-runs — read-only журнал запусков печати."""
    return {"runs": q_query(printer_id, outcome, source, date_from, date_to, limit, offset)}


def _material_out(r, with_snapshot=True):
    """Строка print_run_materials наружу. with_snapshot=False → без тяжёлого snapshot_json (для списков)."""
    d = dict(r)
    raw = d.pop("snapshot_json", None)
    if with_snapshot:
        try:
            d["snapshot"] = json.loads(raw or "{}")
        except Exception:
            d["snapshot"] = {}
    return d


def q_materials(persistent_run_id, with_snapshot=True):
    """Снимок материалов запуска (сортировка по слоту). Ошибка — пустой список, не исключение."""
    try:
        with lock_q:
            rows = conn_q.execute(
                "SELECT * FROM print_run_materials WHERE persistent_run_id=? ORDER BY ams_slot, id",
                (str(persistent_run_id),)).fetchall()
        return [_material_out(r, with_snapshot) for r in rows]
    except Exception:
        log.debug("[quality] materials query failed", exc_info=True)
        return []


def _materials_brief_map(run_ids):
    """Компактные материалы (без snapshot_json) для набора run_id одним запросом — для summary."""
    ids = [str(x) for x in run_ids if x]
    if not ids:
        return {}
    try:
        qs = ",".join("?" * len(ids))
        with lock_q:
            rows = conn_q.execute(
                "SELECT persistent_run_id, material, vendor_name, lot, color_hex FROM print_run_materials "
                "WHERE persistent_run_id IN (%s) ORDER BY ams_slot, id" % qs, ids).fetchall()
        out = {}
        for r in rows:
            out.setdefault(r["persistent_run_id"], []).append(
                {"material": r["material"], "vendor_name": r["vendor_name"],
                 "lot": r["lot"], "color_hex": r["color_hex"]})
        return out
    except Exception:
        return {}


def api_q_print_run_one(run_id: str):
    """GET /api/mod/quality/print-runs/{run_id} — одна запись журнала + снимок материалов."""
    try:
        pid = resolve_persistent_run_id(str(run_id)) or str(run_id)
        with lock_q:
            r = conn_q.execute("SELECT * FROM print_runs WHERE run_id=?", (pid,)).fetchone()
        if not r:
            return {"status": "not_found"}
        d = _row_out(r)
        mats = q_materials(pid)
        d["materials"] = mats
        try:
            acount = int((d.get("source_payload") or {}).get("material_assignment_count") or 0)
        except Exception:
            acount = 0
        mcount = len(mats)
        # Диагностика сопоставления (§8): отличает «файл без материала/назначения» (unavailable)
        # от «назначение было, но катушка не привязана» (partial).
        if acount <= 0:
            status = "unavailable"
        elif mcount >= acount:
            status = "exact"
        else:
            status = "partial"
        d["material_assignment_count"] = acount
        d["material_matched_count"] = mcount
        d["material_capture_status"] = status
        return d
    except Exception:
        log.debug("[quality] get failed", exc_info=True)
        return {"status": "error"}


def api_q_print_run_materials(run_id: str):
    """GET /api/mod/quality/print-runs/{run_id}/materials — только снимок материалов запуска (read-only)."""
    try:
        pid = resolve_persistent_run_id(str(run_id)) or str(run_id)
        return {"materials": q_materials(pid)}
    except Exception:
        log.debug("[quality] materials endpoint failed", exc_info=True)
        return {"materials": []}


def api_q_summary():
    """GET /api/mod/quality/summary — сводка для минимального окна модуля."""
    try:
        with lock_q:
            total = conn_q.execute("SELECT COUNT(*) AS n FROM print_runs").fetchone()["n"]
            by = {r["outcome_raw"]: r["n"] for r in conn_q.execute(
                "SELECT outcome_raw, COUNT(*) AS n FROM print_runs GROUP BY outcome_raw").fetchall()}
            with_mat = conn_q.execute(
                "SELECT COUNT(DISTINCT persistent_run_id) AS n FROM print_run_materials").fetchone()["n"]
        total = int(total); with_mat = int(with_mat)
        without_mat = max(0, total - with_mat)
        rate = round(with_mat / total, 4) if total else 0.0
        recent = q_query(limit=8)
        brief = _materials_brief_map([r.get("run_id") for r in recent])
        for r in recent:
            r["materials"] = brief.get(r.get("run_id"), [])
        return {"active": True, "total": total, "by_outcome": by, "recent": recent,
                "runs_with_material": with_mat, "runs_without_material": without_mat,
                "material_capture_rate": rate, "schema_version": SCHEMA_VERSION}
    except Exception:
        log.debug("[quality] summary failed", exc_info=True)
        return {"active": False, "total": 0, "by_outcome": {}, "recent": [],
                "runs_with_material": 0, "runs_without_material": 0, "material_capture_rate": 0.0}


def register(_core):
    """Точка входа модуля: СВОЯ БД farm_quality.db + подписка на события печати ядра + роуты."""
    global core, conn_q
    core = _core
    conn_q = sqlite3.connect(core.resolve_db("farm_quality.db"), check_same_thread=False)
    conn_q.row_factory = sqlite3.Row
    _init_tables()
    # Alpha 2.785: у каждого маршрута ОБЯЗАТЕЛЕН policy_id — ссылка на запись в едином
    # реестре прав ядра (app/route_policy_registry.py). Само право задаётся ТОЛЬКО там;
    # модуль на него ссылается и никаких прав себе не назначает. Ядро сверяет id модуля,
    # версию, метод, оба пути и имя обработчика, и лишь затем подключает маршруты — все
    # разом, так что ошибка в одном не оставляет остальные наполовину живыми.
    core.add_route("print-runs", api_q_print_runs, ["GET"], policy_id="quality.print_runs.list")
    core.add_route("print-runs/{run_id}", api_q_print_run_one, ["GET"], policy_id="quality.print_runs.read")
    core.add_route("print-runs/{run_id}/materials", api_q_print_run_materials, ["GET"], policy_id="quality.print_runs.materials")
    core.add_route("summary", api_q_summary, ["GET"], policy_id="quality.summary.read")
    core.add_hook("print_run_started", q_on_run_started)
    core.add_hook("print_run_finished", q_on_run_finished)
    #  v0.2.3: разбор строк, оставшихся «печатается» с прошлых запусков. Через паузу, а не сразу:
    #  в первые секунды принтеры ещё не ответили, и каждый выглядел бы выключенным. Поток фоновый
    #  (daemon) — загрузку программы не задерживает и её завершению не мешает.
    if hasattr(core, "printer_states"):
        _t = threading.Timer(SWEEP_DELAY_S, q_sweep_orphans)
        _t.daemon = True
        _t.start()
    log.info("[quality] module registered: 4 routes, 2 print-run hooks (db: farm_quality.db)")
