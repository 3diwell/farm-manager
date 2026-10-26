# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — реестр КАЖДОЙ постоянной пользовательской настройки ядра.

Единственный источник истины о том, что попадает в резервную копию и КАК восстанавливается.
Правило контракта: любая новая постоянная настройка ДОЛЖНА быть зарегистрирована здесь,
иначе автоматический тест краснеет (test_config_backup_contract.py сверяет реестр с
фактическими ключами config.json / app_settings в server.py).

НЕЛЬЗЯ удалять запись о старом ключе (историческая совместимость): устаревшее — помечать
portability=OPERATIONAL/restore=EXCLUDE, но запись сохранять навсегда. Значения полей —
часть публичного контракта восстановления.
"""

# ── Где физически хранится настройка ───────────────────────────────────────────
STORE_CONFIG_JSON = "config_json"      # config.json (реальные bool/int/list)
STORE_APP_SETTINGS = "app_settings"    # таблица app_settings (TEXT '1'/'0'/строка)

# ── Переносимость между машинами ───────────────────────────────────────────────
PORT_PORTABLE = "portable"             # безопасно переносить; сериализуется в core.values
PORT_MACHINE_BOUND = "machine_bound"   # привязано к этой машине (пути/порт); в core.machine_bound
PORT_OPERATIONAL = "operational"       # транзиентное runtime-состояние; НЕ сериализуется
PORT_SECRET_DERIVED = "secret_derived" # производный крипто-материал; НЕ сериализуется (re-pair)

# ── Поведение при восстановлении ───────────────────────────────────────────────
RB_RESTORE = "restore"                       # применить значение
RB_RESTORE_WITH_WARNING = "restore_with_warning"  # применить, но план обязан предупредить
RB_IMPORT_AS_OFF = "import_as_off"           # деструктивная/сетевая функция: восстановить как OFF
RB_CURRENT_ONLY = "current_only"             # оставить текущее значение машины (показать как инфо)
RB_EXCLUDE = "exclude"                        # вообще не входит в snapshot

# ── Чувствительность (для предупреждений плана) ────────────────────────────────
SENS_NORMAL = "normal"
SENS_NETWORK = "network"
SENS_SECURITY = "security"
SENS_PATH = "path"
SENS_SECRET = "secret"

# ── Тип значения ───────────────────────────────────────────────────────────────
T_BOOL = "bool"
T_INT = "int"
T_STR = "str"
T_LIST = "list"
#  Alpha 2.987: значение-СЛОВАРЬ в config.json. Понадобился для книги признаков принтеров
#  (printer_identity), где ключ — идентификатор принтера, значение — что о нём известно.
#  Хранится только в config.json: там значения настоящие, а не текст, как в app_settings.
T_DICT = "dict"


class Setting(object):
    __slots__ = ("key", "store", "vtype", "portability", "restore_behavior", "sensitivity",
                 "restart_required", "default", "introduced_in_backup_schema", "note")

    def __init__(self, key, store, vtype, portability, restore_behavior, sensitivity,
                 restart_required, default, introduced_in_backup_schema, note):
        self.key = key
        self.store = store
        self.vtype = vtype
        self.portability = portability
        self.restore_behavior = restore_behavior
        self.sensitivity = sensitivity
        self.restart_required = bool(restart_required)
        self.default = default
        self.introduced_in_backup_schema = int(introduced_in_backup_schema)
        self.note = note

    def as_dict(self):
        return {"key": self.key, "store": self.store, "type": self.vtype,
                "portability": self.portability, "restore_behavior": self.restore_behavior,
                "sensitivity": self.sensitivity, "restart_required": self.restart_required,
                "introduced_in_backup_schema": self.introduced_in_backup_schema}


def _s(*a):
    return Setting(*a)


_TRUE = ("1", "true", "on", "yes")


def coerce_out(entry, raw):
    """Представление хранилища -> типизированное значение snapshot (по типу настройки)."""
    if raw is None:
        raw = entry.default
    if entry.vtype == T_BOOL:
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in _TRUE
    if entry.vtype == T_INT:
        try:
            return int(raw)
        except Exception:
            return int(entry.default) if entry.default is not None else 0
    if entry.vtype == T_LIST:
        return list(raw) if isinstance(raw, (list, tuple)) else list(entry.default or [])
    if entry.vtype == T_DICT:
        #  Чужое/битое значение не подставляем как есть: только настоящий словарь, иначе
        #  умолчание. Ключи приводятся к строкам — в JSON других и не бывает.
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items()}
        return dict(entry.default or {})
    return str(raw if raw is not None else "")


def coerce_store(entry, value):
    """Типизированное значение snapshot -> представление хранилища (config.json vs app_settings)."""
    if entry.store == STORE_APP_SETTINGS:
        if entry.vtype == T_BOOL:
            return "1" if bool(value) else "0"
        if entry.vtype == T_INT:
            return str(int(value))
        return str(value if value is not None else "")
    if entry.vtype == T_BOOL:
        return bool(value)
    if entry.vtype == T_INT:
        return int(value)
    if entry.vtype == T_LIST:
        return list(value or [])
    if entry.vtype == T_DICT:
        return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}
    return str(value if value is not None else "")


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЕСТР. Порядок фиксирован (детерминированная сериализация). Ничего не удалять.
# ═══════════════════════════════════════════════════════════════════════════════
_REGISTRY = [
    # ── config.json ────────────────────────────────────────────────────────────
    # Входящий LAN-доступ = сетевая экспозиция: переносим, но план ОБЯЗАН предупредить.
    _s("lan_access_enabled", STORE_CONFIG_JSON, T_BOOL, PORT_PORTABLE,
       RB_RESTORE_WITH_WARNING, SENS_NETWORK, True, False, 1,
       "входящий доступ по локальной сети; смена host применяется при рестарте"),
    _s("project_print_enabled", STORE_CONFIG_JSON, T_BOOL, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, False, 1, "режим печати из проекта"),
    _s("modules_disabled", STORE_CONFIG_JSON, T_LIST, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, [], 1, "список отключённых модулей (id)"),
    # Alpha 2.980 (R-092) завела ключ, но в опись он не попал, и в резервную копию не входил —
    # хотя комментарий в server.py обещал обратное. Найдено полным прогоном 09.09.2026
    # (test_config_backup_contract, проверка 19), исправлено в 2.987 по слову владельца.
    # Что это: вечные признаки заведённых принтеров {printer_id: {kind, value, family,
    # last_ip, learned_ts, source}} — по ним принтер узнаётся после смены адреса в сети.
    # Запись появляется, когда ВЛАДЕЛЕЦ подтверждает «это тот самый принтер» (rebind); сама
    # собой она не восстанавливается, поэтому терять её нельзя — за этим и заносим в опись.
    # Переносимо и восстанавливается вместе с записями принтеров: книга ссылается на их
    # идентификаторы, и брать её из другого места, чем сами принтеры, значит получить книгу,
    # указывающую не на те устройства. Следствие честно назвать: восстановление СТАРОЙ копии
    # вернёт и старую книгу — подтверждения, сделанные после копии, придётся повторить.
    # Секретов здесь нет (коды доступа живут в таблице принтеров и шифруются отдельно).
    _s("printer_identity", STORE_CONFIG_JSON, T_DICT, PORT_PORTABLE,
       RB_RESTORE, SENS_NETWORK, False, {}, 1,
       "вечные признаки принтеров (MAC/серийный) для узнавания после смены адреса"),
    # Alpha 2.831: режим сортировки списка принтеров. ТОЛЬКО визуальный порядок в левой колонке —
    # физический order_idx в БД, очередь, dispatch и печать НЕ меняет. Публичный, переносимый,
    # восстанавливается автоматически; старые копии без ключа -> compatibility default "manual".
    _s("printer_sort_mode", STORE_CONFIG_JSON, T_STR, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, "manual", 1,
       "режим сортировки списка принтеров (manual|model); только визуальный, физический порядок не меняет"),
    # Alpha 2.833: предстартовые предпочтения Klipper по принтерам. JSON-строка вида
    # {"<printer_id>":{"<op_id>":true}} с ТОЛЬКО allowlist-операциями (bed mesh/QGL/z-tilt/clean).
    # Переносимо, восстанавливается; отсутствует/битое -> "" -> {} (compatibility default:
    # «Как в файле», все доп. операции OFF). Печать/очередь/dispatch НЕ меняет; сырой G-code/имена
    # макросов здесь не хранятся — только известные option ID (backend — authority).
    _s("klipper_prestart_prefs", STORE_CONFIG_JSON, T_STR, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, "", 1,
       "предстартовые предпочтения Klipper (JSON {printer_id:{op_id:bool}}); только allowlist, default file_controlled/OFF"),
    # Путь рабочих данных — строго машинно-зависим: НЕ переносим автоматически.
    _s("data_dir", STORE_CONFIG_JSON, T_STR, PORT_MACHINE_BOUND,
       RB_CURRENT_ONLY, SENS_PATH, True, "", 1,
       "расположение рабочих данных на ЭТОЙ машине; перенос — только вручную"),
    # Порт прослушивания — машинно-локальный, риск коллизии: не восстанавливаем.
    _s("server_port", STORE_CONFIG_JSON, T_INT, PORT_MACHINE_BOUND,
       RB_CURRENT_ONLY, SENS_NETWORK, True, 8000, 1,
       "порт HTTP-сервера на ЭТОЙ машине; коллизии — не переносим"),
    # Транзиентные/операционные ключи миграции порта и данных — не резервируем.
    _s("pending_server_port", STORE_CONFIG_JSON, T_INT, PORT_OPERATIONAL,
       RB_EXCLUDE, SENS_NETWORK, False, None, 1, "состояние смены порта (транзиент)"),
    _s("previous_server_port", STORE_CONFIG_JSON, T_INT, PORT_OPERATIONAL,
       RB_EXCLUDE, SENS_NETWORK, False, None, 1, "состояние смены порта (транзиент)"),
    _s("migrate_from", STORE_CONFIG_JSON, T_STR, PORT_OPERATIONAL,
       RB_EXCLUDE, SENS_PATH, False, "", 1, "маркер переноса data_dir (транзиент)"),

    # ── app_settings ───────────────────────────────────────────────────────────
    _s("net_monitor", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, True, 1, "мониторинг сети принтеров"),
    _s("security_enabled", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_RESTORE_WITH_WARNING, SENS_SECURITY, False, False, 1,
       "аутентификация приложения; план предупреждает о смене режима безопасности"),
    _s("slicer_callback_enabled", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, True, 1, "приём callback от слайсера"),
    #  29.09.2026 (R-131): выключатель «Проверять обновления» — выбор пользователя, переносится.
    _s("farm_update_check", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, True, 1, "проверка обновлений на сайте программы"),
    _s("printer_files_read_enabled", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_RESTORE, SENS_NORMAL, False, False, 1, "чтение файлов на принтере"),
    # Удаление файлов принтера = деструктивно: восстанавливается КАК OFF (пользователь включит сам).
    _s("printer_files_delete_enabled", STORE_APP_SETTINGS, T_BOOL, PORT_PORTABLE,
       RB_IMPORT_AS_OFF, SENS_SECURITY, False, False, 1,
       "удаление файлов принтера (деструктивно) — импортируется выключенным"),
    # Пути — машинно-зависимы.
    _s("archive_dir", STORE_APP_SETTINGS, T_STR, PORT_MACHINE_BOUND,
       RB_CURRENT_ONLY, SENS_PATH, False, "", 1, "папка архивов на ЭТОЙ машине"),
    _s("slicer_path", STORE_APP_SETTINGS, T_STR, PORT_MACHINE_BOUND,
       RB_CURRENT_ONLY, SENS_PATH, False, "", 1, "путь к слайсеру на ЭТОЙ машине"),
    # Производный крипто-материал callback-токена — НЕ переносим (re-pair на новой машине).
    _s("slicer_callback_token_hash", STORE_APP_SETTINGS, T_STR, PORT_SECRET_DERIVED,
       RB_EXCLUDE, SENS_SECRET, False, "", 1,
       "хэш callback-токена (секрет-производное) — не резервируется, требует повторной привязки"),
    _s("slicer_callback_token_created_at", STORE_APP_SETTINGS, T_STR, PORT_SECRET_DERIVED,
       RB_EXCLUDE, SENS_SECRET, False, "", 1, "метка создания токена (производное)"),
]

_BY_KEY = {}
for _e in _REGISTRY:
    if _e.key in _BY_KEY:
        raise RuntimeError("duplicate setting key in registry: %s" % _e.key)
    #  2.987: словарь живёт ТОЛЬКО в config.json. В app_settings значения хранятся текстом,
    #  и словарь там молча превратился бы в строку вида "{'a': 1}" — не JSON, обратно не
    #  читается. Ошибка на загрузке модуля лучше испорченной настройки у владельца.
    if _e.vtype == T_DICT and _e.store != STORE_CONFIG_JSON:
        raise RuntimeError("dict setting must live in config.json: %s" % _e.key)
    _BY_KEY[_e.key] = _e


def all_settings():
    return list(_REGISTRY)


def get(key):
    return _BY_KEY.get(key)


def all_keys():
    return frozenset(_BY_KEY.keys())


def keys_for_store(store):
    return frozenset(e.key for e in _REGISTRY if e.store == store)


def config_json_keys():
    return keys_for_store(STORE_CONFIG_JSON)


def app_settings_keys():
    return keys_for_store(STORE_APP_SETTINGS)


def portable_settings():
    """Настройки, сериализуемые в core.values (переносятся)."""
    return [e for e in _REGISTRY if e.portability == PORT_PORTABLE]


def machine_bound_settings():
    """Настройки, сериализуемые в core.machine_bound (информация; применяются осознанно)."""
    return [e for e in _REGISTRY if e.portability == PORT_MACHINE_BOUND]


def excluded_settings():
    """Операционные/секрет-производные — не входят в snapshot вообще."""
    return [e for e in _REGISTRY if e.portability in (PORT_OPERATIONAL, PORT_SECRET_DERIVED)]


def serializable_settings():
    """Всё, что попадает в snapshot (portable + machine_bound)."""
    return portable_settings() + machine_bound_settings()
