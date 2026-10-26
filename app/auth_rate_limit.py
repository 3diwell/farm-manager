# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — ограничение повторных попыток входа (Alpha 2.790).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк,
СУБД и принтерные подсистемы, не обращается к сети, не читает конфигурацию и НИЧЕГО не
пишет в журнал. Не знает ни записей пользователей, ни паролей, ни токенов сессий — он
оперирует только ключами и счётчиками, поэтому его можно проверять офлайн-тестами без
запуска приложения и без рабочих данных.

ЗАЧЕМ. Проверка пароля стоит дорого намеренно: pbkdf2-sha256, 200 000 итераций. Без
ограничения любой, кто дотянулся до маршрута входа, может заставлять сервер считать этот
хеш неограниченно — это и перебор пароля, и нагрузка на процессор. Ограничитель — ДОПОЛНИ-
ТЕЛЬНЫЙ барьер ПЕРЕД дорогой проверкой, а не замена проверки учётных данных.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Состояние живёт в памяти процесса: перезапуск Farm Manager обнуляет
счётчики. Постоянное между перезапусками ограничение НЕ заявляется — и это осознанно:
запись счётчиков в рабочую БД дала бы неаутентифицированному клиенту способ писать в неё.
Побочная польза — у владельца, запертого собственной опечаткой, остаётся понятный выход:
перезапуск программы.

ВРЕМЯ. Только монотонные часы: системное время можно перевести назад и снять блокировку.
Часы внедряются параметром, поэтому тест не спит и результат детерминирован.

