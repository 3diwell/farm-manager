# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — содержимое папки данных: что переносится при смене папки, что
копируется ежедневно, и сам перенос (29.09.2026).

ЗАЧЕМ. До 29.09.2026 перенос папки данных знал жёсткий список (три базы и четыре папки), а
ежедневная копия — три базы. Всё, что появилось позже, при смене папки оставалось в старой:
модули и их базы, лицензии, номер установки, файлы заказов «Расчёта заказа». Программа на новом
месте начинала почти с чистого листа. Одноимённый файл в папке назначения молча побеждал
переносимый (устаревшая база подменяла рабочую), а старая папка удалялась целиком ещё до того,
как было проверено, что всё доехало.

Теперь один список на всё, и перенос устроен так, чтобы ошибка не стоила данных:
  1. каждый файл копируется во временное имя рядом с целью, копия сверяется с оригиналом по
     размеру и SHA-256 и только потом получает настоящее имя. Существующий файл в папке
     назначения не перезаписывается никогда: такой же — засчитывается, другой — конфликт;
  2. база переносится вместе со своими -wal/-shm/-journal или не переносится вовсе;
  3. оригиналы удаляются ТОЛЬКО когда всё нужное скопировано и сверено, по одному файлу и по
     одной пустой папке — без rmtree;
  4. при любой ошибке копирования сделанные копии убираются, оригиналы не тронуты, программа
     остаётся на прежней папке, а перенос повторится при следующем запуске;
  5. итог — файл data-move-report.json: что перенесено, что осталось и почему.
Элемент, которого нет в списке, не трогается и попадает в отчёт.

Набор tools/test_data_dir_move.py сверяет список с именами, которые ядро и модули на самом деле
открывают в папке данных: новое имя без решения «переносить или нет» даёт красный набор.

