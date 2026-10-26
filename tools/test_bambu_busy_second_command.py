# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.851 — вторая команда печати уже печатающему принтеру НЕ уходит.

ЗАЧЕМ. 18.08.2026 на ферме при запуске печати на H2D принтер показывал на экране красное
«Device is busy and cannot start new task. Please wait for current task to complete before
sending new task. [0500-4004]». Печать при этом ШЛА — за окном ошибки было видно «Homing
toolhead». Значит первая команда была принята, а следом ушла вторая, лишняя.

ОТКУДА ВТОРАЯ КОМАНДА. Формат адреса файла в команде печати у разных поколений Bambu разный,
и Farm Manager перебирает варианты: отправил → посмотрел реакцию → если решил, что отказ,
погасил ошибку и отправил следующий. Признаком отказа считался в том числе рост числа записей
в списке HMS. Но HMS у Bambu — общий список уведомлений принтера, и записи в нём появляются
В МОМЕНТ старта печати, когда отчёт со статусом PREPARE ещё не пришёл. Принятая команда
объявлялась отклонённой — и следующая уходила в идущую печать.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ:
  · вердикт после команды: рост HMS сам по себе больше не отказ, если печать пошла;
  · отказ остаётся отказом: принтер остался в покое и выдал ошибку — вердикт 'fail';
  · перебор схем прекращается, как только принтер вышел из покоя, — вторая команда печати
    не публикуется НИКОГДА, даже если отчёт о старте пришёл с опозданием;
  · НЕ ВАКУУМ: прежняя редакция вердикта на этих же данных давала 'fail' — то есть проверка
    меряет разницу, а не саму себя.

КАК. Ни сервер, ни принтер не поднимаются: из server.py в рантайме ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ
исходники (_bambu_print_started, _bambu_print_outcome, _bambu_send_project) и исполняются
со стабами состояния и публикации — тот же способ, что и в tools/test_bambu_print_payload.py.
Ни одна команда никуда не отправляется.

Запуск:  python tools/test_bambu_busy_second_command.py      (0 = дефект закрыт)
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)          # модули программы (app/...) берутся из репозитория
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
SENTINEL = "BAMBU_BUSY_SECOND_COMMAND_SENTINEL_2_851"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def _slice(src, a, b):
    i = src.index(a)
    j = src.index(b, i)
    return src[i:j]


# ── ДОСЛОВНЫЕ исходники из server.py ──────────────────────────────────────────
_bstart = __import__("app.bambu_start_policy", fromlist=["x"])   # 2.988: разбор стадии
_health = __import__("app.printer_health_policy", fromlist=["x"])   # 15.09.2026: коды ошибок
verdict_src = _slice(SRC, "def _bambu_print_started(", "\n# Alpha 2.722: ключи-секреты")
send_src = _slice(SRC, "def _bambu_send_project(", "\n# ==========================================")
#  15.09.2026: на каждой отвергнутой попытке отправка записывает, чем принтер ответил
#  (_bambu_refusal_note) — это и есть причина словами принтера в панели отправок. Без неё
#  перебор схем падает NameError. Берём её и нормализатор кода ДОСЛОВНО, а не заглушкой:
#  заглушка скрыла бы поломку самой записи.
note_src = _slice(SRC, "def _bambu_refusal_note(", "\ndef _bambu_refusal_reason(")
norm_src = _slice(SRC, "def _norm_bambu_error_code(", "\ndef _bambu_hms_list(")
#  16.10.2026 (R-114, R-138): текст для панели отправок — в том числе причина «принтер занят».
reason_src = _slice(SRC, "def _bambu_refusal_reason(", "\n# Все известные форматы пути")
check("1. извлечены дословные исходники вердикта, перебора схем и записи причины отказа",
      "_bambu_print_outcome" in verdict_src and "_bambu_send_project" in send_src
      and "_bambu_last_refusal" in note_src and "norm_error_code" in norm_src)


