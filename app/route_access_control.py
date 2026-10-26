# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — чистый движок решений о доступе к маршруту (Alpha 2.784).

ЧТО ЭТО. Единственное место, где из объявленной политики маршрута и состояния сессии
получается решение «пустить / потребовать вход / отказать / отдать обработчику». Движок
детерминирован и не имеет памяти: одинаковый вход всегда даёт одинаковый выход.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ:
  * Это НЕ реестр маршрутов. Какая политика у какого маршрута — в app/route_policy_registry.py.
  * Это НЕ сопоставление URL с маршрутом. Фактически совпавший маршрут определяет
    app/route_matching.py средствами самого веб-фреймворка.
  * Это НЕ полное закрытие S-1. При выключенной авторизации движок сознательно сохраняет
    прежний локальный режим владельца; сетевые предпосылки — отдельный поздний этап.

ГРАНИЦЫ ЭТАПОВ. Решения принимаются для маршрутов, чей этап перечислен в ACTIVE_STAGES:
ядро с Alpha 2.784 (CORE_2_784) и маршруты модулей с Alpha 2.785 (MODULE_2_785). WebSocket
(WEBSOCKET_DEFERRED_2_786) по-прежнему возвращает «отдать прежней модели» — его поведение
не меняется до своего этапа. Историческое значение MODULE_DEFERRED_2_785 сохранено: оно
описывает, как маршруты модулей обслуживались до 2.785, и продолжает означать «прежняя
модель», чтобы старый или сторонний модуль не получил доступа по недосмотру.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека. Не импортирует server.py, FastAPI и Starlette,
не открывает БД и DATA_DIR, не читает config, не обращается к сети, не пишет журнал.
Импорт не имеет побочных эффектов. Коды причин безопасны: в них нет URL, параметров пути,
тела запроса, имён пользователей и секретов.
"""

import enum
from dataclasses import dataclass
from typing import FrozenSet, Optional


class EnforcementStage(enum.Enum):
    """На каком этапе маршрут получает принудительную проверку прав."""
    CORE_2_784 = "CORE_2_784"                            # ядро: решает этот движок, начиная с 2.784
    MODULE_2_785 = "MODULE_2_785"                        # модуль: решает этот движок, начиная с 2.785
    MODULE_DEFERRED_2_785 = "MODULE_DEFERRED_2_785"      # модуль: прежняя модель (историческое значение)
    WEBSOCKET_2_786 = "WEBSOCKET_2_786"                  # /ws: решает app/websocket_access_control.py с 2.786
    WEBSOCKET_DEFERRED_2_786 = "WEBSOCKET_DEFERRED_2_786"  # /ws: прежняя модель (историческое значение)


# Этапы, на которых решение принимает ЭТОТ движок. Всё остальное отдаётся прежней модели
# либо, если этап неизвестен, трактуется как отсутствие политики — то есть отказ.
ACTIVE_STAGES = (EnforcementStage.CORE_2_784, EnforcementStage.MODULE_2_785)


class EnforcedAccess(enum.Enum):
    """Объявленная граница доступа маршрута — то, как ДОЛЖНО быть, начиная с 2.784.

    Отличать от AccessBoundary в реестре: та описывает историческое поведение 2.783.
    """
    PUBLIC = "PUBLIC"                    # доступен без сессии: статика, handshake, вход в систему
    SESSION_ONLY = "SESSION_ONLY"        # нужна действующая сессия, конкретное право не требуется
    CAPABILITY = "CAPABILITY"            # нужна сессия и объявленное право из модели ролей
    HANDLER_ADMIN = "HANDLER_ADMIN"      # нужна сессия; решение об admin принимает _require_admin
    SYSTEM_ADMIN = "SYSTEM_ADMIN"        # целиком за _require_system_admin (2.778): loopback/admin
    CALLBACK_SECRET = "CALLBACK_SECRET"  # целиком за _require_slicer_callback (2.781): ключ+loopback
    LOCAL_RECOVERY = "LOCAL_RECOVERY"    # целиком за local-recovery guard (2.798): loopback+одноразовый tray-токен
    DEFERRED = "DEFERRED"                # решение отложено до своего этапа (модули, WebSocket)


class AccessDecision(enum.Enum):
    """Что общий гейт обязан сделать с запросом."""
    ALLOW = "ALLOW"                                      # пропустить к обработчику
    REQUIRE_SESSION = "REQUIRE_SESSION"                  # 401: нет действующей сессии
    FORBIDDEN = "FORBIDDEN"                              # 403: сессия есть, прав не хватает
    DEFER_TO_HANDLER = "DEFER_TO_HANDLER"                # решает собственный guard обработчика
    DEFER_TO_LEGACY_MODULE = "DEFER_TO_LEGACY_MODULE"    # прежняя модель модулей (до 2.785)
    DEFER_TO_WEBSOCKET = "DEFER_TO_WEBSOCKET"            # прежняя модель WebSocket (до 2.786)
    POLICY_MISSING = "POLICY_MISSING"                    # 500 fail-closed: политика не объявлена


# ---- Безопасные коды причин (попадают в журнал; в ответ уходит только общий текст) ----
REASON_POLICY_MISSING = "route_policy_missing"
REASON_CORE_MARKED_DEFERRED = "core_route_marked_deferred"
REASON_CAPABILITY_NOT_DECLARED = "capability_not_declared"
REASON_UNKNOWN_ACCESS = "unknown_enforced_access"
REASON_AUTH_OFF = "auth_off_local_owner"
REASON_PUBLIC = "public_route"
REASON_NO_SESSION = "no_session"
REASON_USER_DISABLED = "user_disabled"
REASON_UNKNOWN_ROLE = "unknown_role"
REASON_SESSION_OK = "session_ok"
REASON_CAPABILITY_OK = "capability_ok"
REASON_CAPABILITY_MISSING = "capability_missing"
REASON_HANDLER_ADMIN = "handler_admin_guard"
REASON_SYSTEM_ADMIN = "system_admin_guard"
REASON_CALLBACK_SECRET = "callback_secret_guard"
REASON_LOCAL_RECOVERY = "local_recovery_guard"
REASON_MODULE_LEGACY = "module_legacy_until_2_785"
REASON_WEBSOCKET_LEGACY = "websocket_legacy_until_2_786"


@dataclass(frozen=True)
class SecurityContext:
    """Состояние вызывающего. Неизменяем: движок не правит вход и не хранит состояние.

    capabilities=None означает РОЛЬ НЕИЗВЕСТНА (в модели ролей такой роли нет) — это отказ.
    Пустой frozenset() — известная роль без единого права, что не одно и то же.
    """
    security_enabled: bool
    has_session: bool = False
    user_enabled: bool = False
    role: Optional[str] = None
    capabilities: Optional[FrozenSet[str]] = None

    @property
    def role_known(self):
        return self.capabilities is not None


@dataclass(frozen=True)
class Decision:
    """Решение движка. reason — безопасный код без данных запроса."""
    outcome: AccessDecision
    reason: str
    required_capability: Optional[str] = None

    @property
    def allowed(self):
        return self.outcome is AccessDecision.ALLOW

    @property
    def denied(self):
        return self.outcome in (AccessDecision.REQUIRE_SESSION,
                                AccessDecision.FORBIDDEN,
                                AccessDecision.POLICY_MISSING)


def decide(policy, ctx):
    """Решение о доступе к ФАКТИЧЕСКИ совпавшему маршруту.

    policy — запись реестра (утиная типизация: enforcement_stage / enforced_access /
    required_capability). None означает «маршрут ядра найден, но политики нет» — отказ.
    ctx — SecurityContext.

    ОТСУТСТВИЕ ПОЛИТИКИ = ОТКАЗ. Новый маршрут ядра, забытый в реестре, не получает
    доступа по умолчанию: он не доходит до обработчика и даёт 500. Это сознательно
    заметная поломка, а не тихая дыра.
    """
    if policy is None:
        return Decision(AccessDecision.POLICY_MISSING, REASON_POLICY_MISSING)

    stage = getattr(policy, "enforcement_stage", None)
    access = getattr(policy, "enforced_access", None)

    # ---- Этапы, до которых поведение не меняется ----
    if stage is EnforcementStage.MODULE_DEFERRED_2_785:
        return Decision(AccessDecision.DEFER_TO_LEGACY_MODULE, REASON_MODULE_LEGACY)
    # Оба этапа WebSocket отдаются наружу: решение по сокету принимает
    # app/websocket_access_control.py, а этот движок обслуживает только HTTP.
    if stage in (EnforcementStage.WEBSOCKET_DEFERRED_2_786, EnforcementStage.WEBSOCKET_2_786):
        return Decision(AccessDecision.DEFER_TO_WEBSOCKET, REASON_WEBSOCKET_LEGACY)
    if stage not in ACTIVE_STAGES:
        return Decision(AccessDecision.POLICY_MISSING, REASON_POLICY_MISSING)

    # Маршрут активного этапа, помеченный DEFERRED, — противоречие: этап наступил,
    # а решения нет. Отказ, а не тихое разрешение.
    if access is EnforcedAccess.DEFERRED:
        return Decision(AccessDecision.POLICY_MISSING, REASON_CORE_MARKED_DEFERRED)
    if not isinstance(access, EnforcedAccess):
        return Decision(AccessDecision.POLICY_MISSING, REASON_UNKNOWN_ACCESS)

    # ---- АВТОРИЗАЦИЯ ВЫКЛЮЧЕНА ----
    # Локальный режим владельца сохраняется без изменений: общий гейт проверок не делает.
    # Собственные guard обработчиков продолжают работать самостоятельно и НЕ ослабляются:
    # system-admin остаётся loopback-only, callback требует ключ и loopback, а _require_admin
    # без сессии отказывает всегда. Это не закрытие S-1 — это сохранение статус-кво 2.783.
    if not ctx.security_enabled:
        if access in (EnforcedAccess.HANDLER_ADMIN,
                      EnforcedAccess.SYSTEM_ADMIN,
                      EnforcedAccess.CALLBACK_SECRET,
                      EnforcedAccess.LOCAL_RECOVERY):
            return Decision(AccessDecision.DEFER_TO_HANDLER, _guard_reason(access))
        return Decision(AccessDecision.ALLOW, REASON_AUTH_OFF)

    # ---- АВТОРИЗАЦИЯ ВКЛЮЧЕНА ----
    if access is EnforcedAccess.PUBLIC:
        return Decision(AccessDecision.ALLOW, REASON_PUBLIC)

    # Границы, которые целиком принадлежат обработчику. Сессия здесь НЕ требуется гейтом:
    # у нативного слайсера её нет по определению, а system-admin сам различает 401 и 403.
    if access is EnforcedAccess.CALLBACK_SECRET:
        return Decision(AccessDecision.DEFER_TO_HANDLER, REASON_CALLBACK_SECRET)
    if access is EnforcedAccess.SYSTEM_ADMIN:
        return Decision(AccessDecision.DEFER_TO_HANDLER, REASON_SYSTEM_ADMIN)
    # Local recovery: сессия НЕ требуется (пароль как раз забыт). Гейт отдаёт запрос
    # обработчику, а тот проверяет loopback-peer и одноразовый tray-токен.
    if access is EnforcedAccess.LOCAL_RECOVERY:
        return Decision(AccessDecision.DEFER_TO_HANDLER, REASON_LOCAL_RECOVERY)

    # Дальше без действующей сессии не проходит никто.
    if not ctx.has_session:
        return Decision(AccessDecision.REQUIRE_SESSION, REASON_NO_SESSION)
    if not ctx.user_enabled:
        return Decision(AccessDecision.REQUIRE_SESSION, REASON_USER_DISABLED)
    if not ctx.role_known:
        return Decision(AccessDecision.FORBIDDEN, REASON_UNKNOWN_ROLE)

    if access is EnforcedAccess.HANDLER_ADMIN:
        # Сессия проверена гейтом, решение об admin остаётся за _require_admin.
        return Decision(AccessDecision.DEFER_TO_HANDLER, REASON_HANDLER_ADMIN)
    if access is EnforcedAccess.SESSION_ONLY:
        return Decision(AccessDecision.ALLOW, REASON_SESSION_OK)
    if access is EnforcedAccess.CAPABILITY:
        cap = getattr(policy, "required_capability", None)
        if not cap:
            return Decision(AccessDecision.POLICY_MISSING, REASON_CAPABILITY_NOT_DECLARED)
        if cap in ctx.capabilities:
            return Decision(AccessDecision.ALLOW, REASON_CAPABILITY_OK, required_capability=cap)
        return Decision(AccessDecision.FORBIDDEN, REASON_CAPABILITY_MISSING, required_capability=cap)

    return Decision(AccessDecision.POLICY_MISSING, REASON_UNKNOWN_ACCESS)


def needs_session_state(policy):
    """Зависит ли решение по этому маршруту от состояния сессии.

    Позволяет гейту не трогать хранилище сессий там, где ответ движка от него не
    зависит: статика, handshake, вход в систему, а также границы, целиком отданные
    guard обработчика. Это оптимизация, а НЕ отдельная ветка решений: для таких
    маршрутов decide() возвращает одно и то же при любой сессии, что проверяется тестом.
    """
    if policy is None:
        return False
    if getattr(policy, "enforcement_stage", None) not in ACTIVE_STAGES:
        return False
    return getattr(policy, "enforced_access", None) not in (
        EnforcedAccess.PUBLIC,
        EnforcedAccess.SYSTEM_ADMIN,
        EnforcedAccess.CALLBACK_SECRET,
        EnforcedAccess.LOCAL_RECOVERY,
        EnforcedAccess.DEFERRED,
    )


def _guard_reason(access):
    if access is EnforcedAccess.SYSTEM_ADMIN:
        return REASON_SYSTEM_ADMIN
    if access is EnforcedAccess.CALLBACK_SECRET:
        return REASON_CALLBACK_SECRET
    if access is EnforcedAccess.LOCAL_RECOVERY:
        return REASON_LOCAL_RECOVERY
    return REASON_HANDLER_ADMIN