Только стандартная библиотека; server.py не импортируется. Файловые операции есть только в
функциях переноса и отчёта (move_data_dir, write_report, read_report). Их вызывает ядро при
запуске, ДО открытия баз и под замком одиночного экземпляра.
"""

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import time

REPORT_NAME = "data-move-report.json"
REPORT_VERSION = 1
TMP_SUFFIX = ".fm-move-tmp"          # временное имя копии рядом с целью (наш суффикс — и только наш)
DB_SIDECARS = ("-wal", "-shm", "-journal")
SPACE_MARGIN = 64 * 1024 * 1024      # запас свободного места сверх объёма переносимого
LIST_LIMIT = 200                     # сколько имён каждого вида держит отчёт (итоговые числа — все)
RECENT_S = 7 * 24 * 3600             # удачный перенос показывается в настройках неделю
#  Отметка «идёт перенос» (29.09.2026, по проверке). Перенос идёт при запуске, ДО порта и трея, и
#  на большой папке длится минуты. Помощник перезапуска ждёт ответа нового процесса 120 с, после
#  чего запускал ВТОРУЮ копию — та полминуты ждала замок и показывала «закройте прежнюю копию
#  через трей», а значка в трее ещё нет. Пока перенос работает, он раз в несколько секунд
#  обновляет эту отметку в прежней папке (там же лежит журнал перезапуска), и помощник ждёт.
MOVE_MARKER = "data-move-progress.json"
MOVE_MARKER_BEAT_S = 5.0             # как часто перенос обновляет отметку
MOVE_MARKER_FRESH_S = 120.0          # отметка старше — перенос не идёт (процесс оборвался)

MOVE, KEEP, UNKNOWN = "move", "keep", "unknown"
BLOCK, LEAVE = "block", "leave"      # что делать при конфликте или ошибке копирования элемента
KIND_FILE, KIND_DIR, KIND_DB = "file", "dir", "db"

#  Коды причин (машинные; текст для человека строит интерфейс).
R_SAME_FOLDER = "same_folder"
R_SOURCE_UNREADABLE = "source_unreadable"
R_MODULE_SWAP_PENDING = "module_swap_pending"
R_TARGET_INSIDE_ITEM = "target_inside_item"
R_LINK = "link_not_supported"
R_NO_SPACE = "not_enough_space"
R_CONFLICT = "conflict"
R_COPY_FAILED = "copy_failed"
R_VERIFY_FAILED = "verify_failed"
R_DELETE_FAILED = "delete_failed"
R_TEMPORARY = "temporary"

_BAD_NAME_CHARS = r'\\/:*?"<>|'
_DB_RX = re.compile(r"^farm_[^%s]+\.db$" % re.escape(_BAD_NAME_CHARS), re.IGNORECASE)
_DB_MEMBER_RX = re.compile(r"^(farm_[^%s]+\.db)(%s)?$" % (re.escape(_BAD_NAME_CHARS),
                                                            "|".join(re.escape(s) for s in DB_SIDECARS)),
                           re.IGNORECASE)
#  Разовые снимки баз: переносятся вместе с папкой, но в ежедневную копию не входят (это уже копия).
SNAPSHOT_DB_GLOBS = ("farm_cost_before_order_module_*.db",)


class Item(object):
    """Элемент папки данных и решение по нему."""

    __slots__ = ("name", "kind", "action", "on_conflict", "daily", "reason", "what")

    def __init__(self, name, kind, action, on_conflict=BLOCK, daily=False, reason="", what=""):
        self.name = name
        self.kind = kind
        self.action = action
        self.on_conflict = on_conflict
        self.daily = daily
        self.reason = reason
        self.what = what

    def __repr__(self):
        return "Item(%r, %s, %s)" % (self.name, self.kind, self.action)


#  ЕДИНЫЙ СПИСОК. Базы (farm_*.db с -wal/-shm/-journal) описаны маской ниже — так в него сами
#  попадают базы будущих модулей. Всё остальное — поимённо.
ITEMS = (
    Item("modules", KIND_DIR, MOVE, what="установленные модули"),
    Item("modules_previous", KIND_DIR, MOVE, what="прежние версии модулей (для возврата)"),
    Item("licenses", KIND_DIR, MOVE, what="лицензии модулей (.fmlic)"),
    Item("cost_order_files", KIND_DIR, MOVE, what="файлы заказов «Расчёта заказа»"),
    Item("project_files", KIND_DIR, MOVE, what="копии файлов проектов"),
    Item("slicer_uploads", KIND_DIR, MOVE, what="файлы задач"),
    Item("temp_files", KIND_DIR, MOVE, what="файлы задач до отправки"),
    #  Копии баз и журнал: одноимённый файл в новой папке не повод останавливать перенос —
    #  такой файл остаётся в прежней папке (он там цел) и попадает в отчёт.
    Item("backups", KIND_DIR, MOVE, on_conflict=LEAVE, what="ежедневные копии баз"),
    Item("logs", KIND_DIR, MOVE, on_conflict=LEAVE, what="журнал программы"),
    Item("install_id.txt", KIND_FILE, MOVE, what="номер установки (для лицензий)"),
    Item("config-restore-journal.json", KIND_FILE, MOVE, what="журнал восстановления резервной копии"),
    Item("farm_cost_order_module_backup.done", KIND_FILE, MOVE,
         what="отметка «Расчёта заказа»: прежняя база уже сохранена"),
    #  Намеренно НЕ переносятся.
    Item("config.json", KIND_FILE, KEEP, reason="config",
         what="настройки запуска: всегда лежат в папке по умолчанию, иначе их не найти"),
    Item("modules_staging", KIND_DIR, KEEP, reason=R_TEMPORARY, what="временная папка установки модулей"),
    Item("thumb_cache", KIND_DIR, KEEP, reason="cache", what="кэш превью, строится заново"),
    Item("bambu_hms_texts.json", KIND_FILE, KEEP, reason="cache",
         what="кэш текстов сообщений Bambu, скачивается заново"),
    Item("restart-state.json", KIND_FILE, KEEP, reason="restart",
         what="журнал одного перезапуска (его пишет помощник перезапуска в прежнюю папку)"),
    Item("restart-helper.log", KIND_FILE, KEEP, reason="restart", what="журнал помощника перезапуска"),
    Item(REPORT_NAME, KIND_FILE, KEEP, reason="report", what="отчёт о переносе папки данных"),
    Item(MOVE_MARKER, KIND_FILE, KEEP, reason="restart",
         what="отметка «идёт перенос» для помощника перезапуска, живёт только во время переноса"),
    #  16.10.2026 (R-151): папка-карантин режима «папка данных недоступна» — пустая ферма без
    #  принтеров и модулей, в которой программа ждёт возвращения настоящей папки. Не данные фермы.
    Item("data-unavailable", KIND_DIR, KEEP, reason=R_TEMPORARY,
         what="временная пустая папка на время, пока настоящая папка данных недоступна"),
    #  16.10.2026 (R-151): файлы модулей (ModuleCore.data_dir) — переезжают вместе с папкой данных
    #  и не удаляются при удалении модуля.
    Item("module_data", KIND_DIR, MOVE, what="файлы модулей"),
)
_BY_NAME = {it.name.lower(): it for it in ITEMS}

#  Временные файлы: остаток оборванной записи; не переносятся и не удаляются.
TEMP_GLOBS = (".w_test", "*.tmp", "*.part", "*" + TMP_SUFFIX)


def is_database_name(name):
    """Имя базы программы или модуля: farm_<что-то>.db (без -wal/-shm)."""
    return bool(_DB_RX.match(str(name or "")))


def is_snapshot_db(name):
    low = str(name or "").lower()
    return any(fnmatch.fnmatchcase(low, g.lower()) for g in SNAPSHOT_DB_GLOBS)


def database_of(name):
    """Имя базы, к которой относится файл (сама база или её -wal/-shm/-journal), иначе ''."""
    m = _DB_MEMBER_RX.match(str(name or ""))
    return m.group(1) if m else ""


def _is_temp_name(name):
    low = str(name or "").lower()
    return any(fnmatch.fnmatchcase(low, g) for g in TEMP_GLOBS)


def classify(name, is_dir=False):
    """Решение по элементу верхнего уровня папки данных -> Item (action MOVE/KEEP/UNKNOWN)."""
    name = str(name or "")
    it = _BY_NAME.get(name.lower())
    if it is not None:
        if (it.kind == KIND_DIR) == bool(is_dir):
            return it
        return Item(name, KIND_DIR if is_dir else KIND_FILE, UNKNOWN, what="вид не совпал со списком")
    if not is_dir:
        base = database_of(name)
        if base:
            return Item(name, KIND_DB, MOVE, daily=(name == base and not is_snapshot_db(base)),
                        what=("разовый снимок базы" if is_snapshot_db(base) else "база данных"))
        if _is_temp_name(name):
            return Item(name, KIND_FILE, KEEP, reason=R_TEMPORARY, what="временный файл")
    return Item(name, KIND_DIR if is_dir else KIND_FILE, UNKNOWN, what="неизвестный элемент")


# ── Ежедневная копия баз ───────────────────────────────────────────────────────────────────────

def daily_backup_databases(names):
    """[(метка, имя базы)] для ежедневной копии: все farm_*.db, кроме разовых снимков.
    Метка — имя без «farm_» и «.db»: parts, printers, inventory, cost, quality, messengers..."""
    out = []
    for n in names or ():
        n = str(n)
        if is_database_name(n) and not is_snapshot_db(n):
            out.append((n[len("farm_"):-len(".db")], n))
    out.sort(key=lambda t: t[0].lower())
    return out


def backup_file_name(tag, day):
    return "%s_%s.db" % (tag, day)


def backup_file_rx(tag):
    """Имена копий ОДНОЙ базы: <метка>_ГГГГММДД.db. Строго: у метки cost не захватить
    копии базы cost_extra (иначе чистка «последних 30» удаляла бы чужие копии)."""
    return re.compile(r"^%s_(\d{8})\.db$" % re.escape(tag))


# ── Пути ────────────────────────────────────────────────────────────────────────────────────

def _norm(p):
    p = os.path.abspath(str(p or ""))
    try:
        p = os.path.realpath(p)
    except Exception:
        pass
    return os.path.normcase(p).rstrip("\\/")


def same_path(a, b):
    """Одна и та же папка (регистр букв, «..», ссылки)."""
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    return _norm(a) == _norm(b)


def is_inside(child, parent):
    """child совпадает с parent или лежит внутри него."""
    if not str(child or "").strip() or not str(parent or "").strip():
        return False
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p + os.sep) or (os.altsep is not None and c.startswith(p + os.altsep))


def inside_own_item(target, data_dir):
    """Имя элемента папки данных (modules, project_files, thumb_cache...), внутри которого лежит
    target, иначе ''. Такая папка назначения недопустима: перенос копировал бы элемент сам в себя,
    а пустая папка внутри modules выглядела бы сломанным модулем. Просто подпапка папки данных
    (не элемент списка) допустима — перенос обходит её стороной."""
    if not is_inside(target, data_dir) or same_path(target, data_dir):
        return ""
    try:
        rel = os.path.relpath(_norm(target), _norm(data_dir))
    except ValueError:
        return ""
    first = rel.replace("\\", "/").split("/")[0]
    if not first or first in (".", ".."):
        return ""
    probe = classify(first, True)
    if probe.action == UNKNOWN:
        probe = classify(first, False)
    return first if probe.action in (MOVE, KEEP) else ""


def has_farm_data(folder):
    """В папке уже лежат базы Farm Manager (farm_*.db)."""
    try:
        return any(is_database_name(n) and os.path.isfile(os.path.join(folder, n)) for n in os.listdir(folder))
    except OSError:
        return False


# ── Папка данных на месте? (16.10.2026, R-151) ─────────────────────────────────────────────────
#  Своя папка данных (флешка, сетевой диск) могла не подключиться к запуску. Раньше программа
#  либо молча создавала на её месте пустую папку, либо уходила в папку по умолчанию — и ферма
#  раздваивалась: новые принтеры и проекты попадали во вторую пару баз, модулей там не было, склад
#  не списывал. Папка считается на месте, только если она есть И в ней лежит главная база фермы
#  farm_parts.db — тот же приём, что у Syncthing (.stfolder) и Nextcloud (.ncdata), но без нового
#  файла-метки: у уже работающих ферм главная база есть всегда. Функции ниже папок НЕ создают.

UNAVAILABLE_DIR = "data-unavailable"      # папка-карантин внутри папки по умолчанию
FARM_SENTINEL = "farm_parts.db"           # главная база фермы — признак «это наша папка данных»
FOLDER_OK = "ok"
FOLDER_MISSING = "missing"                # папки нет (диск не подключён, папку переименовали)
FOLDER_NO_FARM = "no_farm_data"           # папка есть, но базы фермы в ней нет (чужая флешка, пустая точка подключения)
FOLDER_NOT_WRITABLE = "not_writable"      # папка есть и база есть, но писать нельзя
FOLDER_UNREACHABLE = "unreachable"        # сетевой диск не ответил вовремя


def _probe_folder(path):
    """Один опрос папки без создания чего-либо. -> код состояния."""
    try:
        if not os.path.isdir(path):
            return FOLDER_MISSING
        if not os.path.isfile(os.path.join(path, FARM_SENTINEL)):
            return FOLDER_NO_FARM
        #  Пробный файл — только внутри УЖЕ существующей папки с данными фермы.
        probe = os.path.join(path, ".w_test")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return FOLDER_OK
    except OSError:
        return FOLDER_NOT_WRITABLE


def folder_state(path, probe_timeout_s=5.0):
    """Состояние папки данных -> FOLDER_*. Ничего не создаёт (кроме пробного файла внутри уже
    существующей папки с базой фермы). Опрос идёт в отдельном потоке: сетевой диск, который не
    отвечает, считается недоступным, а не держит запуск программы."""
    path = str(path or "").strip()
    if not path:
        return FOLDER_MISSING
    import threading
    box = {}

    def _run():
        box["st"] = _probe_folder(path)

    t = threading.Thread(target=_run, name="data-dir-probe", daemon=True)
    t.start()
    t.join(max(0.05, float(probe_timeout_s)))
    return box.get("st", FOLDER_UNREACHABLE)


def wait_folder(path, wait_s, poll_s=1.0, clock=None, sleep=None, state_fn=None):
    """Ждать папку данных до wait_s секунд (поздно подключившаяся флешка или сетевой диск
    Windows, который подключается уже после входа). -> последнее состояние FOLDER_*."""
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    state_fn = state_fn or folder_state
    deadline = clock() + max(0.0, float(wait_s or 0))
    st = state_fn(path)
    while st != FOLDER_OK and clock() < deadline:
        sleep(max(0.01, min(float(poll_s), max(0.0, deadline - clock()))))
        st = state_fn(path)
    return st


def _is_link(path):
    try:
        if os.path.islink(path):
            return True
        isj = getattr(os.path, "isjunction", None)
        return bool(isj and isj(path))
    except OSError:
        return False


# ── Файловые операции переноса (подменяются в наборе для проверки отказов) ─────────────────────

class MoveError(Exception):
    """Сбой одного файла при переносе (код причины в .reason)."""

    def __init__(self, reason, detail=""):
        Exception.__init__(self, "%s %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


class FileOps(object):
    """Всё, что перенос делает с диском. Набор проверок подменяет отдельные методы."""

    chunk = 1024 * 1024
    beat = None                          # вызывается на каждом блоке: обновление отметки «идёт перенос»

    def _beat(self):
        b = self.beat
        if b is not None:
            try:
                b()
            except Exception:
                pass

    def sha256(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(self.chunk), b""):
                h.update(block)
                self._beat()
        return h.hexdigest()

    def after_write(self, tmp_path):
        """Точка для набора проверок (порча копии). Штатно — ничего."""

    def copy_verified(self, src, dst):
        """Копия во временное имя -> сверка размера и SHA-256 -> настоящее имя без перезаписи.
        -> (sha256, размер). При любой ошибке цели нет, временный файл убран."""
        tmp = dst + TMP_SUFFIX
        if os.path.lexists(tmp):
            os.remove(tmp)                      # остаток прошлой оборванной попытки — наш суффикс
        h = hashlib.sha256()
        size = 0
        try:
            with open(src, "rb") as fi, open(tmp, "xb") as fo:
                for block in iter(lambda: fi.read(self.chunk), b""):
                    h.update(block)
                    size += len(block)
                    fo.write(block)
                    self._beat()
                fo.flush()
                os.fsync(fo.fileno())
            self.after_write(tmp)
            src_sha = h.hexdigest()
            if os.path.getsize(tmp) != size or os.path.getsize(src) != size:
                raise MoveError(R_VERIFY_FAILED, "size")
            if self.sha256(tmp) != src_sha:
                raise MoveError(R_VERIFY_FAILED, "sha256")
            try:
                #  Время изменения — как у оригинала (задачи сортируются по нему). Только время:
                #  пометка «только чтение» не переносится — иначе база на новом месте не писалась бы.
                st = os.stat(src)
                os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
            except OSError:
                pass
            if os.path.lexists(dst):
                raise MoveError(R_CONFLICT, "appeared")
            os.rename(tmp, dst)                 # Windows: существующий файл не перезаписывается
        except BaseException:
            try:
                if os.path.lexists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise
        return src_sha, size

    def remove(self, path):
        self._beat()
        try:
            os.remove(path)
        except PermissionError:
            #  Windows не удаляет файл с пометкой «только чтение»: снимаем её и пробуем ещё раз.
            #  Удаляется только сверенный оригинал или своя же копия этого переноса.
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            os.remove(path)

    def rmdir(self, path):
        os.rmdir(path)

    def makedir(self, path):
        os.mkdir(path)

    def disk_free(self, path):
        try:
            return shutil.disk_usage(path).free
        except Exception:
            return None


# ── Перенос ────────────────────────────────────────────────────────────────────────────────

class _Blocked(Exception):
    def __init__(self, reason, name, detail=""):
        Exception.__init__(self, reason)
        self.reason = reason
        self.name = name
        self.detail = detail


def _rel(*parts):
    return "/".join(p.replace("\\", "/") for p in parts if p and p != ".")


def _add(rep, key, entry):
    rep[key + "_count"] = rep.get(key + "_count", 0) + 1
    if len(rep[key]) < LIST_LIMIT:
        rep[key].append(entry)


def new_report(src, dst):
    rep = {"version": REPORT_VERSION, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": int(time.time()),
           "from": os.path.abspath(str(src or "")), "to": os.path.abspath(str(dst or "")),
           "status": "failed", "switched": False, "reason": "", "reason_item": "", "detail": "",
           "moved": [], "left": [], "kept": [], "unknown": [], "warnings": [],
           "files_copied": 0, "files_identical": 0, "bytes_copied": 0}
    for k in ("moved", "left", "kept", "unknown", "warnings"):
        rep[k + "_count"] = 0
    return rep


def _swap_pending(src):
    """Незавершённая замена модуля (журнал modules_staging/<id>.swap.json хранит абсолютный путь
    к прежней версии в ЭТОЙ папке). Её сначала доводит до конца сама программа при запуске."""
    try:
        return any(n.lower().endswith(".swap.json") for n in os.listdir(os.path.join(src, "modules_staging")))
    except OSError:
        return False


def _tree_size(path, beat=None):
    if not os.path.isdir(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        if beat is not None:
            beat()
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class _Unit(object):
    """Что переносится одним решением: база с сопутствующими файлами, файл или папка."""

    def __init__(self, name, kind, on_conflict, members):
        self.name = name
        self.kind = kind
        self.on_conflict = on_conflict
        self.members = members          # имена верхнего уровня (у базы — .db и сопутствующие)
        self.done = []                  # (исходный файл, файл в новой папке) — сверены
        self.left = []                  # (относительное имя, причина) — остаются в прежней папке
        self.dirs = []                  # исходные папки (для удаления пустых)
        self.files = 0
        self.bytes = 0


def _place(ops, rep, s, d, created):
    """Один файл: уже такой же -> засчитан; другой -> конфликт; нет -> копия со сверкой."""
    if os.path.lexists(d):
        if os.path.isfile(d) and not _is_link(d) and os.path.getsize(d) == os.path.getsize(s) \
                and ops.sha256(d) == ops.sha256(s):
            rep["files_identical"] += 1
            return
        raise MoveError(R_CONFLICT)
    try:
        _sha, size = ops.copy_verified(s, d)
    except FileExistsError:
        raise MoveError(R_CONFLICT, "appeared")
    created.append(d)
    rep["files_copied"] += 1
    rep["bytes_copied"] += size


def _ensure_dir(ops, d, created_dirs):
    if os.path.isdir(d) and not _is_link(d):
        return
    if os.path.lexists(d):
        raise MoveError(R_CONFLICT, "not_a_folder")
    parent = os.path.dirname(d)
    if parent and parent != d and not os.path.isdir(parent):
        _ensure_dir(ops, parent, created_dirs)
    ops.makedir(d)
    created_dirs.append(d)


def _copy_unit(ops, rep, unit, src, dst, created, created_dirs):
    def fail_or_leave(rel, reason, detail=""):
        if unit.on_conflict == LEAVE:
            unit.left.append((rel, reason))
            return
        raise _Blocked(reason, rel, detail)

    if unit.kind in (KIND_DB, KIND_FILE):
        for m in unit.members:
            s, d = os.path.join(src, m), os.path.join(dst, m)
            if _is_link(s):
                raise _Blocked(R_LINK, m)
            try:
                _place(ops, rep, s, d, created)
            except MoveError as e:
                raise _Blocked(e.reason, m, e.detail)
            except OSError as e:
                raise _Blocked(R_COPY_FAILED, m, e.__class__.__name__)
            unit.done.append((s, d))
            unit.files += 1
            try:
                unit.bytes += os.path.getsize(s)
            except OSError:
                pass
        return
    top = os.path.join(src, unit.name)
    target = os.path.join(dst, unit.name)
    if _is_link(top):
        raise _Blocked(R_LINK, unit.name)
    try:
        _ensure_dir(ops, target, created_dirs)
    except (MoveError, OSError) as e:
        raise _Blocked(getattr(e, "reason", R_COPY_FAILED), unit.name, e.__class__.__name__)

    def walk_error(e):
        #  Папку не удалось прочитать: её содержимое не скопировано — молча оставить его нельзя.
        where = getattr(e, "filename", "") or top
        try:
            rel = _rel(unit.name, os.path.relpath(where, top))
        except ValueError:
            rel = unit.name
        fail_or_leave(rel, R_COPY_FAILED, e.__class__.__name__)

    for root, dirs, files in os.walk(top, onerror=walk_error):
        rel_root = os.path.relpath(root, top)
        unit.dirs.append(root)
        for dn in list(dirs):
            if _is_link(os.path.join(root, dn)):
                dirs.remove(dn)
                fail_or_leave(_rel(unit.name, rel_root, dn), R_LINK)
                continue
            try:
                _ensure_dir(ops, os.path.normpath(os.path.join(target, rel_root, dn)), created_dirs)
            except (MoveError, OSError) as e:
                dirs.remove(dn)
                fail_or_leave(_rel(unit.name, rel_root, dn), getattr(e, "reason", R_COPY_FAILED))
        for fn in sorted(files):
            s = os.path.join(root, fn)
            d = os.path.normpath(os.path.join(target, rel_root, fn))
            rel = _rel(unit.name, rel_root, fn)
            if fn.lower().endswith(TMP_SUFFIX):
                unit.left.append((rel, R_TEMPORARY))   # остаток чужой оборванной попытки — не данные
                continue
            if _is_link(s):
                fail_or_leave(rel, R_LINK)
                continue
            try:
                _place(ops, rep, s, d, created)
            except MoveError as e:
                fail_or_leave(rel, e.reason, e.detail)
                continue
            except OSError as e:
                fail_or_leave(rel, R_COPY_FAILED, e.__class__.__name__)
                continue
            unit.done.append((s, d))
            unit.files += 1
            try:
                unit.bytes += os.path.getsize(s)
            except OSError:
                pass


def _rollback(ops, rep, created, created_dirs):
    """Убрать ТОЛЬКО то, что создал этот перенос (оригиналы целы — их никто не трогал)."""
    for d in reversed(created):
        try:
            ops.remove(d)
        except OSError:
            rep["warnings_count"] += 1
            if len(rep["warnings"]) < LIST_LIMIT:
                rep["warnings"].append({"name": d, "reason": "rollback_failed"})
    for d in reversed(created_dirs):
        try:
            ops.rmdir(d)
        except OSError:
            pass


def _delete_sources(ops, rep, unit, src):
    if unit.kind == KIND_DB:
        #  Сначала сама база: не удалилась — остаётся вся тройка целиком (старая копия непротиворечива).
        base = [p for p in unit.done if os.path.basename(p[0]).lower() == unit.name.lower()]
        rest = [p for p in unit.done if p not in base]
        for s, _d in base + rest:
            try:
                ops.remove(s)
            except OSError:
                _add(rep, "left", {"name": os.path.basename(s), "reason": R_DELETE_FAILED})
                if (s, _d) in base:
                    for s2, _d2 in rest:
                        _add(rep, "left", {"name": os.path.basename(s2), "reason": R_DELETE_FAILED})
                    return
        return
    for s, _d in unit.done:
        try:
            ops.remove(s)
        except OSError:
            _add(rep, "left", {"name": _rel(os.path.relpath(s, src)), "reason": R_DELETE_FAILED})
    for d in sorted(unit.dirs, key=lambda p: -len(p)):
        try:
            if not os.listdir(d):
                ops.rmdir(d)
        except OSError:
            pass


class _MoveMarker(object):
    """Отметка «идёт перенос» в прежней папке: обновляется не чаще раза в MOVE_MARKER_BEAT_S.
    Сбой записи отметки перенос не останавливает — без неё помощник просто ждёт по-старому."""

    def __init__(self, folder, dst, clock=time.time):
        self.path = os.path.join(folder, MOVE_MARKER)
        self.dst = dst
        self.clock = clock
        self.started = clock()
        self.last = None

    def write(self):
        now = self.clock()
        self.last = now
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "started_at": self.started, "updated_at": now,
                           "to": self.dst}, f)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def beat(self):
        if self.last is None or self.clock() - self.last >= MOVE_MARKER_BEAT_S:
            self.write()

    def remove(self):
        for p in (self.path, self.path + ".tmp"):
            try:
                if os.path.lexists(p):
                    os.remove(p)
            except OSError:
                pass


def move_in_progress(folder, now=None, fresh_s=MOVE_MARKER_FRESH_S):
    """Идёт ли сейчас перенос из папки folder: свежая отметка MOVE_MARKER. -> bool.
    Читает помощник перезапуска; отметка оборванного процесса устаревает сама."""
    try:
        path = os.path.join(str(folder or ""), MOVE_MARKER)
        if not folder or not os.path.isfile(path) or os.path.getsize(path) > 64 * 1024:
            return False
        with open(path, encoding="utf-8") as f:
            upd = float((json.load(f) or {}).get("updated_at") or 0.0)
        age = (time.time() if now is None else float(now)) - upd
        return -fresh_s <= age <= fresh_s
    except Exception:
        return False


def move_data_dir(src, dst, log=None, ops=None):
    """Перенести содержимое папки данных src в dst по списку. -> отчёт (dict).

    report["switched"] — можно ли работать из dst: всё нужное скопировано и сверено. False —
    оригиналы не тронуты, копии этого запуска убраны, работать нужно из src.
    Пока перенос идёт, в src лежит отметка MOVE_MARKER (см. move_in_progress)."""
    ops = ops or FileOps()
    src_abs = os.path.abspath(str(src or ""))
    if same_path(src_abs, os.path.abspath(str(dst or ""))) or not os.path.isdir(src_abs):
        return _move_data_dir(src, dst, log, ops)
    marker = _MoveMarker(src_abs, os.path.abspath(str(dst or "")))
    marker.write()
    prev_beat = getattr(ops, "beat", None)
    try:
        ops.beat = marker.beat
        return _move_data_dir(src, dst, log, ops)
    finally:
        try:
            ops.beat = prev_beat
        except Exception:
            pass
        marker.remove()


def _move_data_dir(src, dst, log, ops):
    rep = new_report(src, dst)
    src = os.path.abspath(str(src or ""))
    dst = os.path.abspath(str(dst or ""))

    def fail(reason, name="", detail=""):
        rep.update(status="failed", switched=False, reason=reason, reason_item=name, detail=str(detail or ""))
        if log is not None:
            try:
                log.error("[DATA] data folder move failed: %s %s — data stays in the previous folder" % (reason, name))
            except Exception:
                pass
        return rep

    if same_path(src, dst):
        rep.update(status="ok", switched=True, reason=R_SAME_FOLDER)
        return rep
    try:
        entries = sorted(os.listdir(src))
    except OSError as e:
        return fail(R_SOURCE_UNREADABLE, "", e.__class__.__name__)
    units, dbs = [], {}
    try:
        if _swap_pending(src):
            return fail(R_MODULE_SWAP_PENDING, "modules_staging")
        for name in entries:
            p = os.path.join(src, name)
            is_dir = os.path.isdir(p)
            it = classify(name, is_dir)
            if is_inside(dst, p):
                if it.action == MOVE:
                    return fail(R_TARGET_INSIDE_ITEM, name)
                continue                       # это сама новая папка (или путь к ней) — не данные
            if it.action == KEEP:
                _add(rep, "kept", {"name": name, "reason": it.reason})
                continue
            if it.action == UNKNOWN:
                _add(rep, "unknown", {"name": name})
                continue
            if it.kind == KIND_DB:
                base = database_of(name)
                u = dbs.get(base.lower())
                if u is None:
                    u = dbs[base.lower()] = _Unit(base, KIND_DB, BLOCK, [])
                    units.append(u)
                u.members.append(name)
            else:
                units.append(_Unit(name, it.kind, it.on_conflict, [name]))
        #  Базы — первыми: если не переносятся они, копировать файлы проектов незачем.
        units.sort(key=lambda u: (0 if u.kind == KIND_DB else 1 if u.kind == KIND_FILE else 2, u.name.lower()))
        for u in units:
            if u.kind == KIND_DB:
                u.members.sort(key=lambda m: (0 if m.lower() == u.name.lower() else 1, m.lower()))
        os.makedirs(dst, exist_ok=True)
        needed = sum(_tree_size(os.path.join(src, m), ops._beat if hasattr(ops, "_beat") else None)
                     for u in units for m in u.members)
        free = ops.disk_free(dst)
        if free is not None and needed + SPACE_MARGIN > free:
            rep["needed_bytes"], rep["free_bytes"] = needed, free
            return fail(R_NO_SPACE, "", "%d>%d" % (needed, free))
    except Exception as e:                     # до копирования ничего не тронуто
        return fail(R_COPY_FAILED, "", e.__class__.__name__)

    created, created_dirs = [], []
    try:
        for u in units:
            _copy_unit(ops, rep, u, src, dst, created, created_dirs)
    except _Blocked as b:
        _rollback(ops, rep, created, created_dirs)
        rep["files_copied"] = rep["bytes_copied"] = 0
        return fail(b.reason, b.name, b.detail)
    except Exception as e:                     # непредвиденное — тоже откат, оригиналы целы
        _rollback(ops, rep, created, created_dirs)
        rep["files_copied"] = rep["bytes_copied"] = 0
        return fail(R_COPY_FAILED, "", e.__class__.__name__)

    #  Всё нужное скопировано и сверено: теперь — и только теперь — убираем оригиналы. С этого
    #  места новая папка полна, поэтому никакой сбой уборки не возвращает программу в старую
    #  (там уже может не хватать удалённого): неубранное остаётся копией и попадает в отчёт.
    rep.update(status="ok", switched=True)
    for u in units:
        try:
            for rel, reason in u.left:
                _add(rep, "left", {"name": rel, "reason": reason})
            _delete_sources(ops, rep, u, src)
        except Exception as e:
            _add(rep, "warnings", {"name": u.name, "reason": "cleanup_failed:" + e.__class__.__name__})
        _add(rep, "moved", {"name": u.name, "files": u.files, "bytes": u.bytes})
    if log is not None:
        try:
            log.info("[DATA] data folder moved: %d items, %d files copied, %d already there, %d left, %d unknown"
                     % (rep["moved_count"], rep["files_copied"], rep["files_identical"],
                        rep["left_count"], rep["unknown_count"]))
        except Exception:
            pass
    return rep


# ── Отчёт ───────────────────────────────────────────────────────────────────────────────────

def write_report(folder, report):
    """Отчёт переноса в <folder>/data-move-report.json (атомарно). -> True/False."""
    try:
        path = os.path.join(folder, REPORT_NAME)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def read_report(folder, limit=2 * 1024 * 1024):
    try:
        path = os.path.join(folder, REPORT_NAME)
        if not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8") as f:
            rep = json.load(f)
        return rep if isinstance(rep, dict) else None
    except Exception:
        return None


def summary(report, move_pending, now=None):
    """Короткий итог для окна настроек. active — показывать ли его сейчас: неудачный перенос —
    пока он ещё ждёт повтора; удачный — неделю."""
    if not isinstance(report, dict):
        return None
    now = time.time() if now is None else now
    ok = report.get("status") == "ok" and bool(report.get("switched"))
    if report.get("reason") == R_SAME_FOLDER:
        return None
    try:
        ts = float(report.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    active = (0 <= now - ts <= RECENT_S) if ok else bool(move_pending)

    def names(key, n=8):
        return [str((e or {}).get("name") or "") for e in (report.get(key) or [])[:n]]

    return {"at": str(report.get("at") or ""), "status": "ok" if ok else "failed", "active": bool(active),
            "from": str(report.get("from") or ""), "to": str(report.get("to") or ""),
            "reason": str(report.get("reason") or ""), "reason_item": str(report.get("reason_item") or ""),
            "moved": int(report.get("moved_count") or 0),
            "files": int(report.get("files_copied") or 0) + int(report.get("files_identical") or 0),
            "left": names("left"), "left_count": int(report.get("left_count") or 0),
            "unknown": names("unknown"), "unknown_count": int(report.get("unknown_count") or 0),
            "needed_bytes": int(report.get("needed_bytes") or 0), "free_bytes": int(report.get("free_bytes") or 0)}
