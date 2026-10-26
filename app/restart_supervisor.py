# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — надёжный перезапуск программы (Alpha 2.809).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк, СУБД и
принтерные подсистемы; не открывает БД, не слушает порты, не трогает DATA_DIR и не содержит
бизнес-логики. Все внешние действия (существование файла, живость процесса, занятость порта,
опрос /version, создание процесса) приходят СНАРУЖИ отдельными пробами, поэтому весь сценарий
перезапуска проверяется offline без единого реального процесса.

ЗАЧЕМ (реальный отказ, Alpha 2.808).
Пользователь установил модули и нажал кнопку перезапуска. Прежний процесс завершился, новый
не запустился, интерфейс не вернулся — пришлось запускать программу руками. По журналу фермы
видно ровно это: последняя строка старого процесса, затем 34 секунды тишины, затем запись уже
запущенного вручную процесса. Ни строки об ошибке, ни следа преемника.

Причина не в одной строке кода, а в самой схеме: прежний `_restart_self` создавал процесс
«вслепую» и НЕМЕДЛЕННО завершал себя (`os._exit(0)`), считая сам факт вызова Popen
доказательством успеха. При этом каждый путь раннего выхода преемника молчал: он ждёт
освобождения замка одиночного экземпляра и порта с ограниченным таймаутом, а сообщения об
отказе печатает в консоль, которой у собранного GUI-приложения нет (backend запускается
оболочкой как DETACHED-процесс). В результате сбой преемника был невидим — и невосстановим:
старого сервера уже не существовало.

КОНТРАКТ Alpha 2.809, обратный по порядку:
    1. Сначала строится план и проверяется выполнимость (preflight).
    2. Запускается независимый supervisor.
    3. Supervisor подтверждает готовность (`armed`) через журнал.
    4. И ТОЛЬКО ПОСЛЕ подтверждения старый backend завершает работу.
Если подтверждения нет — перезапуск отменяется, а Farm Manager продолжает работать. Потерять
работающий сервер из-за неудачной подготовки перезапуска нельзя.

ЧТО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ.
  * Не считает создание процесса доказательством перезапуска: успех — только подтверждённый
    ответ `/version` ожидаемой программы на ожидаемом порту.
  * Не выбирает порт сам и не меняет конфигурацию.
  * Не убивает процессы: старый backend завершается штатно сам.
  * Не хранит секретов: ни токенов, ни cookies, ни паролей, ни строк подключения.
