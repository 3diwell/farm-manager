# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Восстановление режима SQLite-соединения после обслуживания БД (Alpha 2.774).
#
# БЕЗ сервера/принтеров/сети/рабочей БД: блок VACUUM извлекается из init_db ДОСЛОВНО через AST
# и исполняется со стабами; БД — sqlite3 ':memory:'; отказ VACUUM вносится обёрткой соединения.
# НАСТОЯЩИЙ VACUUM рабочих БД не выполняется никогда.
#
# CHARACTERIZATION: до Alpha 2.774 восстановление isolation_level стояло вторым выражением на
# строке с VACUUM. Сбой VACUUM оставлял ОБЩЕЕ соединение в autocommit до перезапуска программы —
# и это молча обнуляло защиту 2.772-2.773: DML фиксировались сразу, поздний rollback их не отменял.
#
# Запуск: python tools/test_sqlite_connection_state_restore.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sqlite3
import sys
import textwrap
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def grab_vacuum_block():
    """Дословный production-блок обслуживания БД (ветка `if conn_p.total_changes > _purged_before`)."""
    for fn in ast.walk(TREE):
        if isinstance(fn, ast.FunctionDef) and fn.name == "init_db":
            for n in ast.walk(fn):
                if isinstance(n, ast.If) and "total_changes" in (ast.unparse(n.test) or ""):
                    return textwrap.dedent(ast.get_source_segment(SRC, n))
    raise AssertionError("блок VACUUM в init_db не найден")


BLOCK = grab_vacuum_block()
check("A0. блок обслуживания БД извлечён дословно из init_db",
      "VACUUM" in BLOCK and "isolation_level" in BLOCK)


class VacuumFaultConn(object):
    """Обёртка над настоящим sqlite-соединением: управляемый отказ VACUUM и восстановления."""

    def __init__(self, real, fail_vacuum=False, fail_restore=False, lock=None):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_fail_vacuum", fail_vacuum)
        object.__setattr__(self, "_fail_restore", fail_restore)
        object.__setattr__(self, "_lock", lock)
        object.__setattr__(self, "restore_under_lock", [])
        object.__setattr__(self, "iso_sets", [])

    @property
    def isolation_level(self):
        return self._real.isolation_level

    @isolation_level.setter
    def isolation_level(self, v):
        self.iso_sets.append(v)
        if v is not None:                              # это восстановление рабочего режима
            self.restore_under_lock.append(bool(self._lock and self._lock.held))
            if self._fail_restore:
                raise sqlite3.OperationalError("injected isolation_level restore failure")
        self._real.isolation_level = v

    def execute(self, sql, *a, **k):
        if str(sql).strip().upper().startswith("VACUUM") and self._fail_vacuum:
            raise sqlite3.OperationalError("injected VACUUM failure (disk full)")
        return self._real.execute(sql, *a, **k)

    @property
    def in_transaction(self):
        return self._real.in_transaction

    @property
    def total_changes(self):
        return self._real.total_changes

    def __getattr__(self, item):
        return getattr(object.__getattribute__(self, "_real"), item)


class TrackLock(object):
    def __init__(self):
        self._l = threading.Lock()
        self.held = False

    def __enter__(self):
        self._l.acquire(); self.held = True; return self

    def __exit__(self, *a):
        self.held = False; self._l.release(); return False

    def locked(self):
        return self._l.locked()


class _Log(object):
    def __init__(self):
        self.lines = []
        self.levels = []

    def _mk(self, lvl):
        def rec(*a, **k):
            self.levels.append(lvl)
            try:
                self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
            except Exception:
                self.lines.append(str(a))
        return rec

    def __getattr__(self, item):
        return self._mk(item)