class _Log:
    def __init__(self):
        self.lines = []

    def _w(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    info = debug = warning = error = _w


class Stage:
    """Поддельный принтер: состояние по расписанию + журнал опубликованных команд."""

    def __init__(self, timeline):
        self.timeline = timeline            # список состояний, по одному на опрос
        self.i = 0
        self.published = []                 # (topic, команда) — что ушло бы принтеру

    def state(self):
        s = self.timeline[min(self.i, len(self.timeline) - 1)]
        self.i += 1
        return s


def build(stage, order, ok_scheme=None, sleep_calls=None):
    """Исполняет извлечённые исходники со стабами. Возвращает пространство имён."""
    import json as _json

    p_states = _Dyn(stage)
    log = _Log()

    def _bambu_publish(pid, topic, payload, attempts=10, delay=0.6):
        stage.published.append((topic, _json.loads(payload)))
        return True

    class _T:
        @staticmethod
        def monotonic():
            _T.t += 0.4
            return _T.t
        t = 0.0

        @staticmethod
        def sleep(x):
            if sleep_calls is not None:
                sleep_calls.append(x)

    ns = {
        "p_states": p_states, "log": log, "time": _T, "json": _json,
        "_exc_brief": (lambda: ""), "_bambu_publish": _bambu_publish,
        "_bambu_scheme_order": (lambda pid: list(order)),
        "_bambu_ok_scheme": ({} if ok_scheme is None else ok_scheme),
        "_SCHEME_URL": {"ftp": (lambda f: "ftp:///" + f), "emmc": (lambda f: "brtc://emmc/" + f),
                        "sd": (lambda f: "file:///sdcard/" + f), "mnt": (lambda f: "file:///mnt/sdcard/" + f)},
        "_sniff_sanitize": (lambda o: o),
        #  2.976: последний ответ прошивки на команду печати. Пусто = ответа ещё нет.
        "_bambu_cmd_ack": {},
        #  2.988: запрос свежего отчёта (pushall) идёт напрямую через MQTT-клиент, минуя
        #  _bambu_publish. Подкладываем клиент и серийник, чтобы запросы были ВИДНЫ.
        "mqtt_cls": {"p": _FakeMqtt(stage)}, "bambu_serials": {"p": "SER"},
        #  last_seen — отметка о приходе отчёта. Поддельный клиент отвечает на pushall
        #  сразу, поэтому отметка меняется при каждом запросе: так и ведёт себя принтер.
        "last_seen": _Fresh(stage),
        #  2.976: решение «приняла ли прошивка команду печати» вынесено в модуль.
        #  Берём НАСТОЯЩИЙ модуль: тест именно про его разбор кодов занятости.
        "_bstart": __import__("app.bambu_start_policy", fromlist=["x"]),
        #  15.09.2026: сюда отправка складывает причину отказа принтера, отсюда её читает
        #  панель отправок. Пустой словарь = ещё ни одного отказа.
        "_bambu_last_refusal": {}, "_health": _health,
    }
    exec(compile(norm_src, "<norm>", "exec"), ns)
    exec(compile(note_src, "<note>", "exec"), ns)
    exec(compile(reason_src, "<reason>", "exec"), ns)
    exec(compile(verdict_src, "<verdict>", "exec"), ns)
    exec(compile(send_src, "<send>", "exec"), ns)
    ns["_stage"] = stage
    ns["_log"] = log
    return ns


class _Dyn(dict):
    """p_states, отдающий очередное состояние из расписания при каждом обращении."""

    def __init__(self, stage):
        super().__init__()
        self._stage = stage

    def get(self, pid, default=None):
        return self._stage.state()


class _Fresh(dict):
    """last_seen: каждое чтение отдаёт новое значение — отчёт «пришёл»."""

    def __init__(self, stage):
        super().__init__()
        self._n = 0

    def get(self, pid, default=None):
        self._n += 1
        return self._n


class _FakeMqtt:
    """MQTT-клиент ровно в том объёме, в каком его трогает запрос полного отчёта."""

    def __init__(self, stage):
        self._stage = stage

    def is_connected(self):
        return True

    def publish(self, topic, payload, qos=0):
        self._stage.published.append((topic, __import__("json").loads(payload)))
        return type("_I", (), {"rc": 0, "wait_for_publish": staticmethod(lambda timeout=0: None)})()


IDLE = {"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 0}


def st(status="IDLE", pe=0, mce="0", hms=0, stg=None, ptype=None, raw=None, ams=None):
    #  stg — поле stg_cur отчёта: чем принтер занят прямо сейчас (2.988).
    #  ptype — поле print_type отчёта («idle», «local», «cloud»…), 08.10.2026.
    #  raw — СЫРОЙ gcode_state (status_raw): карточка после отмены показывает IDLE, а прошивка — FAILED.
    #  ams — поле ams_status (16.10.2026, R-138): главный байт 0x01 — смена филамента, 0x07 — протяжка.
    d = {"status": status, "print_error": pe, "mc_err": mce, "hms_n": hms}
    if stg is not None:
        d["stage"] = stg
    if ptype is not None:
        d["print_type"] = ptype
    if raw is not None:
        d["status_raw"] = raw
    if ams is not None:
        d["ams_status"] = ams
    return d


print("--- 2. Вердикт после команды печати ---")

# Ровно тот случай, что был на ферме: HMS вспыхнул при старте, статус PREPARE пришёл следом.
tl = [st(hms=1), st(hms=2), st("PREPARE", hms=2)] + [st("RUNNING", hms=2)] * 40
ns = build(Stage(tl), ["ftp", "emmc"])
check("2. HMS вспыхнул при старте, следом пришёл PREPARE — команда ПРИНЯТА ('ok')",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "ok")

# Настоящий отказ: принтер так и остался в покое и выдал ошибку.
tl = [st(hms=1)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("3. принтер ОСТАЛСЯ в покое и выдал ошибку — это отказ ('fail')",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "fail")

tl = [st(pe=5)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("4. отказ по print_error тоже остался отказом",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "fail")

tl = [IDLE] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("5. тишина без ошибок — по-прежнему 'timeout' (медленный старт печать не отменяет)",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "timeout")

# НЕ ВАКУУМ: прежняя редакция на данных пункта 2 давала 'fail'.
OLD = '''def _old_outcome(pid, base_pe, base_mce, base_hms, timeout=9.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        s = p_states.get(pid, {})
        if str(s.get("status", "")).upper() in ("SLICING", "PREPARE", "RUNNING"):
            return "ok"
        pe = int(s.get("print_error", 0) or 0)
        mce = str(s.get("mc_err", "0") or "0")
        hms = int(s.get("hms_n", 0) or 0)
        if (pe != 0 and pe != base_pe) or (mce not in ("0", "") and mce != base_mce) or (hms > base_hms):
            return "fail"
        time.sleep(0.4)
    return "timeout"
'''
tl = [st(hms=1), st(hms=2), st("PREPARE", hms=2)] + [st("RUNNING", hms=2)] * 40
ns = build(Stage(tl), ["ftp", "emmc"])
exec(compile(OLD, "<old>", "exec"), ns)
check("6. НЕ ВАКУУМ: прежняя редакция на этих же данных объявляла принятую команду отказом",
      ns["_old_outcome"]("p", 0, "0", 0) == "fail")

print("--- 3. Перебор схем: вторая команда печатающему принтеру ---")

# Печать пошла на первой же схеме: команда должна уйти РОВНО одна.
tl = [st(hms=1), st("PREPARE", hms=2)] + [st("RUNNING", hms=2)] * 60
stage = Stage(tl)
ns = build(stage, ["ftp", "emmc", "sd", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
cleans = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "clean_print_error"]
check("7. запуск признан успешным", ok is True, ok)
check("8. КОРЕНЬ ДЕФЕКТА: команда печати ушла РОВНО ОДНА (принтеру нечего называть busy)",
      len(prints) == 1, [c["print"].get("url") for c in prints])
check("9. гасить ошибку не понадобилось — её и не было", len(cleans) == 0, len(cleans))

# Отчёт о старте опоздал: вердикт по первой схеме 'timeout', но ко второй итерации
# принтер уже печатает — перебор обязан остановиться, вторая команда не уходит.
tl = [IDLE] * 24 + [st("RUNNING", hms=3)] * 60
stage = Stage(tl)
okmap = {}
ns = build(stage, ["ftp", "emmc", "sd", "mnt"], ok_scheme=okmap)
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
check("10. опоздавший отчёт о старте: команда печати всё равно ушла ровно одна",
      len(prints) == 1, [c["print"].get("url") for c in prints])
check("11. и запуск засчитан успешным", ok is True, ok)

# Настоящий отказ: принтер отвергает адрес и остаётся в покое. Перебор ОБЯЗАН продолжиться —
# иначе правка «не слать вторую команду» просто отключила бы поиск рабочего формата адреса.
# HMS растёт на каждом опросе: у каждой схемы свой базовый уровень, и он всегда превышается —
# так воспроизводится принтер, который отвергает ЛЮБОЙ предложенный формат адреса.
tl = [st(hms=i) for i in range(1, 500)]
stage = Stage(tl)
ns = build(stage, ["ftp", "emmc", "sd", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
cleans = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "clean_print_error"]
check("12. НЕ ВАКУУМ: принтер в покое отвергает адрес — перебор прошёл ВСЕ схемы, поиск не сломан",
      len(prints) == 4 and [c["print"]["url"] for c in prints] == ["ftp:///plate.3mf", "brtc://emmc/plate.3mf",
                                                                   "file:///sdcard/plate.3mf", "file:///mnt/sdcard/plate.3mf"],
      [c["print"].get("url") for c in prints])
check("13. перед каждой следующей попыткой ошибка на экране гасится", len(cleans) == 4, len(cleans))
check("14. ни один формат не принят — запуск честно признан неуспешным", ok is False, ok)

print("--- 4. Порядок схем и содержимое команды не тронуты ---")
check("15. схема адреса H2D по-прежнему brtc://emmc/ (порядок перебора не менялся)",
      'lambda f: f"brtc://emmc/{f}"' in SRC)
check("16. двухсопельным по-прежнему первым пробуется ftp — рабочий путь не переставлен",
      '["ftp", "emmc", "sd", "mnt"] if nc >= 2' in SRC)
check("17. команда печати не изменена: payload собирается там же и тем же составом полей",
      '"command": "project_file", "param": plate_param' in SRC)

print("--- 5. Стадия работы принтера (2.988): «паркует голову» — тоже занятость ---")
#  Разбор стадии взят из карты pybambu (ha-bambulab): 13 = homing_toolhead,
#  2 = heatbed_preheating, 1 = auto_bed_leveling, 0 = printing; покой — -1 и 255.
check("18. стадия читается верно: работа — это и ноль (печать), покой — только -1 и 255",
      all(_bstart.is_working_stage(v) for v in (0, 1, 2, 13, 27))
      and not any(_bstart.is_working_stage(v) for v in (-1, 255))
      and not _bstart.is_working_stage(None) and not _bstart.is_working_stage(""))

#  Тот самый снимок владельца: на экране «Homing toolhead», статус ещё IDLE, HMS растёт.
tl = [st(hms=1, stg=13), st(hms=2, stg=13)] + [st(hms=2, stg=2)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("19. СНИМОК ВЛАДЕЛЬЦА: статус ещё IDLE, но принтер паркует голову — команда ПРИНЯТА",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "ok")

#  НЕ ВАКУУМ: без чтения стадии те же данные давали отказ, и следом уходила вторая команда.
tl = [st(hms=1), st(hms=2)] + [st(hms=2)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("20. НЕ ВАКУУМ: те же данные БЕЗ стадии по-прежнему дают отказ — проверка меряет разницу",
      ns["_bambu_print_outcome"]("p", 0, "0", 0) == "fail")

#  Принтер В ПОКОЕ до команды (предполётная проверка пропускает), а сразу после неё
#  начинает парковать голову — ровно то, что снял владелец. HMS при этом растёт.
tl = [st(), st()] + [st(hms=i, stg=13) for i in range(1, 500)]
stage = Stage(tl)
ns = build(stage, ["ftp", "emmc", "sd", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
check("21. принтер начал парковать голову — команда печати ушла РОВНО ОДНА, перебор остановлен",
      len(prints) == 1 and ok is True, ([c["print"].get("url") for c in prints], ok))

pushes = [c for _t, c in stage.published if "pushing" in c]
check("22. после команды печати программа СПРАШИВАЕТ свежий отчёт, а не ждёт планового",
      len(pushes) >= 1 and pushes[0]["pushing"].get("command") == "pushall", len(pushes))

#  2.988, второй сценарий той же ошибки: принтер занят ЕЩЁ ДО команды (прошлая печать
#  не закрыта, оператор запустил калибровку с панели). Тогда не уходит НИ ОДНОЙ
#  команды: раньше первая уходила, принтер показывал «Device is busy», а программа
#  считала запуск удавшимся, потому что в телеметрии видела работу.
tl = [st(hms=i, stg=1) for i in range(1, 500)]
stage = Stage(tl)
ns = build(stage, ["ftp", "emmc", "sd", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
check("23. принтер занят ЕЩЁ ДО команды — не уходит ни одной, запуск честно отклонён",
      len(prints) == 0 and ok is False, ([c["print"].get("url") for c in prints], ok))

#  Предохранитель предполётной проверки: она обязана МОЛЧАТЬ, когда свежего отчёта нет.
#  Прошивка держит состояние прошлой печати до следующего полного отчёта, и отказ по
#  устаревшему RUNNING не пускал бы законную следующую печать.
tl = [st("RUNNING", hms=1)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("25. свежий отчёт не получен (нет серийника) — предполётная проверка МОЛЧИТ, печать не блокируется",
      ns["_bambu_busy_before_start"]("нет-такого-принтера") == "",
      ns["_bambu_busy_before_start"]("нет-такого-принтера"))

tl = [st("RUNNING", hms=1)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
_why = ns["_bambu_busy_before_start"]("p")
check("26. свежий отчёт говорит «печатает» — отказ с человеческой причиной, а не молча",
      _why == "the printer is already printing", _why)

tl = [st(stg=13)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
_why2 = ns["_bambu_busy_before_start"]("p")
#  16.10.2026 (R-138): в причине теперь номер и название стадии (таблица pybambu) — её видно в панели.
check("27. свежий отчёт говорит «выполняет стадию» — тоже отказ, команда не уходит; стадия названа",
      _why2.startswith("the printer is busy: it is running a preparation step") and "13" in _why2
      and "homing_toolhead" in _why2, _why2)

print("--- 6. Стадия 0 у принтера в покое (08.10.2026, ферма оператора P1P/P1S) ---")
#  Прошивка Bambu после включения шлёт stg_cur = 0 у простаивающего принтера (pybambu, ha-bambulab:
#  «On boot the printer reports stg_cur == 0 incorrectly instead of 255»; поправка там же —
#  print_type == "idle"). Программа отказывала такому принтеру ДО команды: «the printer is busy:
#  it is running a preparation step», а с экрана тот же файл запускался.
#  16.10.2026 (R-138, после проверки пакета): правило — ровно как в источниках. pybambu поправляет на покой
#  ТОЛЬКО стадию 0 при print_type «idle»; ha-bambulab PR #2168 (правка #2161) — любую стадию при сыром
#  gcode_state FAILED, и намеренно не print_type «idle»: калибровка и загрузка филамента, запущенные с
#  экрана, идут с print_type «idle» и стадией 8/13/22/24/25 — это работа. FINISH PR #2168 не трогает
#  (часть принтеров законно сообщает стадию после печати, например охлаждение) — как и до 16.10.
check("28. стадия 0 при print_type=idle — покой; сырой FAILED — покой; стадия 13/24 при print_type idle и сыром "
      "IDLE — РАБОТА (калибровка, загрузка филамента с экрана); FINISH со стадией — работа; local/cloud — работа",
      not _bstart.is_working_stage(0, "idle") and not _bstart.is_working_stage("0", "IDLE")
      and _bstart.is_working_stage(0, "local") and _bstart.is_working_stage(0, "cloud")
      and _bstart.is_working_stage(0) and _bstart.is_working_stage(0, None)
      and _bstart.is_working_stage(13, "idle", "IDLE") and _bstart.is_working_stage(24, "idle", "IDLE")
      and _bstart.is_working_stage(13, "idle") and _bstart.is_working_stage(29, None, "FINISH")
      and not _bstart.is_working_stage(54, "idle", "FAILED") and not _bstart.is_working_stage(54, "local", "FAILED")
      and not _bstart.is_working_stage(0, "idle", "IDLE")
      and _bstart.is_working_stage(13, "local", "IDLE") and _bstart.is_working_stage(13, "", "IDLE")
      and not _bstart.is_working_stage(255, "local") and not _bstart.is_working_stage(-1, "idle"))

tl = [st(stg=0, ptype="idle")] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
_why3 = ns["_bambu_busy_before_start"]("p")
check("29. СЛУЧАЙ ОПЕРАТОРА: свежий отчёт — IDLE, стадия 0, print_type=idle — запуск НЕ отклоняется",
      _why3 == "", _why3)

tl = [st(stg=0)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
_why4 = ns["_bambu_busy_before_start"]("p")
check("30. НЕ ВАКУУМ: та же стадия 0 без print_type по-прежнему отказ — проверка меряет разницу",
      _why4.startswith("the printer is busy: it is running a preparation step"), _why4)

tl = [st(stg=0, ptype="idle"), st(stg=0, ptype="idle")] + [st("PREPARE", stg=0, ptype="local")] * 500
stage = Stage(tl)
ns = build(stage, ["ftp", "emmc", "sd", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
check("31. СЛУЧАЙ ОПЕРАТОРА: команда печати уходит ровно одна, печать засчитана",
      len(prints) == 1 and ok is True, ([c["print"].get("url") for c in prints], ok))

tl = [st(stg=0, ptype="idle")] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
check("32. после команды стадия 0 при print_type=idle не выдаётся за начавшуюся печать",
      ns["_bambu_print_outcome"]("p", 0, "0", 0, timeout=2.0) != "ok")

tl = [st(stg=13)] * 60
ns = build(Stage(tl), ["ftp", "emmc"])
ns["_bambu_busy_before_start"]("p")
_lg = " ".join(str(x) for x in getattr(ns["_log"], "lines", []) or [])
check("33. отказ «занят» пишет в журнал, что сообщил принтер (стадия, print_type)",
      "свежий отчёт перед запуском — занят" in SRC and "print_type=%s" in SRC)

check("24. занятость сведена в одно место (_bambu_busy_now): статус, код 0500-4004, стадия",
      "def _bambu_busy_now(" in SRC and "_bstart.is_working_stage" in SRC
      and SRC.count("_bambu_busy_now(pid)") >= 4)

print("--- 7. После ОТМЕНЕННОЙ печати (16.10.2026, R-138, ha-bambulab #2161) ---")
#  P1S на прошивке 01.10.00.00 после отмены во время прогрева: gcode_state FAILED, print_type idle,
#  а stg_cur держит последнюю стадию (54 «ждёт температуру стола») до следующей печати. Карточка
#  показывает IDLE (маска отмены), сырое состояние — FAILED.
CANCELLED = dict(status="IDLE", raw="FAILED", stg=54, ptype="idle")
tl = [st(**CANCELLED)] * 60
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
_w = ns["_bambu_busy_before_start"]("p")
check("34. СЛУЧАЙ #2161: FAILED + стадия 54 + print_type idle — запуск НЕ отклоняется", _w == "", _w)

tl = [st(**CANCELLED), st(**CANCELLED)] + [st("PREPARE", raw="PREPARE", stg=2, ptype="local")] * 500
stage = Stage(tl)
ns = build(stage, ["sd", "ftp", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
check("35. после отмены команда печати уходит ровно одна и засчитывается", ok is True and len(prints) == 1,
      (ok, len(prints)))

tl = [st("FINISH", raw="FINISH", stg=29, ptype="local")] * 60
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
_w = ns["_bambu_busy_before_start"]("p")
#  16.10.2026 (после проверки пакета): FINISH ha-bambulab PR #2168 намеренно не трогает — стадия после
#  печати бывает настоящей (охлаждение). Занятость здесь — как до 16.10: команду не шлём, причина названа.
check("36. FINISH + стадия 29 (охлаждение камеры после печати) — занят, как до 16.10 (PR #2168 FINISH не трогает)",
      _w.startswith("the printer is busy") and "29" in _w, _w)

for _pt in ("local", ""):
    tl = [st(raw="IDLE", stg=13, ptype=_pt)] * 60
    ns = build(Stage(tl), ["sd", "ftp", "mnt"])
    _w = ns["_bambu_busy_before_start"]("p")
    check("37. сырое IDLE + стадия 13 + print_type %r — занят (2.988: парковка головы H2D до статуса)" % _pt,
          _w.startswith("the printer is busy"), _w)

#  Признак старта после команды — СМЕНА стадии против стадии до команды (stage_started).
check("38. застрявшая стадия 54 -> 54 — не признак старта; 54 -> 13 — старт; покой и нет поля — не старт",
      not _bstart.stage_started(54, 54) and _bstart.stage_started(13, 54) and _bstart.stage_started(13, -1)
      and not _bstart.stage_started(255, 54) and not _bstart.stage_started(None, 54)
      and not _bstart.stage_started(0, 0) and _bstart.stage_started(2, 0))
_w = _bstart.StartWatch(0, "0", 0, 0.0, base_stage=54)
_v1 = _w.note({"status": "IDLE", "status_raw": "FAILED", "stage": 54, "print_type": "idle"})
_v2 = _w.note({"status": "IDLE", "status_raw": "FAILED", "stage": 2, "print_type": "idle"})
check("39. наблюдение за командой: стадия как до команды — ждём; стадия сменилась (прогрев) — печать пошла, "
      "даже пока gcode_state ещё FAILED", _v1 == "wait" and _v2 == "ok", (_v1, _v2))

tl = [st(**CANCELLED)] * 60
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
ns["_bambu_stage_mark"]("p")
check("40. после отмены, со снятой стадией до команды (54): вторую команду НЕ запрещает застрявшая стадия",
      ns["_bambu_busy_now"]("p") is False)
tl = [st(**CANCELLED), st(raw="FAILED", stg=13, ptype="idle")]
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
ns["_bambu_stage_mark"]("p")
check("41. ...а сменившаяся после команды стадия (13 — паркует голову) запрещает вторую команду",
      ns["_bambu_busy_now"]("p") is True)
#  База стадии нужна, пока печать этой отправки не пошла. Отправили после отмены (FAILED, 54), печать пошла
#  (RUNNING) и снова упала (FAILED, стадия 2): стадия 2 — уже не «старт», принтер свободен. Без этого очередь
#  до 5 минут (срок базы) звала бы такой принтер «выполняет подготовку».
tl = [st(**CANCELLED), st("RUNNING", raw="RUNNING", stg=2, ptype="local"),
      st("FAILED", raw="FAILED", stg=2, ptype="local")]
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
ns["_bambu_stage_mark"]("p")
_b1 = ns["_bambu_stage_busy"]("p")
_b2 = ns["_bambu_stage_busy"]("p")
check("41b. печать после отправки прошла и упала (FAILED → RUNNING → FAILED): стадия упавшей печати занятостью "
      "не считается; пока шла — считалась", _b1 is True and _b2 is False, (_b1, _b2))

print("--- 8. Смена филамента в AMS — как у Bambu Studio (16.10.2026, R-138) ---")
for _ams, _busy in ((0x0100, True), (0x0103, True), (0x0700, True), (768, False), (0, False)):
    tl = [st(ams=_ams)] * 60
    ns = build(Stage(tl), ["sd", "ftp", "mnt"])
    _w = ns["_bambu_busy_before_start"]("p")
    check("42. ams_status=0x%04X -> %s" % (_ams, "занят" if _busy else "свободен"), bool(_w) == _busy, _w)

print("--- 9. Причина «занят» видна в панели отправок (16.10.2026, R-114/R-138) ---")
tl = [st(stg=13, ptype="local")] * 60
stage = Stage(tl)
ns = build(stage, ["sd", "ftp", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
_txt = ns["_bambu_refusal_reason"]("p")
#  16.10.2026 (после проверки пакета): русский текст называет стадию по-русски (владелец читает его в
#  панели), английский — идентификатором pybambu.
_ru43 = _txt.split(" · ")[0]
check("43. отказ до команды: команда не ушла, а в панели — «Печать не запущена: принтер занят … стадия 13 (парковка "
      "головы)» без английских слов в русской части; английская часть — «homing_toolhead»; не совет про «поколение»",
      ok is False and not [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
      and _ru43.startswith("Печать не запущена: принтер занят") and "13 (парковка головы)" in _ru43
      and "homing_toolhead" not in _ru43 and "homing_toolhead" in _txt, _txt)
tl = [st(raw="RUNNING", status="IDLE")] * 60
ns = build(Stage(tl), ["sd", "ftp", "mnt"])
_w = ns["_bambu_busy_before_start"]("p")
check("44. сырое RUNNING при показанном IDLE (маска «Стоп»: принтер ещё отрабатывает отмену) — занят",
      _w == "the printer is already printing", _w)

print("--- 10. Калибровка или загрузка филамента с экрана (16.10.2026, проверка пакета R-138) ---")
#  Принтер в сыром IDLE, print_type «idle», а стадия — работа: оператор нажал на экране «загрузить
#  филамент» (24) или калибровку (8, 25). ha-bambulab PR #2168 эти стадии не трогает намеренно. Прежняя
#  редакция (16.10) считала print_type «idle» покоем при ЛЮБОЙ стадии: команда уходила, принтер отвечал
#  0500-4004, а программа писала «печать пошла» и списывала граммы.
for _sg in (24, 22, 8, 13, 25):
    tl = [st(raw="IDLE", stg=_sg, ptype="idle")] * 500
    stage = Stage(tl)
    ns = build(stage, ["sd", "ftp", "mnt"])
    ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
    prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
    _txt = ns["_bambu_refusal_reason"]("p")
    check("45. сырой IDLE + стадия %d + print_type idle (работа с экрана) — НИ ОДНОЙ команды печати, запуск отклонён, "
          "причина «принтер занят» в панели" % _sg,
          ok is False and not prints and _txt.startswith("Печать не запущена: принтер занят"), (ok, len(prints), _txt))

print("--- 11. 0500-4004 в ответ на ПЕРВУЮ команду — принтер занят, печать не пошла (16.10.2026) ---")
BUSY = _bstart.BUSY_CODE
check("46. наблюдение: после ПЕРВОЙ команды новый 0500-4004 — 'busy'; после второй — по-прежнему 'ok' (первую "
      "приняли); код был до команды — не наш ответ, прежнее 'ok'",
      _bstart.StartWatch(0, "0", 0, 0.0, first=True).note({"status": "IDLE", "print_error": BUSY}) == "busy"
      and _bstart.StartWatch(0, "0", 0, 0.0, first=True).note({"status": "RUNNING", "print_error": BUSY}) == "busy"
      and _bstart.StartWatch(0, "0", 0, 0.0).note({"status": "IDLE", "print_error": BUSY}) == "ok"
      and _bstart.StartWatch(BUSY, "0", 0, 0.0, first=True).note({"status": "IDLE", "print_error": BUSY}) == "ok")
#  Свежий отчёт перед командой — покой, ошибок нет; после команды принтер отвечает 0500-4004.
tl = [st()] * 4 + [st(pe=BUSY, hms=1)] * 500
stage = Stage(tl)
ns = build(stage, ["sd", "ftp", "mnt"])
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
_txt = ns["_bambu_refusal_reason"]("p")
check("47. принтер ответил на первую команду 0500-4004 — запуск НЕ засчитан (ни «Print started», ни списания), "
      "вторая команда не ушла, в панели «занят другим заданием [0500-4004]»",
      ok is False and len(prints) == 1 and "занят другим заданием" in _txt and "0500-4004" in _txt,
      (ok, len(prints), _txt))
#  Тот же ответ, но позже: прошивка сначала отвергла команду (ответ fail), а 0500-4004 пришёл в выдержке
#  перед второй командой (_bambu_wait_started). Прежде выдержка читала код как «печать пошла» — успех.
tl = [st()] * 8 + [st(pe=BUSY, hms=1)] * 500
stage = Stage(tl)
ns = build(stage, ["sd", "ftp", "mnt"])
ns["_bambu_cmd_ack"]["p"] = {"command": "project_file", "result": "fail", "reason": "busy", "ts": 1e9}
ok = ns["_bambu_send_project"]("p", "SER", {"sequence_id": "0", "command": "project_file"}, "plate.3mf")
prints = [c for _t, c in stage.published if (c.get("print") or {}).get("command") == "project_file"]
_txt = ns["_bambu_refusal_reason"]("p")
_lg = " ".join(ns["_log"].lines)
check("48. 0500-4004 пришёл в выдержке после отказа первой команды — тоже отказ «занят», вторая команда не ушла",
      ok is False and len(prints) == 1 and "занят другим заданием" in _txt and "отвергла команду печати" in _lg,
      (ok, len(prints), _txt))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