"""

import json
import os
import re
import tempfile

# ── Стадии перезапуска. Стабильные машинные коды для журнала и диагностики. ────────────────────
STAGE_PLANNING = "planning"
STAGE_ARMED = "armed"
STAGE_WAITING_PARENT = "waiting_parent"
STAGE_LAUNCHING = "launching"
STAGE_PROBING = "probing"
STAGE_READY = "ready"
STAGE_FAILED = "failed"

STAGES = (STAGE_PLANNING, STAGE_ARMED, STAGE_WAITING_PARENT, STAGE_LAUNCHING,
          STAGE_PROBING, STAGE_READY, STAGE_FAILED)

# ── Безопасные коды причин отказа. Пользователю показывается текст, подобранный интерфейсом;
#    ни путей, ни traceback, ни командной строки эти коды не содержат.
ERR_NO_EXECUTABLE = "executable_missing"
ERR_NO_ENTRY = "entry_missing"
ERR_NO_WORKDIR = "workdir_missing"
ERR_BAD_COMMAND = "command_rejected"
ERR_WRONG_EXECUTABLE = "wrong_executable"
ERR_SPAWN_FAILED = "spawn_failed"
ERR_PARENT_ALIVE = "parent_still_running"
ERR_PORT_BUSY = "port_still_busy"
ERR_LOCK_BUSY = "instance_lock_busy"
ERR_SUCCESSOR_EXITED = "successor_exited"
ERR_NOT_READY = "not_ready"
ERR_FOREIGN_SERVER = "foreign_server"
# Alpha 2.810: причины, которые оставляет сам helper (раньше эти пути были немыми).
ERR_JOURNAL_INVALID = "journal_invalid"      # журнал не читается или не наш schema
ERR_RID_MISMATCH = "restart_id_mismatch"     # журнал принадлежит ДРУГОМУ перезапуску
ERR_STALE_PLAN = "stale_plan"                # план слишком старый, выполнять нельзя
ERR_HELPER_CRASH = "helper_crashed"          # неожиданное исключение внутри helper

# Alpha 2.811: диагностика со стороны РОДИТЕЛЯ. Раньше любой отказ подтверждения выглядел
# одинаково («не подтвердил готовность»), хотя причины разные и лечатся по-разному.
ERR_HELPER_NOT_STARTED = "helper_not_started"          # процесс создать не удалось вовсе
ERR_HELPER_NO_VERDICT = "helper_no_verdict"            # процесс жил и умер, не записав вердикта
ERR_HELPER_EXITED_BEFORE_ARM = "helper_exited_before_arm"   # умер до подтверждения готовности
ERR_READINESS_TIMEOUT = "readiness_timeout"            # преемник жив, но не ответил вовремя
ERR_SUCCESSOR_WRONG_PORT = "successor_wrong_port"      # ответ пришёл не на ожидаемом порту

SCHEMA_VERSION = 1

MODE_PACKAGED = "packaged"
MODE_SOURCE = "source"

# Аргумент, включающий режим supervisor в ТОМ ЖЕ исполняемом файле. Отдельный артефакт сборки
# не заводим намеренно: раз supervisor — это тот же файл, он гарантированно существует и
# гарантированно той же версии, что и программа.
SUPERVISOR_FLAG = "--fm-restart-supervisor"
# Alpha 2.810: restart ID передаётся helper'у ЯВНО (а не только внутри журнала), чтобы helper
# мог отличить СВОЙ журнал от журнала другого перезапуска и никогда не писал в чужой.
RID_FLAG = "--fm-restart-id"
# Alpha 2.810: локальный self-test собранного EXE — только CLI, НЕ HTTP-маршрут. Проверяет
# handshake (armed) настоящего packaged helper'а во временной папке, не запуская backend,
# не беря замок, не открывая БД и не занимая порт.
SELFTEST_FLAG = "--fm-restart-supervisor-selftest"

# Исполняемые файлы, которые НИКОГДА не являются backend'ом. Оболочка и клиент только открывают
# окно; запуск любого из них вместо сервера дал бы «процесс есть, Farm Manager нет».
_NON_SERVER_EXE = ("desktop.exe", "client.exe", "3diwell farm manager desktop.exe",
                   "3diwell farm manager client.exe")

# Аргументы, которые НЕ переносятся в новый процесс: одноразовые разрешения и служебные флаги
# перезапуска. Одноразовое право на действие не должно «воскресать» вместе с программой.
# "--fm-restart-supervisor" покрывает и self-test флаг (общий префикс); "--fm-restart-id" —
# чтобы restart ID никогда не переезжал в argv преемника.
_TRANSIENT_ARG_PREFIXES = ("--fm-restart-supervisor", "--fm-restart-id", "--allow-print-once",
                           "--arm-", "--one-shot", "--multiprocessing-fork")

# Символы, которые в командной строке могут означать интерпретацию оболочкой. Мы всегда
# запускаем список аргументов с shell=False, но план валидируем отдельно: если такой символ
# оказался в ПУТИ, это признак, что план собран неверно.
_SHELL_META_RE = re.compile(r"[&|<>^\r\n\0]")


def is_server_executable(path):
    """Является ли путь допустимым backend-исполняемым файлом (а не оболочкой/клиентом)."""
    base = os.path.basename(str(path or "")).strip().lower()
    if not base:
        return False
    return base not in _NON_SERVER_EXE


def filter_args(argv):
    """Аргументы, переносимые в новый процесс. Одноразовые и служебные отбрасываются."""
    out = []
    for a in list(argv or []):
        s = str(a)
        low = s.lower()
        if any(low.startswith(p) for p in _TRANSIENT_ARG_PREFIXES):
            continue
        out.append(s)
    return out


def build_plan(frozen, executable, script, argv, workdir, port, version, pid,
               restart_id, journal_path, wait_port=None, ready_ports=None, mutex_name=None):
    """Собрать план перезапуска. Чистая функция: ничего не запускает и не пишет.

    frozen=True  -> собранная программа: преемник запускается ТЕМ ЖЕ серверным .exe.
    frozen=False -> запуск из исходников: преемник — текущий интерпретатор + абсолютный
                    путь к server.py.
    Пути всегда абсолютные: рабочая папка процесса меняться не должна и на выбор
    исполняемого файла влиять не может.
    """
    exe = os.path.abspath(str(executable or ""))
    if frozen:
        mode = MODE_PACKAGED
        command = [exe] + filter_args(argv)
        entry = exe
    else:
        mode = MODE_SOURCE
        entry = os.path.abspath(str(script or ""))
        command = [exe, entry] + filter_args(argv)
    # Alpha 2.811: портов теперь ДВА РАЗНЫХ смысла, и раньше они были склеены в один.
    #   wait_port   — порт, который должна ОСВОБОДИТЬ уходящая копия (всегда текущий активный);
    #   ready_ports — порты, на которых преемник может ОТВЕТИТЬ. При смене порта это [новый,
    #                 прежний]: новый — если переход удался, прежний — если преемник честно
    #                 откатился (bind нового не удался). Прежняя версия ждала ответа только на
    #                 старом порту, поэтому удачная смена порта всё равно считалась провалом.
    _wait = int(wait_port if wait_port is not None else (port or 0))
    _ready = [int(p) for p in (ready_ports or [port or 0]) if p]
    return {
        "schema": SCHEMA_VERSION,
        "restart_id": str(restart_id or ""),
        "mode": mode,
        "executable": exe,
        "entry": entry,
        "command": command,
        "workdir": os.path.abspath(str(workdir or "")),
        "expected_port": int(port or 0),
        "wait_port": _wait,
        "ready_ports": _ready,
        # Имя замка одиночного экземпляра, освобождения которого ждёт supervisor. Обычно это
        # рабочий замок программы; у изолированного тестового экземпляра — его собственный,
        # иначе тест ждал бы освобождения замка ЧУЖОЙ (рабочей) копии.
        "mutex_name": str(mutex_name or ""),
        "expected_version": str(version or ""),
        "parent_pid": int(pid or 0),
        "journal": os.path.abspath(str(journal_path or "")),
        "stage": STAGE_PLANNING,
        "attempts": 0,
        "error": "",
        # PID helper'а. 0 = helper ещё не подтвердил готовность. Заполняется САМИМ helper'ом
        # атомарной записью armed; parent сверяет его с живым процессом перед остановкой.
        "helper_pid": 0,
        # Порт, на котором преемник ФАКТИЧЕСКИ ответил (0 — ещё не отвечал). Нужен, чтобы
        # отличить удачную смену порта от честного отката к прежнему.
        "ready_port": 0,
    }


def preflight(plan, exists=os.path.exists, isdir=os.path.isdir):
    """Проверить выполнимость плана ДО остановки работающего сервера. -> (ok, код причины).

    Здесь и только здесь решается, можно ли вообще начинать перезапуск. Любой отказ означает,
    что старый backend продолжит работать: неудачная подготовка не должна стоить пользователю
    работающей программы."""
    if not isinstance(plan, dict):
        return False, ERR_BAD_COMMAND
    cmd = plan.get("command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
        return False, ERR_BAD_COMMAND
    exe = plan.get("executable") or ""
    if not exe or not exists(exe):
        return False, ERR_NO_EXECUTABLE
    if not is_server_executable(exe if plan.get("mode") == MODE_PACKAGED else plan.get("entry")):
        return False, ERR_WRONG_EXECUTABLE
    entry = plan.get("entry") or ""
    if not entry or not exists(entry):
        return False, ERR_NO_ENTRY
    wd = plan.get("workdir") or ""
    if not wd or not isdir(wd):
        return False, ERR_NO_WORKDIR
    for part in cmd + [wd]:
        if _SHELL_META_RE.search(part):
            return False, ERR_BAD_COMMAND
    if not plan.get("expected_version"):
        return False, ERR_BAD_COMMAND
    if not (0 < int(plan.get("expected_port") or 0) < 65536):
        return False, ERR_BAD_COMMAND
    return True, ""


# ── Журнал перезапуска ────────────────────────────────────────────────────────────────────────
# Небольшой JSON-файл рядом с рабочими данными программы. Нужен ровно для двух вещей: передать
# supervisor'у план и вернуть обратно подтверждение готовности. Секретов не содержит.
_JOURNAL_KEYS = ("schema", "restart_id", "mode", "expected_port", "ready_port",
                 "expected_version", "parent_pid", "helper_pid", "stage", "attempts", "error",
                 "requested_at", "updated_at")


def journal_public(plan):
    """Безопасный срез журнала: без путей, команды и окружения.

    Наружу (в API и интерфейс) уходит только это. Абсолютные пути и командная строка остаются
    внутри файла журнала, потому что нужны supervisor'у, но пользователю их знать незачем."""
    if not isinstance(plan, dict):
        return {}
    return {k: plan.get(k) for k in _JOURNAL_KEYS if k in plan}


