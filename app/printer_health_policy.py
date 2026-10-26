# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — классификация КАНАЛА ЗДОРОВЬЯ принтера (Alpha 2.818).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк, СУБД
и принтерные подсистемы, не обращается к сети/принтерам, ничего не пишет и не меняет. Только
классификация: вход неизменяем, выход детерминирован.

ЗАЧЕМ. Остановка печати пользователем — это ИСХОД ЗАДАНИЯ, а не неисправность устройства.
Bambu после штатной отмены присылает код print_error из «семейства отмены» (0x0300400C →
0300-400C, 0x00020070 → 0002-0070, 0x0300000A → 0300-000A). Раньше решение «ошибка/не ошибка»
принимал фронтенд по ХАРДКОД-СПИСКУ конкретных кодов (web/app.js: _BAMBU_CANCEL_CODES). Каждый
новый код прошивки (2.732: 0300-400C; 2.735: 0002-0070; 2.818: 0300-000A) заново ломал карточку:
незнакомый код отмены показывался красным «Ошибка принтера» и растил счётчик ошибок в шапке.

ЧТО ДЕЛАЕТ ЭТОТ МОДУЛЬ. Сводит решение в ОДНО место (бэкенд) и делает его КОНТЕКСТНЫМ, а не
«код X всегда безопасен». Код отмены гасится ТОЛЬКО при доказанном контексте задания (была
остановка из Farm Manager, либо принтер только что печатал/готовил/стоял на паузе, либо отмена
уже подтверждена и «залипла» до новой печати). Код отмены БЕЗ активного задания (старт, stale,
чужой отчёт) НЕ гасится. Реальный код неисправности (в т.ч. пришедший ОДНОВРЕМЕННО с отменой)
имеет приоритет над отменой и остаётся видимым — настоящие ошибки не скрываются.

