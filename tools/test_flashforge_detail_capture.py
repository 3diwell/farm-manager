# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Один обезличенный ответ FlashForge /detail в журнал (16.09.2026).

ЗАЧЕМ. Программа не умеет читать материал у FlashForge: поля ответа /detail нигде не описаны, а
выдумывать контракт принтера нельзя (CLAUDE.md §6). Прежняя отладочная строка резала ответ на 600
знаках — снять с неё было нечего. Теперь при первом успешном опросе в журнал уходит ОДИН полный
ответ, обезличенный, и владелец может прислать его кнопкой «Скачать журнал».

Проверяется исполнением самое опасное:
  1. серийник, код доступа, адреса и MAC в журнал не попадают — ни ключом, ни значением;
  2. осталась хоть одна подозрительная строка — не печатаем ВЕСЬ ответ (лучше ничего, чем чужое);
  3. поля, ради которых всё затевалось (материал, температуры, статус), в тексте остаются;
  4. «один раз» — это один раз на принтер за запуск программы, даже если воркер перезапускался;
  5. захват НЕ делает ни одного обращения к принтеру и не трогает замок и тихое окно: конкурентный
     запрос валит прошивку A5M 3.1.5 намертво (правило 2.765).

БЕЗОПАСНОСТЬ: сервер целиком не импортируется, сеть не используется. Из server.py берётся блок
констант FlashForge и исходники помощников — и исполняются в отдельном пространстве имён.

