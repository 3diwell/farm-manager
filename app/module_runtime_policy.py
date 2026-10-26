# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — строгая политика для маршрутов модуля, которых нет в карте прав (26.09.2026).

ЗАЧЕМ. Модуль новее программы (или собран отдельно от неё) объявляет маршрут, о котором карта
прав этой версии программы (app/route_policy_registry.py) не знает. До 26.09.2026 из-за одного
такого маршрута модуль не загружался ЦЕЛИКОМ — так владелец и получал «модуль новее, чем знает
программа, и не ставится». Слово владельца: такой модуль всё равно должен установиться.

ЧТО ДЕЛАЕТ. Маршрут, которого нет в описи, получает СТРОГУЮ политику: при включённой
авторизации — только право admin (администратор); при выключенной общий гейт не проверяет
никого, как и для любого другого маршрута модуля. Мягче карты такая политика не бывает: ни
одному неизвестному маршруту не достаётся право ниже администратора, а маршрут, который карта
знает, получает своё право из описи — как раньше и тем же ключом (метод + шаблон пути), по
которому гейт ищет политику при каждом запросе.

ГРАНИЦЫ. Политики живут только в памяти процесса и заполняются ядром при загрузке модулей;
перезапуск собирает их заново вместе с самими маршрутами. В опись ALL_POLICIES они НЕ входят:
счётчики и сверки описи с исходниками прежние. Запись описи для того же метода и пути всегда
главнее — строгая политика её не перекрывает.

ЧИСТЫЙ МОДУЛЬ: стандартная библиотека и сам реестр; без БД, сети и файловой системы.
"""

from dataclasses import replace

from app import route_policy_registry as _reg
from app.route_access_control import EnforcedAccess

RUNTIME_FALLBACK_CAPABILITY = "admin"
RUNTIME_POLICY_PREFIX = "runtime:"


def is_runtime(policy):
    return bool(policy is not None and str(getattr(policy, "policy_id", "") or "").startswith(RUNTIME_POLICY_PREFIX))


def described_policy(method, path_template):
    """Политика маршрута модуля ТОЛЬКО из описи. None — карта этот маршрут не знает."""
    p = _reg.module_http_policy(method, path_template)
    return None if (p is None or is_runtime(p)) else p


def build(module_id, module_version, method, module_route, handler_name):
    """Строгая политика для маршрута модуля, которого нет в описи. -> RoutePolicy."""
    method = str(method).upper()
    full = "/api/mod/%s/%s" % (module_id, module_route)
    base = _reg._mk("HTTP", method, full, str(handler_name or ""), "module", "module_frontend", "SENSITIVE",
                    ("DATABASE", "FILESYSTEM", "NETWORK"), "NONE", RUNTIME_FALLBACK_CAPABILITY,
                    module_id=module_id, module_version=module_version, module_route=module_route,
                    notes="Маршрут модуля, которого нет в карте прав этой версии программы: доступ "
                          "только администратору до её обновления (26.09.2026).")
    access = EnforcedAccess.CAPABILITY
    return replace(base, enforced_access=access, required_capability=RUNTIME_FALLBACK_CAPABILITY,
                   auth_on_behavior=_reg._auth_on_behavior_for(access),
                   auth_off_behavior=_reg._auth_off_behavior_for(access),
                   policy_id="%s%s:%s:%s" % (RUNTIME_POLICY_PREFIX, module_id, method, module_route))


def register(policy):
    """Подключить строгую политику. -> False, если карта уже знает этот метод и путь (тогда
    строгая политика не нужна и не ставится) или путь не в пространстве своего модуля."""
    if not is_runtime(policy) or not str(policy.path).startswith("/api/mod/%s/" % policy.module_id):
        return False
    key = (policy.method, policy.path)
    if described_policy(policy.method, policy.path) is not None:
        return False
    _reg._RUNTIME_MODULE_HTTP_INDEX[key] = policy
    return True


def clear(module_id=None):
    """Снять строгие политики модуля (или все)."""
    idx = _reg._RUNTIME_MODULE_HTTP_INDEX
    for key in [k for k, p in idx.items() if module_id is None or p.module_id == module_id]:
        idx.pop(key, None)


def policies():
    """Текущие строгие политики (копия)."""
    return tuple(_reg._RUNTIME_MODULE_HTTP_INDEX.values())
