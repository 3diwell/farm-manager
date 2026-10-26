# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — чистый движок решений о доступе к WebSocket (Alpha 2.786).

ЧТО ЭТО. Единственное место, где из нормализованного состояния вызывающего получается
решение «принять соединение / отказать / отдать локальному режиму». Движок детерминирован,
не имеет памяти и не мутирует вход: одинаковое состояние всегда даёт одинаковый вердикт.

ЗАЧЕМ ОТДЕЛЬНО ОТ HTTP. Решение то же по смыслу, но точки применения две и они разные по
природе: у HTTP — один запрос, у WebSocket — рукопожатие ПЛЮС длительное соединение,
которое нужно перепроверять. Источники истины при этом ОБЩИЕ с HTTP: та же cookie, та же
серверная таблица сессий, та же запись пользователя, тот же флаг активности, те же роли и
capability. Отдельной системы авторизации для сокета не вводится.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ:
  * не знает про WebSocket-объекты, Starlette и FastAPI;
  * не открывает БД и не читает DATA_DIR;
  * не разбирает cookie и не хранит сессии;
  * не обращается к сети;
  * не пишет журнал и не видит ни логинов, ни токенов, ни идентификаторов сессий.
Вызывающий сам собирает состояние из штатных источников и передаёт сюда уже
нормализованные факты.

НЕРАЗГЛАШЕНИЕ. Наружу уходит ОДИН из трёх обобщённых кодов причины и код закрытия.
По ним нельзя понять, существует ли пользователь, отключён ли он, какая у него роль,
когда истекает сессия и какой у неё идентификатор. Проблемы уровня сессии — включая
«пользователя больше нет» и «пользователь отключён» — намеренно неотличимы друг от друга
и дают один и тот же код: иначе сокет стал бы оракулом существования учётных записей.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека. Импорт без побочных эффектов.
"""

import enum
from dataclasses import dataclass
from typing import FrozenSet, Optional

# Право, без которого телеметрию отдавать нельзя. То же самое, что у read-only маршрутов
# ядра: WebSocket — это поток чтения, а не канал управления.
REQUIRED_CAPABILITY = "view"

# Прикладные коды закрытия. ВАЖНО про доставку (проверено, а не предположено):
#   * отказ ДО accept() уходит как websocket.close без предшествующего websocket.accept,
#     поэтому ASGI-сервер отклоняет рукопожатие HTTP-ответом, и браузер видит 1006 —
#     прикладной код до него НЕ доходит. Код всё равно проставляется: он осмыслен для
#     нативных клиентов, для журналов и для тестов;
#   * отказ ПОСЛЕ accept() (периодическая перепроверка) доставляется браузеру как есть.
CLOSE_AUTH = 4401       # проблема уровня сессии или субъекта
CLOSE_FORBIDDEN = 4403  # сессия в порядке, прав не хватает
CLOSE_POLICY = 1008     # запасной код, если прикладные не поддерживаются

# Обобщённые причины. Ровно три, как и требует контракт неразглашения.
REASON_HANDSHAKE_AUTH = "ws_handshake_auth"   # не пустили на рукопожатии
REASON_SESSION_AUTH = "ws_session_auth"       # доступ потерян уже на открытом соединении
REASON_AUTHZ = "ws_authz"                     # не хватает права


class WsDecision(enum.Enum):
    ALLOW = "ALLOW"                      # принять соединение / продолжить
    REQUIRE_SESSION = "REQUIRE_SESSION"  # сессии нет вовсе
    SESSION_INVALID = "SESSION_INVALID"  # сессия есть, но негодная (истекла, отозвана, субъекта нет)
    USER_DISABLED = "USER_DISABLED"      # учётная запись отключена
    FORBIDDEN = "FORBIDDEN"              # роль неизвестна либо нет права view
    DEFER_AUTH_OFF = "DEFER_AUTH_OFF"    # авторизация выключена: локальный режим владельца


@dataclass(frozen=True)
class WsAuthState:
    """Нормализованное состояние вызывающего. Неизменяемо.

    capabilities=None означает РОЛЬ НЕИЗВЕСТНА (в модели ролей такой роли нет) — это отказ.
    Пустой frozenset() — известная роль без единого права, что не одно и то же.
    """
    security_enabled: bool
    session_present: bool = False
    session_valid: bool = False
    session_expired: bool = False
    session_revoked: bool = False
    user_exists: bool = False
    user_enabled: bool = False
    role: Optional[str] = None
    capabilities: Optional[FrozenSet[str]] = None

    @property
    def role_known(self):
        return self.capabilities is not None


@dataclass(frozen=True)
class WsVerdict:
    """Решение движка. reason — обобщённый безопасный код без данных о субъекте."""
    decision: WsDecision
    close_code: Optional[int] = None
    reason: str = ""

    @property
    def allowed(self):
        return self.decision in (WsDecision.ALLOW, WsDecision.DEFER_AUTH_OFF)


def evaluate(state, handshake=True):
    """Решение о доступе к WebSocket.

    state — WsAuthState. handshake=True для рукопожатия, False для перепроверки уже
    открытого соединения: набор правил одинаков, различается только код причины, чтобы
    в журнале было видно, где именно доступ потерян.

    Правила при ВКЛЮЧЁННОЙ авторизации — все обязательны:
      действующая сессия; она не истекла и не отозвана; субъект существует; субъект
      включён; роль известна; среди её прав есть view.

    При ВЫКЛЮЧЕННОЙ авторизации возвращается DEFER_AUTH_OFF: локальный режим владельца
    сохраняется без изменений, сессия не требуется и не перепроверяется.
    """
    if not isinstance(state, WsAuthState):
        # Неизвестная форма состояния — отказ, а не разрешение.
        return WsVerdict(WsDecision.SESSION_INVALID, CLOSE_AUTH, _auth_reason(handshake))

    if not state.security_enabled:
        return WsVerdict(WsDecision.DEFER_AUTH_OFF, None, "")

    _auth = _auth_reason(handshake)

    # ---- Уровень сессии. Все отказы здесь неотличимы снаружи. ----
    if not state.session_present:
        return WsVerdict(WsDecision.REQUIRE_SESSION, CLOSE_AUTH, _auth)
    if state.session_revoked or state.session_expired or not state.session_valid:
        return WsVerdict(WsDecision.SESSION_INVALID, CLOSE_AUTH, _auth)
    # «Пользователя нет» и «пользователь отключён» дают ОДИН код: сокет не должен
    # подсказывать, существует ли учётная запись.
    if not state.user_exists:
        return WsVerdict(WsDecision.SESSION_INVALID, CLOSE_AUTH, _auth)
    if not state.user_enabled:
        return WsVerdict(WsDecision.USER_DISABLED, CLOSE_AUTH, _auth)

    # ---- Уровень прав. ----
    if not state.role_known:
        return WsVerdict(WsDecision.FORBIDDEN, CLOSE_FORBIDDEN, REASON_AUTHZ)
    if REQUIRED_CAPABILITY not in state.capabilities:
        return WsVerdict(WsDecision.FORBIDDEN, CLOSE_FORBIDDEN, REASON_AUTHZ)

    return WsVerdict(WsDecision.ALLOW, None, "")


def needs_revalidation(state):
    """Нужно ли перепроверять уже открытое соединение.

    При выключенной авторизации — нет: сессии не существует, проверять нечего, и
    локальный режим владельца не должен обрастать периодическими обращениями к БД.
    """
    return bool(getattr(state, "security_enabled", False))


def _auth_reason(handshake):
    return REASON_HANDSHAKE_AUTH if handshake else REASON_SESSION_AUTH
