# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.987 — признаки принтеров переживают резервное копирование.

ЗАЧЕМ. R-092 (2.980) завёл в config.json ключ `printer_identity` — книгу вечных признаков
заведённых принтеров (MAC или серийный номер). По ней программа узнаёт принтер, когда тот
сменил адрес в сети. Запись появляется, когда ВЛАДЕЛЕЦ подтверждает «это тот самый принтер»,
сама собой она не восстанавливается. В опись настроек резервного копирования ключ тогда не
занесли, и в копию он не попадал — хотя комментарий в server.py обещал обратное. Нашёл
полный прогон 09.09.2026 (test_config_backup_contract, проверка 19).

ЧТО ДОКАЗЫВАЕТСЯ ЗДЕСЬ (исполнением настоящего кода подсистемы, без заглушек):
  * книга уходит в копию и возвращается словарём, байт в байт;
  * в файле копии её нет открытым текстом — только внутри шифра;
  * осмотр копии без пароля признаков не показывает;
  * битое значение не роняет восстановление, а становится пустой книгой;
  * договор восстановления назван прямо: копия несёт ВСЕ переносимые настройки, поэтому
    восстановление приводит книгу к состоянию копии — как и любую другую настройку.

Безопасность прогона: server.py не импортируется, рабочие БД и config не открываются,
сеть и принтеры не используются — только чистые модули app/config_backup.

Запуск: python tools/test_printer_identity_backup.py   (0 = все проверки пройдены)
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config_backup import serializer                      # noqa: E402
from app.config_backup import settings_registry as reg        # noqa: E402
from app.config_backup.repository import DictGateway          # noqa: E402

SENTINEL = "PRINTER_IDENTITY_BACKUP_SENTINEL_2_987"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


BOOK = {
    "pr_1": {"kind": "mac", "value": "AA:BB:CC:DD:EE:01", "family": "bambu",
             "last_ip": "10.0.0.11", "learned_ts": 1788900000.0, "source": "discovery"},
    "pr_2": {"kind": "serial", "value": "FIXTURE_SERIAL_2", "family": "klipper",
             "last_ip": "10.0.0.12", "learned_ts": 1788900001.0, "source": "discovery"},
}
TOKEN = "PRINTER_TOKEN_" + SENTINEL

print("=== Alpha 2.987: признаки принтеров в резервной копии ===")

# ── реестр ────────────────────────────────────────────────────────────────────────────────
_e = reg.get("printer_identity")
check("1. ключ зарегистрирован в описи настроек", _e is not None)
check("2. классифицирован верно: config.json, словарь, переносимо, восстанавливается",
      _e is not None and _e.store == reg.STORE_CONFIG_JSON and _e.vtype == reg.T_DICT
      and _e.portability == reg.PORT_PORTABLE and _e.restore_behavior == reg.RB_RESTORE,
      _e.as_dict() if _e else None)
check("3. словарь живёт только в config.json (в app_settings он стал бы строкой)",
      all(x.store == reg.STORE_CONFIG_JSON for x in reg.all_settings() if x.vtype == reg.T_DICT))
check("4. чужое значение к словарю не приводится: только настоящий словарь или умолчание",
      reg.coerce_out(_e, "битое") == {} and reg.coerce_out(_e, None) == {}
      and reg.coerce_out(_e, BOOK) == BOOK)

# ── сквозной путь: копия -> шифр -> разбор -> восстановление ──────────────────────────────
src = DictGateway(
    config={"lan_access_enabled": False, "project_print_enabled": False, "modules_disabled": [],
            "printer_identity": BOOK, "data_dir": "D:\\data", "server_port": 8000},
    app_settings={"net_monitor": "1", "security_enabled": "0"},
    printers=[{"id": "pr_1", "name": "P1", "type": "bambu", "ip": "10.0.0.11", "port": 8883,
               "token": TOKEN, "last_parts": "{}", "order_idx": 0, "gen": "auto",
               "serial": "FIXTURE_S1", "model": "Bambu Lab X1C"}])

blob = serializer.export_backup(src, "pw", created_by="test", created_at="2026-09-09")
check("5. копия создана", isinstance(blob, (bytes, bytearray)) and len(blob) > 100)

raw = bytes(blob)
check("6. признаки НЕ лежат в файле копии открытым текстом (только внутри шифра)",
      b"AA:BB:CC:DD:EE:01" not in raw and b"FIXTURE_SERIAL_2" not in raw)
check("7. код доступа принтера тоже только внутри шифра", TOKEN.encode() not in raw)
check("8. осмотр копии без пароля признаков не показывает",
      "AA:BB:CC:DD:EE:01" not in json.dumps(serializer.inspect_container(blob),
                                            ensure_ascii=False, default=str))

dst = DictGateway(config={"data_dir": "E:\\data", "server_port": 8000}, app_settings={}, printers=[])
check("9. на чистой машине признаков нет",
      not (dst.get_config_json() or {}).get("printer_identity"))

mut = serializer.payload_to_mutation(serializer.decode_payload(blob, "pw"), {"core", "printers"})
check("10. книга попала в мутацию восстановления", "printer_identity" in mut.config_set,
      sorted(mut.config_set))

dst.apply_mutation(mut)
got = (dst.get_config_json() or {}).get("printer_identity")
check("11. после восстановления книга на месте и совпадает с исходной", got == BOOK, got)
check("12. восстановлен СЛОВАРЬ, а не текст", isinstance(got, dict))

# ── битое значение ────────────────────────────────────────────────────────────────────────
src_bad = DictGateway(config={"printer_identity": "не словарь", "data_dir": "D:\\data",
                              "server_port": 8000}, app_settings={}, printers=[])
blob_bad = serializer.export_backup(src_bad, "pw", created_by="test", created_at="2026-09-09")
mut_bad = serializer.payload_to_mutation(serializer.decode_payload(blob_bad, "pw"), {"core"})
check("13. битое значение становится пустой книгой, а не роняет восстановление",
      mut_bad.config_set.get("printer_identity") == {},
      mut_bad.config_set.get("printer_identity"))

# ── договор восстановления назван прямо ───────────────────────────────────────────────────
#  Копия несёт ВСЕ переносимые настройки: чего на машине нет, попадает умолчанием. Значит
#  восстановление приводит машину к состоянию копии — это верно и для книги признаков.
src_empty = DictGateway(config={"data_dir": "D:\\data", "server_port": 8000},
                        app_settings={}, printers=[])
blob_empty = serializer.export_backup(src_empty, "pw", created_by="test", created_at="2026-09-09")
mut_empty = serializer.payload_to_mutation(serializer.decode_payload(blob_empty, "pw"), {"core"})
check("14. копия с машины без признаков несёт пустую книгу (как и прочие настройки)",
      mut_empty.config_set.get("printer_identity") == {},
      mut_empty.config_set.get("printer_identity"))

dst2 = DictGateway(config={"printer_identity": BOOK}, app_settings={}, printers=[])
dst2.apply_mutation(mut_empty)
check("15. восстановление такой копии приводит книгу к состоянию копии; подтверждения "
      "«это тот принтер», сделанные ПОСЛЕ копии, придётся повторить",
      (dst2.get_config_json() or {}).get("printer_identity") == {},
      (dst2.get_config_json() or {}).get("printer_identity"))

dst3 = DictGateway(config={}, app_settings={}, printers=[])
dst3.apply_mutation(serializer.payload_to_mutation(serializer.decode_payload(blob, "pw"), {"core"}))
check("16. и наоборот: копия с книгой приносит её на машину, где книги не было",
      (dst3.get_config_json() or {}).get("printer_identity") == BOOK)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
