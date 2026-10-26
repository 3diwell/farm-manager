# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — служебные CLI-режимы перезапуска (Alpha 2.810).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк, СУБД,
принтерные подсистемы; не берёт замок одиночного экземпляра, не открывает БД, не слушает порты
и не трогает DATA_DIR (пишет ТОЛЬКО туда, куда указывает путь журнала, переданный аргументом).

ЗАЧЕМ (реальный отказ Alpha 2.809, доказан воспроизведением).
Кнопка перезапуска создавала helper-процесс БЕЗ std-handles (DETACHED, без перенаправления).
У такого процесса sys.stdout is None, и module-level код server.py
(`sys.stdout.reconfigure(...)` с обработчиком, зовущим ещё не определённые `log`/`_exc_brief`)
падал с NameError ВО ВРЕМЯ ИМПОРТА — за ~1 секунду, до ветки supervisor, до единственной
записи в журнал. Родитель честно ждал 20 секунд и отменял перезапуск: «helper не подтвердил
готовность». Журнал застывал на стадии planning без attempts и без причины.

ЧТО ИЗМЕНЕНО В СХЕМЕ (Alpha 2.810).
  1. Служебные режимы обрабатываются САМОЙ РАННЕЙ веткой server.py — до тяжёлых импортов,
     до настройки логов, до замка, DATA_DIR, БД, модулей, трея, порта и опроса принтеров.
  2. Вся логика режимов живёт здесь: server.py лишь передаёт argv.
  3. Каждый helper-процесс ГАРАНТИРОВАННО оставляет вердикт: armed (и дальше по журналу)
     либо failed с безопасной причиной; при невозможности писать в журнал — строку в
     ограниченном helper-логе рядом с журналом. Немых путей выхода больше нет.
  4. Все создаваемые процессы (helper и преемник) получают DEVNULL вместо отсутствующих
     std-handles: sys.stdout у них никогда не None.
  5. Отдельный self-test (--fm-restart-supervisor-selftest) проверяет handshake НАСТОЯЩЕГО
     собранного EXE во временной папке: без backend, без замка, без БД, без bind порта.

Секретов здесь нет: ни токенов, ни cookies, ни паролей; в лог не пишутся пути, команды,
окружение и адреса — только стадии, безопасные коды и укороченный restart ID.
"""

import json
import os
import sys
import tempfile
import time

from app import restart_supervisor as rsup

# ── Константы процесса ────────────────────────────────────────────────────────────────────────
# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: самостоятельный процесс без консоли, не
# привязанный к жизни родителя. Обязательная пара к нему — DEVNULL на всех std-handles
# (см. spawn_detached): именно отсутствие handles валило helper Alpha 2.809.
DETACHED_FLAGS = 0x00000008 | 0x00000200

# Ограниченный лог helper'а рядом с журналом. Больше лимита — файл начинается заново:
# это диагностический след последних попыток, а не архив.
HELPER_LOG_NAME = "restart-helper.log"
HELPER_LOG_LIMIT = 64 * 1024

# Exit-коды helper'а (машиночитаемые). 0 — вердикт оставлен в журнале (успех ИЛИ отказ);
# 2 — журнал не наш/недоступен, вердикт оставлен только в helper-логе.
EXIT_VERDICT_WRITTEN = 0
EXIT_NO_JOURNAL = 2

_STILL_ACTIVE = 259
_ERR_ACCESS_DENIED = 5
_ERR_INVALID_PARAMETER = 87


def short_rid(rid):
    """Укороченный restart ID для лога (полный не нужен и не пишется)."""
    r = str(rid or "")
    return r[:12] if r else "-"


def helper_log_path(journal_path):
    """Путь helper-лога — в ТОЙ ЖЕ стабильной папке, что и журнал (не в _MEI и не в temp)."""
    return os.path.join(os.path.dirname(os.path.abspath(str(journal_path))), HELPER_LOG_NAME)


def hlog(journal_path, rid, message):
    """Строка в ограниченный helper-лог. Ошибка записи никогда не роняет helper."""
    try:
        p = helper_log_path(journal_path)
        try:
            if os.path.getsize(p) > HELPER_LOG_LIMIT:
                with open(p, "w", encoding="utf-8") as f:
                    f.write("")  # лимит: начинаем файл заново
        except OSError:
            pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s pid=%d rid=%s %s\n" % (ts, os.getpid(), short_rid(rid), str(message)))
    except Exception:
        pass


def pid_alive(pid):
    """Жив ли процесс с этим PID — ТОЛЬКО вопрос системе (ctypes, без подпроцессов).

    OpenProcess с минимальным правом; STILL_ACTIVE => жив. ACCESS_DENIED означает
    «процесс существует, но чужой» => жив. Неоднозначность трактуем как «жив»
    (fail-closed: подождать лишнюю секунду дешевле, чем начать при живом прежнем)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            err = ctypes.get_last_error()
            if err == _ERR_ACCESS_DENIED:
                return True          # существует, но доступа нет
            if err == _ERR_INVALID_PARAMETER:
                return False         # такого PID нет
            return True              # неясность = считаем живым (fail-closed)
        try:
            k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            code = ctypes.c_uint32(0)
            if not k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return True
            return int(code.value) == _STILL_ACTIVE
        finally:
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return False


