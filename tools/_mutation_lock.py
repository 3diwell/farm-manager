# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841: ОДИН mutation proof в единицу времени.

ЗАЧЕМ. Наборы mutation proof намеренно портят одни и те же файлы репозитория
(`server.py`, `app/*.py`, `web/app.js`) и восстанавливают их из своей копии в
памяти. Если два таких набора идут одновременно, откат одного затирает откат
другого, и в рабочем дереве ОСТАЁТСЯ чужая мутация. Это уже происходило: во
время Alpha 2.841 параллельный запуск оставил в `app/klipper_contract_probe.py`
порчу `mesh_fingerprint` (пустой profile_name), из-за чего полный gate дал
четыре ложно-красных набора, а рабочее дерево пришлось чинить руками.

КОНТРАКТ.
  * захват — атомарное создание файла (O_CREAT|O_EXCL) во временной папке;
  * ожидание ОГРАНИЧЕНО: не дождались за `wait` секунд → `mutation_lock_busy`
    и КРАСНЫЙ выход, а не тихое начало правки файлов;
  * замок снимается в `finally`/`atexit` и переживает исключение;
  * замок с мёртвым владельцем (процесса нет) забирается принудительно —
    иначе аварийно убитый прогон блокировал бы весь gate навсегда;
  * замок НЕ защищает от правок человеком: он только сериализует наборы.

Использование в наборе (три строки, до первой записи в файлы):

    from _mutation_lock import acquire_or_die
    acquire_or_die("test_layout_topbar_mutation_proof")
"""
import atexit
import errno
import io
import os
import signal
import sys
import tempfile
import time

LOCK_PATH = os.path.join(tempfile.gettempdir(), "fm-mutation-proof.lock")
DEFAULT_WAIT = 900.0          # соизмеримо с самым долгим набором (browser-gate ~640 c)
_HELD = [False]


def _pid_alive(pid):
    """Жив ли процесс с таким PID. Неизвестно → считаем ЖИВЫМ (не отбираем замок зря)."""
    try:
        pid = int(pid)
    except Exception:
        return True
    if pid <= 0:
        return True
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFO
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259                        # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_owner():
    try:
        return io.open(LOCK_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _try_take(owner):
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as e:
        if e.errno in (errno.EEXIST,):
            return False
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("%d %s %s" % (os.getpid(), owner, time.strftime("%Y-%m-%d %H:%M:%S")))
    return True


def release():
    """Снять замок, если он наш. Никогда не бросает."""
    if not _HELD[0]:
        return
    try:
        if str(os.getpid()) == _read_owner().split(" ", 1)[0]:
            os.remove(LOCK_PATH)
    except Exception:
        pass
    _HELD[0] = False


_GUARDED = {}


def _restore_guarded():
    """Вернуть все взятые под охрану файлы к исходным байтам. Никогда не бросает."""
    for p, b in _GUARDED.items():
        try:
            if io.open(p, "rb").read() != b:
                io.open(p, "wb").write(b)
        except Exception:
            try:
                io.open(p, "wb").write(b)
            except Exception:
                pass


def guard_files(*paths):
    """Взять файлы под охрану: снимок байтов + восстановление при ЛЮБОМ завершении.

    ЗАЧЕМ ОТДЕЛЬНО ОТ `finally`. Блок finally не отрабатывает, если процесс убит извне
    (тайм-аут раннера, закрытие окна, kill). Ровно так во время Alpha 2.841 в рабочем дереве
    осталась мутация `web/app.js`: набор был убит по лимиту, откат не состоялся. atexit плюс
    обработчики сигналов закрывают штатное завершение, исключение и SIGINT/SIGTERM/SIGBREAK.
    Мгновенное SIGKILL/TerminateProcess не переживает ничто — на этот случай остаётся сверка
    SHA-256 в самом наборе и чистое дерево как условие зелёного релиза.
    """
    first = not _GUARDED
    for p in paths:
        if p and p not in _GUARDED:
            try:
                _GUARDED[p] = io.open(p, "rb").read()
            except Exception:
                pass
    if first and _GUARDED:
        atexit.register(_restore_guarded)
        for _sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
            _s = getattr(signal, _sig, None)
            if _s is None:
                continue
            try:
                signal.signal(_s, lambda *a: (_restore_guarded(), release(), sys.exit(1)))
            except Exception:
                pass


def acquire_or_die(owner, wait=DEFAULT_WAIT, poll=1.0):
    """Захватить замок или выйти КРАСНЫМ с `mutation_lock_busy`. → None."""
    t0 = time.monotonic()
    while True:
        if _try_take(owner):
            _HELD[0] = True
            atexit.register(release)
            return
        info = _read_owner()
        pid = info.split(" ", 1)[0] if info else ""
        if info and not _pid_alive(pid):
            # Владелец умер, не сняв замок: забираем принудительно, иначе gate встанет навсегда.
            try:
                os.remove(LOCK_PATH)
            except Exception:
                pass
            continue
        if time.monotonic() - t0 > wait:
            print("mutation_lock_busy: замок занят (%s) дольше %.0f c — набор НЕ начинает "
                  "портить файлы. Параллельный запуск mutation proof запрещён." % (info, wait))
            sys.stdout.flush()
            raise SystemExit(3)
        time.sleep(poll)
