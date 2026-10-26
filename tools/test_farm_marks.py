# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Настройки фермы на сервере (Alpha 2.927) и удалённые пометки принтера (12.09.2026).

ЗАЧЕМ. 2.927 перенесла с компьютера на сервер пометки принтера «сопло / материал / группа» и
настройки фермы: пересел за другой компьютер — всё на месте. 12.09.2026 владелец решил пометки
убрать целиком: блок из пульта принтера, запись на сервер и поля в ответе со списком принтеров.
Настройки фермы остаются. Проверяется:
  1. пометок нет нигде, откуда их видно или можно записать: пульт, код страницы, маршрут,
     реестр прав, DTO; колонки в базе оставлены (схема не меняется, данные не удаляются);
  2. настройки фермы пишутся только по известным ключам, чужие молча отбрасываются;
  3. выбор модулей на панели и пресеты прогрева живут по тем же правилам (исполнением).

БЕЗОПАСНОСТЬ — КАК В test_queue_wait. Рабочая база НЕ открывается: сервер целиком не
импортируется. Берётся ИСХОДНЫЙ ТЕКСТ функций из server.py и исполняется в отдельном
пространстве имён поверх ВРЕМЕННОЙ базы. Ни одна строка владельца не может быть затронута.

Запуск:  python tools/test_farm_marks.py
"""
import ast
import importlib.util
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "FARM_MARKS_SENTINEL_2_927"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def _read(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding="utf-8").read()


SRC = _read("server.py")
REG = _read("app", "route_policy_registry.py")
DTO = _read("app", "printer_dto.py")
IDX = _read("web", "index.html")
APPJS = _read("web", "app.js")
CSS = _read("web", "ui3", "ui3.css")

print("--- 1. пометок принтера больше нет (решение владельца 12.09.2026) ---")
check("1. колонки пометок в базе оставлены как были: схема не меняется, данные не удаляются",
      "mark_nozzle TEXT DEFAULT ''" in SRC and "mark_material TEXT DEFAULT ''" in SRC
      and "mark_group TEXT DEFAULT ''" in SRC)
check("2. маршрута записи пометок нет ни в сервере, ни в реестре прав",
      "/api/printer/marks" not in SRC and "api_printer_marks" not in SRC
      and "_apply_printer_marks" not in SRC and "api_printer_marks" not in REG
      and "('POST', '/api/printer/marks'" not in REG)
_fields = re.search(r"PUBLIC_PRINTER_FIELDS = \((.*?)\n\)", DTO, re.S)
check("3. пометки не уходят в браузер: в allowlist DTO их нет",
      _fields is not None and "mark_" not in _fields.group(1), _fields.group(1) if _fields else None)
#  Исполнением: чистый модуль DTO грузится из файла напрямую — без базы, сети и server.py.
_spec = importlib.util.spec_from_file_location("fm_printer_dto_marks_check",
                                               os.path.join(ROOT, "app", "printer_dto.py"))
_dto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dto)
_out = _dto.printer_public_dto({"id": "p1", "name": "X1C-01", "token": "FIXTURE_T1",
                                "mark_nozzle": "0.4", "mark_material": "PLA", "mark_group": "Цех А"})
check("3а. исполнением: строка базы со старыми пометками отдаётся без них и без секрета",
      not any(str(k).startswith("mark_") for k in _out) and "token" not in _out
      and _out.get("name") == "X1C-01" and _out.get("credential_configured") is True, _out)
check("4. в пульте принтера нет блока пометок, в коде страницы — ни записи, ни разового переноса",
      "ui3-pp-marks" not in IDX and "saveMark" not in IDX and "Пометки фермы" not in IDX
      and "saveMark" not in APPJS and "_migrateOldMarks" not in APPJS
      and "/api/printer/marks" not in APPJS and "ui3-pp-marks" not in CSS and ".ui3-mark " not in CSS)
check("5. секреты по-прежнему не выходят из DTO",
      'SECRET_PRINTER_FIELDS = ("token",)' in DTO)
#  2.965 добавила к настройкам фермы порог остатка филамента (low_pct) — экран «Филамент»
#  предупреждает, когда катушка ниже него. Список по-прежнему ЯВНЫЙ, в этом смысл проверки.
check("6. ключи настроек фермы перечислены явно (allowlist)",
      '_FARM_SETTINGS_KEYS = ("stagger_on", "stagger_sec", "low_pct", "queue_auto_start", "update_check")' in SRC)
check("6а. настройки фермы: чтение открыто, запись требует права project",
      REG.count("'/api/farm-settings'") == 2
      and "('GET', '/api/farm-settings', 'api_farm_settings_get', 'printers', 'browser', "
      "'OPERATIONAL', ('DATABASE',), 'NONE', None)" in REG
      and "('POST', '/api/farm-settings', 'api_farm_settings_set', 'printers', 'browser', "
      "'OPERATIONAL', ('DATABASE',), 'NONE', 'project')" in REG)

print("--- 2. НАСТОЯЩИЙ код настроек фермы на временной базе ---")
_tree = ast.parse(SRC)
WANT = ("_farm_settings_read", "_farm_settings_write",
        #  2.984 (R-103): пресеты прогрева читаются вместе с настройками фермы
        "_farm_presets_validate", "_farm_presets_read",
        #  2.1000: выбор модулей для панели — тоже настройка фермы, читается там же
        "_farm_bar_modules_validate", "_farm_bar_modules_read",
        #  16.09.2026: список принтеров с разрешённым автозапуском — тоже настройка фермы
        "_farm_auto_start_validate", "_farm_auto_start_read",
        #  16.10.2026 (R-151): настройки интерфейса модулей (адреса камер видеостены и т.п.)
        "_farm_module_ui_validate", "_farm_module_ui_read", "_module_id_ok")
_src_by_name = {}
for node in _tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT:
        _src_by_name[node.name] = ast.get_source_segment(SRC, node)
check("7. исходники функций найдены в server.py",
      all(n in _src_by_name for n in WANT), sorted(_src_by_name))

_tmp = tempfile.mkdtemp(prefix="farmset927_")
conn_p = sqlite3.connect(os.path.join(_tmp, "parts.db"), check_same_thread=False)
conn_p.row_factory = sqlite3.Row
conn_p.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '')")
conn_p.commit()

NS = {"conn_p": conn_p, "lock_p": threading.RLock(),
      #  16.09.2026: queue_auto_start — выключатель автозапуска очереди, обычный строковый ключ
      "_FARM_SETTINGS_KEYS": ("stagger_on", "stagger_sec", "queue_auto_start", "update_check"),
      #  2.984 (R-103): ключ и пределы пресетов — те же, что в server.py
      "_FARM_PRESETS_KEY": "farm_preheat_presets", "_PRESET_NAME_MAX": 12, "_PRESETS_MAX": 24,
      "_PRESET_LIMITS": {"n": (0, 350), "b": (0, 120), "c": (0, 65)}, "json": __import__("json"),
      #  2.1000: ключ и пределы выбора модулей — те же, что в server.py
      "_FARM_BAR_MODULES_KEY": "farm_bar_modules", "_BAR_MODULES_MAX": 24, "_BAR_ID_MAX": 64,
      #  16.09.2026: ключ и пределы списка автозапуска — те же, что в server.py
      "_FARM_AUTO_START_KEY": "farm_auto_start_printers", "_AUTO_START_MAX": 512,
      "_AUTO_START_ID_MAX": 64,
      #  16.10.2026 (R-151): ключ и предел настроек интерфейса модулей — те же, что в server.py
      "_FARM_MODULE_UI_PREFIX": "farm_module_ui.", "_FARM_MODULE_UI_MAX": 256 * 1024,
      "re": __import__("re"),
      "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None)})(),
      "_exc_brief": lambda: "?"}
for n in WANT:
    exec(_src_by_name[n], NS)          # noqa: S102 — свой исходник в песочнице
_fread = NS["_farm_settings_read"]
_fwrite = NS["_farm_settings_write"]

#  ── 2.1001: выбор модулей для панели — настройка ФЕРМЫ и живёт по тем же правилам ───────
_fwrite({"bar_modules": ["messengers", "quality"]})
check("15а. выбор модулей сохраняется и читается обратно",
      _fread().get("bar_modules") == ["messengers", "quality"], _fread())
_fwrite({"stagger_sec": "70"})
check("15б. запись соседней настройки НЕ стирает выбор модулей",
      _fread().get("bar_modules") == ["messengers", "quality"], _fread())
check("15в. пустой выбор законен: «не показывать ни одного» — это не ошибка",
      _fwrite({"bar_modules": []}).get("ok") is True and _fread().get("bar_modules") == [])
check("15г. мусор в списке отвергается целиком, прежний выбор цел",
      _fwrite({"bar_modules": ["плохой id!"]}).get("ok") is False
      and _fread().get("bar_modules") == [])
check("15д. не список — отказ",
      _fwrite({"bar_modules": "messengers"}).get("ok") is False)

#  ── 16.09.2026: автозапуск очереди ожидания — выключатель фермы и список принтеров ───────
#  Разрешение двойное: принтер обязан быть и в этом списке, и с отметкой queue_allowed. Отметку
#  queue_allowed согласием на автомат не считаем: она давалась под обещание «печать начинается
#  по вашему подтверждению».
check("15е. выключатель автозапуска — обычная настройка фермы: записан и прочитан",
      _fwrite({"queue_auto_start": "1"}).get("ok") is True
      and _fread().get("queue_auto_start") == "1", _fread())
_fwrite({"auto_start_printers": ["p1s", "x1c"]})
check("15ж. список принтеров автозапуска сохраняется и читается обратно",
      _fread().get("auto_start_printers") == ["p1s", "x1c"], _fread())
check("15з. запись соседней настройки НЕ стирает список автозапуска",
      _fwrite({"stagger_sec": "70"}).get("ok") is True
      and _fread().get("auto_start_printers") == ["p1s", "x1c"], _fread())
check("15и. пустой список законен: «автозапуск не разрешён никому»",
      _fwrite({"auto_start_printers": []}).get("ok") is True
      and _fread().get("auto_start_printers") == [])
check("15к. мусор в списке отвергается ЦЕЛИКОМ, прежний список цел",
      _fwrite({"auto_start_printers": ["ok_id", ""]}).get("ok") is False
      and _fread().get("auto_start_printers") == [])
check("15л. не список — отказ",
      _fwrite({"auto_start_printers": "p1s"}).get("ok") is False)

#  ── 16.10.2026 (R-151): настройки интерфейса модулей — общие для всех компьютеров ─────────────
_cams = {"ip_sources": [{"id": "c1", "name": "Камера 1", "url": "rtsp://camera.example/stream"}]}
check("15о. пока модули ничего не сохраняли — в чтении module_ui нет (прежний ответ не меняется)",
      "module_ui" not in _fread(), _fread())
_mu = _fwrite({"module_ui": {"camera_wall": _cams}})
check("15п. настройки интерфейса модуля записаны и читаются обратно — с любого компьютера и после смены порта",
      _mu.get("ok") is True and _fread().get("module_ui") == {"camera_wall": _cams}, (_mu, _fread()))
check("15р. запись соседней настройки и другого модуля не стирает их",
      _fwrite({"stagger_sec": "70"}).get("ok") is True
      and _fwrite({"module_ui": {"appearance": {"x": 1}}}).get("ok") is True
      and _fread().get("module_ui") == {"camera_wall": _cams, "appearance": {"x": 1}}, _fread())
check("15с. id модуля проверяется: чужой ключ отклонён целиком, в базу ничего не попало",
      _fwrite({"module_ui": {"../x": {"a": 1}}}).get("error") == "bad_module_ui_id"
      and _fwrite({"module_ui": {"ok_id": {"a": 1}, "bad id": {}}}).get("error") == "bad_module_ui_id"
      and "ok_id" not in (_fread().get("module_ui") or {}))
check("15т. больше 256 КБ на модуль — отказ, прежнее значение цело",
      _fwrite({"module_ui": {"camera_wall": {"big": "x" * (256 * 1024)}}}).get("error") == "module_ui_too_large"
      and (_fread().get("module_ui") or {}).get("camera_wall") == _cams)
check("15у. не объект — отказ",
      _fwrite({"module_ui": {"camera_wall": [1, 2]}}).get("error") == "bad_module_ui_value"
      and _fwrite({"module_ui": "camera_wall"}).get("error") == "bad_module_ui")
check("15ф. null удаляет настройки модуля, остальные остаются",
      _fwrite({"module_ui": {"appearance": None}}).get("ok") is True
      and _fread().get("module_ui") == {"camera_wall": _cams}
      and conn_p.execute("SELECT COUNT(*) c FROM app_settings WHERE key='farm_module_ui.appearance'").fetchone()["c"] == 0)
_fwrite({"module_ui": {"camera_wall": None}})

#  ── R-131 (29.09.2026): выключатель «Проверять обновления» — настройка фермы, только «0»/«1» ──
check("15м. выключатель проверки обновлений записан и прочитан",
      _fwrite({"update_check": "0"}).get("ok") is True
      and _fread().get("update_check") == "0", _fread())
check("15н. мусор вместо «0»/«1» отвергается, прежнее значение цело",
      _fwrite({"update_check": "True"}).get("error") == "bad_update_check"
      and _fread().get("update_check") == "0", _fread())
_fwrite({"update_check": "1"})

r = _fwrite({"stagger_on": "1", "stagger_sec": "90", "evil_key": "hack"})
got = _fread()
check("16. настройки фермы записаны и читаются",
      got.get("stagger_on") == "1" and got.get("stagger_sec") == "90", got)
#  2.984 (R-103): пресеты прогрева — отдельный ключ, едут вместе с настройками фермы.
check("16а. пока пресеты не правили — в чтении их нет", "preheat_presets" not in got, got)
_rp = _fwrite({"preheat_presets": [{"name": "PLA", "n": 215, "b": 55}, {"name": "ASA", "n": 255, "b": 95, "c": 55}]})
_gp = _fread()
check("16б. пресеты записаны и читаются вместе с настройками фермы",
      _rp.get("ok") is True and [x["name"] for x in _gp.get("preheat_presets") or []] == ["PLA", "ASA"]
      and (_gp.get("preheat_presets") or [{}])[1].get("c") == 55 and _gp.get("stagger_sec") == "90", _gp)
check("16в. битые пресеты отклонены с причиной, прежние остались",
      _fwrite({"preheat_presets": [{"name": "X", "n": 999, "b": 60}]}).get("error") == "preset_value_out_of_range"
      and len(_fread().get("preheat_presets") or []) == 2)
check("17. чужой ключ отброшен и в базу не попал",
      conn_p.execute("SELECT COUNT(*) c FROM app_settings WHERE key LIKE '%evil%'")
      .fetchone()["c"] == 0 and "evil_key" not in r)
_fwrite({"stagger_sec": "y" * 100})
check("18. значение настройки ограничено по длине",
      len(_fread().get("stagger_sec", "")) == 32)
check("19. запись без известных ключей — ошибка no_fields",
      _fwrite({"foo": "bar"}).get("error") == "no_fields")

try:
    conn_p.close()
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