def write_journal(path, plan):
    """Атомарная запись журнала: временный файл рядом + os.replace.

    Частично записанный журнал недопустим: supervisor читает его как источник плана, а
    следующий запуск программы — как признак незавершённого перезапуска."""
    path = os.path.abspath(str(path))
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".restart-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise
    return path


def read_journal(path):
    """Прочитать журнал. Битый или отсутствующий журнал -> None (никогда не исключение)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("schema") == SCHEMA_VERSION else None
    except Exception:
        return None


def set_stage(path, plan, stage, error="", now=None):
    """Перевести журнал в новую стадию (атомарно).

    now — НАСТЕННОЕ время (time.time) для отметки свежести записи; None = не менять.
    Свежесть нужна parent'у: подтверждением считается только НЕустаревшая запись armed
    именно этого restart ID (см. verify_armed)."""
    plan = dict(plan or {})
    plan["stage"] = stage if stage in STAGES else STAGE_FAILED
    plan["error"] = str(error or "")
    if now is not None:
        plan["updated_at"] = float(now)
    write_journal(path, plan)
    return plan


def is_stale_journal(plan, now, max_age_seconds=3600):
    """Устаревший журнал (программа была выключена, перезапуск не завершился).

    Такой журнал НЕ должен ничего запускать сам: он только диагностический след. Автоматический
    перезапуск по найденному на диске файлу — это ровно тот класс сюрпризов, которого на
    производственной ферме быть не должно."""
    if not isinstance(plan, dict):
        return True
    try:
        upd = float(plan.get("updated_at") or plan.get("requested_at") or 0)
    except (TypeError, ValueError):
        return True
    return (float(now) - upd) > float(max_age_seconds)


# ── Ожидания ──────────────────────────────────────────────────────────────────────────────────
def wait_until(predicate, timeout, sleep, now):
    """Ограниченное по времени ожидание. -> True, если условие выполнилось.

    Времени и сна модуль не берёт из системы: и то и другое передаётся вызывающим, поэтому
    сценарии ожидания воспроизводятся в тестах мгновенно и детерминированно."""
    deadline = now() + float(timeout)
    while True:
        if predicate():
            return True
        if now() >= deadline:
            return False
        sleep(0.25)


class Probes(object):
    """Внешние действия supervisor'а. В тестах подменяются целиком."""

    def __init__(self, pid_alive, port_in_use, lock_free, http_version, spawn, now, sleep,
                 process_alive=None, wall=None, data_move_active=None):
        self.pid_alive = pid_alive          # (pid) -> bool
        self.port_in_use = port_in_use      # (port) -> bool
        self.lock_free = lock_free          # () -> bool
        self.http_version = http_version    # (port) -> str | None
        self.spawn = spawn                  # (command, workdir) -> handle | None
        self.now = now                      # () -> float — МОНОТОННЫЕ часы для дедлайнов
        self.sleep = sleep                  # (seconds) -> None
        self.process_alive = process_alive or (lambda h: True)   # (handle) -> bool
        # Настенные часы (time.time) — ТОЛЬКО для отметки свежести журнала. Дедлайны на них
        # строить нельзя (перевод системного времени сломал бы ожидания), поэтому часов двое.
        self.wall = wall or now             # () -> float
        # 29.09.2026: () -> bool — преемник сейчас переносит папку данных (свежая отметка
        # app/data_dir_items.MOVE_MARKER рядом с журналом). Пока это так, он жив и занят делом:
        # ждать дальше, а не запускать вторую копию.
        self.data_move_active = data_move_active or (lambda: False)


