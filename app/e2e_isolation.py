# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — изоляция собранного backend для packaged E2E-теста (Alpha 2.811).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, БД, сеть и принтерные
подсистемы. Ничего не создаёт и не изменяет — только ПРОВЕРЯЕТ переданные пути и отвечает,
разрешена ли изоляция.

ЗАЧЕМ. Настоящий перезапуск собранной программы (родитель -> helper -> преемник) невозможно
проверить mock-тестами: реальный отказ Alpha 2.810 случился ровно в том звене, которое моки
подменяли. Чтобы прогнать этот путь на НАСТОЯЩЕМ .exe, нужен второй экземпляр программы,
полностью отделённый от рабочего: своя папка данных, свой config, свой замок одиночного
экземпляра, свой порт, без трея, браузера, обнаружения, принтеров и модулей.

ГРАНИЦА БЕЗОПАСНОСТИ (главное правило этого файла).
Переменные окружения FM_E2E_* читаются ТОЛЬКО при явном аргументе командной строки
`--fm-packaged-e2e`. Без него они не существуют для программы вовсе: подсунуть окружение
работающей программе и увести её данные в чужую папку нельзя. Дополнительно:
  * папка теста обязана содержать маркер с тем же случайным токеном, что и FM_E2E_SENTINEL
    (доказательство, что папку создал именно запустивший тест, а не посторонний);
  * папка теста не может совпадать с рабочей папкой данных и не может лежать внутри неё;
  * ссылки/стыки (reparse point) запрещены — иначе «временная» папка могла бы указывать в рабочую;
  * имя замка обязано отличаться от рабочего — иначе тест конкурировал бы с рабочей копией;
  * config теста обязан лежать внутри папки теста.
Любая непройденная проверка — ОТКАЗ ЗАПУСКА (fail-closed), а не тихий откат к рабочим данным:
наполовину изолированный экземпляр опаснее, чем незапустившийся тест.