# ── 🔒 Alpha 2.811, ROOT CAUSE ОТКАЗА 2.810. ──────────────────────────────────────────────────
# Собранная onefile-программа распаковывает себя во временную папку и сообщает об этом ДОЧЕРНИМ
# процессам через переменные окружения. Если из собранной программы запустить копию ТОГО ЖЕ
# .exe, её загрузчик видит «архив уже распакован» и НЕ распаковывается заново — он берёт файлы
# из папки, указанной в окружении. Пока родитель жив, это работает (именно поэтому helper 2.810
# успешно вооружался). Но преемник запускается ПОСЛЕ штатного завершения родителя, а уходящий
# родитель свою папку распаковки удаляет — и преемник умирает внутри загрузчика, не выполнив ни
# строки Python. В журнале это выглядело как `successor_exited` (две попытки), а у пользователя
# программа исчезала целиком: ни сервера, ни значка в трее.
# Проверено экспериментом на собранном .exe: с унаследованными переменными процесс завершается
# кодом 0xFFFFFFFF, с очищенными — стартует нормально.
# ПОЭТОМУ: любой запускаемый нами процесс получает окружение БЕЗ этих переменных и распаковывает
# себя сам. Точка ровно одна — эта функция.
_PYI_ENV_PREFIXES = ("_PYI", "_MEIPASS", "PYINSTALLER_")


def clean_child_env(environ=None):
    """Окружение для дочернего процесса: без служебных переменных распаковщика onefile.

    Всё остальное сохраняется без изменений — программа должна стартовать в тех же условиях,
    что и обычно (переменные пользователя, PATH, параметры изолированного теста)."""
    src = os.environ if environ is None else environ
    return {k: v for k, v in dict(src).items()
            if not str(k).upper().startswith(_PYI_ENV_PREFIXES)}


def spawn_detached(command, workdir=None, env=None):
    """ЕДИНАЯ точка запуска служебных процессов перезапуска (helper и преемник).

    Список аргументов, shell=False, DETACHED + новая группа, ОБЯЗАТЕЛЬНО DEVNULL на всех
    std-handles (у DETACHED-процесса без handles sys.stdout = None — это убивало helper 2.809)
    и ОБЯЗАТЕЛЬНО очищенное от переменных распаковщика окружение (это убивало преемника 2.810).
    -> Popen | None."""
    import subprocess
    try:
        return subprocess.Popen(
            list(command), cwd=(workdir or None), close_fds=True,
            env=clean_child_env(env),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=DETACHED_FLAGS)
    except Exception:
        return None


