# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Backend-тест перехвата команд Bambu Studio (Alpha 2.722). БЕЗ подключения к принтеру и БЕЗ БД:
# из server.py в рантайме ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники (_SNIFF_SECRET_KEYS/_sniff_sanitize и класс
# _BambuStudioSniffer) и исполняются в изолированном namespace со стабами. MQTT полностью замокан
# фейковым клиентом — ни одного реального сокета. Доказываем:
#   S1  _sniff_sanitize вырезает секреты на ЛЮБОЙ глубине (dict/list), структуру сохраняет, вход не мутирует;
#   S2  start(): по on_connect клиент делает subscribe РОВНО на device/<serial>/request; publish НЕ вызывается;
#   S3  project_file помечается is_project_file и санитайзится (access_code → ***);
#   S4  соседняя request-команда (не project_file) НЕ отбрасывается (остаётся в списке);
#   S5  лимит 20: приняли 25 → хранится 20 (последние), received=25;
#   S6  ручная остановка → status 'stopped', teardown зовёт loop_stop+disconnect, active=False;
#   S7  таймаут (укороченный) → status 'timeout', соединение закрыто;
#   S8  ПАРАЛЛЕЛЬНОСТЬ: имитация штатного mqtt_cls/bambu_serials НЕ изменяется (класс их не касается);
#   S9  snapshot: секретов в сериализованном снимке нет; remaining_s в пределах таймаута;
#   S10 СТАТИКА: в исходнике перехвата НЕТ ни одного client.publish( (только subscribe);
#   S11 [BAMBU_PAYLOAD] логируется через _sniff_sanitize НЕПОСРЕДСТВЕННО перед штатным publish, payload не меняется.
# Запуск: python tools/test_bambu_studio_sniff.py   (0 = все проверки пройдены)
import os, sys, io, re, json, time, threading, collections, uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1

def _slice(src, start_marker, end_marker):
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]

# ── извлекаем ДОСЛОВНЫЙ исходник (не копию) ──
block_a = _slice(SRC, "_SNIFF_SECRET_KEYS = {", "\ndef _bambu_send_project(")
block_b = _slice(SRC, "_SNIFF_TIMEOUT_S = 120.0", "\n_bambu_studio_sniffer = _BambuStudioSniffer(log)")
check("извлечены исходники: _sniff_sanitize + класс _BambuStudioSniffer",
      "_sniff_sanitize" in block_a and "class _BambuStudioSniffer" in block_b and "def start(" in block_b)

# ── S10 СТАТИКА: в перехвате нет ни одного publish (только subscribe) ──
check("S10. в исходнике перехвата НЕТ client.publish( — только subscribe (read-only гарантия на уровне кода)",
      ".publish(" not in block_b and "subscribe(" in block_b and block_b.count("subscribe(") >= 1)

# ── S11 СТАТИКА: [BAMBU_PAYLOAD] через _sniff_sanitize и ПЕРЕД publish, payload не меняется ──
_send = _slice(SRC, "def _bambu_send_project(", "\n# ==========================================")
_pay_i = _send.find("[BAMBU_PAYLOAD]")
_pub_i = _send.find('_bambu_publish(pid, topic, json.dumps({"print": pl}))')
check("S11. [BAMBU_PAYLOAD] логируется через _sniff_sanitize НЕПОСРЕДСТВЕННО перед publish; сам pl не мутируется",
      _pay_i > 0 and _pub_i > _pay_i and "_sniff_sanitize(pl)" in _send and "pl =" not in _send[_pay_i:_pub_i])

# ── исполняем извлечённые блоки в изолированном namespace со стабами ──
class _Log:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
ns = {"threading": threading, "collections": collections, "time": time, "json": json,
      "uuid": uuid, "_exc_brief": (lambda: ""), "log": _Log()}
exec(block_a, ns)
exec(block_b, ns)
Sniffer = ns["_BambuStudioSniffer"]
sanitize = ns["_sniff_sanitize"]

# ═══ S1: санитайзер вырезает секреты на любой глубине, вход не мутирует ═══
deep = {"print": {"command": "project_file", "url": "ftp:///a.3mf", "use_ams": True,
                  "access_code": "SECRET123", "nested": {"password": "p", "ok": 1,
                  "arr": [{"token": "t", "keep": "v"}, {"AccessCode": "x"}]}}}