ЧТО МОДУЛЬ НЕ ДЕЛАЕТ. Не трогает допуск к печати (это printer_state_policy/orchestrator), не
считает готовые детали (это lifecycle: и отмена, и сбой готовыми НЕ считаются), не различает
отмену/сбой в gcode_state Bambu (её там нет — только код). Klipper/FlashForge различают отмену
СВОЕЙ строкой состояния (printer_job_lifecycle._CANCEL_RAW) — их health-канал ведёт err_msg/
FAILED, а не список кодов, поэтому кодового «белого списка» у них нет и здесь не заводится.
"""


# ── Семейство кодов ОТМЕНЫ Bambu (нормализованный вид 'XXXX-XXXX'). Подтверждено на железе:
#    0300-400C — Alpha 2.732; 0002-0070 (P2S) — Alpha 2.735; 0300-000A (H2D) — Alpha 2.818.
#    Список НАМЕРЕННО узкий: похожие коды (0300-400D, 0002-006F, 0300-000B и т. п.) отменой НЕ
#    считаются и показываются как настоящая ошибка.
BAMBU_CANCEL_ERROR_CODES = frozenset(("0300-400C", "0002-0070", "0300-000A"))

# mc_print_error_code «технический дубль» отмены: десятичный 16396 == hex 0x400C.
BAMBU_CANCEL_MC = frozenset(("16396", "400C"))

# HMS-коды семейства ОТМЕНЫ (нормализованный вид 'XXXX-XXXX'). Подтверждено на ЖИВОМ железе:
#    0003-000A — H2D сообщает этот HMS при остановке печати С ЭКРАНА принтера ОДНОВРЕМЕННО с
#    print_error 0300-400C и mc 16396 (Alpha 2.820; снято из живой телеметрии p_states, а не со
#    скриншота). Это УВЕДОМЛЕНИЕ об отмене, а НЕ аппаратная неисправность. Раньше карточка брала
#    device_error из ПЕРВОГО «реального» HMS (см. _bambu_real_code), поэтому 0003-000A показывался
#    красной «Ошибкой принтера» ДО проверки контекста — фиксы 2.732/2.735/2.818/2.819 правили только
#    СПИСОК print_error и промахивались мимо HMS. Список НАМЕРЕННО узкий: похожие HMS (0003-000B и
#    т. п.) отменой НЕ считаются и показываются как настоящая ошибка. Гасится только при доказанном
#    контексте задания (см. classify_bambu) — как и коды print_error-семейства.
BAMBU_CANCEL_HMS = frozenset(("0003-000A",))

# Известные HMS-коды — ТОЛЬКО КЛЮЧИ для приоритета выбора кода (человекочитаемый текст и
# severity показывает фронтенд по i18n-таблице). Здоровью канала важен сам факт реального кода.
KNOWN_BAMBU_HMS = frozenset(("07FF-8011", "07FF-8007", "12FF-8011", "12FF-8007"))


# ── Alpha 2.992: уведомления принтера (HMS) — то, что видно на его экране ────────────────────
#
# ЗАЧЕМ. Владелец попросил показывать в программе сообщения, которые всплывают на экранах
# принтеров: «Micro Lidar lens seems to be dirty», «филамент кончился, перешёл на такой же» и
# прочие. Раньше программа держала из каждой записи HMS только ПОЛОВИНУ кода (восемь HEX) —
# этого хватало, чтобы отличить отмену от сбоя, но не хватало, чтобы назвать уведомление.
#
# КОНТРАКТ. Запись HMS несёт два 32-битных числа, attr и code. Печатный код принтера — четыре
# группы по четыре HEX: attr>>16, attr&0xFFFF, code>>16, code&0xFFFF. Пример с экрана владельца
# 10.09.2026: attr=0x0C000100, code=0x00010004 -> «0C00-0100-0001-0004».
#   · важность берётся из code>>16: 1 фатально, 2 серьёзно, 3 обычно, 4 сведения;
#   · узел берётся из attr>>24: 0x03 плата движения, 0x05 материнская плата, 0x07 AMS,
#     0x08 голова, 0x0C камера/лидар.
# Разбор снят с открытой реализации ha-bambulab (pybambu: HMS_SEVERITY_LEVELS, HMS_MODULES,
# code>>16 и attr>>24) и сверен с примером владельца: 0x0C -> камера, и уведомление на экране
# действительно про микро-лидар.
#
# ЧЕГО ЗДЕСЬ НЕТ. Текста уведомления: его рисует прошивка из своей таблицы, по MQTT приходят
# только числа. Программа не выдумывает расшифровки — известные ей коды переводит по таблице
# интерфейса, остальные показывает кодом, важностью и узлом.
HMS_SEVERITY = {1: "fatal", 2: "serious", 3: "common", 4: "info"}
#  15.09.2026: 0x18 — AMS-HT. Источник — официальная таблица Bambu (e.bambulab.com/query.php):
#  коды 1880-2000-0002-0058 и подобные подписаны там «AMS-HT A…H».
HMS_MODULES = {0x03: "mc", 0x05: "mainboard", 0x07: "ams", 0x08: "toolhead", 0x0C: "xcam", 0x18: "amsht"}
#  2.993: переводы уведомлений, ИЗВЕСТНЫЕ программе, для текста сообщений в мессенджеры.
#  Правило то же, что у таблицы интерфейса (web/app.js KNOWN_HMS_TEXT, держать одинаковыми):
#  без подтверждённого источника не добавлять. Источник обоих — wiki.bambulab.com.
HMS_KNOWN_TEXT = {
    "0C00-0100-0001-0004": {"ru": "Загрязнилась линза микро-лидара — протрите её",
                            "en": "Micro Lidar lens is dirty — clean the lens"},
    "0700-2000-0003-0002": {"ru": "Филамент в слоте AMS закончился — принтер сам перешёл на такой же",
                            "en": "AMS slot ran out of filament — the printer switched to an identical spool"},
}


def _hms_int(v):
    """Целое из числа или строки (в т.ч. '0x...'), иначе None. Пустое — не ноль, а None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    t = str(v).strip()
    if not t:
        return None
    try:
        return int(t, 16) if t.lower().startswith("0x") else int(t)
    except Exception:
        try:
            return int(t, 16)
        except Exception:
            return None