# ── Реальные пробы supervisor'а (в тестах подменяются целиком) ────────────────────────────────
def _real_port_in_use(port):
    """Занят ли порт: пробный bind. Вызывается ТОЛЬКО после ухода прежнего сервера."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", int(port)))
            return False
        finally:
            s.close()
    except Exception:
        return True


def _real_lock_free(mutex_name=None):
    """Свободен ли замок одиночного экземпляра — ТОЛЬКО проверка существования объекта.

    Брать замок здесь категорически нельзя: single_instance.acquire держит handle до конца
    процесса, и helper, взяв замок, навсегда закрыл бы дорогу преемнику. OpenMutexW не даёт
    владения и ничего не создаёт. При любой неясности считаем занятым (fail-closed).

    Alpha 2.811: имя замка приходит из плана. У изолированного тестового экземпляра он свой,
    иначе helper теста ждал бы освобождения замка рабочей копии — то есть вечно."""
    try:
        import ctypes
        from app import single_instance as _si
        name = str(mutex_name or "") or _si.MUTEX_NAME
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = ctypes.c_void_p
        k32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        h = k32.OpenMutexW(0x00100000, False, name)   # SYNCHRONIZE
        if not h:
            return True                  # объекта нет — прежняя копия ушла
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle(ctypes.c_void_p(h))
        return False
    except Exception:
        return False


def _real_http_version(port):
    """Версия ответившего сервера на порту или None."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/version" % int(port), timeout=3) as r:
            return str((json.loads(r.read().decode("utf-8")) or {}).get("version") or "")
    except Exception:
        return None


def _real_data_move_active(journal_path):
    """Идёт ли перенос папки данных: свежая отметка переноса рядом с журналом перезапуска.

    Журнал лежит в папке данных уходящей копии, а преемник переносит именно из неё — туда же
    он и пишет отметку (app/data_dir_items.MOVE_MARKER). Любая неясность — «не идёт»: тогда
    helper ведёт себя как раньше."""
    try:
        if not journal_path:
            return False
        from app import data_dir_items as _ddi
        return _ddi.move_in_progress(os.path.dirname(os.path.abspath(str(journal_path))))
    except Exception:
        return False


def _with_data_move(probes, journal_path):
    """Добавить к пробам слежение за переносом папки данных рядом с журналом journal_path."""
    probes.data_move_active = lambda: _real_data_move_active(journal_path)
    return probes


def build_probes(mutex_name=None):
    """Пробы для НАСТОЯЩЕГО запуска helper'а."""
    return rsup.Probes(
        pid_alive=pid_alive,
        port_in_use=_real_port_in_use,
        lock_free=(lambda: _real_lock_free(mutex_name)),
        http_version=_real_http_version,
        spawn=spawn_detached,
        now=time.monotonic,
        sleep=time.sleep,
        process_alive=lambda h: (h is not None and h.poll() is None),
        wall=time.time)