orig = json.loads(json.dumps(deep))   # снимок для проверки неизменности
clean = sanitize(deep)
flat = json.dumps(clean)
check("S1. секреты вырезаны на любой глубине (access_code/password/token/AccessCode → ***), полезные поля целы",
      "SECRET123" not in flat and '"p"' not in flat and '"t"' not in flat
      and clean["print"]["access_code"] == "***"
      and clean["print"]["nested"]["password"] == "***"
      and clean["print"]["nested"]["arr"][0]["token"] == "***"
      and clean["print"]["nested"]["arr"][1]["AccessCode"] == "***"
      and clean["print"]["command"] == "project_file" and clean["print"]["use_ams"] is True
      and clean["print"]["nested"]["arr"][0]["keep"] == "v"
      and deep == orig)   # вход НЕ изменён

# ── фейковый MQTT-клиент: считает subscribe/publish, хранит колбэки, connect/loop — заглушки ──
class FakeMsg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else payload.encode("utf-8")
class FakeClient:
    def __init__(self, cid):
        self.client_id = cid
        self.subscribed = []
        self.publish_calls = []       # ДОЛЖЕН остаться пустым
        self.connected = False
        self.looping = False
        self.disconnected = False
        self.loop_stopped = False
        self.on_connect = None
        self.on_message = None
    def connect(self, ip, port, ka): self.connected = True; self._ip = ip; self._port = port
    def loop_start(self): self.looping = True
    def loop_stop(self): self.loop_stopped = True
    def disconnect(self): self.disconnected = True
    def subscribe(self, topic): self.subscribed.append(topic)
    def publish(self, *a, **k): self.publish_calls.append((a, k))   # если вызовется — тест провалится

made = []
def factory(cid):
    c = FakeClient(cid); made.append(c); return c

# ═══ S2: start → connect; on_connect → subscribe ровно на нужный топик; publish не вызван ═══
snf = Sniffer(_Log())
r = snf.start("node_ab12cd", "X1C", "10.0.0.9", 8883, "01PSERIAL9", factory)
c = made[0]
c.on_connect(c, None, None, 0)   # эмулируем успешное подключение paho → срабатывает подписка
snap = snf.snapshot()
check("S2. start: connect на 10.0.0.9:8883; subscribe РОВНО device/01PSERIAL9/request; publish НЕ вызван; client_id уникальный (не FM_<pid>)",
      r.get("ok") is True and c.connected and c.looping
      and c.subscribed == ["device/01PSERIAL9/request"]
      and c.publish_calls == []
      and c.client_id.startswith("FM_SNIFF_") and c.client_id != "FM_node_ab12cd"
      and snap["status"] == "listening" and snap["active"] is True)

# ═══ S3: project_file помечается и санитайзится ═══
proj = json.dumps({"print": {"command": "project_file", "param": "Metadata/plate_1.gcode",
                             "use_ams": True, "ams_mapping": [0], "timelapse": False,
                             "flow_cali": True, "bed_leveling": True, "access_code": "LEAK"}})
c.on_message(c, None, FakeMsg("device/01PSERIAL9/request", proj))
snap = snf.snapshot()
m0 = snap["messages"][-1]
check("S3. project_file: is_project_file=True, command='project_file', access_code вырезан, поля команды видны",
      m0["is_project_file"] is True and m0["command"] == "project_file"
      and "LEAK" not in json.dumps(m0) and m0["json"]["print"]["access_code"] == "***"
      and m0["json"]["print"]["use_ams"] is True and m0["json"]["print"]["flow_cali"] is True)

# ═══ S4: соседняя request-команда НЕ отбрасывается ═══
nb = json.dumps({"print": {"command": "gcode_line", "param": "M104 S220"}})
c.on_message(c, None, FakeMsg("device/01PSERIAL9/request", nb))
snap = snf.snapshot()
last = snap["messages"][-1]
check("S4. соседняя команда (gcode_line) СОХРАНЕНА (не отброшена), помечена не-project_file",
      last["command"] == "gcode_line" and last["is_project_file"] is False
      and len(snap["messages"]) == 2 and c.publish_calls == [])

# ═══ S5: лимит 20 (приняли 25 → хранится 20, received=25) ═══
snf2 = Sniffer(_Log())
snf2.start("p2", "P1S", "10.0.0.8", 8883, "SER2", factory)
c2 = made[-1]; c2.on_connect(c2, None, None, 0)
for i in range(25):
    c2.on_message(c2, None, FakeMsg("device/SER2/request", json.dumps({"print": {"command": "c%02d" % i}})))