def hms_record(attr, code):
    """Одна запись HMS -> {code, severity, module} или None, если разобрать нечего.

    code — печатный вид с дефисами (как на экране принтера и в его QR-ссылке), чтобы владелец
    мог сверить один в один. severity/module — 'unknown', если число вне известных значений:
    выдумывать степень важности нельзя, лучше честно сказать «не знаю»."""
    a, c = _hms_int(attr), _hms_int(code)
    if a is None or c is None:
        return None
    if a < 0 or c < 0 or a > 0xFFFFFFFF or c > 0xFFFFFFFF:
        return None
    if a == 0 and c == 0:
        return None                      # пустая запись — не уведомление
    text = "%04X-%04X-%04X-%04X" % ((a >> 16) & 0xFFFF, a & 0xFFFF, (c >> 16) & 0xFFFF, c & 0xFFFF)
    return {"code": text,
            "severity": HMS_SEVERITY.get((c >> 16) & 0xFFFF, "unknown"),
            "module": HMS_MODULES.get((a >> 24) & 0xFF, "unknown")}


def hms_records(entries):
    """Список записей print.hms -> список уведомлений без повторов, в исходном порядке.

    Порядок принтера сохраняем: он ставит первым то, что показал на экране. Неразбираемые
    записи молча пропускаются — одна битая запись не должна прятать остальные."""
    out, seen = [], set()
    for e in list(entries or []):
        if not isinstance(e, dict):
            continue
        rec = hms_record(e.get("attr"), e.get("code"))
        if rec is None or rec["code"] in seen:
            continue
        seen.add(rec["code"])
        out.append(rec)
    return out


#  15.09.2026: тексты сообщений. Источник — официальная таблица Bambu (app/bambu_hms_texts.py,
#  та же, что за QR-кодом на экране принтера); сервер подключает её сюда через HMS_TEXT_LOOKUP /
#  ERROR_TEXT_LOOKUP. Без неё остаются две встроенные записи HMS_KNOWN_TEXT. Модуль по-прежнему
#  чистый: сеть и файлы — снаружи, здесь только поиск по словарю.
HMS_TEXT_LOOKUP = None       # callable(печатный код) -> {"ru":..., "en":...} | None
ERROR_TEXT_LOOKUP = None     # callable('XXXX-XXXX') -> {"ru":..., "en":...} | None


def hms_text_for(code):
    """Текст уведомления по печатному коду: таблица производителя, затем встроенные записи."""
    if not code:
        return None
    if callable(HMS_TEXT_LOOKUP):
        try:
            t = HMS_TEXT_LOOKUP(code)
            if isinstance(t, dict) and t:
                return dict(t)
        except Exception:
            pass
    t = HMS_KNOWN_TEXT.get(str(code))
    return dict(t) if isinstance(t, dict) else None


def error_text_for(code):
    """Текст ошибки печати (print_error) по коду 'XXXX-XXXX' из таблицы производителя, иначе None."""
    if not code or not callable(ERROR_TEXT_LOOKUP):
        return None
    try:
        t = ERROR_TEXT_LOOKUP(code)
        return dict(t) if isinstance(t, dict) and t else None
    except Exception:
        return None


def hms_with_texts(records):
    """К каждой записи уведомления добавить text={"ru","en"}, если текст известен. Записи без
    текста остаются как есть — интерфейс покажет код, узел и важность."""
    out = []
    for r in list(records or []):
        if not isinstance(r, dict):
            continue
        r = dict(r)
        t = hms_text_for(r.get("code"))
        if t:
            r["text"] = t
        out.append(r)
    return out


#  16.09.2026, по жалобе владельца: в ячейках H2D и P2S висели «Уведомление принтера» с кодами
#  0500-0200-0003-000A и 0500-0600-0002-0070, которых на экранах самих принтеров не было.
#  Проверено: обоих кодов НЕТ в официальной таблице Bambu (1978 уведомлений, e.bambulab.com),
#  а Bambu Studio такие записи не показывает вовсе — карточка уведомления создаётся только при
#  непустом тексте (BambuStudio, src/slic3r/GUI/HMSPanel.cpp: if (!msg.empty()) { ... }).
#  Значит, код без текста в таблице производителя — служебная запись прошивки, а не сообщение
#  для человека, и показывать его владельцу нельзя.
HMS_TABLE_READY = None       # callable() -> bool: таблица производителя действительно загружена


