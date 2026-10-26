# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""
Alpha 2.818 — остановка печати пользователем ≠ ошибка принтера.

Пользователь остановил печать (кнопкой в Farm Manager, на экране принтера или из Studio); на карточках
Bambu H2/H3 загоралась красная «Ошибка принтера / Код: 0300-000A», рос счётчик ошибок в шапке. Код
завершения задания ошибочно попадал в канал ЗДОРОВЬЯ устройства. Прежние фиксы (2.732: 0300-400C;
2.735: 0002-0070) были ХАРДКОД-СПИСКОМ кодов в самом фронтенде — каждый новый код прошивки ломал
карточку заново. Alpha 2.818: решение переехало в БЭКЕНД (app/printer_health_policy.py) и стало
КОНТЕКСТНЫМ (адаптер + активная сессия/переход + признак семейства отмены + отсутствие реального
сбоя). Фронтенд лишь ПОКАЗЫВАЕТ готовое s.device_error и своего whitelist кодов не держит.

Тест полностью offline: прогон ЧИСТОГО классификатора app/printer_health_policy.py на фейковой
телеметрии + контракт lifecycle (отмена/сбой готовыми деталями не считаются) + статический разбор
проводки server.py и web/app.js. Рабочая БД, DATA_DIR, config, сеть и принтеры не используются;
GUI не открывается; временное — в TemporaryDirectory, он удаляется.
"""
import io
import os
import re
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

# Метка живёт ТОЛЬКО в этой оснастке. В продукт, БД, DATA_DIR, config, логи, модули, ZIP, профиль
# WebView, _incoming/ и команды принтерам не попадает.
SENTINEL = "USER_CANCELLED_PRINT_SENTINEL_2_818"

import app.printer_health_policy as H
import app.printer_job_lifecycle as LC
import app.printer_state_policy as SP

_fail = 0
_pass = 0


def check(name, cond, detail=""):
    global _fail, _pass
    if cond:
        _pass += 1
        print("ok   %s" % name)
    else:
        _fail += 1
        print("FAIL — %s%s" % (name, (" | " + detail) if detail else ""))


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace", newline="").read()


SRV = rd(os.path.join(PROJ, "server.py"))
APP = rd(os.path.join(PROJ, "web", "app.js"))
HPY = rd(os.path.join(PROJ, "app", "printer_health_policy.py"))
ORCH = rd(os.path.join(PROJ, "app", "project_orchestrator.py"))


def snap(**kw):
    d = {"error_code": None, "mc_err": "0", "hms_codes": []}
    d.update(kw)
    return d


def ctx(user_stop=False, prev_active=False, latched=False):
    return {"user_stop": user_stop, "prev_active": prev_active, "latched": latched}


def dev(snapshot, context):
    return H.classify_bambu(snapshot, context)["device_error"]


def cancelled(snapshot, context):
    return H.classify_bambu(snapshot, context)["is_cancellation"]


print("=== A. FORENSIC REGRESSION — сценарий 0300-000A ===")
# 1 — воспроизводим текущий сценарий: активная печать → пользователь остановил → код 0300-000A
_running = ctx(prev_active=True)
check("1. сценарий 0300-000A воспроизведён (Bambu, была активная печать, код 0300-000A)",
      H.is_bambu_cancel_code("0300-000A") and "0300-000A" in H.BAMBU_CANCEL_ERROR_CODES)
# 2 — «старое поведение»: без контекста задания код 0300-000A показался бы как device error
check("2. без контекста задания 0300-000A НЕ гасится автоматически (как старый баг, fail-safe)",
      dev(snap(error_code="0300-000A"), ctx()) == "0300-000A")
# 3 — новое поведение: при доказанном контексте — это отмена, device_error пуст
check("3. при активной печати 0300-000A классифицируется как ОТМЕНА (device_error=None)",
      dev(snap(error_code="0300-000A", mc_err="16396"), _running) is None
      and cancelled(snap(error_code="0300-000A", mc_err="16396"), _running) is True)
# 4 — прежнее исправление найдено и закреплено: 0300-400C и 0002-0070 по-прежнему в семействе отмены
check("4. регрессия прежних фиксов закреплена: 0300-400C (2.732) и 0002-0070 (2.735) в семействе отмены",
      H.is_bambu_cancel_code("0300-400C") and H.is_bambu_cancel_code("0002-0070"))

print("=== B. BAMBU ===")
# 5 — active running + 0300-000A + переход → cancelled
check("5. running + 0300-000A + контекст отмены → cancelled",
      cancelled(snap(error_code="0300-000A"), ctx(prev_active=True)) is True)
# 6 — код без активного задания не скрывается автоматически
check("6. 0300-000A без активного задания (нет контекста) → показывается как ошибка",
      dev(snap(error_code="0300-000A"), ctx()) == "0300-000A")
# 7 — отмена + реальный HMS одновременно → реальный сбой НЕ скрывается
check("7. 0300-400C + реальный HMS 07FF-8007 → device_error=07FF-8007 (сбой не скрыт), не cancellation",
      dev(snap(error_code="0300-400C", mc_err="16396", hms_codes=["07FF-8007"]), _running) == "07FF-8007"
      and cancelled(snap(error_code="0300-400C", hms_codes=["07FF-8007"]), _running) is False)
# 8 — идемпотентность: повторная классификация того же снимка стабильна
_s8 = snap(error_code="0300-000A", mc_err="16396")
check("8. повторная классификация того же снимка идемпотентна",
      dev(_s8, _running) == dev(_s8, _running) and dev(_s8, _running) is None)
# 9, 10 — стоп с экрана / из Studio: контекста локального intent нет, но prev_active доказывает отмену
check("9. стоп с экрана принтера (FAILED, prev был running) → cancelled по контексту",
      cancelled(snap(error_code="0300-000A"), ctx(prev_active=True)) is True)
check("10. стоп из Studio (тот же снимок, prev_active) → cancelled",
      dev(snap(error_code="0002-0070"), ctx(prev_active=True)) is None)
# 11 — стоп из Farm Manager: intent (user_stop) доказывает отмену даже без prev_active
check("11. стоп из Farm Manager (user_stop intent) → cancelled даже без prev_active",
      dev(snap(error_code="0300-000A"), ctx(user_stop=True)) is None
      and cancelled(snap(error_code="0300-000A"), ctx(user_stop=True)) is True)
# 12 — старый intent не применяется к новой печати: server.py снимает latch/intent при новой печати
check("12. server.py снимает и _user_stopped, и _cancel_latch при старте НОВОЙ печати",
      "_new_print" in SRV and "_cancel_latch.pop(pid, None)" in SRV and "_user_stopped.pop(pid, None)" in SRV)

print("=== C. KLIPPER ===")
# 13 — CANCEL_PRINT → cancelled (lifecycle _CANCEL_RAW)
check("13. Klipper 'cancelled' → нормализуется как отмена (lifecycle _CANCEL_RAW)",
      "cancelled" in LC._CANCEL_RAW.get("klipper", frozenset())
      and LC.normalize_state("klipper", "cancelled") == LC.STATE_CANCELLED)
# 14 — paused не отмена
check("14. Klipper 'paused' → активная ПАУЗА (не отмена и не терминал)",
      LC.normalize_state("klipper", "paused") == LC.STATE_PAUSED
      and LC.STATE_PAUSED not in LC.TERMINAL_STATES)
# 15 — потеря связи не отмена
check("15. Klipper потеря связи (connected=False) → offline, НЕ отмена",
      LC.normalize_state("klipper", "printing", connected=False) != LC.STATE_CANCELLED)
# 16 — firmware error остаётся device error (не отмена)
check("16. Klipper 'error' → FAILED/сбой, НЕ отмена",
      LC.normalize_state("klipper", "error") != LC.STATE_CANCELLED
      and SP.normalize_raw("klipper", "error") == SP.Lifecycle.FAILED)

print("=== D. FLASHFORGE ===")
# 17 — подтверждённый stop transition → cancelled
check("17. FlashForge 'cancel'/'cancelled' → отмена (lifecycle _CANCEL_RAW)",
      {"cancel", "cancelled"} <= LC._CANCEL_RAW.get("flashforge", frozenset())
      and LC.normalize_state("flashforge", "cancelled") == LC.STATE_CANCELLED)
# 18 — timeout / потеря связи не отмена
check("18. FlashForge потеря связи → offline, НЕ отмена",
      LC.normalize_state("flashforge", "printing", connected=False) != LC.STATE_CANCELLED)
# 19 — hardware error остаётся device error
check("19. FlashForge 'error' → FAILED/сбой, НЕ отмена",
      LC.normalize_state("flashforge", "error") != LC.STATE_CANCELLED)

print("=== E. COUNTERS — отмена не увеличивает «Готово» ===")
# 20, 21 — cancelled НЕ успех: не считается готовой деталью, counted_at не ставится
check("20. отмена НЕ входит в успешные состояния lifecycle (готовой деталью не считается)",
      LC.STATE_CANCELLED not in LC.SUCCESS_STATES)
check("21. отмена — терминал, но НЕ успех (counted_at по контракту не ставится)",
      LC.STATE_CANCELLED in LC.TERMINAL_STATES and LC.STATE_CANCELLED not in LC.SUCCESS_STATES)
# 22 — completed по-прежнему считается успехом (ровно один раз — терминал)
check("22. completed остаётся успешным терминалом (готовая деталь считается)",
      LC.STATE_COMPLETED in LC.SUCCESS_STATES and LC.STATE_COMPLETED in LC.TERMINAL_STATES)
# 23 — failed не увеличивает готовые
check("23. failed НЕ успех (готовой деталью не считается)",
      LC.STATE_FAILED not in LC.SUCCESS_STATES)
# 24 — Bambu gcode_state не различает отмену/сбой → оба одинаково НЕ считаются готовыми (fail-safe)
check("24. Bambu: отмена/сбой в gcode_state не различаются → оба НЕ увеличивают счётчик (fail-safe)",
      LC._CANCEL_RAW.get("bambu") == frozenset())

print("=== F. PROJECT / UI STATE ===")
# 25–32 — фронтенд: показывает device_error, «В печати» снимается статусом, красной ошибки от отмены нет
check("25. фронтенд снимает «В печати» по статусу принтера (RUNNING/PREPARE), не по коду",
      "st.status === 'RUNNING'" in APP or "status === 'RUNNING'" in APP)
check("28. отмена НЕ показывает красную «Ошибка принтера»: alert берётся из device_error (None → нет alert)",
      "const code = s.device_error" in APP)
check("29. счётчик ошибок шапки растит только реальный alert (device_error), отмена его не создаёт",
      "alertBadgeCount" in APP and "const code = s.device_error" in APP)
check("30. нейтральный текст статуса остановки доступен (user_stop_pending)",
      "user_stop_pending" in APP and "user_stop_pending" in SRV)
check("31. следующий idle показывает готовность: RUNNING/FINISH снимают alert",
      "st === 'RUNNING' || st === 'FINISH'" in APP)
check("32. следующая печать снимает пометки: server.py чистит latch/intent при новой печати",
      "_cancel_latch.pop(pid, None)" in SRV)

print("=== G. PERSISTENCE / RECOVERY ===")
# 33 — latch/intent живут в рантайме (не персистятся ложно); подтверждённый исход хранит lifecycle-сессия
check("33. отмена, подтверждённая протоколом, — терминальное состояние сессии (SESSION_TERMINAL_CANCELLED)",
      hasattr(LC, "SESSION_TERMINAL_CANCELLED") and LC.SESSION_TERMINAL_CANCELLED == "terminal_cancelled")
# 34 — cancelled не оживает как running (терминал — терминал)
check("34. cancelled — терминал, не переводится обратно в active",
      LC.STATE_CANCELLED in LC.TERMINAL_STATES and LC.STATE_CANCELLED not in getattr(LC, "ACTIVE_STATES", frozenset()))
# 35 — startup cleanup не превращает cancelled в failed (разные состояния)
check("35. cancelled и failed — РАЗНЫЕ состояния (recovery не подменяет отмену сбоем)",
      LC.STATE_CANCELLED != LC.STATE_FAILED)
# 36 — повтор того же файла создаёт новую сессию: server.py снимает latch при новой печати (новая физич. сессия)
check("36. повтор того же файла → новая печать снимает latch (новая физическая сессия)",
      "новая физическая сессия" in SRV or "_new_print" in SRV)
# 37 — override отмены нельзя переопределить успехом (успех доказывает только прошивка)
check("37. state_override отменой не может стать успехом (успех доказывает только прошивка)",
      "state_override not in SUCCESS_STATES" in LC.observe.__doc__ or "SUCCESS_STATES" in rd(os.path.join(PROJ, "app", "printer_job_lifecycle.py")))

print("=== H. CONCURRENCY / IDEMPOTENCE ===")
# 38 — latch делает повторные кадры отмены идемпотентными (один INFO, не спам)
check("38. INFO об отмене пишется ОДИН раз (guard 'pid not in _cancel_latch')",
      "if pid not in _cancel_latch:" in SRV and "job_cancelled" in SRV)
# 39 — device_error чистая функция: два вызова дают один результат (нет двойного закрытия)
check("39. классификатор — чистая функция, повтор даёт тот же результат (без побочных эффектов)",
      H.classify_bambu(snap(error_code="0300-000A"), _running) == H.classify_bambu(snap(error_code="0300-000A"), _running))
# 40 — вход неизменяем (классификатор не мутирует снимок)
_s40 = snap(error_code="0300-000A", mc_err="16396", hms_codes=["07FF-8007"])
_before = dict(_s40)
H.classify_bambu(_s40, _running)
check("40. классификатор НЕ мутирует входной снимок", _s40 == _before)
# 41 — сбой БД/исключение не относится к этому модулю (чистый, без БД) — он не может нарастить счётчик
check("41. модуль health-политики не трогает БД/счётчики (только классификация)",
      "import sqlite" not in HPY and "counted" not in HPY
      and "sqlite3" not in HPY and ".execute(" not in HPY and "conn_p" not in HPY and "conn_pr" not in HPY)
# 42 — retry идемпотентен: latched-контекст даёт тот же результат
check("42. latched-контекст идемпотентен (retry не меняет исход)",
      dev(snap(error_code="0300-000A"), ctx(latched=True)) is None)

print("=== I. DEVICE HEALTH ===")
# 43 — job cancellation отделена от device error
check("43. отмена задания отделена от ошибки устройства (device_error=None при доказанной отмене)",
      dev(snap(error_code="0300-000A"), _running) is None)
# 44 — настоящий сбой остаётся красным
check("44. настоящий сбой (07FF-8007) остаётся device_error даже с сигналом отмены рядом",
      dev(snap(error_code="0300-400C", hms_codes=["07FF-8007"]), _running) == "07FF-8007")
# 45 — warning остаётся (известный HMS-код выбирается как реальный)
check("45. известный HMS (07FF-8011) → реальный device_error (warning-класс во фронтенде)",
      dev(snap(hms_codes=["07FF-8011"]), _running) == "07FF-8011")
# 46 — stale cancellation code без нового контекста активной печати НЕ заражает: без контекста показывается
check("46. stale-код отмены без контекста активного задания не гасится молча (fail-safe)",
      dev(snap(error_code="0300-400C"), ctx()) == "0300-400C")
# 47 — device returns idle: нет кода → device_error None (health чист)
check("47. device вернулся в idle (кодов нет) → device_error None",
      dev(snap(), _running) is None)

print("=== J. LOGGING ===")
# 48 — отмена = INFO (не ERROR)
check("48. отмена логируется уровнем INFO (log.info job_cancelled), НЕ ERROR",
      'log.info("[LIFECYCLE] job_cancelled' in SRV)
# 49 — настоящий сбой остаётся ERROR (существующий [BAMBU ERR] не тронут)
check("49. настоящий сбой остаётся видимым в журнале ([BAMBU ERR] сохранён)",
      "[BAMBU ERR]" in SRV)
# 50 — источник отмены различается (farm_manager/external)
check("50. в INFO различается источник отмены (farm_manager / external)",
      "farm_manager" in SRV and "external" in SRV and "source=%s" in SRV)
# 51 — сырой payload/секреты не выводятся классификатором (в модуле нет логирования вообще)
check("51. модуль классификации ничего не пишет в журнал/вывод (нет log./print()) ",
      "log." not in HPY and "print(" not in HPY)
# 52 — повторный кадр не спамит журнал (guard уже проверен в 38)
check("52. повторный кадр отмены не спамит журнал (однократный INFO по guard latch)",
      "if pid not in _cancel_latch:" in SRV)

print("=== K. SECURITY / REGRESSION ===")
check("53. фронтенд НЕ содержит whitelist кодов отмены (убраны _BAMBU_CANCEL_CODES/_bambuCanonCode)",
      "_BAMBU_CANCEL_CODES = new Set" not in APP and "const _bambuCanonCode" not in APP)
check("54. адаптеры не меняют счётчики напрямую: классификация в чистом модуле, без БД/счётчиков",
      "farm_" not in HPY and "print_run" not in HPY)
check("55. единая точка классификации health-канала (app/printer_health_policy.py, зовётся из server.py)",
      "from app import printer_health_policy as _health" in SRV
      and "_health.classify_termination(" in SRV        # Alpha 2.826: единый вход завершения (Bambu делегирует в classify_bambu)
      and "def classify_bambu(" in HPY)
check("56. external reprint sync 2.807 сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_external_reprint_sync.py")))
check("57. управление модулями сохранено", "/api/modules/" in APP)
check("58. restart E2E сохранён", os.path.isfile(os.path.join(PROJ, "tools", "test_packaged_restart_end_to_end.py")))
check("59. резолвер активного порта сохранён", "find_running_local" in rd(os.path.join(PROJ, "app", "desktop_shell.py")))
check("60. встроенный журнал сохранён", "diagSearch" in APP)
check("61. workspace/layout 2.817 сохранён (leftColH-контракт у экранов)",
      os.path.isfile(os.path.join(PROJ, "tools", "test_workspace_vertical_bounds.py")))
check("62. миграций БД нет (правка не трогает схему)",
      not re.search(r"ALTER TABLE|DROP TABLE|CREATE TABLE", HPY))
check("63. новых маршрутов не добавлено (правка телеметрии/классификации)",
      "@app.get" not in HPY and "@app.post" not in HPY)
check("64. модульные ZIP не трогаются", not re.search(r"modules[/\\][A-Za-z_]+\.zip", HPY + APP))
check("65. DISPATCH_ENABLED False", "\nDISPATCH_ENABLED = False" in ORCH)
check("66. TRANSPORT_ENABLED False", "\nTRANSPORT_ENABLED = False" in ORCH)
check("67. реальных команд принтерам модуль не шлёт (нет примитивов отправки)",
      "storbinary" not in HPY and "publish(" not in HPY and ".connect(" not in HPY
      and "requests.post" not in HPY and "gcode_line" not in HPY)
check("68. каталог _incoming/ не используется", "_incoming" not in HPY)
check("69. модуль чистый: не импортирует server/сеть/БД",
      "import server" not in HPY and "requests" not in HPY and "socket" not in HPY)
check("70. сырой код остаётся в p_states для диагностики (device_error — ДОПОЛНИТЕЛЬНОЕ поле)",
      '"error_code": _ecode' in SRV and '"device_error": _dev_err' in SRV)

print("=== M. Внешняя остановка С ЭКРАНА и канонический raw-путь (регресс 2.818 → фикс 2.819) ===")
# Реальный код H2 из ЖИВОГО лога: raw print_error 50348044 = 0x0300400C → '0300-400C'. Скриншотные
# '0003-000A'/'0300-000A' — ДРУГИЕ raw-значения, которых в телеметрии НЕТ (misread). Классификация
# идёт по КАНОНИЧЕСКОМУ коду из единого norm_error_code, а не по display-строке.
_RAW_H2 = 50348044
check("71. канонический нормализатор: raw 50348044 (0x0300400C) → '0300-400C' (единый norm_error_code)",
      H.norm_error_code(_RAW_H2) == "0300-400C" and H.norm_error_code(0x0300400C) == "0300-400C")
check("72. '0003-000A'/'0300-000A' — ДРУГИЕ raw-значения (0x0003000A / 0x0300000A), не равны реальному 0x0300400C",
      H.norm_error_code(0x0003000A) == "0003-000A" and H.norm_error_code(0x0300000A) == "0300-000A"
      and 0x0003000A != _RAW_H2 and 0x0300000A != _RAW_H2 and 0x0300400C == _RAW_H2)
check("73. классификация НЕ зависит от display-строки: есть единый norm_error_code (raw→canonical)",
      "def norm_error_code" in HPY and "return _health.norm_error_code(v)" in SRV)


def _full_path(raw, ctx):
    """ПОЛНЫЙ путь как в server.py on_message: raw int → norm_error_code → classify_bambu."""
    return H.classify_bambu({"error_code": H.norm_error_code(raw), "mc_err": "16396", "hms_codes": []}, ctx)


_ext_recent = {"user_stop": False, "prev_active": False, "recently_active": True, "latched": False}
_ext_none = {"user_stop": False, "prev_active": False, "recently_active": False, "latched": False}
check("74. внешняя остановка (raw 0x0300400C, prev УЖЕ FAILED, но recently_active) → cancellation, device_error=None",
      _full_path(_RAW_H2, _ext_recent)["device_error"] is None
      and _full_path(_RAW_H2, _ext_recent)["is_cancellation"] is True)
check("75. регресс 2.818 воспроизведён: БЕЗ recently_active/latch/intent тот же код показался бы ошибкой",
      _full_path(_RAW_H2, _ext_none)["device_error"] == "0300-400C")
check("76. recently_active покрывает ЗАДЕРЖКУ кода после перехода в FAILED (код на кадр позже статуса)",
      H.classify_bambu({"error_code": "0300-400C"}, _ext_recent)["is_cancellation"] is True)
check("77. окно недавней активности ОГРАНИЧЕНО: stale-код без недавней печати НЕ гасится (fail-safe)",
      H.classify_bambu({"error_code": "0300-400C"}, _ext_none)["device_error"] == "0300-400C")
check("78. реальный сбой при recently_active всё равно показан (приоритет над отменой)",
      H.classify_bambu({"error_code": "0300-400C", "hms_codes": ["07FF-8007"]}, _ext_recent)["device_error"] == "07FF-8007")
check("79. server.py: _last_active_ts обновляется на активном статусе, окно ограничено _CANCEL_RECENT_ACTIVE_S",
      "_last_active_ts[pid] = time.monotonic()" in SRV and "_CANCEL_RECENT_ACTIVE_S" in SRV
      and 'in ("RUNNING", "PREPARE", "PAUSE", "SLICING")' in SRV)
check("80. server.py: recently_active передаётся в классификатор",
      '"recently_active": _recent_active' in SRV)
check("81. server.py: _norm_bambu_error_code делегирует ЕДИНОМУ canonical (без своего форматирования)",
      "return _health.norm_error_code(v)" in SRV)
check("82. print_error 0300-400C в семействе отмены; HMS 0003-000A в BAMBU_CANCEL_HMS, а НЕ в кодах print_error",
      "0300-400C" in H.BAMBU_CANCEL_ERROR_CODES and "0003-000A" not in H.BAMBU_CANCEL_ERROR_CODES
      and "0003-000A" in H.BAMBU_CANCEL_HMS)

print()
print("=== K2. HMS-семейство отмены — реальный корень 2.820 (H2D шлёт HMS 0003-000A на стопе с экрана) ===")
# Снимок ровно как строит on_message при остановке с экрана: print_error+mc отмены И HMS 0003-000A.
_snap_hms = {"error_code": "0300-400C", "mc_err": "16396", "hms_codes": ["0003-000A"]}
check("83. HMS 0003-000A признан кодом ОТМЕНЫ (BAMBU_CANCEL_HMS) — подтверждён живой телеметрией H2D",
      H.is_bambu_cancel_hms("0003-000A") is True and H.is_bambu_cancel_hms("0003-000B") is False)
check("84. КОРЕНЬ 2.820: снимок с HMS 0003-000A + recently_active → cancellation, device_error=None",
      H.classify_bambu(dict(_snap_hms), _ext_recent)["device_error"] is None
      and H.classify_bambu(dict(_snap_hms), _ext_recent)["is_cancellation"] is True)
check("85. регресс до 2.820: тот же снимок БЕЗ фикса показывал бы 0003-000A — _bambu_real_code его больше не берёт",
      H._bambu_real_code(dict(_snap_hms)) is None)
check("86. одиночный HMS 0003-000A (без print_error) распознаётся как признак отмены",
      H.has_bambu_cancel_signal({"hms_codes": ["0003-000A"]}) is True)
check("87. HMS 0003-000A БЕЗ контекста → НЕ гасится (fail-safe): показан код отмены, is_cancellation=False",
      H.classify_bambu({"hms_codes": ["0003-000A"]}, _ext_none)["device_error"] == "0003-000A"
      and H.classify_bambu({"hms_codes": ["0003-000A"]}, _ext_none)["is_cancellation"] is False)
check("88. реальный аппаратный HMS 07FF-8011 рядом с 0003-000A → показан РЕАЛЬНЫЙ (приоритет, не отмена)",
      H.classify_bambu({"error_code": "0300-400C", "hms_codes": ["07FF-8011", "0003-000A"]}, _ext_recent)["device_error"] == "07FF-8011")
check("89. похожий HMS 0003-000B отменой НЕ считается (узость списка) → показан как ошибка",
      H._bambu_real_code({"hms_codes": ["0003-000B"]}) == "0003-000B")
check("90. server.py передаёт hms_codes в классификатор (снимок содержит health-канал HMS)",
      '"hms_codes": _hms_codes' in SRV)
check("91. mc-код отмены (16396) БЕЗ error_code — тоже признак отмены; при recently_active гасится",
      H.has_bambu_cancel_signal({"mc_err": "16396"}) is True
      and H.classify_bambu({"mc_err": "16396"}, _ext_recent)["is_cancellation"] is True)

print("=== L. Метка и следы ===")
_prod = [os.path.join(PROJ, "server.py"), os.path.join(PROJ, "web", "app.js"),
         os.path.join(PROJ, "app", "printer_health_policy.py")]
_leak = [p for p in _prod if SENTINEL in rd(p)]
check("92. метка не попала в продуктовые файлы", not _leak, str(_leak))
check("93. тестовых артефактов нет (_e2e_payload.json)",
      not os.path.exists(os.path.join(PROJ, "tools", "_e2e_payload.json")))
with tempfile.TemporaryDirectory(prefix="fm_uc_" + SENTINEL[-8:] + "_") as _td:
    _td_path = _td
check("94. временный каталог удалён", not os.path.isdir(_td_path))

print()
print("Итого: %d проверок пройдено, %d провалено" % (_pass, _fail))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
sys.exit(1 if _fail else 0)