# ── Режим HELPER ──────────────────────────────────────────────────────────────────────────────
def run_helper(argv, probes=None, wall=None):
    """Основной путь helper'а. -> exit code.

    ГАРАНТИЯ: ни один путь выхода не остаётся немым. Либо в журнале стоит вердикт
    (armed → ... → ready | failed + причина), либо (журнал не наш/недоступен) причина
    остаётся в helper-логе, а exit code отличим от успешного."""
    wall = wall or time.time
    jp = rsup.parse_supervisor_argv(argv)
    rid_arg = rsup.parse_supervisor_rid(argv)
    if not jp:
        return EXIT_NO_JOURNAL                     # нечем даже логировать: пути журнала нет
    hlog(jp, rid_arg, "helper start")
    plan = rsup.read_journal(jp)
    if not isinstance(plan, dict):
        hlog(jp, rid_arg, "verdict=no-journal code=%s" % rsup.ERR_JOURNAL_INVALID)
        return EXIT_NO_JOURNAL
    if rid_arg and str(plan.get("restart_id") or "") != rid_arg:
        # Журнал принадлежит ДРУГОМУ перезапуску: писать в него нельзя ничего.
        hlog(jp, rid_arg, "verdict=foreign-journal code=%s" % rsup.ERR_RID_MISMATCH)
        return EXIT_NO_JOURNAL
    rid = str(plan.get("restart_id") or "")
    if not rid_arg:
        hlog(jp, rid, "rid arg missing (journal rid used)")

    def _fail(code):
        try:
            rsup.set_stage(jp, plan, rsup.STAGE_FAILED, code, now=wall())
        except Exception:
            pass
        hlog(jp, rid, "verdict=failed code=%s" % code)
        return EXIT_VERDICT_WRITTEN

    try:
        if rsup.is_stale_journal(plan, now=wall()):
            return _fail(rsup.ERR_STALE_PLAN)      # старый план ничего не запускает
        ok, why = rsup.preflight(plan)
        hlog(jp, rid, "plan validation: %s" % ("ok" if ok else why))
        if not ok:
            return _fail(why)
        # Подтверждение готовности: атомарная запись armed со СВОИМ PID и свежим временем.
        # Только после неё parent имеет право начать штатное завершение.
        plan["helper_pid"] = os.getpid()
        plan = rsup.set_stage(jp, plan, rsup.STAGE_ARMED, "", now=wall())
        hlog(jp, rid, "armed helper_pid=%d" % os.getpid())
        ok, why = rsup.run_supervisor(
            plan, probes or _with_data_move(build_probes(plan.get("mutex_name")), jp), journal_path=jp)
        hlog(jp, rid, "finished ok=%s code=%s" % (ok, why or "-"))
        return EXIT_VERDICT_WRITTEN
    except Exception as e:
        # Немых падений helper'а не бывает: последний рубеж оставляет вердикт и строку в логе.
        # Перезаписывать READY нельзя (перезапуск уже удался); всё остальное честно помечается.
        hlog(jp, rid, "crash %s" % type(e).__name__)
        try:
            cur = rsup.read_journal(jp)
            if isinstance(cur, dict) and str(cur.get("restart_id") or "") == rid \
                    and cur.get("stage") != rsup.STAGE_READY:
                rsup.set_stage(jp, cur, rsup.STAGE_FAILED, rsup.ERR_HELPER_CRASH, now=wall())
        except Exception:
            pass
        return EXIT_VERDICT_WRITTEN


# ── Режим SELF-TEST (только локальный CLI; НЕ HTTP-маршрут) ───────────────────────────────────
SELFTEST_ARMED_TIMEOUT = 90.0      # холодный старт onefile EXE укладывается с запасом
SELFTEST_VERDICT_TIMEOUT = 60.0    # ожидание вердикта отказа после armed
SELFTEST_PARENT_EXIT_TIMEOUT = 3.0  # маленький таймаут ветки ожидания parent в плане self-test