DEFAULT_TIMEOUTS = {
    "parent_exit": 45.0,     # сколько ждём исчезновения прежнего процесса
    "lock_free": 45.0,       # сколько ждём освобождения замка одиночного экземпляра
    "port_free": 45.0,       # сколько ждём освобождения порта
    "ready": 120.0,          # сколько ждём подтверждённого /version нового сервера
    "data_move": 6 * 3600.0, # 29.09.2026: предел ожидания, пока преемник переносит папку данных
}

MAX_LAUNCH_ATTEMPTS = 2      # первый запуск + ровно один повтор той же команды


def run_supervisor(plan, probes, timeouts=None, journal_path=None):
    """Основной цикл supervisor'а. -> (ok, код причины).

    Порядок принципиален и обратен прежнему: сначала дожидаемся, что старого сервера ДЕЙСТВИТЕЛЬНО
    не осталось (процесс, замок одиночного экземпляра, порт), и только потом запускаем новый.
    Успехом считается не факт запуска процесса, а подтверждённый ответ `/version` именно нашей
    программы именно на ожидаемом порту."""
    t = dict(DEFAULT_TIMEOUTS)
    t.update(timeouts or {})
    # Alpha 2.810: план может нести СВОИ таймауты (используется self-test'ом собранного EXE,
    # чтобы ветка отказа проверялась за секунды, а не минуты). Значения зажимаются в разумные
    # рамки; журнал пишет только parent тем же пользователем, так что это не граница доверия —
    # план и так несёт полную команду запуска.
    _plan_t = plan.get("timeouts") if isinstance(plan.get("timeouts"), dict) else {}
    for _k, _v in _plan_t.items():
        if _k in t:
            try:
                t[_k] = max(0.5, min(float(_v), 900.0))
            except (TypeError, ValueError):
                pass
    jp = journal_path or plan.get("journal")

    def stage(name, error=""):
        if jp:
            try:
                plan.update({"stage": name, "error": error, "updated_at": probes.wall()})
                write_journal(jp, plan)
            except Exception:
                pass

    stage(STAGE_WAITING_PARENT)
    pid = int(plan.get("parent_pid") or 0)
    if pid and not wait_until(lambda: not probes.pid_alive(pid), t["parent_exit"],
                              probes.sleep, probes.now):
        stage(STAGE_FAILED, ERR_PARENT_ALIVE)
        return False, ERR_PARENT_ALIVE
    if not wait_until(probes.lock_free, t["lock_free"], probes.sleep, probes.now):
        stage(STAGE_FAILED, ERR_LOCK_BUSY)
        return False, ERR_LOCK_BUSY
    # Освободиться должен ИМЕННО текущий активный порт уходящей копии (wait_port), а вот
    # ответить преемник может уже на другом (ready_ports) — см. комментарий в build_plan.
    wport = int(plan.get("wait_port") or plan.get("expected_port") or 0)
    if wport and not wait_until(lambda: not probes.port_in_use(wport), t["port_free"],
                                probes.sleep, probes.now):
        stage(STAGE_FAILED, ERR_PORT_BUSY)
        return False, ERR_PORT_BUSY

    ready_ports = [int(p) for p in (plan.get("ready_ports") or []) if p]
    if not ready_ports:
        ready_ports = [int(plan.get("expected_port") or 0)]
    want = str(plan.get("expected_version") or "")
    last = ERR_NOT_READY
    for attempt in range(1, MAX_LAUNCH_ATTEMPTS + 1):
        plan["attempts"] = attempt
        stage(STAGE_LAUNCHING)
        handle = None
        try:
            handle = probes.spawn(list(plan.get("command") or []), plan.get("workdir") or "")
        except Exception:
            handle = None
        if handle is None:
            last = ERR_SPAWN_FAILED
            stage(STAGE_FAILED, last)
            continue
        stage(STAGE_PROBING)
        answered = [0]
        found_foreign = [False]

        def _ready():
            if not probes.process_alive(handle):
                return False
            for p in ready_ports:
                v = probes.http_version(p)
                if not v:
                    continue
                if v != want:
                    # На нашем порту отвечает не то, что мы запускали. Успехом это не является
                    # никогда: открытый порт сам по себе ничего не доказывает.
                    found_foreign[0] = True
                    continue
                answered[0] = p
                return True
            return False

        ok = wait_until(_ready, t["ready"], probes.sleep, probes.now)
        if not ok and probes.process_alive(handle) and probes.data_move_active():
            # 29.09.2026: преемник жив и переносит папку данных (это идёт ДО порта и может занять
            # минуты). Раньше здесь начиналась вторая попытка: ещё одна копия программы полминуты
            # ждала замок и показывала ложное «закройте прежнюю копию через трей». Теперь ждём,
            # пока перенос идёт (отметка свежая), а потом — обычные t["ready"] на подъём сервера.
            plan["data_move"] = True
            stage(STAGE_PROBING)
            wait_until(lambda: (not probes.process_alive(handle)) or (not probes.data_move_active())
                       or _ready(), t["data_move"], probes.sleep, probes.now)
            ok = bool(answered[0]) or (probes.process_alive(handle)
                                       and wait_until(_ready, t["ready"], probes.sleep, probes.now))
        if ok:
            plan["ready_port"] = answered[0]
            stage(STAGE_READY)
            return True, ""
        if not probes.process_alive(handle):
            last = ERR_SUCCESSOR_EXITED
        elif found_foreign[0]:
            last = ERR_FOREIGN_SERVER
        else:
            last = ERR_READINESS_TIMEOUT
        stage(STAGE_FAILED, last)
    return False, last


