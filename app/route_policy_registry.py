# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — декларативный реестр маршрутов (Alpha 2.783, расширен в 2.784).

ЧТО ЭТО. Машинно-проверяемая опись ВСЕХ маршрутов приложения: HTTP-маршрутов ядра,
WebSocket и маршрутов установленных модулей. Для каждого записано ДВА независимых слоя:

  1. Поля current_* — ФАКТИЧЕСКОЕ поведение Alpha 2.782/2.783. Это исторические данные:
     как система вела себя ДО явной карты прав. Их нельзя переписывать под новую модель,
     иначе исчезнет база для сравнения и semantic access diff станет недоказуемым.
  2. Поля enforcement_stage / enforced_access / required_capability / auth_*_behavior —
     объявленная карта прав Alpha 2.784. Это то, как ДОЛЖНО быть.

Начиная с Alpha 2.784 второй слой ИСПОЛЬЗУЕТСЯ В РАНТАЙМЕ: общий гейт server.py находит
фактически совпавший маршрут (app/route_matching.py) и принимает решение движком
(app/route_access_control.py). Сам реестр по-прежнему остаётся ДАННЫМИ — он ничего не
разрешает и не запрещает, решения принимает движок.

ГРАНИЦЫ ЭТАПА 2.784 — читать обязательно:
  * Принудительная проверка включена ТОЛЬКО для HTTP-маршрутов ядра (CORE_2_784).
  * Маршруты модулей помечены MODULE_DEFERRED_2_785 и работают по прежней модели.
  * WebSocket помечен WEBSOCKET_DEFERRED_2_786 и работает по прежней модели.
  * При ВЫКЛЮЧЕННОЙ авторизации локальный режим владельца сохранён без изменений.
  * Это НЕ закрытие S-1: сетевые предпосылки, bind и миграция — отдельный поздний этап.
    Собственные guard обработчиков (2.778–2.782) остаются независимыми границами.

ЗАЧЕМ. Чтобы дальнейшие этапы опирались на полную опись, а не на память: тесты
tools/test_route_policy_registry.py и tools/test_core_route_permissions.py сверяют реестр
с исходниками и краснеют при любом расхождении — новый маршрут без записи, удалённый
маршрут, изменение метода, пути, обработчика, состава _GATE_EXCLUDE, handler-level guard
или маршрут ядра, оставшийся без объявленной политики.

ПРАВИЛО СОПРОВОЖДЕНИЯ. Любое изменение состава маршрутов, их методов, обработчиков или
защит обязано сопровождаться обновлением этого файла — иначе тест красный. Новый маршрут
ядра без объявленной политики не получает доступа по умолчанию: он не доходит до
обработчика и даёт 500.