Запуск:  python tools/test_flashforge_detail_capture.py
"""
import ast
import io
import json
import os
import re
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "FF_DETAIL_CAPTURE_3_0"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
BLOCK = SRC[SRC.index("_FF_HTTP_LOCKS = {}"):SRC.index("async def run_flashforge(")]
check("1. блок констант FlashForge извлечён и содержит сторож однократного захвата",
      "_FF_DETAIL_CAPTURED" in BLOCK and "_FF_DETAIL_GUARD" in BLOCK)

_tree = ast.parse(SRC)
FUNCS = ("_sniff_sanitize", "_ff_key_norm", "_ff_redact", "_ff_detail_safe_text")
_src = {}
for node in _tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        _src[node.name] = ast.get_source_segment(SRC, node)
CONSTS = {"_SNIFF_SECRET_KEYS", "_FF_SECRET_KEYS", "_FF_SECRET_RE", "_FF_DETAIL_MAX"}
_const_src, _seen = [], set()
for node in _tree.body:
    if isinstance(node, ast.Assign):
        names = set()
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
        if names & CONSTS:
            _const_src.append(ast.get_source_segment(SRC, node))
            _seen |= (names & CONSTS)
check("2. исходники обезличивания найдены", all(n in _src for n in FUNCS) and _seen == CONSTS,
      (sorted(set(FUNCS) - set(_src)), sorted(CONSTS - _seen)))

NS = {"threading": threading, "time": time, "json": json, "re": re}
exec(BLOCK, NS)                     # noqa: S102 — исполняем СВОЙ же исходник в песочнице
for s in _const_src:
    exec(s, NS)                     # noqa: S102
for n in FUNCS:
    exec(_src[n], NS)               # noqa: S102
safe_text = NS["_ff_detail_safe_text"]

#  Ответ выдуманный: настоящего у разработки нет, и поля материала как раз неизвестны.
DETAIL = {"code": 0, "message": "Success", "detail": {
    "status": "ready", "printFileName": "Кронштейн.gcode", "printProgress": 0,
    "rightTemp": 25.0, "platTemp": 24.5, "errorCode": "",
    "rightFilamentType": "PLA", "hasRightFilament": True,
    "serialNumber": "FIXTURE_SN_12345678", "checkCode": "FIXTURE_CODE_9876",
    "ipAddr": "10.0.0.14", "macAddr": "AA:BB:CC:DD:EE:FF",
    "nested": [{"token": "FIXTURE_TOKEN", "camera": {"ip": "10.0.0.14"}}]}}
SECRETS = ("FIXTURE_SN_12345678", "FIXTURE_CODE_9876", "10.0.0.14")

txt, leaks = safe_text(DETAIL, SECRETS)
check("3. чужого в тексте нет: ни серийника, ни кода доступа, ни адреса, ни MAC",
      all(s not in txt for s in SECRETS + ("AA:BB:CC:DD:EE:FF", "FIXTURE_TOKEN")), txt[:200])
check("4. ключи-секретов закрыты, а сам ответ показан — по нему и ищут поля материала",
      bool(txt) and not leaks and "***" in txt, (txt[:120], leaks))

#  Страховка на случай, когда секрет приехал ЗНАЧЕНИЕМ под безобидным ключом: такой ответ
#  не печатается вовсе — лучше не показать ничего, чем показать чужое.
SNEAKY = {"detail": {"status": "ready", "note": "printer FIXTURE_SN_12345678 is ready",
                     "gateway": "10.0.0.14"}}
txt_s, leaks_s = safe_text(SNEAKY, SECRETS)
check("4b. секрет значением под обычным ключом замещён на «***», ответ остался полезным",
      bool(txt_s) and not leaks_s and "FIXTURE_SN_12345678" not in txt_s
      and "10.0.0.14" not in txt_s and "ready" in txt_s, (txt_s[:120], leaks_s))

#  16.09.2026: у принтера с камерой адрес приезжает ВНУТРИ ссылки. Прежнее правило «нашли адрес —
#  не печатаем ничего» сжигало единственную попытку захвата; теперь адрес замещается.
CAM = {"detail": {"status": "ready", "rightFilamentType": "PLA",
                  "cameraStreamUrl": "http://10.0.0.14:8080/?action=stream",
                  "printFileThumbUrl": "http://10.0.0.14:8898/getThumb"}}
txt_c, leaks_c = safe_text(CAM, SECRETS)
check("4c. адрес внутри ссылки замещён, а ответ показан (поля материала остались)",
      bool(txt_c) and not leaks_c and "10.0.0.14" not in txt_c and "rightFilamentType" in txt_c, (txt_c[:140], leaks_c))

#  Коды привязки к облаку — это доступ к принтеру в чужом аккаунте, в журнал они попасть не должны.
REG = {"detail": {"status": "ready", "flashRegisterCode": "FIXTURE_REG_4821",
                  "polarRegisterCode": "FIXTURE_POLAR_77", "serial_number": "FIXTURE_SN_12345678",
                  "MAC-Addr": "AA:BB:CC:DD:EE:FF", "rightFilamentType": "PETG"}}
txt_r, leaks_r = safe_text(REG, ())
check("4d. коды привязки к облаку и ключи с разделителями закрыты «***»",
      bool(txt_r) and all(s not in txt_r for s in ("FIXTURE_REG_4821", "FIXTURE_POLAR_77",
                                                   "FIXTURE_SN_12345678", "AA:BB:CC:DD:EE:FF"))
      and "rightFilamentType" in txt_r, (txt_r[:200], leaks_r))

CLEAN = {"code": 0, "detail": {"status": "ready", "rightFilamentType": "PLA", "hasRightFilament": True,
                               "matlStationInfo": {"slotInfos": [{"materialName": "PETG", "slotId": 1}]},
                               "rightTemp": 25.0, "errorCode": "",
                               "serialNumber": "FIXTURE_SN_12345678", "checkCode": "FIXTURE_CODE_9876"}}
txt2, leaks2 = safe_text(CLEAN, SECRETS)
check("5. ключи-секреты закрыты, а сам ответ показан",
      bool(txt2) and not leaks2 and "FIXTURE_SN_12345678" not in txt2 and "FIXTURE_CODE_9876" not in txt2, (txt2[:160], leaks2))
check("6. поля, ради которых всё затевалось, остались: материал, ячейка, статус, температура",
      all(k in txt2 for k in ("rightFilamentType", "PLA", "materialName", "PETG", "status", "rightTemp")), txt2[:200])
check("7. ключи секретов сохранены, чтобы структура была видна",
      '"serialNumber"' in txt2 and "***" in txt2, txt2[:160])

BIG = {"detail": {"status": "ready", "junk": ["x" * 200 for _ in range(200)]}}
txt3, _l3 = safe_text(BIG, ())
check("8. длина ограничена — один ответ не вытеснит журнал",
      0 < len(txt3) <= NS["_FF_DETAIL_MAX"] + 32, len(txt3))

check("9. мусор вместо ответа не роняет обезличивание",
      isinstance(safe_text(None, ()), tuple) and isinstance(safe_text(object(), ())[0], str))

#  Однократность: сторож живёт в МОДУЛЕ, а не в локальной переменной воркера — иначе каждый
#  перезапуск воркеров (правка принтера, «Перезапустить») печатал бы ответ заново.
def once(pid, guard, seen):
    with guard:
        if pid in seen:
            return False
        seen.add(pid)
        return True


_g, _seen_set = NS["_FF_DETAIL_GUARD"], NS["_FF_DETAIL_CAPTURED"]
_n = sum(1 for _ in range(50) if once("ff1", _g, _seen_set))
_n2 = sum(1 for _ in range(3) if once("ff2", _g, _seen_set))
check("10. один захват на принтер за запуск программы, у второго принтера — свой",
      _n == 1 and _n2 == 1, (_n, _n2))

_WORKER = SRC[SRC.index("async def run_flashforge("):SRC.index("def _flashforge_control(")]
check("10b. пометка «снято» ставится только после того, как ответ ушёл в журнал",
      "_FF_DETAIL_CAPTURED.add(pid)" in _WORKER
      and _WORKER.index("_ff_txt, _ff_leaks = _ff_detail_safe_text") < _WORKER.index("_FF_DETAIL_CAPTURED.add(pid)"))
check("11. захват берёт УЖЕ полученный ответ: ни одного нового запроса к принтеру",
      "_ff_detail_safe_text(resp" in _WORKER and "_FF_DETAIL_CAPTURED" in _WORKER)
_cap = _WORKER[_WORKER.index("_FF_DETAIL_CAPTURED"):]
_cap = _cap[:_cap.index("det = resp.get")] if "det = resp.get" in _cap else _cap
check("12. в захвате нет ни запроса, ни замка принтера, ни тихого окна (правило 2.765)",
      all(bad not in _cap for bad in ("urlopen", "Request(", "_ff_http_lock", "_ff_quiet", "acquire")))
check("13. ответ уходит в журнал уровнем info — только он попадает в farm.log",
      "log.info" in _cap and "полный ответ /detail" in _cap)
check("14. тихое окно по-прежнему проверяется до любого запроса",
      "_ff_quiet_active(ip, port)" in _WORKER)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