HTTP-путей сюда нет: режим включается только аргументом локально запущенного процесса.
"""

import json
import os
import stat

FLAG = "--fm-packaged-e2e"
MARKER_NAME = ".fm-e2e-marker"
MIN_TOKEN_LEN = 16

ENV_SENTINEL = "FM_E2E_SENTINEL"
ENV_INSTANCE = "FM_E2E_INSTANCE_ID"
ENV_DATA_DIR = "FM_E2E_DATA_DIR"
ENV_CONFIG = "FM_E2E_CONFIG_PATH"
ENV_MUTEX = "FM_E2E_MUTEX_NAME"
ENV_PORT = "FM_E2E_PORT"
ENV_NO_TRAY = "FM_E2E_DISABLE_TRAY"
ENV_NO_BROWSER = "FM_E2E_DISABLE_BROWSER"
ENV_NO_DISCOVERY = "FM_E2E_DISABLE_DISCOVERY"
ENV_NO_PRINTERS = "FM_E2E_DISABLE_PRINTERS"
ENV_NO_MODULES = "FM_E2E_DISABLE_MODULES"

# Коды отказа (машинные, без путей). Возвращаются вызывающему для честного сообщения.
ERR_NO_SENTINEL = "e2e_sentinel_missing"
ERR_NO_ROOT = "e2e_root_missing"
ERR_ROOT_NOT_DIR = "e2e_root_not_directory"
ERR_ROOT_REPARSE = "e2e_root_reparse_point"
ERR_ROOT_IN_PRODUCTION = "e2e_root_inside_production"
ERR_MARKER = "e2e_marker_invalid"
ERR_MUTEX = "e2e_mutex_invalid"
ERR_CONFIG = "e2e_config_outside_root"
ERR_PORT = "e2e_port_invalid"

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class Isolation(object):
    """Проверенные параметры изолированного тестового экземпляра."""

    __slots__ = ("root", "data_dir", "config_path", "mutex_name", "port", "instance_id",
                 "disable_tray", "disable_browser", "disable_discovery",
                 "disable_printers", "disable_modules")

    def __init__(self, root, data_dir, config_path, mutex_name, port, instance_id,
                 disable_tray, disable_browser, disable_discovery,
                 disable_printers, disable_modules):
        self.root = root
        self.data_dir = data_dir
        self.config_path = config_path
        self.mutex_name = mutex_name
        self.port = port
        self.instance_id = instance_id
        self.disable_tray = disable_tray
        self.disable_browser = disable_browser
        self.disable_discovery = disable_discovery
        self.disable_printers = disable_printers
        self.disable_modules = disable_modules

    # ── Внешние обращения изолированного экземпляра ─────────────────────────
    # Не поле и не переменная окружения, а СВОЙСТВО принятой изоляции: включить его
    # иначе, чем пройдя весь официальный контракт, невозможно. Отдельного выключателя
    # обновлений у пользователя не появляется, а обычный запуск сюда не попадает вовсе,
    # потому что там объекта Isolation просто нет.
    @property
    def disable_update_check(self):
        """Изолированному экземпляру запрещено ходить на сайт за манифестом обновлений.

        ПОЧЕМУ. Тестовый экземпляр обязан быть замкнут на петлю: единственное исходящее
        соединение делает картину «внешней сети нет» недоказуемой, а проверка обновлений
        для теста бессмысленна — версия и так известна.
        """
        return True

    def describe(self):
        """Безопасный срез для журнала: без абсолютных путей."""
        return {"instance": self.instance_id, "port": self.port,
                "tray": not self.disable_tray, "printers": not self.disable_printers,
                "modules": not self.disable_modules,
                "update_check": not self.disable_update_check}


def requested(argv):
    """Запрошен ли режим изоляции. Только по аргументу командной строки."""
    return FLAG in list(argv or [])


def external_calls_allowed(isolation):
    """Можно ли этому экземпляру обращаться к внешним сервисам.

    Единственный источник истины — ПРИНЯТЫЙ контракт: `isolation is None` означает
    обычную работу, где ничего не ограничивается. Функция сделана общей, чтобы будущие
    внешние фоновые обращения спрашивали здесь, а не заводили каждый свой флаг.
    """
    return isolation is None


def _is_reparse(path):
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    if stat.S_ISLNK(getattr(st, "st_mode", 0)):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _has_reparse_in_chain(path):
    """Ссылка/стык в самой папке или в любом её родителе (bounded обход до корня диска)."""
    cur = os.path.abspath(path)
    for _ in range(64):
        if _is_reparse(cur):
            return True
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            return False
        cur = parent
    return False


def _inside(child, parent):
    """child == parent или child внутри parent (сравнение нормализованных путей)."""
    try:
        c = os.path.normcase(os.path.abspath(child)).rstrip("\\/")
        p = os.path.normcase(os.path.abspath(parent)).rstrip("\\/")
    except Exception:
        return True                      # не смогли сравнить -> считаем опасным
    return c == p or c.startswith(p + os.sep) or c.startswith(p + "/")


def detect(argv, environ, production_data_dir, production_mutex_name):
    """Разобрать и ПРОВЕРИТЬ изоляцию. -> (Isolation | None, код отказа | "").

    (None, "") — режим не запрашивался: программа работает как обычно.
    (None, код) — режим запрошен, но проверка не пройдена: запускаться НЕЛЬЗЯ.
    """
    if not requested(argv):
        return None, ""                  # без CLI-флага переменные окружения игнорируются целиком

    env = environ or {}
    token = str(env.get(ENV_SENTINEL) or "").strip()
    if len(token) < MIN_TOKEN_LEN:
        return None, ERR_NO_SENTINEL

    root = str(env.get(ENV_DATA_DIR) or "").strip()
    if not root or not os.path.isabs(root):
        return None, ERR_NO_ROOT
    if not os.path.isdir(root):
        return None, ERR_ROOT_NOT_DIR
    if _has_reparse_in_chain(root):
        return None, ERR_ROOT_REPARSE
    if _inside(root, production_data_dir) or _inside(production_data_dir, root):
        return None, ERR_ROOT_IN_PRODUCTION

    # Маркер: доказательство, что папку подготовил именно тот, кто знает токен.
    try:
        with open(os.path.join(root, MARKER_NAME), encoding="utf-8") as f:
            marker = json.load(f)
        if str((marker or {}).get("token") or "") != token:
            return None, ERR_MARKER
    except Exception:
        return None, ERR_MARKER

    mutex = str(env.get(ENV_MUTEX) or "").strip()
    if not mutex or mutex == production_mutex_name or not mutex.startswith("Local\\"):
        return None, ERR_MUTEX

    config_path = str(env.get(ENV_CONFIG) or "").strip() or os.path.join(root, "config.json")
    if not os.path.isabs(config_path) or not _inside(os.path.dirname(config_path), root):
        return None, ERR_CONFIG

    port = 0
    raw_port = str(env.get(ENV_PORT) or "").strip()
    if raw_port:
        try:
            port = int(raw_port)
        except ValueError:
            return None, ERR_PORT
        if not (1024 <= port <= 65535):
            return None, ERR_PORT

    def flag(name, default=True):
        v = str(env.get(name) or "").strip()
        return (v == "1") if v else default

    return Isolation(
        root=os.path.abspath(root),
        data_dir=os.path.abspath(root),
        config_path=os.path.abspath(config_path),
        mutex_name=mutex,
        port=port,
        instance_id=str(env.get(ENV_INSTANCE) or "")[:32],
        # По умолчанию всё «шумное» выключено: тест не должен трогать ни трей, ни принтеров.
        disable_tray=flag(ENV_NO_TRAY),
        disable_browser=flag(ENV_NO_BROWSER),
        disable_discovery=flag(ENV_NO_DISCOVERY),
        disable_printers=flag(ENV_NO_PRINTERS),
        disable_modules=flag(ENV_NO_MODULES),
    ), ""