def hms_table_ready():
    """Загружена ли таблица сообщений производителя. Хука нет или он сломан — считаем, что нет:
    тогда фильтр не применяется и поведение остаётся прежним."""
    if not callable(HMS_TABLE_READY):
        return False
    try:
        return bool(HMS_TABLE_READY())
    except Exception:
        return False


def hms_user_visible(records, table_ready=None):
    """Оставить только те уведомления, которые принтер показывает ЧЕЛОВЕКУ.

    Правило: запись без текста из таблицы производителя человеку не показывается — ровно так
    поступает Bambu Studio (см. комментарий выше). Применяется ТОЛЬКО когда таблица загружена:
    без неё текста нет ни у одного кода, и фильтр спрятал бы вообще все сообщения (свежая
    установка без интернета). table_ready=True/False — явный ответ для проверок.

    Записей других марок это не касается: у Klipper и FlashForge текст приходит от самого
    принтера и кладётся в запись при разборе, через эту функцию они не проходят."""
    recs = [r for r in list(records or []) if isinstance(r, dict)]
    ready = hms_table_ready() if table_ready is None else bool(table_ready)
    if not ready:
        return recs
    return [r for r in recs if r.get("text")]


def norm_code(value):
    """Код к каноническому виду для сравнения: строка, без пробелов, ВЕРХНИЙ регистр."""
    if value is None:
        return ""
    s = str(value).strip().upper()
    return s


def norm_mc(value):
    """mc_print_error_code к сравнимому виду: без ведущего '0X', ВЕРХНИЙ регистр."""
    if value is None:
        return ""
    s = str(value).strip().upper()
    if s.startswith("0X"):
        s = s[2:]
    return s


def norm_error_code(v):
    """ЕДИНЫЙ canonical нормализатор кода Bambu (print_error / HMS): int, dec-строка или hex '0x…'
    → 'XXXX-XXXX' (ровно 8 HEX) или None. И телеметрия server.py, и классификация используют ИМЕННО
    ЭТУ функцию, чтобы решение НЕ зависело от форматирования строки в интерфейсе. signed приводится
    через & 0xFFFFFFFF; 0/пусто/мусор → None. Порядок групп фиксирован: старшие 16 бит — «группа»,
    младшие 16 бит — «код» (как в Bambu Studio). Пример: 50348044 (0x0300400C) → '0300-400C'; НЕ
    '0003-000A' (это был бы 0x0003000A) и НЕ '400C-0300' (это был бы word-swap). Endian/порядок групп
    здесь зафиксирован числом, а не догадкой."""
    try:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            if s.lower().startswith("0x"):
                n = int(s, 16)
            else:
                try:
                    n = int(s, 10)
                except Exception:
                    n = int(s, 16)
        else:
            n = int(v)
    except Exception:
        return None
    n &= 0xFFFFFFFF
    if n == 0:
        return None
    h = "%08X" % n
    return h[:4] + "-" + h[4:]


def is_bambu_cancel_code(code):
    """Полный код print_error принадлежит семейству отмены (точное совпадение)."""
    return norm_code(code) in BAMBU_CANCEL_ERROR_CODES


def is_bambu_cancel_mc(mc):
    """mc_print_error_code — «технический дубль» отмены (16396 / 400C)."""
    return norm_mc(mc) in BAMBU_CANCEL_MC


def is_bambu_cancel_hms(code):
    """HMS-код принадлежит семейству ОТМЕНЫ (уведомление об отмене, а не неисправность)."""
    return norm_code(code) in BAMBU_CANCEL_HMS