def supervisor_command(frozen, executable, script, journal_path, restart_id=None):
    """Команда запуска supervisor'а — ТОТ ЖЕ файл в специальном режиме.

    Отдельного артефакта сборки нет намеренно: один и тот же исполняемый файл гарантированно
    существует рядом и гарантированно той же версии, что и программа.
    restart_id передаётся ЯВНЫМ аргументом (Alpha 2.810): helper сверяет его с журналом и
    отказывается работать с журналом чужого перезапуска."""
    exe = os.path.abspath(str(executable or ""))
    jp = os.path.abspath(str(journal_path or ""))
    cmd = [exe] if frozen else [exe, os.path.abspath(str(script or ""))]
    cmd += [SUPERVISOR_FLAG, jp]
    if restart_id:
        cmd += [RID_FLAG, str(restart_id)]
    return cmd


def parse_supervisor_argv(argv):
    """Если процесс запущен как supervisor -> путь журнала, иначе None.

    Проверяется в САМОМ начале запуска программы: supervisor не должен ни брать замок
    одиночного экземпляра, ни открывать базы, ни поднимать опрос принтеров."""
    args = list(argv or [])
    if SUPERVISOR_FLAG not in args:
        return None
    i = args.index(SUPERVISOR_FLAG)
    if i + 1 >= len(args):
        return None
    p = str(args[i + 1] or "").strip()
    return p or None