def run_block(fail_vacuum=False, fail_restore=False, start_iso="", open_txn=False):
    """Исполнить дословный production-блок под локом. -> (conn, log, raised)"""
    real = sqlite3.connect(":memory:")
    real.isolation_level = start_iso
    real.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    real.commit()
    lock = TrackLock()
    conn = VacuumFaultConn(real, fail_vacuum, fail_restore, lock)
    log = _Log()
    if open_txn:
        conn.execute("INSERT INTO t (v) VALUES ('open')")      # оставляем транзакцию открытой
    ns = {"conn_p": conn, "log": log, "_exc_brief": (lambda: "injected"),
          "_purged_before": -1}                                 # total_changes > -1 всегда -> блок выполняется
    raised = None
    try:
        with lock:
            exec(BLOCK, ns)
    except Exception as e:
        raised = e
    return conn, log, lock, raised, real


print("=== Alpha 2.774: восстановление режима SQLite после VACUUM ===")

# ═══ 1. Успешный VACUUM: временно autocommit, затем точное восстановление ═══
conn, log, lock, raised, real = run_block(fail_vacuum=False, start_iso="")
check("1a. исходный isolation_level не None (соединение транзакционное)", conn.iso_sets and conn.iso_sets[-1] is not None)
check("1b. в блоке соединение временно переводилось в autocommit", None in conn.iso_sets)
check("1c. после успешного VACUUM восстановлено ТОЧНОЕ исходное значение",
      conn.isolation_level == "" and raised is None)
check("1d. восстановление выполнено ПОД ТЕМ ЖЕ локом", all(conn.restore_under_lock))
check("1e. лок освобождён", not lock.locked())

# ═══ 2. Ошибка VACUUM: [ХАРАКТЕРИЗАЦИЯ] режим обязан восстановиться ═══
conn, log, lock, raised, real = run_block(fail_vacuum=True, start_iso="")
check("2a. ошибка VACUUM не прерывает запуск (обработана существующим контрактом)", raised is None)
check("2b. [ХАРАКТЕРИЗАЦИЯ] isolation_level ВОССТАНОВЛЕН, соединение НЕ в autocommit",
      conn.isolation_level == "")
check("2c. ошибка VACUUM не скрыта полностью (есть запись в журнале)",
      any("VACUUM" in s or "vacuum" in s.lower() for s in log.lines))
check("2d. уровень записи не ниже warning (не debug)",
      any(l in ("warning", "error", "critical") for l in log.levels))
check("2e. в журнал не попали путь к БД и данные",
      not any((".db" in s) or ("DATA_DIR" in s) or ("C:\\" in s) for s in log.lines))

# ═══ 3. [ХАРАКТЕРИЗАЦИЯ] защита 2.773 продолжает работать после сбоя VACUUM ═══
# После неудачного обслуживания соединение обязано снова давать НАСТОЯЩИЕ транзакции.
conn2 = conn
real2 = real
real2.execute("DELETE FROM t")
real2.commit()
conn2.execute("INSERT INTO t (v) VALUES ('first')")     # первая DML многошаговой операции
in_txn = conn2.in_transaction
conn2.rollback()                                        # как сделал бы _rollback_sqlite_on_error
left = real2.execute("SELECT COUNT(*) FROM t").fetchone()[0]
check("3a. [КЛЮЧЕВОЕ] после сбоя VACUUM DML открывает НАСТОЯЩУЮ транзакцию (in_transaction=True)", in_txn is True)
check("3b. [КЛЮЧЕВОЕ] rollback реально отменяет первую запись (защита 2.773 жива)", left == 0)
conn2.execute("INSERT INTO t (v) VALUES ('other')")     # чужая последующая операция
conn2.commit()
check("3c. чужой commit не воскресил остаток провалившейся операции",
      [r[0] for r in real2.execute("SELECT v FROM t")] == ["other"])

# ═══ 5-8. Точное восстановление разных исходных режимов ═══
for iso, label in ((None, "None (уже autocommit)"), ("", '"" (по умолчанию)'),
                   ("DEFERRED", "DEFERRED"), ("IMMEDIATE", "IMMEDIATE"), ("EXCLUSIVE", "EXCLUSIVE")):
    c, lg, lk, rs, rl = run_block(fail_vacuum=True, start_iso=iso)
    check("5. исходный режим %-24s восстановлен точно" % label, c.isolation_level == iso and rs is None)

