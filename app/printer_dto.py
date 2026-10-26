# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — безопасное публичное представление принтера (Alpha 2.777).

ЧИСТЫЙ модуль: только стандартная библиотека. Не импортирует server.py, не открывает БД,
не ходит в сеть и ничего не знает о принтерных протоколах — чтобы его можно было проверять
офлайн-тестами и чтобы граница «что уходит наружу» была видна одним файлом.

ЗАЧЕМ. Раньше GET /api/printers делал SELECT * и отдавал строку БД целиком, поэтому в
браузер уходило поле token: у Bambu это access code, у FlashForge — serial:checkcode,
у Klipper — API key. Секрет оказывался в памяти вкладки у любого, кому разрешено читать
список принтеров.

ПРИНЦИП — ЯВНЫЙ ALLOWLIST, А НЕ BLACKLIST. Мы перечисляем поля, которые МОЖНО отдать, а не
вычёркиваем опасные. Это важно на будущее: новый столбец, добавленный в таблицу когда-нибудь
потом, НЕ попадёт в API автоматически — его придётся внести сюда осознанно.

ПРО SERIAL. Он остаётся в публичном представлении намеренно: это не пароль, а идентификатор
устройства, напечатанный на самом принтере. Пользователю он нужен, чтобы проверить настройку
Bambu P1 (без него не работает pushall). Полный контроль над принтером давала связка
serial + token — без token сам по себе serial доступа не даёт. Это осознанное решение, а не
недосмотр; остаточный риск раскрытия идентификатора устройства зафиксирован отдельно.
"""

#  16.10.2026 (R-020): чистая проверка адреса (только стандартная библиотека) — для поля
#  address_problem, по которому карточка помечает принтер с неполным адресом. Наборы проверок
#  грузят этот файл и напрямую, без пакета app, — тогда поле просто не заполняется.
try:
    from app import printer_address as _paddr
except ImportError:
    _paddr = None

# Поля, которые РАЗРЕШЕНО отдавать наружу. Добавление сюда — сознательное решение.
PUBLIC_PRINTER_FIELDS = (
    "id",          # идентификатор записи
    "name",        # отображаемое имя
    "type",        # bambu / flashforge / klipper — выбор адаптера в UI
    "ip",          # адрес: нужен форме редактирования
    "port",        # порт: нужен форме редактирования
    "gen",         # формат пути печати Bambu (auto/old/new/ftp)
    "serial",      # идентификатор устройства, НЕ секрет (см. докстроку модуля)
    "model",       # модель для обложки и совместимости
    "order_idx",   # порядок в списке
    #  Пометки принтера (2.927) убраны 12.09.2026 вместе с самой функцией — наружу не отдаются.
)

# Поля, которые НИКОГДА не покидают сервер. Перечислены явно — как документация границы.
SECRET_PRINTER_FIELDS = ("token",)

# Целочисленные поля: нормализуем, чтобы DTO не зависел от того, что вернул драйвер БД.
_INT_FIELDS = ("port", "order_idx")


def has_credential(row):
    """Настроены ли учётные данные принтера. Только факт, без единого байта значения.

    Пусто, None и строка из одних пробелов считаются «не настроено» — ровно та же
    трактовка, что у серверного merge при сохранении (Alpha 2.776)."""
    try:
        v = (row or {}).get("token")
    except Exception:
        return False
    return bool(v is not None and str(v).strip())


def printer_public_dto(row, extra=None):
    """Безопасное представление принтера по ЯВНОМУ allowlist. Возвращает НОВЫЙ dict.

    Исходную строку БД не мутирует. Секретов не отдаёт вовсе: ни значения, ни длины,
    ни фрагмента, ни хеша — только булев признак credential_configured.
    extra — уже вычисленные производные поля (например model_key/cover_url); они
    добавляются поверх и тоже проходят осознанно, а не «всё, что было в строке»."""
    src = row or {}
    out = {}
    for key in PUBLIC_PRINTER_FIELDS:
        try:
            val = src.get(key)
        except Exception:
            val = None
        if key in _INT_FIELDS:
            try:
                val = int(val) if val is not None and str(val) != "" else None
            except Exception:
                val = None
        out[key] = val
    out["credential_configured"] = has_credential(src)
    #  16.10.2026 (R-020): «short» / «bad» — адрес записан так, что связь по нему не запускается
    #  (неполный «198.68.104» Windows достроила бы до публичного 198.68.0.104); иначе None.
    try:
        out["address_problem"] = _paddr.address_problem(src.get("ip"), src.get("type")) if _paddr else None
    except Exception:
        out["address_problem"] = None
    if extra:
        for k, v in dict(extra).items():
            if k in SECRET_PRINTER_FIELDS:
                continue      # производные поля тоже не могут протащить секрет
            out[k] = v
    return out
