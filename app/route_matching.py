# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — определение ФАКТИЧЕСКИ совпавшего маршрута (Alpha 2.784).

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Общий гейт — это HTTP-middleware, а он работает ДО того, как
маршрутизатор выбрал обработчик: `scope["route"]` на этом этапе ещё не заполнен. Значит,
привязать запрос к записи реестра нужно самостоятельно. Единственный безопасный способ —
спросить у самого фреймворка теми же средствами, которыми через мгновение воспользуется
маршрутизатор.

ЧТО ЗАПРЕЩЕНО И ПОЧЕМУ. Ни startswith, ни поиск подстроки, ни самодельный regex, ни
сырой URL в качестве ключа реестра. Любой из этих способов расходится с фактической
маршрутизацией на параметрах пути, кодировании, повторных слэшах и регистре — а расхождение
между «кого пустил гейт» и «кто на самом деле выполнился» и есть классическая дыра обхода
авторизации. Здесь используется route.matches(scope) и засчитывается ТОЛЬКО Match.FULL,
то есть ровно то решение, которое примет маршрутизатор.

ПОВЕДЕНИЕ НА КРАЯХ (доказано тестами, а не предположено):
  * Match.PARTIAL (путь есть, метод не тот) НЕ считается совпадением: запрос уходит дальше
    и получает штатный 405, а не 401/403/500.
  * Ничего не совпало — тоже дальше: неизвестный URL обязан остаться 404, гейт не должен
    превращать опечатку в ошибку доступа и подтверждать существование путей.
  * HEAD. Поведение РАЗНОЕ у двух классов маршрутов, и это проверено, а не предположено:
      - APIRoute (всё, что объявлено декораторами @app.get/@app.post в server.py) хранит
        ровно объявленные методы. HEAD там даёт PARTIAL, то есть штатный 405, и никакой
        политики не требует.
      - starlette.routing.Route (маршруты, которые создаёт сам FastAPI: /docs, /redoc,
        /openapi.json, /docs/oauth2-redirect) добавляет HEAD к GET автоматически. Там
        HEAD даёт FULL и НАСЛЕДУЕТ политику GET, а не получает отдельную выдуманную.
    Поэтому приведение HEAD -> GET делается только когда маршрут действительно объявляет
    GET: выдумывать HEAD-политику там, где фреймворк отдаёт 405, было бы ложью.
  * OPTIONS. Отдельных OPTIONS-маршрутов в приложении нет, CORS-middleware удалён в 2.775,
    поэтому OPTIONS даёт PARTIAL и штатный 405. Собственная политика ему не нужна.

ЧИСТЫЙ МОДУЛЬ: импортирует только Starlette (сопоставление маршрутов) и стандартную
библиотеку. Не импортирует server.py, не открывает БД и DATA_DIR, не читает config,
не обращается к сети, не принимает решений о доступе и не пишет журнал.
"""

from dataclasses import dataclass

from starlette.routing import Match

# Модули-плагины регистрируются ядром строго под этим префиксом (ModuleCore.add_route).
# Это классификация УЖЕ НАЙДЕННОГО шаблона маршрута, а не сопоставление URL: сам маршрут
# определён фреймворком выше. Нужна, чтобы отличать ядро (обязана быть политика) от
# модулей (до Alpha 2.785 работают по прежней модели).
MODULE_ROUTE_PREFIX = "/api/mod/"


@dataclass(frozen=True)
class ResolvedRoute:
    """Фактически совпавший маршрут. Неизменяем."""
    path_template: str      # шаблон маршрута ('/api/printer/{pid}/webrtc'), НЕ сырой URL
    method: str             # метод для поиска политики: HEAD приведён к GET
    raw_method: str         # метод как пришёл в запросе
    endpoint_name: str      # имя функции-обработчика
    is_module_route: bool   # маршрут установленного модуля, а не ядра


def resolve_matched_route(routes, scope):
    """Найти маршрут, который выберет маршрутизатор для этого scope.

    routes — список маршрутов приложения (request.app.routes), включая добавленные
    модулями в рантайме. scope — ASGI-scope запроса (request.scope).

    -> ResolvedRoute, если совпадение полное; None, если полного совпадения нет.
    None означает «пропустить дальше без вмешательства»: пусть фреймворк сам выдаст
    404, 405 или редирект на канонический путь.
    """
    for route in routes:
        match, _child = route.matches(scope)
        if match is not Match.FULL:
            continue
        path_template = getattr(route, "path", "") or ""
        raw_method = str(scope.get("method") or "").upper()
        return ResolvedRoute(
            path_template=path_template,
            method=_policy_method(raw_method, route),
            raw_method=raw_method,
            endpoint_name=_endpoint_name(route),
            is_module_route=path_template.startswith(MODULE_ROUTE_PREFIX),
        )
    return None


def _policy_method(raw_method, route):
    """HEAD, отданный GET-маршрутом самим фреймворком, ищет политику как GET.

    Приведение делается ТОЛЬКО когда маршрут действительно объявляет GET: если когда-нибудь
    появится отдельный HEAD-маршрут, он получит собственную политику, а не чужую.
    """
    if raw_method == "HEAD":
        methods = getattr(route, "methods", None) or ()
        if "GET" in methods:
            return "GET"
    return raw_method


def _endpoint_name(route):
    """Имя обработчика: сперва сама функция, затем имя маршрута."""
    endpoint = getattr(route, "endpoint", None)
    name = getattr(endpoint, "__name__", None)
    if name:
        return name
    return getattr(route, "name", "") or ""
