# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — защита от повторного запуска (одиночный экземпляр).

САМОСТОЯТЕЛЬНЫЙ модуль: ТОЛЬКО стандартная библиотека. НЕ импортирует server.py,
FastAPI, SQLite, MQTT, uvicorn и любые другие подсистемы приложения — потому что
вызывается САМЫМ РАННИМ шагом старта: ДО вычисления DATA_DIR, до _resolve_db(),
до открытия SQLite, до _backup_dbs(), до файлового журнала, до создания рабочих
папок, до чистки thumb_cache, до init_db(), до загрузки модулей и recovery.

ЗАЧЕМ (Alpha 2.770). Раньше второй запуск программы успевал выполнить ВСЮ стартовую
уборку по ЖИВОЙ базе уже работающей копии (DELETE FROM active_jobs, жёсткое удаление
сирот, VACUUM, сброс очереди запусков, инвалидация «стол очищен») — и только ПОСЛЕ
этого убивал первую копию через taskkill /F. Отсюда испорченные и «зависшие» записи.
Теперь второй запуск не открывает вообще ничего и не трогает чужой процесс.

ПОЧЕМУ named mutex, а не lock-файл в DATA_DIR: вычисление DATA_DIR само по себе уже
создаёт папки и может запустить перенос данных — то есть это СЛИШКОМ ПОЗДНО. Системный
mutex не требует ни одного пути на диске и снимается ядром Windows автоматически при
любом завершении процесса, включая аварийное (тогда следующий ждущий получает
WAIT_ABANDONED и становится владельцем — залипшего замка не остаётся).