ЧИСТЫЙ МОДУЛЬ: стандартная библиотека плюс app/route_access_control.py (тоже чистая
модель данных без зависимостей). Не импортирует server.py и веб-фреймворк, не открывает
БД и DATA_DIR, не обращается к сети, не регистрирует маршруты, не выполняет авторизацию
и не содержит секретов. Импорт не имеет побочных эффектов.
"""

import enum
from dataclasses import dataclass
from typing import Optional, Tuple

from app.route_access_control import EnforcedAccess, EnforcementStage


class RouteKind(enum.Enum):
    HTTP = "HTTP"
    WEBSOCKET = "WEBSOCKET"


class AccessBoundary(enum.Enum):
    """Через какую границу доступа маршрут проходит ФАКТИЧЕСКИ."""
    PUBLIC = "PUBLIC"                                # вне /api/, статика и логотипы
    AUTH_NAMESPACE_BYPASS = "AUTH_NAMESPACE_BYPASS"  # /api/auth/* — гейт пропускает по префиксу
    SESSION_GATE = "SESSION_GATE"                    # обычный маршрут общего гейта
    HANDLER_ADMIN = "HANDLER_ADMIN"                  # _require_admin в обработчике
    SYSTEM_ADMIN = "SYSTEM_ADMIN"                    # _require_system_admin (2.778)
    CALLBACK_SECRET = "CALLBACK_SECRET"              # _require_slicer_callback (2.781)
    LOCAL_RECOVERY = "LOCAL_RECOVERY"                # локальное восстановление админа (2.798): loopback+одноразовый tray-токен


class AuthOffScope(enum.Enum):
    """Кому маршрут доступен при ВЫКЛЮЧЕННОЙ авторизации (текущее состояние по умолчанию)."""
    LAN_ALLOWED = "LAN_ALLOWED"            # любому клиенту сети: гейт не выполняет проверок
    LOOPBACK_ONLY = "LOOPBACK_ONLY"        # только с этого компьютера (system-admin)
    CALLBACK_LOOPBACK = "CALLBACK_LOOPBACK"  # только с этого компьютера И с ключом интеграции
    DENIED_ALWAYS = "DENIED_ALWAYS"        # недоступен вообще: _require_admin без сессии -> отказ
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Sensitivity(enum.Enum):
    PUBLIC = "PUBLIC"
    OPERATIONAL = "OPERATIONAL"
    SENSITIVE = "SENSITIVE"
    SECRET_BEARING = "SECRET_BEARING"


class SideEffect(enum.Enum):
    NONE = "NONE"
    DATABASE = "DATABASE"
    FILESYSTEM = "FILESYSTEM"
    CONFIG = "CONFIG"
    PRINTER = "PRINTER"
    NETWORK = "NETWORK"
    SUBPROCESS = "SUBPROCESS"
    QUEUE = "QUEUE"
    RECOVERY = "RECOVERY"
    MODULE_STATE = "MODULE_STATE"
    SESSION_STATE = "SESSION_STATE"
    AUDIT = "AUDIT"


class HandlerGuard(enum.Enum):
    NONE = "NONE"
    HANDLER_ADMIN = "HANDLER_ADMIN"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    CALLBACK_SECRET = "CALLBACK_SECRET"
    LOCAL_RECOVERY = "LOCAL_RECOVERY"


# Состав _GATE_EXCLUDE из server.py. Зеркало, а не источник истины: тест сверяет их
# посимвольно и краснеет при расхождении.
GATE_EXCLUDE_PATHS = frozenset((
    "/api/slicer-hook", "/api/version", "/api/server", "/api/connection", "/api/files/local",
))

# Префикс, который _auth_gate пропускает мимо проверок отдельной строкой условия.
AUTH_NAMESPACE_PREFIX = "/api/auth/"

MUTATING_METHODS = frozenset(("POST", "PUT", "PATCH", "DELETE"))

# Alpha 2.794: read_only выводился ИСКЛЮЧИТЕЛЬНО из HTTP-метода, из-за чего изменяющий метод
# автоматически означал мутацию. Маршруты модулей, которые доказанно НИЧЕГО не пишут (разбор графа
# вызовов обработчика: только SELECT, ни INSERT/UPDATE/DELETE, ни commit), перечислены здесь.
# Список ЯВНЫЙ и короткий — он фиксирует исключения, а не отменяет правило; на маршруты ядра
# (policy_id=None) не влияет.
# 3.0: cost.calculate из списка убран. Модуль «Себестоимость печати» удалён по слову владельца,
# под тем же id стоит «Расчёт заказа»: его расчёт разбирает загруженный файл во временной папке и
# обновляет кэш моделей принтеров в своей базе — это запись, и POST честно считается изменяющим.
READ_ONLY_DESPITE_METHOD = frozenset((
    "inventory.spool.bulk_delete_preview",   # inv_bulk_delete_preview: классификация, без изменений
))


# ═══════════════════════════════════════════════════════════════════════════════
# КАРТА ПРАВ Alpha 2.784. Ниже — только объявленная модель; фактическое историческое
# поведение 2.783 живёт в полях current_* и этими решениями НЕ переписывается.
# ═══════════════════════════════════════════════════════════════════════════════


class AuthOnBehavior(enum.Enum):
    """Что происходит при ВКЛЮЧЁННОЙ авторизации."""
    ALLOW_ANONYMOUS = "ALLOW_ANONYMOUS"        # пускаем без сессии (статика, handshake, вход)
    REQUIRE_SESSION = "REQUIRE_SESSION"        # нужна действующая сессия, право не проверяем
    REQUIRE_CAPABILITY = "REQUIRE_CAPABILITY"  # нужна сессия и объявленное право
    HANDLER_DECIDES = "HANDLER_DECIDES"        # решает собственный guard обработчика
    LEGACY_UNCHANGED = "LEGACY_UNCHANGED"      # прежняя модель (модули до 2.785, /ws до 2.786)


class AuthOffBehavior(enum.Enum):
    """Что происходит при ВЫКЛЮЧЕННОЙ авторизации — текущий режим владельца."""
    ALLOW_LOCAL_OWNER = "ALLOW_LOCAL_OWNER"  # как в 2.783: общий гейт проверок не делает
    HANDLER_DECIDES = "HANDLER_DECIDES"      # guard обработчика продолжает работать сам
    LEGACY_UNCHANGED = "LEGACY_UNCHANGED"    # прежняя модель модулей и WebSocket


# Особые решения владельца (Alpha 2.784). Каждое СУЖАЕТ или СОХРАНЯЕТ доступ, ни одно
# не расширяет. Причины — в notes соответствующих строк и в CURRENT_STATE.md.
_SPECIAL_ENFORCED = {
    # Диагностика, меняющая состояние сервера или работающая с потоком данных принтера.
    "POST /api/diagnostics/bambu-sniff/start": (EnforcedAccess.CAPABILITY, "admin"),
    "POST /api/diagnostics/bambu-sniff/stop":  (EnforcedAccess.CAPABILITY, "admin"),
    "POST /api/diagnostics/verbose":           (EnforcedAccess.CAPABILITY, "admin"),
    "POST /api/diagnostics/monitor":           (EnforcedAccess.CAPABILITY, "admin"),
    "POST /api/diagnostics/clear":             (EnforcedAccess.CAPABILITY, "admin"),
    # 2.980 (R-092): сырая запись сетевых объявлений — открывает сокеты и пишет файл.
    "POST /api/diagnostics/net-capture/start": (EnforcedAccess.CAPABILITY, "admin"),
    "POST /api/diagnostics/net-capture/stop":  (EnforcedAccess.CAPABILITY, "admin"),
    "GET /api/diagnostics/net-capture":        (EnforcedAccess.CAPABILITY, "admin"),
    # НЕ административная диагностика: приёмник ошибок браузерного интерфейса
    # (Vue errorHandler, window.onerror). Его вызывают обычные пользователи, поэтому
    # admin-only здесь лишил бы operator/observer возможности сообщать о сбоях.
    "POST /api/diagnostics/client":            (EnforcedAccess.SESSION_ONLY, None),
    # Alpha 2.823: файловый менеджер принтеров — ЧТЕНИЕ. Отдельное узкое право
    # printer_files_read (admin/operator в _ROLE_PERMS): листинг файлов устройства (2.823) —
    # операция оператора, не наблюдателя (2.823). Удаление сюда НЕ входит (2.823): delete и
    # settings закрыты границей SYSTEM_ADMIN обработчика (ветвь 3) + предохранителем (2.823).
    "GET /api/printer-files/capabilities":     (EnforcedAccess.CAPABILITY, "printer_files_read"),
    "GET /api/printer-files/storages":         (EnforcedAccess.CAPABILITY, "printer_files_read"),
    "POST /api/printer-files/list":            (EnforcedAccess.CAPABILITY, "printer_files_read"),
    #  2.989: картинка предпросмотра — то же чтение файлов принтера, что и листинг:
    #  право printer_files_read, наблюдателю ни к чему содержимое накопителя.
    "GET /api/printer-files/preview":          (EnforcedAccess.CAPABILITY, "printer_files_read"),
    # Alpha 2.825: resolve файла для печати — операция ЧТЕНИЯ (листинг + проверка);
    # команды принтеру не шлёт; старт — прежний POST /api/printer/{pid}/cmd (operate, 2.825).
    "POST /api/printer-files/select-for-print": (EnforcedAccess.CAPABILITY, "printer_files_read"),
    # 2.980 (R-092): поиск принтеров в сети. Право «заводить принтеры» (printer_write) нужно и на
    # ЧТЕНИЕ снимка: в нём видны адреса, серийные номера и имена устройств сети — наблюдателю
    # это ни к чему. Тот же приём, что у файлов принтеров выше: общее правило прав не трогаем,
    # а доступ закрываем здесь.
    "POST /api/printer-discovery/start":       (EnforcedAccess.CAPABILITY, "printer_write"),
    "GET /api/printer-discovery":              (EnforcedAccess.CAPABILITY, "printer_write"),
    "POST /api/printer-discovery/stop":        (EnforcedAccess.CAPABILITY, "printer_write"),
    "POST /api/printer-discovery/rebind":      (EnforcedAccess.CAPABILITY, "printer_write"),
    # Только устанавливает/получает видеопоток камеры; команду оборудованию не шлёт.
    "POST /api/printer/{pid}/webrtc":          (EnforcedAccess.CAPABILITY, "view"),
    # Системный журнал: IP принтеров, серийные номера, имена файлов, локальные пути.
    "GET /api/logs/download":                  (EnforcedAccess.CAPABILITY, "admin"),
    # Alpha 2.789. Встроенный файловый менеджер даёт обзор ВСЕГО диска (это его назначение,
    # см. FILE_MANAGER_ENABLED). До 2.789 три его маршрута были GET и потому получали общее
    # право view — то есть при включённой авторизации observer мог перечислять любые папки
    # и читать превью любого файла, доступного процессу. Обзор диска сохранён, но право
    # приведено к фактическому назначению: менеджер открывается ТОЛЬКО из действий уровня
    # project/operate (добавить файлы в задачи, файлы проекта, импорт плана, печать).
    "GET /api/fs/list":                        (EnforcedAccess.CAPABILITY, "project"),
    "GET /api/fs/thumb":                       (EnforcedAccess.CAPABILITY, "project"),
    "GET /api/fs/roots":                       (EnforcedAccess.CAPABILITY, "project"),
    # Отдаёт абсолютный путь папки архива (раскрытие раскладки диска) и нужен только для
    # открытия менеджера в этой папке — то же назначение, то же право.
    "GET /api/archive-path":                   (EnforcedAccess.CAPABILITY, "project"),
    # Единственный файловый маршрут, который СОЗДАЁТ каталог по пути от клиента и
    # ПЕРЕНОСИТ в него существующие архивы. Это операция с данными, а не обычная работа
    # оператора: до 2.789 её мог выполнить любой, у кого есть право project.
    "POST /api/storage/archive":               (EnforcedAccess.CAPABILITY, "admin"),
    # 2.978: смена ПАПКИ ДАННЫХ — то же самое действие и тот же риск, что смена папки архивов:
    # каталог создаётся по пути от клиента, и при следующем запуске туда переезжает вся база.
    # Раньше маршрут стоял на праве 'project' (оператор), теперь — admin, как у соседа.
    "POST /api/storage/data":                  (EnforcedAccess.CAPABILITY, "admin"),
    # 16.10.2026 (R-149, аудит arch-auth-19, paid-boundary-14): файлы интерфейса модулей — только
    # после входа. До входа их не грузит никто: окно входа модулей не показывает (список модулей
    # /api/modules сам требует сессию), приложение для телефона /modules/* не спрашивает. При
    # выключенном входе гейт не проверяет ничего — для владельца без входа всё как раньше.
    "GET /modules/{module_id}/{asset_path:path}": (EnforcedAccess.SESSION_ONLY, None),
}

# Пространство /api/auth/*. До 2.784 весь префикс обходил общий гейт одной строкой
# условия; теперь каждый из 11 маршрутов классифицирован поимённо. Маршрут этого
# пространства, не попавший ни в один из наборов и не имеющий guard, ОСТАЁТСЯ БЕЗ
# ПОЛИТИКИ и потому блокируется — новый auth-маршрут не станет public по умолчанию.
_AUTH_PUBLIC = frozenset((
    "POST /api/auth/login",   # вход обязан работать до входа
    "POST /api/auth/setup",   # первичное включение защиты
    "GET /api/auth/status",   # интерфейс спрашивает, включена ли защита, ещё до входа
))
_AUTH_SESSION_ONLY = frozenset((
    "POST /api/auth/logout",
    "POST /api/auth/disable",  # обработчик дополнительно требует admin — граница сохранена
))


# ═══════════════════════════════════════════════════════════════════════════════
# КАРТА ПРАВ МАРШРУТОВ МОДУЛЕЙ (Alpha 2.785)
#
# ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ. Право маршрута модуля объявляется ЗДЕСЬ и больше нигде.
# Модуль при регистрации лишь ССЫЛАЕТСЯ на запись по policy_id; ни backend модуля, ни
# middleware самостоятельного capability не задают. Иначе появились бы два расходящихся
# источника прав, и один из них рано или поздно стал бы неверным.
#
# policy_id — стабильный идентификатор, не зависящий от того, как выглядит путь. Ядро при
# регистрации сверяет по нему module id, версию модуля, метод, относительный и итоговый
# путь, имя обработчика и активность этапа.
#
# КАК ВЫВЕДЕНЫ ПРАВА. По фактическому коду обработчика и по тому, кто вызывает маршрут в
# интерфейсе, а не по методу HTTP и не по слову в пути. Опорные правила:
#   * чтение рабочих данных модуля -> view;
#   * обычная складская/производственная работа, доступная оператору -> project;
#   * операции пересчёта количества -> count;
#   * то, что меняется ГЛОБАЛЬНО за пределами правимого объекта: цена филамента (уходит в
#     себестоимость), каскадное удаление остатков, ставки фермы, ветка формулы расчёта,
#     конфигурация модуля -> admin.
# Правило границы admin: «меняет ли это деньги или удаляет ли это остатки». Смена цвета
# филамента правит один косметический столбец и потому остаётся работой оператора, а смена
# price_per_kg или каскадное удаление катушек — нет.
#
# ФАКТИЧЕСКАЯ МОДЕЛЬ РОЛЕЙ (server.py, _ROLE_PERMS): count принадлежит operator и admin,
# у assembler его НЕТ. rework есть у assembler, но в модулях нет ни одной операции брака
# или доработки, поэтому rework здесь не используется ни разу. Новых capability и ролей
# этот этап не вводит.
# ═══════════════════════════════════════════════════════════════════════════════

_MODULE_ENFORCED_ROWS = (
    # (policy_id, module_id, метод, относительный путь, граница, право)

    # ── Складской учёт: чтение ──
    ("inventory.summary.read",              "inventory", "GET",    "summary",                      "CAPABILITY", "view"),
    ("inventory.filament.list",             "inventory", "GET",    "filament",                     "CAPABILITY", "view"),
    ("inventory.ams.read",                  "inventory", "GET",    "ams",                          "CAPABILITY", "view"),
    ("inventory.spool.ledger",              "inventory", "GET",    "spool/{sid}/ledger",           "CAPABILITY", "view"),
    ("inventory.item.list",                 "inventory", "GET",    "items",                        "CAPABILITY", "view"),
    ("inventory.item.ledger",               "inventory", "GET",    "item/{iid}/ledger",            "CAPABILITY", "view"),
    ("inventory.cost.read",                 "inventory", "GET",    "cost",                         "CAPABILITY", "view"),
    ("inventory.forecast.read",             "inventory", "GET",    "forecast",                     "CAPABILITY", "view"),
    ("inventory.location.list",             "inventory", "GET",    "locations",                    "CAPABILITY", "view"),
    ("inventory.settings.read",             "inventory", "GET",    "settings",                     "CAPABILITY", "view"),
    ("inventory.reconcile.read",            "inventory", "GET",    "reconcile/{printer_id}",       "CAPABILITY", "view"),
    # ── Складской учёт: обычная работа оператора ──
    ("inventory.spool.create",              "inventory", "POST",   "spool",                        "CAPABILITY", "project"),
    ("inventory.spool.update",              "inventory", "PATCH",  "spool/{sid}",                  "CAPABILITY", "project"),
    ("inventory.spool.delete",              "inventory", "DELETE", "spool/{sid}",                  "CAPABILITY", "project"),
    ("inventory.spool.bulk_delete_preview", "inventory", "POST",   "spools/bulk-delete/preview",   "CAPABILITY", "project"),
    ("inventory.spool.bulk_delete",         "inventory", "POST",   "spools/bulk-delete",           "CAPABILITY", "project"),
    ("inventory.spool.bind",                "inventory", "POST",   "spool/{sid}/bind",             "CAPABILITY", "project"),
    ("inventory.spool.unbind",              "inventory", "POST",   "spool/{sid}/unbind",           "CAPABILITY", "project"),
    ("inventory.spool.sync_color",          "inventory", "POST",   "spool/{sid}/sync-color",       "CAPABILITY", "project"),
    ("inventory.item.create",               "inventory", "POST",   "item",                         "CAPABILITY", "project"),
    ("inventory.item.update",               "inventory", "PATCH",  "item/{iid}",                   "CAPABILITY", "project"),
    ("inventory.item.delete",               "inventory", "DELETE", "item/{iid}",                   "CAPABILITY", "project"),
    ("inventory.location.create",           "inventory", "POST",   "location",                     "CAPABILITY", "project"),
    ("inventory.location.update",           "inventory", "PATCH",  "location/{lid}",               "CAPABILITY", "project"),
    ("inventory.location.delete",           "inventory", "DELETE", "location/{lid}",               "CAPABILITY", "project"),
    ("inventory.ams.replace",               "inventory", "POST",   "ams/replace",                  "CAPABILITY", "project"),
    # ── Складской учёт: пересчёт количества ──
    ("inventory.spool.adjust",              "inventory", "POST",   "spool/{sid}/adjust",           "CAPABILITY", "count"),
    ("inventory.item.adjust",               "inventory", "POST",   "item/{iid}/adjust",            "CAPABILITY", "count"),
    # ── Складской учёт: глобальный справочник и настройки модуля ──
    ("inventory.filament.update",           "inventory", "PATCH",  "filament/{fid}",               "CAPABILITY", "admin"),
    ("inventory.filament.delete",           "inventory", "DELETE", "filament/{fid}",               "CAPABILITY", "admin"),
    ("inventory.settings.write",            "inventory", "POST",   "settings",                     "CAPABILITY", "admin"),

    # ── Расчёт заказа (id cost; 3.0 — на месте удалённой «Себестоимости печати»): чтение и расчёт.
    #    Права маршрутов прежние: модуль сохранил имена, пути и методы, чтобы подойти к этой карте.
    ("cost.settings.read",                  "cost", "GET",  "settings",                     "CAPABILITY", "view"),
    ("cost.printers.read",                  "cost", "GET",  "printers",                     "CAPABILITY", "view"),
    ("cost.calculate",                      "cost", "POST", "calculate",                    "CAPABILITY", "view"),
    ("cost.calculations.list",              "cost", "GET",  "calculations",                 "CAPABILITY", "view"),
    ("cost.calculations.read",              "cost", "GET",  "calculations/{calc_id}",       "CAPABILITY", "view"),
    ("cost.summary.read",                   "cost", "GET",  "summary",                      "CAPABILITY", "view"),
    # ── Расчёт заказа: сохранение, удаление заказа и создание проекта по нему ──
    ("cost.calculations.save",              "cost", "POST", "calculations",                 "CAPABILITY", "project"),
    ("cost.calculations.recalc",            "cost", "POST", "calculations/{calc_id}/recalc", "CAPABILITY", "project"),
    # ── Расчёт заказа: тарифы фермы и ставки принтеров ──
    ("cost.settings.write",                 "cost", "POST", "settings",                     "CAPABILITY", "admin"),
    ("cost.printer_settings.write",         "cost", "POST", "printer-settings/{pid}",       "CAPABILITY", "admin"),

    # ── Аналитика качества: только чтение (через HTTP модуль ничего не пишет) ──
    ("quality.print_runs.list",             "quality", "GET", "print-runs",                      "CAPABILITY", "view"),
    ("quality.print_runs.read",             "quality", "GET", "print-runs/{run_id}",             "CAPABILITY", "view"),
    ("quality.print_runs.materials",        "quality", "GET", "print-runs/{run_id}/materials",   "CAPABILITY", "view"),
    ("quality.summary.read",                "quality", "GET", "summary",                         "CAPABILITY", "view"),
    # ── Уведомления в мессенджеры (модуль messengers 0.1.8): адреса получателей, состояние
    #    ключей, выход в сеть — всё только администратору. Своей таблицы прав у модуля нет.
    ("messengers.settings.read",             "messengers", "GET",  "settings",    "CAPABILITY", "admin"),
    ("messengers.settings.write",            "messengers", "POST", "settings",    "CAPABILITY", "admin"),
    ("messengers.test.send",                 "messengers", "POST", "test",        "CAPABILITY", "admin"),
    ("messengers.pair.start",                "messengers", "POST", "pair/start",  "CAPABILITY", "admin"),
    ("messengers.pair.status",               "messengers", "GET",  "pair/status", "CAPABILITY", "admin"),
    ("messengers.pair.stop",                 "messengers", "POST", "pair/stop",   "CAPABILITY", "admin"),
)

# policy_id -> (module_id, метод, относительный путь, граница, право)
_MODULE_ENFORCED = {r[0]: r[1:] for r in _MODULE_ENFORCED_ROWS}
# (module_id, метод, относительный путь) -> policy_id
_MODULE_ENFORCED_BY_ROUTE = {(r[1], r[2], r[3]): r[0] for r in _MODULE_ENFORCED_ROWS}


def _enforced_module(module_id, method, module_route):
    """Политика маршрута модуля по единой таблице Alpha 2.785.

    Нет записи -> DEFERRED. Такой маршрут не получит доступа при включённой авторизации,
    а его регистрация будет отклонена ядром: неизвестный маршрут модуля не должен
    становиться доступным по умолчанию.
    """
    pid = _MODULE_ENFORCED_BY_ROUTE.get((module_id, method, module_route))
    if not pid:
        return (EnforcementStage.MODULE_2_785, EnforcedAccess.DEFERRED, None, None)
    _mid, _m, _rel, access, cap = _MODULE_ENFORCED[pid]
    return (EnforcementStage.MODULE_2_785, EnforcedAccess(access), cap, pid)


def _enforced_for(kind, method, path, guard, perm, module_id, module_route=None):
    """Механическое отображение записи описи в объявленную политику.

    -> (EnforcementStage, EnforcedAccess, required_capability|None, policy_id|None)

    Порядок ветвей значим: сначала модули и отложенные этапы, затем собственные guard
    обработчиков, затем поимённые решения, и только потом общие правила ядра.
    """
    route_id = "%s %s" % (method, path)

    # 1. Маршруты модулей — по единой таблице (Alpha 2.785).
    if module_id is not None:
        return _enforced_module(module_id, method, module_route)
    # 2. WebSocket (Alpha 2.786): активный этап. Решение принимает отдельный чистый движок
    #    app/websocket_access_control.py — у сокета две точки применения (рукопожатие и
    #    периодическая перепроверка живого соединения), а не одна, как у HTTP-запроса.
    #    Требуемое право то же, что у read-only маршрутов ядра: WebSocket — поток чтения.
    if kind == "WS":
        return (EnforcementStage.WEBSOCKET_2_786, EnforcedAccess.CAPABILITY, "view", None)

    stage = EnforcementStage.CORE_2_784

    # 3. Собственные guard обработчиков (2.778/2.781): граница остаётся у обработчика.
    if guard == "SYSTEM_ADMIN":
        return (stage, EnforcedAccess.SYSTEM_ADMIN, None, None)
    if guard == "CALLBACK_SECRET":
        return (stage, EnforcedAccess.CALLBACK_SECRET, None, None)
    if guard == "LOCAL_RECOVERY":
        return (stage, EnforcedAccess.LOCAL_RECOVERY, None, None)
    if guard == "HANDLER_ADMIN":
        return (stage, EnforcedAccess.HANDLER_ADMIN, None, None)

    # 4. Поимённые решения владельца.
    if route_id in _SPECIAL_ENFORCED:
        access, cap = _SPECIAL_ENFORCED[route_id]
        return (stage, access, cap, None)

    # 5. Пространство авторизации — только поимённо, без общего правила.
    if path.startswith(AUTH_NAMESPACE_PREFIX):
        if route_id in _AUTH_PUBLIC:
            return (stage, EnforcedAccess.PUBLIC, None, None)
        if route_id in _AUTH_SESSION_ONLY:
            return (stage, EnforcedAccess.SESSION_ONLY, None, None)
        return (stage, EnforcedAccess.DEFERRED, None, None)   # нет политики -> отказ

    # 6. Маршруты вне /api/: общий гейт их не видит и в 2.783 не видел. Оставляем
    #    PUBLIC, чтобы поведение не изменилось. Единственный изменяющий маршрут этой
    #    группы — POST /server/files/upload — закрыт в 2.788 собственным guard
    #    обработчика и до этой ветви не доходит (решение принимает ветвь 3).
    #    Остальные пути вне /api/ — статика и Moonraker-handshake из констант.
    if not path.startswith("/api/"):
        return (stage, EnforcedAccess.PUBLIC, None, None)

    # 7. Статический OctoPrint-handshake из _GATE_EXCLUDE: константы без побочных
    #    эффектов, осознанно открытые в 2.781. Маршруты приёма файлов из того же
    #    набора имеют CALLBACK_SECRET и обработаны выше.
    if path in GATE_EXCLUDE_PATHS:
        return (stage, EnforcedAccess.PUBLIC, None, None)

    # 8. Общее правило чтения: вместо неявного «GET разрешён всем» — явное право view.
    if method not in MUTATING_METHODS:
        return (stage, EnforcedAccess.CAPABILITY, "view", None)

    # 9. Общее правило изменения: переносим УЖЕ существующее право, без расширения.
    #    Изменяющий маршрут без права сюда дойти не должен: все семь таких разобраны
    #    поимённо выше. Если дойдёт — политики нет, значит отказ.
    if perm:
        return (stage, EnforcedAccess.CAPABILITY, perm, None)
    return (stage, EnforcedAccess.DEFERRED, None, None)


def _auth_on_behavior_for(access):
    if access is EnforcedAccess.DEFERRED:
        return AuthOnBehavior.LEGACY_UNCHANGED
    if access is EnforcedAccess.PUBLIC:
        return AuthOnBehavior.ALLOW_ANONYMOUS
    if access is EnforcedAccess.SESSION_ONLY:
        return AuthOnBehavior.REQUIRE_SESSION
    if access is EnforcedAccess.CAPABILITY:
        return AuthOnBehavior.REQUIRE_CAPABILITY
    return AuthOnBehavior.HANDLER_DECIDES


def _auth_off_behavior_for(access):
    if access is EnforcedAccess.DEFERRED:
        return AuthOffBehavior.LEGACY_UNCHANGED
    if access in (EnforcedAccess.HANDLER_ADMIN, EnforcedAccess.SYSTEM_ADMIN,
                  EnforcedAccess.CALLBACK_SECRET, EnforcedAccess.LOCAL_RECOVERY):
        return AuthOffBehavior.HANDLER_DECIDES
    return AuthOffBehavior.ALLOW_LOCAL_OWNER


@dataclass(frozen=True)
class RoutePolicy:
    """Одна запись описи. Неизменяема: реестр — данные, а не состояние."""
    route_id: str
    kind: RouteKind
    method: str
    path: str
    handler: str
    source: str
    domain: str
    caller: str
    read_only: bool
    sensitivity: Sensitivity
    side_effects: Tuple[SideEffect, ...]
    current_access_boundary: AccessBoundary
    current_permission: Optional[str]
    auth_off_scope: AuthOffScope
    gate_excluded: bool
    auth_namespace_bypass: bool
    handler_guard: HandlerGuard
    # ---- Объявленная карта прав Alpha 2.784. Поля выше описывают ИСТОРИЮ (как было
    #      в 2.783), поля ниже — ОБЪЯВЛЕННУЮ МОДЕЛЬ (как должно быть). Смешивать нельзя.
    enforcement_stage: EnforcementStage
    enforced_access: EnforcedAccess
    required_capability: Optional[str]
    auth_on_behavior: AuthOnBehavior
    auth_off_behavior: AuthOffBehavior
    # Стабильный идентификатор политики. Есть только у маршрутов модулей (Alpha 2.785):
    # именно по нему модуль ссылается на запись при регистрации, а ядро сверяет
    # module id, версию, метод, оба пути, обработчик и активность этапа.
    policy_id: Optional[str] = None
    module_id: Optional[str] = None
    module_version: Optional[str] = None
    module_route: Optional[str] = None
    notes: str = ""


def _boundary_for(path, guard):
    if guard is HandlerGuard.SYSTEM_ADMIN:
        return AccessBoundary.SYSTEM_ADMIN
    if guard is HandlerGuard.CALLBACK_SECRET:
        return AccessBoundary.CALLBACK_SECRET
    if guard is HandlerGuard.LOCAL_RECOVERY:
        return AccessBoundary.LOCAL_RECOVERY
    if guard is HandlerGuard.HANDLER_ADMIN:
        return AccessBoundary.HANDLER_ADMIN
    if path.startswith(AUTH_NAMESPACE_PREFIX):
        return AccessBoundary.AUTH_NAMESPACE_BYPASS
    if not path.startswith("/api/"):
        return AccessBoundary.PUBLIC
    return AccessBoundary.SESSION_GATE


def _auth_off_scope_for(boundary):
    """ФАКТИЧЕСКОЕ поведение при выключенной авторизации.

    Общий гейт при AUTH OFF выходит немедленно, поэтому обычный маршрут доступен любому
    клиенту сети. Исключения — только собственные guard обработчиков: system-admin требует
    loopback, callback требует loopback и ключ, а _require_admin без сессии отказывает
    всегда, то есть при AUTH OFF такой маршрут недоступен даже локально.
    """
    if boundary is AccessBoundary.SYSTEM_ADMIN:
        return AuthOffScope.LOOPBACK_ONLY
    if boundary is AccessBoundary.LOCAL_RECOVERY:
        return AuthOffScope.LOOPBACK_ONLY   # обработчик требует loopback-peer + одноразовый токен
    if boundary is AccessBoundary.CALLBACK_SECRET:
        return AuthOffScope.CALLBACK_LOOPBACK
    if boundary is AccessBoundary.HANDLER_ADMIN:
        return AuthOffScope.DENIED_ALWAYS
    return AuthOffScope.LAN_ALLOWED


def _mk(kind, method, path, handler, domain, caller, sensitivity, effects, guard, perm,
        module_id=None, module_version=None, module_route=None, notes=""):
    g = HandlerGuard(guard)
    b = _boundary_for(path, g)
    stage, access, cap, pid = _enforced_for(kind, method, path, guard, perm, module_id, module_route)
    return RoutePolicy(
        route_id="%s %s" % (method, path),
        kind=RouteKind.WEBSOCKET if kind == "WS" else RouteKind.HTTP,
        method="WS" if kind == "WS" else method,
        path=path, handler=handler, source="server.py" if module_id is None else "modules/%s/backend.py" % module_id,
        domain=domain, caller=caller,
        read_only=(method not in MUTATING_METHODS) or (pid in READ_ONLY_DESPITE_METHOD),
        sensitivity=Sensitivity(sensitivity),
        side_effects=tuple(SideEffect(e) for e in effects),
        current_access_boundary=b,
        current_permission=perm,
        auth_off_scope=_auth_off_scope_for(b),
        gate_excluded=(path in GATE_EXCLUDE_PATHS),
        auth_namespace_bypass=path.startswith(AUTH_NAMESPACE_PREFIX),
        handler_guard=g,
        enforcement_stage=stage,
        enforced_access=access,
        required_capability=cap,
        auth_on_behavior=_auth_on_behavior_for(access),
        auth_off_behavior=_auth_off_behavior_for(access),
        policy_id=pid,
        module_id=module_id, module_version=module_version, module_route=module_route,
        notes=notes,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# ДАННЫЕ. Строки описи ниже сняты с фактического исходника Alpha 2.783 и проверяются
# тестом при каждом прогоне. Порядок полей ядра:
#   (метод, путь, обработчик, домен, вызывающий, чувствительность,
#    побочные эффекты, handler-guard, текущее право _route_perm)
# Порядок полей модуля:
#   (module_id, версия модуля, относительный путь, итоговый путь, метод, обработчик,
#    побочные эффекты, текущее право _route_perm)
# ═══════════════════════════════════════════════════════════════════════════════

_CORE_ROWS = (
    ('GET', '/', 'home', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/api/archive-path', 'g_archive_path', 'core', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', None),
    ('GET', '/api/auth/audit', 'auth_audit_list', 'auth', 'browser', 'SENSITIVE', ('DATABASE',), 'HANDLER_ADMIN', None),
    ('GET', '/api/auth/audit/export', 'auth_audit_export', 'auth', 'browser', 'SENSITIVE', ('DATABASE',), 'HANDLER_ADMIN', None),
    ('POST', '/api/auth/disable', 'auth_disable', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'NONE', 'project'),
    ('POST', '/api/auth/local-recovery/complete', 'auth_local_recovery_complete', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'LOCAL_RECOVERY', 'project'),
    ('POST', '/api/auth/login', 'auth_login', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'NONE', 'project'),
    ('POST', '/api/auth/logout', 'auth_logout', 'auth', 'browser', 'SENSITIVE', ('SESSION_STATE', 'AUDIT'), 'NONE', 'project'),
    ('POST', '/api/auth/setup', 'auth_setup', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'NONE', 'project'),
    ('GET', '/api/auth/status', 'auth_status', 'auth', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('GET', '/api/auth/users', 'auth_users_list', 'auth', 'browser', 'SENSITIVE', ('DATABASE',), 'HANDLER_ADMIN', None),
    ('POST', '/api/auth/users', 'auth_users_create', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'AUDIT'), 'HANDLER_ADMIN', 'project'),
    ('DELETE', '/api/auth/users/{uid}', 'auth_users_delete', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'HANDLER_ADMIN', 'project'),
    ('PATCH', '/api/auth/users/{uid}', 'auth_users_update', 'auth', 'browser', 'SENSITIVE', ('DATABASE', 'SESSION_STATE', 'AUDIT'), 'HANDLER_ADMIN', 'project'),
    ('GET', '/api/changelog', 'api_changelog', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    # config-backup (Alpha 2.827): постоянный контракт резервного копирования конфигурации.
    # config-backup: все четыре маршрута — граница SYSTEM_ADMIN (loopback/локально).
    # config-backup: export раскрывает секреты только в зашифрованном виде (SECRET_BEARING).
    # config-backup: restore пишет config/БД атомарно с журналом отката; запрет при активной печати.
    ('POST', '/api/config-backup/export', 'cfgbackup_export', 'core', 'browser', 'SECRET_BEARING', ('DATABASE',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/config-backup/inspect', 'cfgbackup_inspect', 'core', 'browser', 'SENSITIVE', ('NONE',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/config-backup/restore', 'cfgbackup_restore', 'core', 'browser', 'SENSITIVE', ('CONFIG', 'DATABASE', 'RECOVERY', 'AUDIT'), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/config-backup/status', 'cfgbackup_status', 'core', 'browser', 'OPERATIONAL', ('DATABASE',), 'SYSTEM_ADMIN', None),
    ('GET', '/api/connection', 'octo_connection', 'core', 'native_slicer', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/api/diagnostics', 'diagnostics', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'SYSTEM_ADMIN', None),
    ('GET', '/api/diagnostics/bambu-sniff', 'api_bambu_sniff_status', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('POST', '/api/diagnostics/bambu-sniff/start', 'api_bambu_sniff_start', 'diagnostics', 'browser', 'SENSITIVE', ('DATABASE',), 'NONE', None),
    ('POST', '/api/diagnostics/bambu-sniff/stop', 'api_bambu_sniff_stop', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('POST', '/api/diagnostics/clear', 'diagnostics_clear', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('POST', '/api/diagnostics/client', 'diagnostics_client', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('GET', '/api/diagnostics/fleet', 'api_diagnostics_fleet', 'diagnostics', 'browser', 'SENSITIVE', ('DATABASE',), 'NONE', None),
    ('POST', '/api/diagnostics/monitor', 'api_diag_monitor_set', 'diagnostics', 'browser', 'SENSITIVE', ('CONFIG',), 'NONE', None),
    ('GET', '/api/diagnostics/summary', 'api_diagnostics_summary', 'diagnostics', 'browser', 'SENSITIVE', ('DATABASE',), 'NONE', None),
    ('POST', '/api/diagnostics/verbose', 'diagnostics_verbose', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('POST', '/api/files/local', 'octo_files_local', 'files', 'native_slicer', 'OPERATIONAL', ('NONE',), 'CALLBACK_SECRET', 'project'),
    #  26.09.2026: лицензии модулей (/api/licenses) — список, импорт файла, удаление; только администратор.
    ('GET', '/api/licenses', 'api_licenses_list', 'modules', 'browser', 'SENSITIVE', ('FILESYSTEM',), 'SYSTEM_ADMIN', None),
    ('POST', '/api/licenses/import', 'api_licenses_import', 'modules', 'browser', 'SENSITIVE', ('FILESYSTEM',), 'SYSTEM_ADMIN', 'project'),
    ('DELETE', '/api/licenses/{license_id}', 'api_licenses_delete', 'modules', 'browser', 'SENSITIVE', ('FILESYSTEM',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/fs/list', 'fs_list', 'files', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/fs/roots', 'fs_roots', 'files', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/fs/stage', 'fs_stage', 'files', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('GET', '/api/fs/thumb', 'fs_thumb', 'files', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', None),
    ('POST', '/api/import-path', 'import_path', 'import', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', 'project'),
    ('GET', '/api/import/parallelism', 'import_parallelism', 'import', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/logs/download', 'download_logs', 'logs', 'browser', 'SENSITIVE', ('FILESYSTEM',), 'NONE', None),
    ('GET', '/api/modules', 'api_modules_list', 'modules', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/modules/install', 'api_modules_install', 'modules', 'browser', 'SENSITIVE', ('MODULE_STATE',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/modules/install-path', 'api_modules_install_path', 'modules', 'browser', 'SENSITIVE', ('FILESYSTEM', 'MODULE_STATE'), 'SYSTEM_ADMIN', 'project'),
    ('DELETE', '/api/modules/{module_id}', 'api_modules_delete', 'modules', 'browser', 'SENSITIVE', ('FILESYSTEM', 'MODULE_STATE'), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/modules/{module_id}/disable', 'api_modules_disable', 'modules', 'browser', 'SENSITIVE', ('NONE',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/modules/{module_id}/enable', 'api_modules_enable', 'modules', 'browser', 'SENSITIVE', ('MODULE_STATE',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/network', 'g_network', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/network', 'set_network', 'core', 'browser', 'SENSITIVE', ('CONFIG',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/part/attach-upload', 'part_attach_upload', 'parts', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', 'project'),
    ('POST', '/api/part/pick', 'part_pick', 'parts', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/part/pick-path', 'part_pick_path', 'parts', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/part/print', 'part_print', 'parts', 'browser', 'OPERATIONAL', ('DATABASE', 'FILESYSTEM', 'QUEUE'), 'NONE', 'operate'),
    ('POST', '/api/part/{part_name}/reveal', 'part_reveal', 'parts', 'browser', 'OPERATIONAL', ('DATABASE', 'SUBPROCESS'), 'NONE', 'project'),
    ('GET', '/api/parts', 'g_parts', 'parts', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/parts/rebuild-previews', 'parts_rebuild_previews', 'parts', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/parts/save', 's_parts', 'parts', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('GET', '/api/print-hooks', 'api_print_hooks', 'print', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    #  Alpha 2.920: очередь ОЖИДАНИЯ — что печатать, принтер ещё не выбран.
    #  Alpha 2.920: чтение — как у прочих очередей; изменения — право 'project',
    #  Alpha 2.920: как у постановки в очередь запусков (то же действие владельца).
    ('GET', '/api/queue-wait', 'api_queue_wait_get', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE'), 'NONE', None),
    ('POST', '/api/queue-wait/add', 'api_queue_wait_add', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE'), 'NONE', 'project'),
    ('POST', '/api/queue-wait/remove', 'api_queue_wait_remove', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE'), 'NONE', 'project'),
    ('POST', '/api/queue-wait/start', 'api_queue_wait_start', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE'), 'NONE', 'project'),
    #  2.980 (R-092): поиск принтеров, объявившихся в сети. Чтение снимка — право 'project'
    #  (его же имеет наблюдатель ферм), запуск поиска и смена адреса — 'printer_write':
    #  запуск шлёт запросы в сеть, а смена адреса меняет запись принтера.
    ('POST', '/api/printer-discovery/start', 'api_discovery_start', 'core', 'browser', 'OPERATIONAL', ('NETWORK',), 'NONE', 'project'),
    ('GET', '/api/printer-discovery', 'api_discovery_state', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/printer-discovery/stop', 'api_discovery_stop', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/printer-discovery/rebind', 'api_discovery_rebind', 'core', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    #  Сырая запись сетевых объявлений — инструмент снятия контракта на ферме. Пишет файл и
    #  слушает сеть, поэтому право администратора, как у прочей диагностики.
    ('POST', '/api/diagnostics/net-capture/start', 'api_net_capture_start', 'diagnostics', 'browser', 'SENSITIVE', ('NETWORK', 'FILESYSTEM'), 'NONE', None),
    ('POST', '/api/diagnostics/net-capture/stop', 'api_net_capture_stop', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('GET', '/api/diagnostics/net-capture', 'api_net_capture_state', 'diagnostics', 'browser', 'SENSITIVE', ('NONE',), 'NONE', None),
    ('POST', '/api/printer/queue-allowed', 'api_printer_queue_allowed', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    #  16.09.2026: подтверждение «Стол очищен» вне проектного запуска (очередь ожидания и автозапуск).
    #  Право то же, что у постановки в очередь: это действие оператора у принтера, а не настройка.
    ('POST', '/api/printer/{printer_id}/plate-clear', 'api_printer_plate_clear', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/printer/{printer_id}/plate-clear/revoke', 'api_printer_plate_clear_revoke', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    #  Alpha 2.927: настройки фермы — единые на всю ферму с любого компьютера (разрешение владельца
    #  29.08.2026). Пометки принтера и маршрут /api/printer/marks удалены 12.09.2026 (слово владельца, 2.927).
    ('GET', '/api/farm-settings', 'api_farm_settings_get', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),   # Alpha 2.927
    ('POST', '/api/farm-settings', 'api_farm_settings_set', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),   # Alpha 2.927
    ('GET', '/api/print-queue', 'api_print_queue_get', 'print', 'browser', 'OPERATIONAL', ('QUEUE',), 'NONE', None),
    ('POST', '/api/print-queue/cancel', 'api_print_queue_cancel', 'print', 'browser', 'OPERATIONAL', ('QUEUE',), 'NONE', 'project'),
    ('GET', '/api/print-queue/durable', 'api_print_queue_durable', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE', 'RECOVERY'), 'NONE', None),
    ('POST', '/api/print-queue/durable/cancel', 'api_print_queue_durable_cancel', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE', 'RECOVERY'), 'NONE', 'project'),
    ('POST', '/api/print-queue/enqueue', 'api_print_queue_enqueue', 'print', 'browser', 'OPERATIONAL', ('QUEUE',), 'NONE', 'project'),
    ('GET', '/api/print-queue/recovery-notice', 'api_print_queue_recovery_notice', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE', 'RECOVERY'), 'NONE', None),
    ('POST', '/api/print-queue/recovery/cancel', 'api_print_queue_recovery_cancel', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE', 'RECOVERY'), 'NONE', 'project'),
    ('POST', '/api/print-queue/recovery/continue', 'api_print_queue_recovery_continue', 'print', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE', 'RECOVERY'), 'NONE', 'project'),
    ('GET', '/api/printer-badges', 'api_printer_badges', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/printer-filament', 'api_printer_filament', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    # Alpha 2.823: файловый менеджер принтеров. Чтение — отдельное право printer_files_read
    # (2.823, объявлено поимённо ниже); удаление и флаги — граница SYSTEM_ADMIN (2.823)
    # плюс серверный предохранитель printer_files_delete_enabled (по умолчанию выключен).
    ('GET', '/api/printer-files/capabilities', 'pf_capabilities', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/printer-files/delete', 'pf_delete', 'printers', 'browser', 'SENSITIVE', ('DATABASE', 'NETWORK', 'PRINTER', 'AUDIT'), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/printer-files/list', 'pf_list', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', 'project'),
    #  2.989: только чтение — скачивает картинку у принтера, ничего не меняет.
    ('GET', '/api/printer-files/preview', 'pf_preview', 'printers', 'browser', 'OPERATIONAL', ('NETWORK',), 'NONE', None),
    # Alpha 2.825: resolve файла для печати (НИЧЕГО не печатает — только повторная проверка
    # на устройстве и нормализованное имя для существующего C1-flow; старт остаётся в p_cmd — 2.825).
    ('POST', '/api/printer-files/select-for-print', 'pf_select_for_print', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', 'project'),
    ('POST', '/api/printer-files/settings', 'pf_settings_set', 'printers', 'browser', 'SENSITIVE', ('DATABASE', 'AUDIT'), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/printer-files/storages', 'pf_storages', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    ('GET', '/api/printer-models', 'printer_models', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    # Alpha 2.831 printer-sort-mode: визуальная сортировка списка принтеров. GET — публичное чтение.
    # Alpha 2.831 printer-sort-mode: POST — мутирующий маршрут, право по фолбэку _route_perm ('project').
    # Alpha 2.831 printer-sort-mode: пишет config.json (в backup); физический порядок/очередь/печать не меняет.
    ('GET', '/api/printer-sort-mode', 'get_printer_sort_mode', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/printer-sort-mode', 'set_printer_sort_mode', 'printers', 'browser', 'OPERATIONAL', ('CONFIG',), 'NONE', 'project'),
    ('POST', '/api/printer/verify', 'verify_printer', 'printers', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'printer_write'),
    ('GET', '/api/printer/{pid}/camera', 'printer_camera', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    # Alpha 2.870: тот же поток без перекодирования (fMP4). Права и последствия те же, что у /camera:
    # Alpha 2.870: только чтение камеры, принтеру ничего не отправляется.
    ('GET', '/api/printer/{pid}/camera.mp4', 'printer_camera_mp4', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    #  Alpha 2.879: тот же поток по WebSocket. Причина — измеренный предел браузера:
    #  Alpha 2.879: шесть длинных ответов HTTP/1.1 на один адрес, седьмая камера ничего не получает.
    ('WS', '/api/printer/{pid}/camera.ws', 'printer_camera_ws', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    ('POST', '/api/printer/{pid}/cmd', 'p_cmd', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'PRINTER', 'NETWORK', 'QUEUE'), 'NONE', 'operate'),
    ('GET', '/api/printer/{pid}/diagnose', 'api_printer_diagnose', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('GET', '/api/printer/{pid}/files', 'g_files', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    # Alpha 2.833 klipper-prestart: GET read-only discovery (objects/gcode-help/config Moonraker), public.
    # Alpha 2.833 klipper-prestart: POST сохраняет per-printer prefs в config.json (в backup); allowlist-only.
    ('GET', '/api/printer/{pid}/klipper-prestart', 'get_klipper_prestart', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    ('POST', '/api/printer/{pid}/klipper-prestart', 'set_klipper_prestart', 'printers', 'browser', 'OPERATIONAL', ('CONFIG',), 'NONE', 'project'),
    # Alpha 2.839 klipper-contract-report: диагностический сбор контракта подготовки печати.
    # Alpha 2.839: POST только к Farm Manager; ПРИНТЕРУ уходят исключительно GET по неизменяемому
    # Alpha 2.839: allowlist (app/klipper_contract_probe.ALLOWED_PATHS). Ничего не пишет — ни БД,
    # Alpha 2.839: ни config, ни файлы. Отчёт обезличен и проверен самопроверкой перед выдачей.
    ('POST', '/api/printer/{pid}/klipper-contract-report', 'klipper_contract_report', 'printers', 'browser', 'OPERATIONAL', ('NETWORK',), 'NONE', 'project'),
    ('GET', '/api/printer/{pid}/ping', 'api_printer_ping', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/printer/{pid}/print_path', 'u_print_path', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'FILESYSTEM', 'QUEUE'), 'NONE', 'operate'),
    ('POST', '/api/printer/{pid}/speedtest', 'api_printer_speedtest', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'operate'),
    ('GET', '/api/printer/{pid}/thumb', 'printer_file_thumb', 'printers', 'browser', 'OPERATIONAL', ('FILESYSTEM', 'NETWORK'), 'NONE', None),
    ('POST', '/api/printer/{pid}/upload_print', 'u_print', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'QUEUE'), 'NONE', 'operate'),
    ('POST', '/api/printer/{pid}/webrtc', 'printer_webrtc', 'printers', 'browser', 'OPERATIONAL', ('DATABASE', 'NETWORK'), 'NONE', None),
    ('GET', '/api/printers', 'g_printers', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/printers/save', 's_printers', 'printers', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'printer_write'),
    ('POST', '/api/project-orchestrator/print-enabled', 'orch_set_print_enabled', 'core', 'browser', 'OPERATIONAL', ('CONFIG',), 'NONE', 'project'),
    ('GET', '/api/project-orchestrator/transport-status', 'orch_transport_status', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/project-runs', 'whole_print_list_runs', 'projects', 'browser', 'OPERATIONAL', ('RECOVERY',), 'NONE', None),
    ('GET', '/api/project-runs/diagnostics', 'whole_print_diagnostics', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/project-runs/{run_id}', 'whole_print_run_snapshot', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/project-runs/{run_id}/cancel', 'whole_print_cancel', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('GET', '/api/project-runs/{run_id}/items/{item_id}/feed-candidates', 'whole_print_feed_candidates', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/project-runs/{run_id}/items/{item_id}/feed-plan/approve', 'whole_print_feed_approve', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/items/{item_id}/feed-plan/clear', 'whole_print_feed_clear', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/items/{item_id}/feed-plan/select', 'whole_print_feed_select', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/items/{item_id}/resolve', 'whole_print_resolve_item', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/pause', 'whole_print_pause', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/printers/{printer_id}/plate-clear', 'whole_print_plate_clear', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/printers/{printer_id}/plate-clear/revoke', 'whole_print_plate_clear_revoke', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/resume', 'whole_print_resume', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/project-runs/{run_id}/start', 'whole_print_start', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('GET', '/api/projects/export', 'export_projects', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/projects/import', 'import_projects', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('GET', '/api/projects2', 'g_projects2', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/projects2', 'c_project2', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/archive', 'archive_projects2', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('GET', '/api/projects2/export', 'export_projects2', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/projects2/files/{file_id}/part-thumb', 'project2_file_part_thumb', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/projects2/files/{file_id}/slice', 'project2_file_slice', 'projects', 'browser', 'OPERATIONAL', ('DATABASE', 'SUBPROCESS'), 'NONE', 'project'),
    ('GET', '/api/projects2/files/{file_id}/thumb', 'project2_file_thumb', 'projects', 'browser', 'OPERATIONAL', ('DATABASE', 'FILESYSTEM'), 'NONE', None),
    ('POST', '/api/projects2/import-begin', 'import_begin_project', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/import-files', 'import_files_as_project', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('DELETE', '/api/projects2/{project_id}', 'd_project2', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('PATCH', '/api/projects2/{project_id}', 'u_project2', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('PATCH', '/api/projects2/{project_id}/file-parts/{file_part_id}', 'u_project2_filepart', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/pick', 'pick_project2_file', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/pick-path', 'pickpath_project2_file', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/pick-paths', 'pickpaths_project2_files', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/restore', 'restore_project2_file', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/upload', 'up_project2_file', 'projects', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', 'project'),
    ('DELETE', '/api/projects2/{project_id}/files/{file_id}', 'del_project2_file', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/{file_id}/locate', 'locate_project2_file', 'projects', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/{file_id}/manual-part', 'add_project2_manual_part', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/projects2/{project_id}/files/{file_id}/print', 'print_project2_file', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'operate'),
    ('POST', '/api/projects2/{project_id}/parts/restore', 'restore_project2_part', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('DELETE', '/api/projects2/{project_id}/parts/{part_id}', 'd_project2_part', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('PATCH', '/api/projects2/{project_id}/parts/{part_id}', 'u_project2_part', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'count'),
    ('POST', '/api/projects2/{project_id}/parts/{part_id}/rework', 'request_part_rework', 'projects', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'rework'),
    ('GET', '/api/projects2/{project_id}/partsview', 'g_project2_partsview', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/projects2/{project_id}/tree', 'g_project2_tree', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('GET', '/api/projects2/{project_id}/whole-print/preflight', 'whole_print_preflight', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/projects2/{project_id}/whole-print/runs', 'whole_print_create_run', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/restart', 'restart_app', 'core', 'browser', 'SENSITIVE', ('NONE',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/send-jobs', 'api_send_jobs', 'send', 'browser', 'OPERATIONAL', ('QUEUE',), 'NONE', None),
    ('POST', '/api/send-jobs/{job_id}/dismiss', 'api_send_jobs_dismiss', 'send', 'browser', 'OPERATIONAL', ('QUEUE',), 'NONE', 'project'),
    ('GET', '/api/server', 'octo_server', 'core', 'native_slicer', 'PUBLIC', ('NONE',), 'NONE', None),
    ('POST', '/api/slicer-callback/generate', 'slicer_callback_generate', 'slicer', 'browser', 'SENSITIVE', ('CONFIG',), 'SYSTEM_ADMIN', 'project'),
    ('POST', '/api/slicer-callback/revoke', 'slicer_callback_revoke', 'slicer', 'browser', 'SENSITIVE', ('CONFIG',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/slicer-callback/status', 'slicer_callback_status', 'slicer', 'browser', 'SENSITIVE', ('NONE',), 'SYSTEM_ADMIN', None),
    ('POST', '/api/slicer-hook', 's_hook', 'slicer', 'native_slicer', 'OPERATIONAL', ('DATABASE',), 'CALLBACK_SECRET', 'project'),
    ('POST', '/api/slicer/choose', 'slicer_choose', 'slicer', 'browser', 'SENSITIVE', ('CONFIG',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/slicer/list', 'slicer_list_api', 'slicer', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/slicer/pick', 'slicer_pick', 'slicer', 'browser', 'SENSITIVE', ('CONFIG',), 'SYSTEM_ADMIN', 'project'),
    ('GET', '/api/staging', 'staging_list', 'tasks', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', None),
    ('POST', '/api/staging/delete', 'staging_delete', 'tasks', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/staging/pick', 'staging_pick', 'tasks', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/staging/save', 'save_staging', 'tasks', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/staging/sync', 'staging_project_sync', 'tasks', 'browser', 'OPERATIONAL', ('DATABASE',), 'NONE', 'project'),
    ('POST', '/api/staging/upload', 'staging_upload', 'tasks', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('POST', '/api/staging/{filename}/reveal', 'staging_reveal', 'tasks', 'browser', 'OPERATIONAL', ('SUBPROCESS',), 'NONE', 'project'),
    ('POST', '/api/staging/{filename}/slice', 'staging_slice', 'tasks', 'browser', 'OPERATIONAL', ('SUBPROCESS',), 'NONE', 'project'),
    ('GET', '/api/staging/{filename}/thumb', 'staging_thumb', 'tasks', 'browser', 'OPERATIONAL', ('FILESYSTEM',), 'NONE', None),
    ('POST', '/api/staging/{filename}/to-project', 'staging_to_project', 'tasks', 'browser', 'OPERATIONAL', ('DATABASE', 'FILESYSTEM'), 'NONE', 'project'),
    ('GET', '/api/storage', 'g_storage', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None),
    ('POST', '/api/storage/archive', 'set_storage_archive', 'core', 'browser', 'OPERATIONAL', ('FILESYSTEM', 'CONFIG'), 'NONE', 'project'),
    ('POST', '/api/storage/data', 'set_storage_data', 'core', 'browser', 'OPERATIONAL', ('CONFIG',), 'NONE', 'project'),
    ('POST', '/api/storage/open', 'open_storage_folder', 'core', 'browser', 'OPERATIONAL', ('FILESYSTEM', 'SUBPROCESS'), 'NONE', 'project'),
    ('GET', '/api/update-check', 'api_update_check', 'core', 'browser', 'OPERATIONAL', ('NETWORK',), 'NONE', None),
    ('POST', '/api/upload-plan', 'u_plan', 'core', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', 'project'),
    ('GET', '/api/version', 'octo_version', 'core', 'native_slicer', 'PUBLIC', ('NONE',), 'NONE', None),
    #  Alpha 2.903: второй интерфейс. Права ровно те же, что у главной страницы и её файлов —
    #  2.903: это статика браузера, ничего не выполняющая на сервере.
    ('GET', '/ui3', 'home_ui3', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/ui3/', 'home_ui3', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/ui3/{asset_path:path}', '_serve_ui3_asset', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/assets/app.css', '_serve_app_css', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/assets/app.js', '_serve_app_js', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/assets/{module_path:path}', '_serve_ui_module', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/bg.jpg', '_serve_bg', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/covers/{filename}', 'serve_cover', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/design/{design_path:path}', '_serve_design_layer', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/favicon.ico', 'serve_favicon', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/favicon.png', 'serve_favicon', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/logo-light.svg', 'serve_logo_light', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/logo.svg', 'serve_logo', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/machine/update/status', 'mr_update_status', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/modules/{module_id}/{asset_path:path}', '_serve_module_asset', 'core', 'browser', 'PUBLIC', ('FILESYSTEM',), 'NONE', None),
    ('GET', '/printer/info', 'mr_printer_info', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('POST', '/server/files/upload', 'proxy_upload', 'core', 'browser', 'PUBLIC', ('DATABASE', 'FILESYSTEM'), 'CALLBACK_SECRET', 'project'),
    ('GET', '/server/info', 'mr_server_info', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/vendor/tailwind.css', '_serve_tw_local', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/vendor/vue.esm-browser.js', '_serve_vue_local', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('GET', '/version', 'version', 'core', 'browser', 'PUBLIC', ('NONE',), 'NONE', None),
    ('WS', '/ws', 'ws_ep', 'core', 'browser', 'PUBLIC', ('SESSION_STATE',), 'NONE', None),
)

_MODULE_ROWS = (
    #  Расчёт заказа (cost 0.2.0) — 3.0, 12.09.2026: заменил «Себестоимость печати» 0.1.3 по слову
    #  владельца. С 26.09.2026 версия загрузку не запрещает: старый модуль, если он остался на ферме,
    #  запустится с пометкой «есть новее» в настройках (печати он не мешает — только считает).
    #  Эффекты — по графу вызовов обработчиков (tools/test_cost_module.py, раздел «эффекты»):
    #  FILESYSTEM — разбор загруженного файла во временной папке и файлы заказов в cost_order_files;
    #  NETWORK — запросы модуля к САМОЙ программе на 127.0.0.1 (список принтеров, задачи, проекты,
    #  импорт проекта) с сеансом того же пользователя; во внешнюю сеть модуль не ходит.
    ('cost', '0.2.0','calculate', '/api/mod/cost/calculate', 'POST', 'api_calculate', ('DATABASE', 'FILESYSTEM', 'NETWORK'), 'project'),
    ('cost', '0.2.0','calculations', '/api/mod/cost/calculations', 'GET', 'api_calc_list', ('NONE',), None),
    ('cost', '0.2.0','calculations', '/api/mod/cost/calculations', 'POST', 'api_calc_save', ('DATABASE', 'FILESYSTEM', 'NETWORK'), 'project'),
    ('cost', '0.2.0','calculations/{calc_id}', '/api/mod/cost/calculations/{calc_id}', 'GET', 'api_calc_one', ('NONE',), None),
    ('cost', '0.2.0','calculations/{calc_id}/recalc', '/api/mod/cost/calculations/{calc_id}/recalc', 'POST', 'api_calc_recalc', ('DATABASE', 'FILESYSTEM', 'NETWORK'), 'project'),
    ('cost', '0.2.0','printer-settings/{pid}', '/api/mod/cost/printer-settings/{pid}', 'POST', 'api_printer_set', ('DATABASE', 'NETWORK'), 'project'),
    ('cost', '0.2.0','printers', '/api/mod/cost/printers', 'GET', 'api_printers', ('DATABASE', 'NETWORK'), None),
    ('cost', '0.2.0','settings', '/api/mod/cost/settings', 'GET', 'api_settings_get', ('NONE',), None),
    ('cost', '0.2.0','settings', '/api/mod/cost/settings', 'POST', 'api_settings_set', ('DATABASE',), 'project'),
    ('cost', '0.2.0','summary', '/api/mod/cost/summary', 'GET', 'api_summary', ('NONE',), None),
    ('inventory', '1.7.29','ams', '/api/mod/inventory/ams', 'GET', 'api_inv_ams', ('NONE',), None),
    ('inventory', '1.7.29','ams/replace', '/api/mod/inventory/ams/replace', 'POST', 'api_inv_ams_replace', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','cost', '/api/mod/inventory/cost', 'GET', 'api_inv_cost', ('NONE',), None),
    ('inventory', '1.7.29','filament', '/api/mod/inventory/filament', 'GET', 'api_inv_filament', ('NONE',), None),
    ('inventory', '1.7.29','filament/{fid}', '/api/mod/inventory/filament/{fid}', 'DELETE', 'api_inv_filament_delete', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','filament/{fid}', '/api/mod/inventory/filament/{fid}', 'PATCH', 'api_inv_filament_update', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','forecast', '/api/mod/inventory/forecast', 'GET', 'api_inv_forecast', ('NONE',), None),
    ('inventory', '1.7.29','item', '/api/mod/inventory/item', 'POST', 'api_inv_item_create', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','item/{iid}', '/api/mod/inventory/item/{iid}', 'DELETE', 'api_inv_item_delete', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','item/{iid}', '/api/mod/inventory/item/{iid}', 'PATCH', 'api_inv_item_update', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','item/{iid}/adjust', '/api/mod/inventory/item/{iid}/adjust', 'POST', 'api_inv_item_adjust', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','item/{iid}/ledger', '/api/mod/inventory/item/{iid}/ledger', 'GET', 'api_inv_item_ledger', ('NONE',), None),
    ('inventory', '1.7.29','items', '/api/mod/inventory/items', 'GET', 'api_inv_items', ('NONE',), None),
    ('inventory', '1.7.29','location', '/api/mod/inventory/location', 'POST', 'api_inv_location_create', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','location/{lid}', '/api/mod/inventory/location/{lid}', 'DELETE', 'api_inv_location_delete', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','location/{lid}', '/api/mod/inventory/location/{lid}', 'PATCH', 'api_inv_location_update', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','locations', '/api/mod/inventory/locations', 'GET', 'api_inv_locations', ('NONE',), None),
    ('inventory', '1.7.29','reconcile/{printer_id}', '/api/mod/inventory/reconcile/{printer_id}', 'GET', 'api_inv_reconcile', ('NONE',), None),
    ('inventory', '1.7.29','settings', '/api/mod/inventory/settings', 'GET', 'api_inv_settings_get', ('NONE',), None),
    ('inventory', '1.7.29','settings', '/api/mod/inventory/settings', 'POST', 'api_inv_settings_set', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool', '/api/mod/inventory/spool', 'POST', 'api_inv_spool_create', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}', '/api/mod/inventory/spool/{sid}', 'DELETE', 'api_inv_spool_delete', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}', '/api/mod/inventory/spool/{sid}', 'PATCH', 'api_inv_spool_update', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}/adjust', '/api/mod/inventory/spool/{sid}/adjust', 'POST', 'api_inv_spool_adjust', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}/bind', '/api/mod/inventory/spool/{sid}/bind', 'POST', 'api_inv_spool_bind', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}/ledger', '/api/mod/inventory/spool/{sid}/ledger', 'GET', 'api_inv_spool_ledger', ('NONE',), None),
    ('inventory', '1.7.29','spool/{sid}/sync-color', '/api/mod/inventory/spool/{sid}/sync-color', 'POST', 'api_inv_spool_sync_color', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spool/{sid}/unbind', '/api/mod/inventory/spool/{sid}/unbind', 'POST', 'api_inv_spool_unbind', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spools/bulk-delete', '/api/mod/inventory/spools/bulk-delete', 'POST', 'api_inv_spools_bulk_delete', ('DATABASE',), 'project'),
    ('inventory', '1.7.29','spools/bulk-delete/preview', '/api/mod/inventory/spools/bulk-delete/preview', 'POST', 'api_inv_spools_bulk_delete_preview', ('NONE',), 'project'),
    ('inventory', '1.7.29','summary', '/api/mod/inventory/summary', 'GET', 'api_inventory_summary', ('NONE',), None),
    ('quality', '0.2.3','print-runs', '/api/mod/quality/print-runs', 'GET', 'api_q_print_runs', ('NONE',), None),
    ('quality', '0.2.3','print-runs/{run_id}', '/api/mod/quality/print-runs/{run_id}', 'GET', 'api_q_print_run_one', ('NONE',), None),
    ('quality', '0.2.3','print-runs/{run_id}/materials', '/api/mod/quality/print-runs/{run_id}/materials', 'GET', 'api_q_print_run_materials', ('NONE',), None),
    ('quality', '0.2.3','summary', '/api/mod/quality/summary', 'GET', 'api_q_summary', ('NONE',), None),
    #  Уведомления в мессенджеры (0.1.8): настройки без секретов, правка, пробная отправка,
    #  мастер подключения (проверка ключа + ожидание первого сообщения — выход в сеть).
    ('messengers', '0.1.8','settings', '/api/mod/messengers/settings', 'GET', 'api_msg_settings_get', ('NONE',), None),
    ('messengers', '0.1.8','settings', '/api/mod/messengers/settings', 'POST', 'api_msg_settings_set', ('DATABASE',), 'project'),
    ('messengers', '0.1.8','test', '/api/mod/messengers/test', 'POST', 'api_msg_test', ('NETWORK',), 'project'),
    ('messengers', '0.1.8','pair/start', '/api/mod/messengers/pair/start', 'POST', 'api_msg_pair_start', ('DATABASE', 'NETWORK'), 'project'),
    ('messengers', '0.1.8','pair/status', '/api/mod/messengers/pair/status', 'GET', 'api_msg_pair_status', ('NONE',), None),
    ('messengers', '0.1.8','pair/stop', '/api/mod/messengers/pair/stop', 'POST', 'api_msg_pair_stop', ('NONE',), 'project'),
)

# Примечания к отдельным маршрутам ядра. Вынесены в отдельную таблицу, чтобы не менять
# состав и порядок полей строк описи 2.783 — он сверяется тестом посимвольно.
_CORE_NOTES = {
    "POST /server/files/upload": (
        "ЗАКРЫТО в Alpha 2.788. Прежде: изменяющий маршрут (пишет в БД и на диск) вне "
        "префикса /api/, а общий гейт смотрит только пути под /api/ — поэтому в 2.783-2.787 "
        "он оставался доступен без сессии ДАЖЕ ПРИ ВКЛЮЧЁННОЙ авторизации, и multipart "
        "разбирался зависимостью File(...) до любой проверки источника. Теперь граница та же, "
        "что у Moonraker-близнеца /api/files/local (2.781): _require_slicer_callback первым "
        "оператором обработчика — loopback из транспорта И действующий ключ интеграции, ДО "
        "разбора формы, чтения потока, записи файла и изменений БД. Ключ НЕ отдельный: тот же "
        "per-installation секрет и тот же заголовок X-Api-Key (app/slicer_callback_auth.py). "
        "Сигнатура сменена с File(...) на Request сознательно — иначе FastAPI разобрал бы "
        "multipart раньше проверки. Обязателен при обоих режимах авторизации; сессия браузера "
        "ключ не заменяет; LAN-клиент отклоняется даже с верным ключом."
    ),
    "GET /api/version": (
        "Статический OctoPrint-handshake. Осознанно открыт в 2.781: константы, без "
        "побочных эффектов и без раскрытия данных. Закрыть нельзя, не сломав кнопку "
        "Test в слайсере, — проверить, шлёт ли слайсер ключ и сюда, без запуска нельзя."
    ),
    "GET /api/server": ("Статический OctoPrint-handshake, см. GET /api/version."),
    "GET /api/connection": ("Статический OctoPrint-handshake, см. GET /api/version."),
    "POST /api/auth/local-recovery/complete": (
        "Alpha 2.798: локальное одноразовое восстановление доступа администратора. Сессия НЕ "
        "требуется (пароль как раз забыт), поэтому маршрут не под общей сессионной границей; "
        "собственный guard обработчика требует ФАКТИЧЕСКИЙ loopback-peer (адрес из транспорта, "
        "заголовки прокси игнорируются) И действующий одноразовый recovery-токен, выданный "
        "ТОЛЬКО из меню трея и живущий только в памяти процесса (app/local_admin_recovery.py). "
        "Пароль меняется тем же PBKDF2, что и обычная смена; все сессии администратора "
        "отзываются; grant уничтожается. Роль/enabled/username не меняются, пользователь не "
        "создаётся. Удалённый клиент отклоняется ДО работы с БД даже с верным токеном."
    ),
    "POST /api/network": (
        "Alpha 2.787: открытие фермы в локальную сеть — административное действие. До 2.787 "
        "маршрут не имел собственной границы вовсе и требовал лишь право 'project', то есть "
        "при включённой авторизации сеть мог открыть оператор. Теперь _require_system_admin "
        "плюс проверка предпосылок (включённая авторизация и активный администратор) ДО "
        "записи конфигурации."
        " Alpha 2.837: добавлена ВТОРАЯ, машинная граница _require_server_machine — и порт,"
        " и сетевой режим (2.837) меняет только фактический loopback-вызывающий; адрес берётся"
        " из транспорта, а удалённый клиент (2.837) читает состояние через GET, но не меняет."
    ),
    "GET /machine/update/status": (
        "Moonraker-handshake вне /api/: константы. Общий гейт такие пути не видит."
    ),
    "GET /printer/info": ("Moonraker-handshake вне /api/, см. GET /machine/update/status."),
    "GET /server/info": ("Moonraker-handshake вне /api/, см. GET /machine/update/status."),
}

CORE_POLICIES = tuple(
    _mk(kind, "GET" if kind == "WS" else kind, path, handler, domain, caller, sens, eff, guard, perm,
        notes=_CORE_NOTES.get("%s %s" % ("GET" if kind == "WS" else kind, path), ""))
    for (kind, path, handler, domain, caller, sens, eff, guard, perm) in _CORE_ROWS
)

MODULE_POLICIES = tuple(
    _mk("HTTP", method, full, handler, "module", "module_frontend", "OPERATIONAL", eff, "NONE", perm,
        module_id=mid, module_version=ver, module_route=rel,
        notes="Маршрут модуля: регистрируется в рантайме через core.add_route на том же приложении, "
              "поэтому проходит общий гейт и получает право по общему fallback.")
    for (mid, ver, rel, full, method, handler, eff, perm) in _MODULE_ROWS
)

ALL_POLICIES = CORE_POLICIES + MODULE_POLICIES

# ═══════════════════════════════════════════════════════════════════════════════
# МАРШРУТЫ, КОТОРЫЕ СОЗДАЁТ САМ ВЕБ-ФРЕЙМВОРК
#
# FastAPI добавляет их без единого декоратора в исходнике. Поэтому в опись 2.783 —
# она снята С ИСХОДНОГО КОДА и равна 167 маршрутам ядра — они не входят и входить не
# должны: иначе baseline перестанет сходиться, а тест полноты C1/C2 станет ложным.
#
# НО В РАБОТАЮЩЕМ ПРИЛОЖЕНИИ ОНИ СУЩЕСТВУЮТ, и до Alpha 2.784 были доступны анонимно
# ДАЖЕ ПРИ ВКЛЮЧЁННОЙ авторизации: их пути не начинаются с /api/, а общий гейт такие
# пути не проверял вовсе. Это отдавало полную схему API (все эндпоинты и параметры)
# любому устройству сети без входа.
#
# РЕШЕНИЕ 2.784: требуется действующая сессия. Интерактивная документация остаётся
# доступной вошедшему пользователю любой роли, но не анонимному. Доступ НЕ расширяется
# ни для кого. При ВЫКЛЮЧЕННОЙ авторизации поведение не меняется — гейт неактивен.
# Полное отключение документации или сужение до admin — отдельное решение владельца.
# ═══════════════════════════════════════════════════════════════════════════════

_FRAMEWORK_ROWS = (
    ('GET', '/openapi.json', 'openapi', 'Полная схема API: перечень всех маршрутов и параметров.'),
    ('GET', '/docs', 'swagger_ui_html', 'Интерактивная документация Swagger UI.'),
    ('GET', '/docs/oauth2-redirect', 'swagger_ui_redirect', 'Служебный редирект Swagger UI.'),
    ('GET', '/redoc', 'redoc_html', 'Документация ReDoc.'),
)

FRAMEWORK_POLICIES = tuple(
    RoutePolicy(
        route_id="%s %s" % (method, path), kind=RouteKind.HTTP, method=method, path=path,
        handler=handler, source="fastapi", domain="framework", caller="browser",
        read_only=True, sensitivity=Sensitivity.SENSITIVE, side_effects=(SideEffect.NONE,),
        # Историческая граница: гейт этих путей не видел, значит фактически PUBLIC.
        current_access_boundary=AccessBoundary.PUBLIC, current_permission=None,
        auth_off_scope=AuthOffScope.LAN_ALLOWED, gate_excluded=False,
        auth_namespace_bypass=False, handler_guard=HandlerGuard.NONE,
        enforcement_stage=EnforcementStage.CORE_2_784,
        enforced_access=EnforcedAccess.SESSION_ONLY, required_capability=None,
        auth_on_behavior=AuthOnBehavior.REQUIRE_SESSION,
        auth_off_behavior=AuthOffBehavior.ALLOW_LOCAL_OWNER,
        notes="Маршрут создан самим FastAPI, в исходнике не объявлен и в опись 167 не входит. "
              "До 2.784 был доступен анонимно даже при включённой авторизации. " + note,
    )
    for (method, path, handler, note) in _FRAMEWORK_ROWS
)


def all_policies():
    """Все записи описи. Возвращает неизменяемый кортеж."""
    return ALL_POLICIES


def policies_for_domain(domain):
    return tuple(p for p in ALL_POLICIES if p.domain == domain)


def policies_for_module(module_id):
    return tuple(p for p in ALL_POLICIES if p.module_id == module_id)


def policy_for(method, path_template):
    """Запись по ТОЧНОМУ шаблону маршрута и методу.

    Принимает именно шаблон (например '/api/printer/{pid}/cmd'), а НЕ фактический URL с
    пользовательскими данными: это инструмент анализа, а не маршрутизатор.
    """
    m = "WS" if str(method).upper() in ("WS", "WEBSOCKET") else str(method).upper()
    for p in ALL_POLICIES:
        if p.method == m and p.path == path_template:
            return p
    return None


def registry_counts():
    """Сводка по описи. Только агрегаты, никаких значений настроек и секретов."""
    core = [p for p in ALL_POLICIES if p.module_id is None]
    mod = [p for p in ALL_POLICIES if p.module_id is not None]
    def _c(seq, key):
        d = {}
        for p in seq:
            k = key(p)
            d[k] = d.get(k, 0) + 1
        return dict(sorted(d.items(), key=lambda kv: str(kv[0])))
    return {
        "total": len(ALL_POLICIES),
        "core": len(core),
        "modules": len(mod),
        "websocket": sum(1 for p in ALL_POLICIES if p.kind is RouteKind.WEBSOCKET),
        "by_method": _c(ALL_POLICIES, lambda p: p.method),
        "by_boundary": _c(ALL_POLICIES, lambda p: p.current_access_boundary.value),
        "by_auth_off_scope": _c(ALL_POLICIES, lambda p: p.auth_off_scope.value),
        "by_sensitivity": _c(ALL_POLICIES, lambda p: p.sensitivity.value),
        "by_permission": _c(ALL_POLICIES, lambda p: str(p.current_permission)),
        "read_only": sum(1 for p in ALL_POLICIES if p.read_only),
        "mutating": sum(1 for p in ALL_POLICIES if not p.read_only),
        "gate_excluded": sum(1 for p in ALL_POLICIES if p.gate_excluded),
        "auth_namespace_bypass": sum(1 for p in ALL_POLICIES if p.auth_namespace_bypass),
        "handler_guarded": sum(1 for p in ALL_POLICIES if p.handler_guard is not HandlerGuard.NONE),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# РАНТАЙМ Alpha 2.784. Ниже — доступ к объявленной карте прав для общего гейта.
# Реестр остаётся ДАННЫМИ: решение принимает app/route_access_control.py.
# ═══════════════════════════════════════════════════════════════════════════════

# Индекс только по HTTP-маршрутам ЯДРА плюс маршруты самого фреймворка. Модули
# (до 2.785) и WebSocket (до 2.786) обслуживаются прежней моделью и в рантайм-поиске
# сознательно не участвуют. Маршруты фреймворка входят В ИНДЕКС, но НЕ в опись 167:
# они существуют в работающем приложении, значит обязаны иметь политику, иначе гейт
# закроет их отказом 500 как маршрут ядра без объявленных прав.
_CORE_HTTP_INDEX = {(p.method, p.path): p
                    for p in (tuple(CORE_POLICIES) + FRAMEWORK_POLICIES)
                    if p.kind is RouteKind.HTTP}


def core_http_policy(method, path_template):
    """Политика HTTP-маршрута ЯДРА по ФАКТИЧЕСКОМУ шаблону совпавшего маршрута.

    Ключ — шаблон ('/api/printer/{pid}/cmd'), а не сырой URL: шаблон даёт
    app/route_matching.py средствами самого фреймворка.

    -> RoutePolicy или None. None означает «маршрут ядра есть, политики нет» и
    обязан приводить к отказу до вызова обработчика, а не к разрешению.
    """
    return _CORE_HTTP_INDEX.get((str(method).upper(), path_template))


# Индексы маршрутов МОДУЛЕЙ (Alpha 2.785). Ключ по шаблону — для гейта, ключ по
# policy_id — для проверки при регистрации.
_MODULE_HTTP_INDEX = {(p.method, p.path): p for p in MODULE_POLICIES}
_MODULE_BY_POLICY_ID = {p.policy_id: p for p in MODULE_POLICIES if p.policy_id}


def module_http_policy(method, path_template):
    """Политика маршрута МОДУЛЯ по фактическому шаблону совпавшего маршрута.

    -> RoutePolicy или None. None означает «маршрут под /api/mod/ есть, политики нет»
    и обязан приводить к отказу до вызова обработчика, а не к разрешению.
    """
    key = (str(method).upper(), path_template)   # 26.09.2026: неизвестный карте маршрут модуля
    return _MODULE_HTTP_INDEX.get(key) or _RUNTIME_MODULE_HTTP_INDEX.get(key)   # 26.09.2026: -> app/module_runtime_policy.py


_RUNTIME_MODULE_HTTP_INDEX = {}   # 26.09.2026: строгие политики, заполняет только app/module_runtime_policy.py


def websocket_policy():
    """Единственная политика WebSocket (Alpha 2.786).

    Отдельный доступ, а не через HTTP-индексы: сокет обслуживается своим движком, и
    смешивать эти две карты нельзя. -> RoutePolicy или None, если WebSocket в описи нет.
    """
    for p in CORE_POLICIES:
        if p.kind is RouteKind.WEBSOCKET:
            return p
    return None


def module_policy_by_id(policy_id):
    """Политика модуля по стабильному policy_id. None — идентификатор неизвестен."""
    if not policy_id:
        return None
    return _MODULE_BY_POLICY_ID.get(str(policy_id))


def enforced_counts():
    """Сводка объявленной карты прав 2.784. Только агрегаты, без секретов."""
    def _c(seq, key):
        d = {}
        for p in seq:
            k = key(p)
            d[k] = d.get(k, 0) + 1
        return dict(sorted(d.items(), key=lambda kv: str(kv[0])))
    core_http = [p for p in CORE_POLICIES if p.kind is RouteKind.HTTP]
    cap = [p for p in core_http if p.enforced_access is EnforcedAccess.CAPABILITY]
    return {
        "core_http": len(core_http),
        "by_stage": _c(ALL_POLICIES, lambda p: p.enforcement_stage.value),
        "core_by_access": _c(core_http, lambda p: p.enforced_access.value),
        "core_by_capability": _c(cap, lambda p: str(p.required_capability)),
        "core_by_auth_on": _c(core_http, lambda p: p.auth_on_behavior.value),
        "core_by_auth_off": _c(core_http, lambda p: p.auth_off_behavior.value),
    }