snap2 = snf2.snapshot()
check("S5. лимит: received=25, хранится РОВНО 20 последних (c05..c24), max=20",
      snap2["received"] == 25 and snap2["stored"] == 20 and snap2["max"] == 20
      and snap2["messages"][0]["command"] == "c05" and snap2["messages"][-1]["command"] == "c24"
      and c2.publish_calls == [])

# ═══ S6: ручная остановка ═══
snf2.stop()
time.sleep(0.25)   # даём сторожу проснуться
snap2b = snf2.snapshot()
check("S6. ручной stop: active=False, status='stopped', loop_stop+disconnect вызваны; сообщения остаются видимы",
      snap2b["active"] is False and snap2b["status"] == "stopped"
      and c2.loop_stopped and c2.disconnected and snap2b["stored"] == 20)

# ═══ S7: таймаут (укороченный через globals извлечённого namespace) ═══
ns["_SNIFF_TIMEOUT_S"] = 0.4
snf3 = Sniffer(_Log())
snf3.start("p3", "H2D", "10.0.0.7", 8883, "SER3", factory)
c3 = made[-1]; c3.on_connect(c3, None, None, 0)
time.sleep(0.75)   # больше таймаута
snap3 = snf3.snapshot()
check("S7. таймаут: сессия сама остановилась (status='timeout', active=False, disconnect вызван)",
      snap3["active"] is False and snap3["status"] == "timeout" and c3.disconnected and c3.publish_calls == [])
ns["_SNIFF_TIMEOUT_S"] = 120.0

# ═══ S8: параллельность — имитация штатных структур НЕ изменяется классом ═══
main_mqtt_cls = {"node_ab12cd": object()}      # как штатный воркер
main_serials = {"node_ab12cd": "01PSERIAL9"}
before_cls = dict(main_mqtt_cls); before_ser = dict(main_serials)
snf4 = Sniffer(_Log())
snf4.start("node_ab12cd", "X1C", "10.0.0.9", 8883, "01PSERIAL9", factory)
c4 = made[-1]; c4.on_connect(c4, None, None, 0)
c4.on_message(c4, None, FakeMsg("device/01PSERIAL9/request", proj))
# Доказательство изоляции: класс исполнялся в namespace, где нет НИ ОДНОГО штатного имени
# (mqtt_cls/bambu_serials/worker_epoch/p_states/mqtt_pub), и ВСЕ методы (start/on_connect/on_message/
# stop/watchdog/snapshot) отработали без NameError → класс физически не может к ним обращаться.
# Плюс код-обращения (не docstring): в исходнике нет паттернов доступа mqtt_cls[ / bambu_serials.
_forbidden_ns = all(k not in ns for k in ("mqtt_cls", "bambu_serials", "worker_epoch", "p_states", "_bambu_publish"))
_no_access = ("mqtt_cls[" not in block_b and "mqtt_cls.get" not in block_b
              and "bambu_serials" not in block_b and "worker_epoch" not in block_b)
check("S8. изоляция от штатного MQTT: namespace без mqtt_cls/bambu_serials/worker_epoch/p_states — все методы отработали; имитация штатных структур не изменилась; свой клиент отдельный; нет код-доступа к ним",
      _forbidden_ns and _no_access
      and main_mqtt_cls == before_cls and main_serials == before_ser
      and c4 is not main_mqtt_cls["node_ab12cd"])
snf4.stop()

# ═══ S9: снимок без секретов + remaining в пределах таймаута ═══
snap9 = snf.snapshot()
check("S9. snapshot: секретов нет в сериализации; remaining_s в (0..120]; поля received/stored/messages присутствуют",
      "LEAK" not in json.dumps(snap9) and 0 < snap9["remaining_s"] <= 120
      and "received" in snap9 and "messages" in snap9 and snap9["timeout_s"] == 120)
snf.stop()

# суммарная проверка: НИ ОДНОГО publish за весь тест ни на одном клиенте
total_pub = sum(len(x.publish_calls) for x in made)
check("итог: за весь тест НИ ОДНОГО client.publish() ни на одном перехватчике (доказано рантаймом)", total_pub == 0)

print("\n" + ("FAIL: %d проверок провалено" % fail if fail else
             "PASS: перехват Bambu Studio — read-only (0 publish), лимит/таймаут/стоп/фильтр/санитайзер работают, штатный MQTT не тронут"))
sys.exit(1 if fail else 0)
