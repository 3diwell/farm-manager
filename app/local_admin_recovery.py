# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — локальное одноразовое восстановление доступа администратора (Alpha 2.798).

ЧТО ЭТО. Владелец, забывший пароль администратора, инициирует восстановление ТОЛЬКО из меню
значка Farm Manager в системном трее (то есть физически за этим компьютером). Ядро выдаёт
криптографически случайный ОДНОРАЗОВЫЙ recovery-grant, живущий ТОЛЬКО в памяти процесса, и
открывает локальную страницу с токеном во фрагменте URL. Фрагмент не уходит на сервер; страница
сразу его считывает, стирает из адресной строки и держит в памяти окна. Владелец вводит имя
существующего администратора и новый пароль; ядро принимает запрос только от фактического
loopback-клиента, с действующим неистёкшим токеном, и меняет пароль тем же алгоритмом, что и
обычная смена, после чего отзывает все сессии этого администратора и уничтожает grant.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это НЕ удалённое восстановление, НЕ email/MFA, и НЕ защита от того, кто уже
имеет доступ к пользовательской сессии Windows на этом компьютере: локальное восстановление
намеренно доверяет физическому доступу к трею. Постоянного recovery-секрета нет — токен живёт
только в памяти и исчезает при перезапуске процесса.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека. НЕ импортирует server.py, FastAPI/Starlette, НЕ
открывает БД, НЕ читает config, НЕ обращается к сети, НЕ запускает потоки, НЕ логирует токены и
пароли, НЕ знает о принтерах/очереди/печати. Оперирует только digest'ами и счётчиками, поэтому
проверяется офлайн-тестами без запуска приложения и без рабочих данных. Часы внедряются
параметром (monotonic) — тест детерминирован и не спит.