def has_bambu_cancel_signal(snapshot):
    """Присутствует ли в снимке хоть один признак семейства отмены (print_error, mc ИЛИ HMS).
    HMS-признак важен для остановки С ЭКРАНА: у H2D код отмены приходит как HMS 0003-000A, и без его
    учёта одиночный HMS выглядел бы «кода нет вовсе» и молча гас бы (нарушение fail-safe)."""
    ec = norm_code(snapshot.get("error_code"))
    mc = norm_mc(snapshot.get("mc_err"))
    hms = [norm_code(x) for x in (snapshot.get("hms_codes") or [])]
    return ((bool(ec) and is_bambu_cancel_code(ec))
            or is_bambu_cancel_mc(mc)
            or any(is_bambu_cancel_hms(c) for c in hms))


def _bambu_real_code(snapshot):
    """Каноничный РЕАЛЬНЫЙ код неисправности (не из семейства отмены), или None.
    Порядок как исторически во фронтенде: error_code > известный HMS > первый HMS > MC-<mc>."""
    ec = norm_code(snapshot.get("error_code"))
    if ec and not is_bambu_cancel_code(ec):
        return ec
    hms = [c for c in (norm_code(x) for x in (snapshot.get("hms_codes") or [])) if c]
    # Реальная аппаратная неисправность (клог/обрыв и т. п.) ПРИОРИТЕТНА даже во время отмены —
    # известные HMS проверяем ПЕРВЫМИ, поэтому настоящий сбой на остановленной печати не скрывается.
    known = next((c for c in hms if c in KNOWN_BAMBU_HMS), None)
    if known:
        return known
    # HMS семейства отмены (0003-000A) — НЕ «реальный код»: это уведомление об отмене, решение о
    # показе принимает classify_bambu по контексту. Иначе оно короткозамыкало бы контекст-гейт.
    first_real = next((c for c in hms
                       if not is_bambu_cancel_code(c) and not is_bambu_cancel_hms(c)), None)
    if first_real:
        return first_real
    mc = norm_mc(snapshot.get("mc_err"))
    if mc and mc not in ("0", "") and not is_bambu_cancel_mc(mc):
        return "MC-" + mc
    return None


def classify_bambu(snapshot, context):
    """Классифицировать health-канал Bambu.

    snapshot: словарь телеметрии (error_code, mc_err, hms_codes). Неизменяем.
    context:  {user_stop, prev_active, recently_active, latched} — доказательства контекста задания:
        user_stop       — стоит пометка намеренной веб-остановки (_user_stopped);
        prev_active     — НЕПОСРЕДСТВЕННО предыдущий кадр был печать/подготовка/пауза;
        recently_active — принтер был активен НЕДАВНО, в пределах окна (Alpha 2.819). КРИТИЧНО для
                          остановки С ЭКРАНА/из Studio: код семейства отмены (0300-400C и др.) часто
                          приходит на 1-2 кадра ПОЗЖЕ, чем статус уже стал FAILED, поэтому prev_active
                          к тому моменту уже False. Без этого признака известный код отмены снова
                          показывался бы «Ошибкой принтера» (регресс 2.818). Окно ограничено, поэтому
                          код БЕЗ недавней печати (старт, stale) по-прежнему НЕ гасится;
        latched         — отмена этой сессии уже подтверждена ранее и держится до новой печати.

    Возвращает {'device_error': str|None, 'is_cancellation': bool}:
        device_error   — код для КРАСНОГО индикатора карточки/счётчика ошибок, или None (чисто);
        is_cancellation — доказанная штатная отмена (вызывающий защёлкивает её до новой печати).
    """
    context = context or {}
    real = _bambu_real_code(snapshot)
    if real is not None:
        # Настоящая ошибка (в т.ч. одновременно с отменой) — приоритет, отмена её не скрывает.
        return {"device_error": real, "is_cancellation": False}
    if not has_bambu_cancel_signal(snapshot):
        return {"device_error": None, "is_cancellation": False}   # кода нет вовсе
    proven = bool(context.get("user_stop") or context.get("prev_active")
                  or context.get("recently_active") or context.get("latched"))
    if proven:
        return {"device_error": None, "is_cancellation": True}    # штатная отмена → health чист
    # Код отмены БЕЗ доказанного активного задания — НЕ гасим (мог «залипнуть» вне печати).
    # Показываем ровно тот код семейства отмены, что реально пришёл: print_error → HMS → mc.
    ec = norm_code(snapshot.get("error_code"))
    mc = norm_mc(snapshot.get("mc_err"))
    if ec and is_bambu_cancel_code(ec):
        shown = ec
    else:
        hms = [norm_code(x) for x in (snapshot.get("hms_codes") or [])]
        shown = next((c for c in hms if is_bambu_cancel_hms(c)), None) or ("MC-" + mc)
    return {"device_error": shown, "is_cancellation": False}