КЛЮЧИ. Адрес берётся ТОЛЬКО из транспорта; заголовки прокси сюда не передаются и
передаваться не должны. Логин не хранится в открытом виде — ключом служит sha256 от
нормализованного имени: перечислить, кого именно перебирали, по состоянию нельзя.
"""

import hashlib
import threading
import time as _time

# ── Пороги. Подобраны так, чтобы обычная опечатка не запирала владельца: пять попыток на
#    одно имя — это четыре ошибки подряд плюс исходная. Перебор при этом становится
#    бессмысленным: 5 попыток за 5 минут против пространства паролей.
LOGIN_ACCOUNT_MAX = 5            # неудач на (логин + адрес) за окно
LOGIN_ACCOUNT_WINDOW = 5 * 60
LOGIN_PEER_MAX = 20              # неудач на один адрес за окно (перебор по разным именам)
LOGIN_PEER_WINDOW = 5 * 60
SETUP_PEER_MAX = 5               # первичное включение защиты — отдельное пространство
SETUP_PEER_WINDOW = 15 * 60
BLOCK_SECONDS = 15 * 60

# Верхний предел числа ключей. При переполнении ограничитель НЕ отключается: вытесняются
# самые старые записи. Отказ в защите ради экономии памяти был бы худшим из решений.
MAX_KEYS = 4096

# Пространства имён: вход и первичная настройка считаются отдельно, иначе setup стал бы
# обходом ограничителя входа.
NS_LOGIN_ACCOUNT = "login_account"
NS_LOGIN_PEER = "login_peer"
NS_SETUP_PEER = "setup_peer"

REASON_OK = ""
REASON_RATE_LIMITED = "auth_rate_limited"

_LIMITS = {
    NS_LOGIN_ACCOUNT: (LOGIN_ACCOUNT_MAX, LOGIN_ACCOUNT_WINDOW),
    NS_LOGIN_PEER: (LOGIN_PEER_MAX, LOGIN_PEER_WINDOW),
    NS_SETUP_PEER: (SETUP_PEER_MAX, SETUP_PEER_WINDOW),
}


def account_key(login, peer=""):
    """Ключ по имени пользователя и адресу: sha256 нормализованного значения, не само имя.

    Нормализация ДОЛЖНА совпадать с той, что применяет поиск пользователя, иначе
    ограничение обходилось бы регистром или пробелами. В этом проекте поиск делает
    strip() и сравнивает регистрозависимо (SQLite: username=?), поэтому здесь то же самое:
    менять семантику логина молча нельзя.

    16.10.2026 (аудит arch-auth-09): адрес входит в ключ. Раньше счёт шёл по одному имени, и
    любое устройство в сети пятью неверными паролями закрывало вход администратору на 15 минут
    отовсюду, включая сам компьютер фермы. Перебор с одного адреса по-прежнему ограничен и здесь,
    и заслоном адреса (LOGIN_PEER_MAX).
    """
    key = str(login or "").strip()
    if peer:
        key = key + "\0" + str(peer)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Decision(object):
    """Неизменяемый результат. allow=False -> запрос дальше не идёт."""

    __slots__ = ("allow", "reason", "retry_after", "namespace")

    def __init__(self, allow, reason=REASON_OK, retry_after=0, namespace=""):
        self.allow = bool(allow)
        self.reason = reason
        self.retry_after = int(retry_after)
        self.namespace = namespace

    def __eq__(self, other):
        return (isinstance(other, Decision) and self.allow == other.allow
                and self.reason == other.reason and self.retry_after == other.retry_after)

    def __repr__(self):   # ни ключа, ни логина, ни адреса — только исход
        return "Decision(allow=%r, reason=%r, retry_after=%r)" % (
            self.allow, self.reason, self.retry_after)


ALLOWED = Decision(True)


class AuthRateLimiter(object):
    """Счётчики неудачных попыток с окном и блокировкой.

    Потокобезопасен: сервер обслуживает запросы в нескольких потоках, и без замка два
    одновременных запроса могли бы прочитать один и тот же счётчик и оба пройти порог.
    Замок держится только на коротких операциях со словарём — дорогая проверка пароля
    выполняется ВНЕ его.
    """

    def __init__(self, clock=None, max_keys=MAX_KEYS):
        self._clock = clock or _time.monotonic
        self._max_keys = int(max_keys)
        self._lock = threading.Lock()
        # (namespace, key) -> {"fails": [метки времени], "blocked_until": float}
        self._state = {}

    # ── внутреннее ──────────────────────────────────────────────────────────
    def _prune(self, now):
        """Удалить записи, которые уже ничего не ограничивают. Вызывается по необходимости,
        а не на каждый запрос: полный обход при каждом входе был бы лишней работой."""
        dead = []
        for k, ent in self._state.items():
            window = _LIMITS[k[0]][1]
            if ent["blocked_until"] > now:
                continue
            if ent["fails"] and (now - ent["fails"][-1]) <= window:
                continue
            dead.append(k)
        for k in dead:
            self._state.pop(k, None)
        # Вытесняем до max_keys-1, чтобы после добавления новой записи размер не превысил
        # предел: иначе словарь стабилизировался бы на max_keys+1 и граница не соблюдалась.
        if len(self._state) >= self._max_keys:
            ordered = sorted(self._state.items(),
                             key=lambda kv: max(kv[1]["fails"] or [kv[1]["blocked_until"]],
                                                default=0))
            excess = len(self._state) - (self._max_keys - 1)
            for k, _v in ordered[:max(0, excess)]:
                self._state.pop(k, None)

    def _entry(self, ns, key):
        return self._state.setdefault((ns, key), {"fails": [], "blocked_until": 0.0})

    # ── публичное ───────────────────────────────────────────────────────────
    def check(self, ns, key):
        """Разрешена ли попытка. НЕ считает саму попытку — только читает состояние."""
        if not key:
            return ALLOWED
        now = self._clock()
        with self._lock:
            ent = self._state.get((ns, key))
            if not ent:
                return ALLOWED
            if ent["blocked_until"] > now:
                return Decision(False, REASON_RATE_LIMITED,
                                max(1, int(ent["blocked_until"] - now) + 1), ns)
            return ALLOWED

    def register_failure(self, ns, key):
        """Учесть неудачную попытку. -> Decision: заблокирован ли ключ ПОСЛЕ этой неудачи."""
        if not key:
            return ALLOWED
        now = self._clock()
        limit, window = _LIMITS[ns]
        with self._lock:
            if len(self._state) >= self._max_keys:
                self._prune(now)
            ent = self._entry(ns, key)
            if ent["blocked_until"] > now:
                return Decision(False, REASON_RATE_LIMITED,
                                max(1, int(ent["blocked_until"] - now) + 1), ns)
            ent["fails"] = [t for t in ent["fails"] if (now - t) <= window]
            ent["fails"].append(now)
            if len(ent["fails"]) >= limit:
                ent["blocked_until"] = now + BLOCK_SECONDS
                ent["fails"] = []
                return Decision(False, REASON_RATE_LIMITED, BLOCK_SECONDS, ns)
            return ALLOWED

    def clear(self, ns, key):
        """Снять накопленные неудачи после успешного входа.

        Снимает ТОЛЬКО состояние конкретного ключа и ТОЛЬКО если он не заблокирован:
        иначе один удачный вход по известному имени снимал бы общий заслон адреса, и
        перебор возобновлялся бы бесконечно.
        """
        if not key:
            return False
        now = self._clock()
        with self._lock:
            ent = self._state.get((ns, key))
            if not ent:
                return False
            if ent["blocked_until"] > now:
                return False
            self._state.pop((ns, key), None)
            return True

    def prune(self):
        """Явная уборка (для периодического вызова и тестов)."""
        now = self._clock()
        with self._lock:
            self._prune(now)
        return len(self._state)

    def size(self):
        with self._lock:
            return len(self._state)