ПОЧЕМУ В STORE НЕ ХРАНИТСЯ СЫРОЙ ТОКЕН. Хранится только SHA-256 digest; сравнение — через
hmac.compare_digest (постоянное время). Даже дамп памяти store не выдаёт токен в пригодном для
предъявления виде. consume() атомарен: повторное использование (replay) невозможно, два
параллельных consume дают ровно один успех.
"""

import enum
import hashlib
import hmac
import secrets
import threading
import time as _time

# ── Параметры. Токен — 256 бит энтропии; TTL и лимит попыток намеренно малы. ──
TOKEN_BYTES = 32                 # secrets.token_urlsafe(32) -> >= 256 бит энтропии
TTL_SECONDS = 10 * 60            # grant живёт не дольше 10 минут
MAX_ATTEMPTS = 5                 # не больше 5 неверных предъявлений на один grant
MAX_TOKEN_LEN = 256             # разумный верхний предел длины предъявленной строки

# Локальный ограничитель по фактическому peer — для дешёвых malformed/invalid попыток.
PEER_MAX_FAILURES = 10
PEER_WINDOW_SECONDS = 5 * 60
PEER_BLOCK_SECONDS = 5 * 60
PEER_MAX_KEYS = 256


class Reason(enum.Enum):
    """Внутренние коды решения. Наружу пользователю дословно не отдаются."""
    VALID = "valid"
    MISSING = "missing"            # активного grant нет
    MALFORMED = "malformed"        # предъявлено не строкой / пусто / слишком длинно
    INVALID = "invalid"           # digest не совпал
    EXPIRED = "expired"           # истёк TTL
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    CONSUMED = "consumed"         # уже использован
    REPLACED = "replaced"         # вытеснен новым grant (историческое состояние)
    UNAVAILABLE = "unavailable"   # store в непригодном состоянии


class Decision(object):
    """Неизменяемый результат проверки/потребления grant. ok=False -> дальше нельзя."""

    __slots__ = ("ok", "reason")

    def __init__(self, ok, reason):
        self.ok = bool(ok)
        self.reason = reason

    def __eq__(self, other):
        return isinstance(other, Decision) and self.ok == other.ok and self.reason == other.reason

    def __repr__(self):   # ни токена, ни digest — только исход
        return "Decision(ok=%r, reason=%r)" % (self.ok, self.reason.value if isinstance(self.reason, Reason) else self.reason)


def _digest(raw):
    """SHA-256 hex от токена. Сырой токен нигде не сохраняется — только его digest."""
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


class LocalRecoveryGrantStore(object):
    """Хранилище ОДНОГО активного recovery-grant в памяти процесса.

    Инварианты:
      * не больше одного активного grant одновременно (issue() вытесняет прежний);
      * сырой токен не хранится — только SHA-256 digest;
      * сравнение через hmac.compare_digest;
      * время — только монотонные часы (перевод системного времени назад ничего не даёт);
      * consume() атомарен и одноразов; повторное использование невозможно;
      * перезапуск процесса очищает store сам собой (state только в памяти).
    """

    def __init__(self, clock=None):
        self._clock = clock or _time.monotonic
        self._lock = threading.RLock()
        self._digest = None       # SHA-256 hex активного токена; None = активного grant нет
        self._expires_at = 0.0    # монотонная метка истечения
        self._attempts = 0        # число неверных предъявлений текущего grant
        self._consumed = False    # текущий grant уже использован

    # ── выдача ────────────────────────────────────────────────────────────────
    def issue(self):
        """Создать новый grant, вытеснив прежний. -> сырой токен (только вызывающему)."""
        raw = secrets.token_urlsafe(TOKEN_BYTES)
        with self._lock:
            self._digest = _digest(raw)
            self._expires_at = self._clock() + TTL_SECONDS
            self._attempts = 0
            self._consumed = False
        return raw

    # ── внутренняя проверка (под замком) ──────────────────────────────────────
    def _evaluate(self, raw):
        if self._digest is None:
            return Reason.MISSING
        if self._consumed:
            return Reason.CONSUMED
        if not isinstance(raw, str) or not raw or len(raw) > MAX_TOKEN_LEN:
            return Reason.MALFORMED
        if self._attempts >= MAX_ATTEMPTS:
            return Reason.TOO_MANY_ATTEMPTS
        if self._clock() > self._expires_at:
            return Reason.EXPIRED
        if not hmac.compare_digest(self._digest, _digest(raw)):
            return Reason.INVALID
        return Reason.VALID

    # ── неизменяющая проверка ─────────────────────────────────────────────────
    def validate(self, raw):
        """Проверить токен, НЕ потребляя его. -> Decision."""
        with self._lock:
            r = self._evaluate(raw)
            return Decision(r is Reason.VALID, r)

    # ── учёт неверной попытки ─────────────────────────────────────────────────
    def record_failure(self, raw):
        """Учесть неверное предъявление. По достижении лимита grant становится непригодным.
        -> Decision о состоянии grant ПОСЛЕ учёта."""
        with self._lock:
            if self._digest is None:
                return Decision(False, Reason.MISSING)
            if self._consumed:
                return Decision(False, Reason.CONSUMED)
            self._attempts += 1
            if self._attempts >= MAX_ATTEMPTS:
                # Grant исчерпан — уничтожаем digest, дальше только новый tray-grant.
                self._digest = None
                self._expires_at = 0.0
                return Decision(False, Reason.TOO_MANY_ATTEMPTS)
            return Decision(False, Reason.INVALID)

    # ── атомарное одноразовое потребление ─────────────────────────────────────
    def consume(self, raw):
        """Атомарно проверить И потребить grant. Успех ровно один раз.

        При успехе digest немедленно уничтожается: повторный consume того же токена
        (replay) и параллельный второй consume вернут MISSING/CONSUMED. -> Decision."""
        with self._lock:
            r = self._evaluate(raw)
            if r is not Reason.VALID:
                return Decision(False, r)
            self._consumed = True
            self._digest = None
            self._expires_at = 0.0
            return Decision(True, Reason.VALID)

    # ── аннулирование ─────────────────────────────────────────────────────────
    def invalidate_all(self):
        """Аннулировать любой активный grant (перезапуск восстановления, ручной сброс)."""
        with self._lock:
            self._digest = None
            self._expires_at = 0.0
            self._attempts = 0
            self._consumed = False

    # ── диагностика без секретов ──────────────────────────────────────────────
    def active_metadata(self):
        """Безопасные метаданные для теста/диагностики: НИ токена, НИ digest.

        Возвращает только факты состояния. remaining_seconds округлён вниз."""
        with self._lock:
            has = self._digest is not None and not self._consumed
            remaining = 0
            if has:
                remaining = max(0, int(self._expires_at - self._clock()))
            return {
                "active": has,
                "attempts": self._attempts,
                "max_attempts": MAX_ATTEMPTS,
                "remaining_seconds": remaining,
                "consumed": self._consumed,
            }


class LocalRecoveryPeerLimiter(object):
    """Совместимый локальный ограничитель дешёвых неверных попыток по ФАКТИЧЕСКОМУ peer.

    Отдельный от auth_rate_limit по назначению, но той же модели: монотонные часы,
    ограниченный размер, вытеснение самых старых. Ключ — адрес ИЗ ТРАНСПОРТА (loopback);
    заголовки прокси сюда не передаются. Не создаёт глобальной вечной блокировки: только
    per-peer окно, поэтому один локальный клиент не может навсегда закрыть восстановление
    для всех — новый tray-grant всегда можно выдать и предъявить с чистого peer-счётчика.
    """

    def __init__(self, clock=None, max_keys=PEER_MAX_KEYS):
        self._clock = clock or _time.monotonic
        self._lock = threading.Lock()
        self._max_keys = int(max_keys)
        self._state = {}   # peer -> {"fails": [ts...], "blocked_until": float}

    def _prune(self, now):
        dead = [k for k, e in self._state.items()
                if e["blocked_until"] <= now
                and (not e["fails"] or (now - e["fails"][-1]) > PEER_WINDOW_SECONDS)]
        for k in dead:
            self._state.pop(k, None)
        if len(self._state) >= self._max_keys:
            ordered = sorted(self._state.items(),
                             key=lambda kv: max(kv[1]["fails"] or [kv[1]["blocked_until"]], default=0))
            for k, _v in ordered[:max(0, len(self._state) - (self._max_keys - 1))]:
                self._state.pop(k, None)

    def check(self, peer):
        """Разрешена ли попытка с этого peer. Не считает попытку. -> True/False."""
        if not peer:
            return True
        now = self._clock()
        with self._lock:
            e = self._state.get(peer)
            if not e:
                return True
            return not (e["blocked_until"] > now)

    def register_failure(self, peer):
        """Учесть неверную попытку. -> True, если peer теперь заблокирован."""
        if not peer:
            return False
        now = self._clock()
        with self._lock:
            if len(self._state) >= self._max_keys:
                self._prune(now)
            e = self._state.setdefault(peer, {"fails": [], "blocked_until": 0.0})
            if e["blocked_until"] > now:
                return True
            e["fails"] = [t for t in e["fails"] if (now - t) <= PEER_WINDOW_SECONDS]
            e["fails"].append(now)
            if len(e["fails"]) >= PEER_MAX_FAILURES:
                e["blocked_until"] = now + PEER_BLOCK_SECONDS
                e["fails"] = []
                return True
            return False

    def clear(self, peer):
        """Снять счётчики peer после успешного восстановления (если не заблокирован)."""
        if not peer:
            return False
        now = self._clock()
        with self._lock:
            e = self._state.get(peer)
            if not e or e["blocked_until"] > now:
                return False
            self._state.pop(peer, None)
            return True

    def size(self):
        with self._lock:
            return len(self._state)


# Открытая длина фрагмента и его префикс — единый источник для сервера и фронтенда.
URL_FRAGMENT_PREFIX = "local-admin-recovery="