def parse_supervisor_rid(argv):
    """Явно переданный restart ID (--fm-restart-id <rid>) или None."""
    args = list(argv or [])
    if RID_FLAG not in args:
        return None
    i = args.index(RID_FLAG)
    if i + 1 >= len(args):
        return None
    r = str(args[i + 1] or "").strip()
    return r or None


# Стадии, в которых helper подтвердил готовность (armed и дальше по успешному пути).
ARMED_STAGES = (STAGE_ARMED, STAGE_WAITING_PARENT, STAGE_LAUNCHING, STAGE_PROBING, STAGE_READY)

# Максимальный возраст записи armed, который parent готов принять. Записи старше — след
# какого-то прежнего запуска, а не ответ нашего helper'а.
ARMED_MAX_AGE_SECONDS = 300.0


def verify_armed(journal, restart_id, pid_alive, now_wall, max_age_seconds=ARMED_MAX_AGE_SECONDS):
    """Проверка parent'а: действительно ли НАШ helper подтвердил готовность. -> (state, code).

    state: "armed"   — подтверждение принято, можно начинать штатное завершение;
           "pending" — ответа ещё нет, продолжать ждать;
           "failed"  — helper оставил вердикт отказа (code — безопасная причина).
    Подтверждением считается ТОЛЬКО запись с НАШИМ restart_id, живым helper_pid и свежей
    отметкой времени: журнал без ID, журнал другого перезапуска, запись без PID или
    устаревшая запись подтверждением не являются никогда."""
    if not isinstance(journal, dict):
        return "pending", ""
    if not restart_id or journal.get("restart_id") != restart_id:
        return "pending", ""                       # чужой или недописанный журнал — не наш ответ
    st = journal.get("stage") or ""
    if st == STAGE_FAILED:
        return "failed", str(journal.get("error") or ERR_NOT_READY)
    if st not in ARMED_STAGES:
        return "pending", ""
    try:
        hp = int(journal.get("helper_pid") or 0)
    except (TypeError, ValueError):
        hp = 0
    if hp <= 0:
        return "pending", ""                       # armed без PID helper'а не принимается
    try:
        upd = float(journal.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        upd = 0.0
    if upd <= 0.0 or (float(now_wall) - upd) > float(max_age_seconds):
        return "pending", ""                       # устаревшая запись — не подтверждение
    if st != STAGE_READY and not pid_alive(hp):
        return "pending", ""                       # запись есть, а helper уже мёртв — не верим
    return "armed", ""