def device_error(transport, snapshot, context=None):
    """Единая точка: код health-канала для карточки принтера, или None.

    Bambu — по семейству кодов отмены с учётом контекста (см. classify_bambu). Прочие транспорты
    ведут health-канал не списком кодов (Klipper — err_msg, FlashForge — FAILED), поэтому здесь
    кодовой фильтрации у них нет: их отмена различается строкой состояния в printer_job_lifecycle.
    """
    if str(transport or "").strip().lower() == "bambu":
        return classify_bambu(snapshot or {}, context or {})["device_error"]
    return None


# ── Alpha 2.826: ЕДИНЫЙ session-aware контракт завершения печати (job outcome != device health) ──
# Одно место для ВСЕХ адаптеров. Исход задания (completed/cancelled/failed) ОТДЕЛЁН от здоровья
# устройства (device_error): пользовательская отмена — исход задания, а НЕ неисправность, поэтому
# device_error=None и красной карточки нет. Настоящий сбой, потеря связи, перегрев, прошивка —
# по-прежнему device_error. Доказательства ОТМЕНЫ — АДАПТЕРНЫЕ, не общий список кодов на всех:
#   Bambu           — семейство кодов отмены + HMS (classify_bambu; аппаратный HMS приоритетнее);
#   FlashForge/     — СОБСТВЕННАЯ строка состояния 'cancelled' (printer_job_lifecycle._CANCEL_RAW,
#   Klipper/Moonraker  доказано телеметрией FFA5M-1); term_state приходит уже нормализованным.
# Инварианты: cancelled != completed != failed; потеря связи (offline) НЕ отмена и НЕ health-сбой
# (её ведёт OFFLINE-статус); неизвестный адаптер/состояние fail-safe — сбой НЕ скрывается;
# аппаратная ошибка приоритетнее отмены; 'FAILED' сам по себе device fault только при отсутствии
# доказанного признака отмены.
TERM_NONE = "none"
TERM_COMPLETED = "completed"
TERM_CANCELLED = "cancelled"
TERM_FAILED = "failed"
TERM_OUTCOMES = frozenset((TERM_NONE, TERM_COMPLETED, TERM_CANCELLED, TERM_FAILED))

# Безопасные источники завершения (для лога/решения). printer_panel НЕ утверждаем без доказательств
# протокола — внешнюю остановку без явного intent помечаем vendor_external.
SRC_NONE = ""
SRC_LOCAL_STOP = "local_stop"
SRC_VENDOR_EXTERNAL = "vendor_external"
SRC_HARDWARE_FAILURE = "hardware_failure"
SRC_UNKNOWN_FAILURE = "unknown_failure"

GENERIC_FAILED = "FAILED"    # у FlashForge своего кода сбоя нет — generic-признак для карточки


def _adapter_fault(adapter, snapshot):
    """РЕАЛЬНАЯ неисправность адаптера (код/сообщение), или None. Klipper отдаёт готовый текст
    (err_msg — печать/прошивка); FlashForge своего кода не имеет -> generic 'FAILED'; прочие —
    generic 'FAILED' (fail-safe: сбой не скрываем)."""
    a = str(adapter or "").strip().lower()
    if a in ("klipper", "creality"):     # 12.10.2026: у Creality — код и текст ошибки с экрана (err_msg)
        msg = str((snapshot or {}).get("err_msg", "") or "").strip()
        return (" ".join(msg.split())[:240] or GENERIC_FAILED)
    return GENERIC_FAILED