Пространство имён `Local\\` — это один mutex на пользовательскую Windows-сессию:
разные пользователи в разных сессиях (RDP, быстрое переключение) друг другу не мешают.
"""

import sys
import threading

# Стабильное имя замка. Менять НЕЛЬЗЯ без необходимости: при смене имени старая и новая
# сборки перестанут видеть друг друга и смогут запуститься одновременно.
MUTEX_NAME = r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"

# Сколько ждать освобождения замка при ШТАТНОМ перезапуске кнопкой (см. _restart_self
# в server.py). Ограниченный таймаут обязателен: бесконечное ожидание повесило бы старт.
RESTART_WAIT_SECONDS = 30.0

# --- Возможные исходы -------------------------------------------------------
ACQUIRED = "acquired"                 # замок наш — можно продолжать запуск
ALREADY_RUNNING = "already_running"   # программа уже запущена — второй копии не быть
POOL_WORKER = "pool_worker"           # дочерний процесс пула разбора файлов — guard неприменим
UNSUPPORTED = "unsupported"           # не Windows или WinAPI недоступен — fail-open
WAIT_TIMEOUT = "wait_timeout"         # штатный перезапуск не дождался прежней копии

# --- Коды WinAPI ------------------------------------------------------------
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080   # прежний владелец умер, не отпустив замок → владение переходит к нам
_WAIT_TIMEOUT = 0x00000102

_lock = threading.Lock()
_handle = None    # ХЭНДЛ держим до конца процесса: закрыть его = отдать замок другим
_result = None    # кэш исхода — повторный вызов acquire() идемпотентен


class Result(object):
    """Исход попытки занять замок: статус + человекочитаемая деталь."""

    __slots__ = ("status", "detail")

    def __init__(self, status, detail=""):
        self.status = status
        self.detail = detail

    @property
    def ok(self):
        """Можно ли продолжать запуск: замок наш либо защита неприменима."""
        return self.status in (ACQUIRED, POOL_WORKER, UNSUPPORTED)

    def __repr__(self):
        return "Result(status=%r, detail=%r)" % (self.status, self.detail)


def _is_windows():
    """Работаем ли мы на Windows (named mutex — механизм Windows)."""
    return sys.platform.startswith("win")


def acquire(is_pool_worker=False, wait_seconds=0.0, mutex_name=MUTEX_NAME):
    """Занять замок одиночного экземпляра.

    is_pool_worker — дочерний процесс пула разбора файлов (multiprocessing при spawn
      ПЕРЕИСПОЛНЯЕТ главный модуль). Такому процессу замок брать нельзя: он всегда занят
      родителем, и пул встал бы намертво. Для него guard просто пропускается.
    wait_seconds — сколько ждать освобождения (>0 только для ШТАТНОГО перезапуска кнопкой).
      0 — обычный запуск: не ждём ни секунды, сразу сообщаем «уже запущено».
    mutex_name — переопределяется ТОЛЬКО тестами, чтобы не пересечься с рабочей копией.

    Повторный вызов в том же процессе возвращает тот же самый Result (идемпотентность).
    """
    global _handle, _result
    with _lock:
        if _result is not None:
            return _result

        if is_pool_worker:
            _result = Result(POOL_WORKER, "multiprocessing worker: guard skipped")
            return _result

        if not _is_windows():
            # На не-Windows защиты нет — но импорт и старт ломать нельзя (fail-open).
            _result = Result(UNSUPPORTED, "named mutex is Windows-only")
            return _result

        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateMutexW.restype = wintypes.HANDLE
            k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            k32.WaitForSingleObject.restype = wintypes.DWORD
            k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]

            # bInitialOwner=False + WaitForSingleObject: так корректно обрабатывается
            # «брошенный» замок после аварийного завершения прежней копии.
            h = k32.CreateMutexW(None, False, mutex_name)
            if not h:
                _result = Result(UNSUPPORTED, "CreateMutexW failed (err=%d)" % ctypes.get_last_error())
                return _result

            ms = 0 if (wait_seconds or 0) <= 0 else int(float(wait_seconds) * 1000)
            rc = int(k32.WaitForSingleObject(h, ms))

            if rc in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                _handle = h   # НЕ закрываем: владение живёт до завершения процесса
                _result = Result(ACQUIRED, "previous owner terminated abnormally" if rc == _WAIT_ABANDONED else "")
                return _result

            try:
                k32.CloseHandle(h)   # замок не наш — отпускаем свою ссылку на объект
            except Exception:
                pass

            if rc == _WAIT_TIMEOUT and ms > 0:
                _result = Result(WAIT_TIMEOUT, "previous instance still running after %.1fs" % float(wait_seconds))
            elif rc == _WAIT_TIMEOUT:
                _result = Result(ALREADY_RUNNING, "another instance owns the mutex")
            else:
                _result = Result(UNSUPPORTED, "WaitForSingleObject returned 0x%X" % rc)
            return _result
        except Exception as e:
            # Любой сбой WinAPI не должен мешать программе стартовать (fail-open):
            # хуже отсутствия защиты только незапускающаяся ферма.
            _result = Result(UNSUPPORTED, "guard unavailable: %s" % (e,))
            return _result


def message_box(title, text):
    """Показать модальное окно Windows (MessageBoxW). True — окно показано.

    Нужно для СОБРАННОГО .exe: там консоль прячется в трей, и обычный print()
    пользователь просто не увидит. На не-Windows и при любой ошибке — тихо False.
    """
    if not _is_windows():
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.MessageBoxW.restype = ctypes.c_int
        u32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        MB_OK = 0x00000000
        MB_ICONINFORMATION = 0x00000040
        MB_SETFOREGROUND = 0x00010000
        MB_TOPMOST = 0x00040000
        u32.MessageBoxW(None, str(text), str(title),
                        MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST)
        return True
    except Exception:
        return False


def _reset_for_tests():
    """ТОЛЬКО ДЛЯ ТЕСТОВ: отпустить замок и забыть исход, чтобы проверить другую ветку.

    В рабочем пути не вызывается никогда — отпускать замок живого сервера нельзя.
    """
    global _handle, _result
    with _lock:
        h, _handle, _result = _handle, None, None
        if h and _is_windows():
            try:
                import ctypes
                from ctypes import wintypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                try:
                    k32.ReleaseMutex(h)
                except Exception:
                    pass
                k32.CloseHandle(h)
            except Exception:
                pass