# ═══ 9. Активная транзакция перед VACUUM: скрытого commit чужой работы быть не должно ═══
c, lg, lk, rs, rl = run_block(fail_vacuum=False, start_iso="", open_txn=True)
check("9a. при активной транзакции соединение НЕ переводится в autocommit (VACUUM пропущен)",
      None not in c.iso_sets and rs is None)
check("9b. чужая транзакция НЕ закоммичена молча — она всё ещё открыта", c.in_transaction is True)
check("9c. режим соединения не изменён", c.isolation_level == "")
check("9d. пропуск обслуживания зафиксирован в журнале",
      any("транзакц" in s.lower() for s in lg.lines))

# ═══ 10-11. Ошибка ВОССТАНОВЛЕНИЯ: запуск продолжаться не должен ═══
c, lg, lk, rs, rl = run_block(fail_vacuum=True, fail_restore=True, start_iso="")
check("10a. ошибка восстановления НЕ проглочена — исключение вышло наружу", rs is not None)
check("10b. ошибка восстановления записана как error/critical",
      any(l in ("error", "critical") for l in lg.levels))
check("11. обе причины диагностируемы (и VACUUM, и восстановление)",
      any("VACUUM" in s or "vacuum" in s.lower() for s in lg.lines)
      and any("восстанов" in s.lower() or "restore" in s.lower() for s in lg.lines))
check("14. лок освобождён и после ошибки восстановления", not lk.locked())

# ═══ 4. Сбой самого логирования не мешает восстановлению ═══
real3 = sqlite3.connect(":memory:")
real3.isolation_level = ""
lock3 = TrackLock()
conn3 = VacuumFaultConn(real3, fail_vacuum=True, lock=lock3)


class _BoomLog(object):
    def __getattr__(self, item):
        def boom(*a, **k):
            raise RuntimeError("logging backend down")
        return boom


ns3 = {"conn_p": conn3, "log": _BoomLog(), "_exc_brief": (lambda: "x"), "_purged_before": -1}
_r3 = None
try:
    with lock3:
        exec(BLOCK, ns3)
except Exception as e:
    _r3 = e
check("4. сбой логирования не мешает восстановить режим соединения",
      conn3.isolation_level == "")

# ═══ 17-18. Статические проверки production-кода ═══
print("--- статические проверки ---")
check("17a. восстановление isolation_level находится в finally", "finally:" in BLOCK)
check("17b. восстанавливается СОХРАНЁННОЕ исходное значение, а не константа",
      "isolation_level = _iso" in BLOCK and '"DEFERRED"' not in BLOCK)
check("17c. восстановление НЕ на одной строке с VACUUM (прежний дефект)",
      not any(("VACUUM" in ln and "isolation_level = _iso" in ln) for ln in BLOCK.splitlines()))
check("17d. VACUUM не обёрнут в _rollback_sqlite_on_error", "_rollback_sqlite_on_error" not in BLOCK)
check("17e. блок не добавляет собственный commit", "commit()" not in BLOCK)

# 18: во всём production-коде не осталось незащищённых временных изменений состояния соединения
prod = SRC
iso_lines = [(i + 1, l.strip()) for i, l in enumerate(prod.splitlines())
             if "isolation_level" in l and "=" in l and not l.strip().startswith("#")
             and "isolation_level," not in l]
check("18. все присваивания isolation_level в production — только в защищённом блоке VACUUM (%d шт.)"
      % len(iso_lines), all("_iso" in t or "None" in t for _, t in iso_lines))
check("18b. VACUUM в production ровно один и он в init_db",
      len([1 for l in prod.splitlines() if "VACUUM" in l and "execute" in l]) == 1)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