def _term_result(outcome, dev, is_cancel, reason, source):
    return {"outcome": outcome, "device_error": dev, "is_cancellation": bool(is_cancel),
            "reason_code": reason, "source": source}


def classify_termination(adapter, term_state, snapshot=None, context=None):
    """ЕДИНЫЙ вход завершения печати -> {outcome, device_error, is_cancellation, reason_code, source}.

    adapter    — 'bambu'|'flashforge'|'klipper'|... (регистр не важен).
    term_state — нормализованное состояние НАБЛЮДЕНИЯ (printer_job_lifecycle.normalize_state):
                 'cancelled'/'failed'/'completed'/'printing'/'paused'/'idle'/'offline'/'unknown'.
                 У Bambu отмена в gcode_state не выражена -> term_state там НИКОГДА не 'cancelled'
                 (решение по коду). Незнакомая строка приходит как 'unknown' — сбоем НЕ считается,
                 но и отменой тоже (нейтральный none), а вот доказанный 'failed' — device fault.
    snapshot   — телеметрия: Bambu {error_code,mc_err,hms_codes}; Klipper {err_msg}; FF {}.
    context    — {user_stop, prev_active, recently_active, latched, connection_lost}.
    """
    a = str(adapter or "").strip().lower()
    ctx = context or {}
    snap = snapshot or {}
    ts = str(term_state or "").strip().lower()

    # Потеря связи — НЕ завершение задания (ведёт отдельный OFFLINE-статус, не health-канал).
    if ts == "offline" or ctx.get("connection_lost"):
        return _term_result(TERM_NONE, None, False, "connection_lost", SRC_NONE)

    # Bambu: отмену от сбоя различает КОД (gcode_state их не различает). HMS-приоритет сохранён.
    if a == "bambu":
        hc = classify_bambu(snap, ctx)
        dev, is_cancel = hc["device_error"], hc["is_cancellation"]
        if dev is not None:                      # настоящий код (в т.ч. одновременно с отменой)
            return _term_result(TERM_FAILED, dev, False, "device_fault", SRC_HARDWARE_FAILURE)
        if is_cancel:                            # доказанная отмена по коду/контексту
            return _term_result(TERM_CANCELLED, None, True, "vendor_cancel_code",
                                SRC_LOCAL_STOP if ctx.get("user_stop") else SRC_VENDOR_EXTERNAL)
        if ts == TERM_COMPLETED:
            return _term_result(TERM_COMPLETED, None, False, "completed", SRC_NONE)
        if ts == TERM_FAILED:                    # FAILED без кода — health чист (у Bambu код всегда есть)
            return _term_result(TERM_FAILED, None, False, "failed_no_code", SRC_NONE)
        return _term_result(TERM_NONE, None, False, "active", SRC_NONE)

    # FlashForge/Klipper/Moonraker/прочие: отмену доказывает СОБСТВЕННАЯ строка состояния.
    # Настоящий сбой у них приходит ОТДЕЛЬНЫМ состоянием ('error'/'shutdown' -> term_state 'failed'),
    # а не тем же кадром, что 'cancelled' — поэтому 'cancelled' всегда штатная отмена (health чист).
    if ts == TERM_CANCELLED:
        return _term_result(TERM_CANCELLED, None, True, "vendor_cancel_state",
                            SRC_LOCAL_STOP if ctx.get("user_stop") else SRC_VENDOR_EXTERNAL)
    if ts == TERM_FAILED:
        fault = _adapter_fault(a, snap)          # fail-safe: сбой НЕ скрываем даже без текста
        return _term_result(TERM_FAILED, fault, False, "device_fault",
                            SRC_HARDWARE_FAILURE if snap.get("err_msg") else SRC_UNKNOWN_FAILURE)
    if ts == TERM_COMPLETED:
        return _term_result(TERM_COMPLETED, None, False, "completed", SRC_NONE)
    return _term_result(TERM_NONE, None, False, "active", SRC_NONE)