def run_selftest(argv, spawn=None, emit=None):
    """Self-test handshake настоящего исполняемого файла. -> exit code (0 = пройден).

    Что делает: во ВРЕМЕННОЙ папке создаётся план с живым parent'ом (сам self-test-процесс)
    и малым таймаутом ожидания его ухода; запускается НАСТОЯЩИЙ helper тем же исполняемым
    файлом; проверяется, что helper подтвердил armed (правильный restart ID, свой PID,
    свежая отметка), затем — что он оставил честный вердикт отказа parent_still_running и
    завершился, НЕ запустив преемника. Backend не стартует, замок не берётся, БД не
    открывается, порт не bind'ится (ветка порта в этом сценарии недостижима).

    Печатает одну JSON-строку отчёта (если stdout существует) и возвращает exit code."""
    spawn = spawn or spawn_detached
    out = {"ok": False, "mode": "packaged" if getattr(sys, "frozen", False) else "source",
           "stages_seen": [], "reason": ""}

    def _report(code):
        try:
            if emit:
                emit(json.dumps(out, ensure_ascii=False))
            elif sys.stdout is not None:
                print(json.dumps(out, ensure_ascii=False))
        except Exception:
            pass
        return code

    try:
        import secrets
        rid = "selftest_" + secrets.token_hex(8)
    except Exception:
        rid = "selftest_%d_%d" % (os.getpid(), int(time.time()))

    frozen = bool(getattr(sys, "frozen", False))
    script = None if frozen else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")
    with tempfile.TemporaryDirectory(prefix="fm_restart_selftest_") as td:
        jp = os.path.join(td, "restart-selftest.json")
        # Временная папка self-test'а не должна жить внутри распаковки onefile (_MEI...):
        # она исчезает вместе с процессом, а журнал должен переживать helper.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.realpath(td).startswith(os.path.realpath(meipass)):
            out["reason"] = "tempdir_inside_meipass"
            return _report(1)
        plan = rsup.build_plan(
            frozen=frozen, executable=sys.executable, script=script,
            argv=["--no-browser"], workdir=os.path.dirname(os.path.abspath(sys.executable)),
            port=int(os.environ.get("FM_SELFTEST_PORT") or 8000),  # ветка порта недостижима: parent жив
            version="Alpha selftest", pid=os.getpid(),
            restart_id=rid, journal_path=jp)
        plan["requested_at"] = time.time()
        plan["updated_at"] = time.time()
        # Малый таймаут ожидания ухода parent: parent (этот процесс) ЖИВ до конца self-test,
        # поэтому helper обязан честно отказаться кодом parent_still_running за секунды.
        plan["timeouts"] = {"parent_exit": SELFTEST_PARENT_EXIT_TIMEOUT}
        rsup.write_journal(jp, plan)

        cmd = rsup.supervisor_command(frozen, sys.executable, script, jp, restart_id=rid)
        h = spawn(cmd, os.path.dirname(jp))
        if h is None:
            out["reason"] = "helper_spawn_failed"
            return _report(1)

        deadline = time.monotonic() + SELFTEST_ARMED_TIMEOUT
        armed_seen = False
        helper_pid = 0
        while time.monotonic() < deadline:
            cur = rsup.read_journal(jp) or {}
            st = cur.get("stage") or ""
            if st and (not out["stages_seen"] or out["stages_seen"][-1] != st):
                out["stages_seen"].append(st)
            state, _code = rsup.verify_armed(cur, rid, pid_alive, time.time())
            if state == "armed":
                armed_seen = True
                helper_pid = int(cur.get("helper_pid") or 0)
                break
            if state == "failed":
                break                     # отказ ДО armed — провал self-test, причина в reason
            time.sleep(0.2)
        out["armed"] = armed_seen
        out["helper_pid_seen"] = bool(helper_pid)
        if not armed_seen:
            cur = rsup.read_journal(jp) or {}
            out["reason"] = str(cur.get("error") or "armed_timeout")
            return _report(1)

        # Дальше helper обязан отказаться (parent жив) и завершиться — с вердиктом.
        deadline = time.monotonic() + SELFTEST_VERDICT_TIMEOUT
        final = {}
        while time.monotonic() < deadline:
            cur = rsup.read_journal(jp) or {}
            st = cur.get("stage") or ""
            if st and (not out["stages_seen"] or out["stages_seen"][-1] != st):
                out["stages_seen"].append(st)
            if st == rsup.STAGE_FAILED:
                final = cur
                break
            time.sleep(0.2)
        out["verdict_error"] = str(final.get("error") or "")
        if final.get("error") != rsup.ERR_PARENT_ALIVE:
            out["reason"] = "expected_parent_still_running"
            return _report(1)
        if int(final.get("attempts") or 0) != 0 or rsup.STAGE_LAUNCHING in out["stages_seen"]:
            out["reason"] = "successor_was_launched"   # преемник в self-test запрещён
            return _report(1)
        # Дождаться выхода helper-процесса (bounded), чтобы не оставить его за собой.
        # Живость определяется по handle процесса (poll), а PID из журнала — запасной путь:
        # для реального onefile-EXE handle принадлежит bootloader-родителю и завершается
        # вместе с настоящим helper'ом.
        def _helper_alive():
            try:
                if hasattr(h, "poll"):
                    return h.poll() is None
            except Exception:
                pass
            return pid_alive(helper_pid)

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and _helper_alive():
            time.sleep(0.2)
        out["helper_exited"] = not _helper_alive()
        if not out["helper_exited"]:
            out["reason"] = "helper_still_running"
            return _report(1)
        out["ok"] = True
    # TemporaryDirectory убрал временные артефакты вместе с журналом self-test'а.
    return _report(0)


def main(argv):
    """Диспетчер служебных режимов. Возвращает exit code; обычный старт сервера сюда не попадает."""
    args = list(argv or [])
    if rsup.SELFTEST_FLAG in args:
        return run_selftest(args)
    if rsup.SUPERVISOR_FLAG in args:
        return run_helper(args)
    return EXIT_NO_JOURNAL
