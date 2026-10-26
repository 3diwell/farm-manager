# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Политика прямых команд принтеру (Alpha 2.782).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: обработчик /api/printer/{pid}/cmd
# извлекается из server.py ДОСЛОВНО через AST и исполняется со стабами. Вместо MQTT,
# HTTP к Moonraker и HTTP к FlashForge стоят шпионы: НИ ОДНА команда никуда не уходит.
#
# ЗАКРЫВАЕМАЯ ДЫРА. `val` приходил строкой и подставлялся в G-code как есть:
#     param = f"M104 S{val}\\n"
# Значение "100<LF>M112" превращало один разрешённый запрос в ДВЕ команды, вторая из
# которых — аварийная остановка. Фильтрацией одного символа это не лечится: клиент всё
# равно смог бы прислать опасную команду первой и единственной. Поэтому проверяется
# другое: клиент называет ЛОГИЧЕСКОЕ действие из закрытого списка, значение разбирается
# по типу и диапазону, а строка команды собирается сервером заново.
#
# ГРАНИЦА ЗАДАЧИ. start_print — файловая печать со своим контрактом (очередь, reservation,
# recovery); это не ручная команда, её ветка не трогается. Внутренние многострочные
# G-code блоки печати файлов к этой политике не относятся.
#
# Запуск: python tools/test_printer_command_policy.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

SENTINEL = "GCODE_INJECTION_SENTINEL_2_782"

LF, CR, NUL, VT, FF = chr(0x0A), chr(0x0D), chr(0x00), chr(0x0B), chr(0x0C)
NEL, LS, PS = chr(0x85), chr(0x2028), chr(0x2029)

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


FN = {}
for _n in ast.walk(TREE):
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FN.setdefault(_n.name, _n)


def grab(name):
    fn = FN.get(name)
    if not fn:
        raise AssertionError("функция не найдена: " + name)
    return ast.get_source_segment(SRC, fn)


def src_of(name):
    return ast.unparse(FN[name]) if name in FN else ""


class Spy(object):
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.result

    @property
    def called(self):
        return bool(self.calls)

    def payloads(self):
        return [repr(a) + repr(k) for a, k in self.calls]


class Row(dict):
    """Строка принтера из БД: доступ и по ключу, и как у sqlite3.Row."""

    def __getitem__(self, k):
        return dict.__getitem__(self, k)


class PCmdStub(object):
    """Замена pydantic-модели PCmd: ровно те поля, что объявлены в server.py."""

    def __init__(self, cmd, val="", ams_slot=None, force=False):
        self.cmd = cmd
        self.val = val
        self.ams_slot = ams_slot
        self.force = force


print("=== Alpha 2.782: политика прямых команд принтеру ===")

# ═══ ЧАСТЬ 1. Карта публичных command-путей ═══
print("--- карта командных путей ---")


def route_of(name):
    fn = FN.get(name)
    if not fn:
        return (None, None)
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args:
            if isinstance(d.args[0], ast.Constant):
                return (d.func.attr, d.args[0].value)
    return (None, None)


check("M1. /api/printer/{pid}/cmd — POST, обработчик p_cmd",
      route_of("p_cmd") == ("post", "/api/printer/{pid}/cmd"))

# Единственный публичный маршрут прямой команды: новый такой же без политики уронит тест.
_cmd_routes = set()
for _n, _fn in FN.items():
    _m, _p = route_of(_n)
    if _p and _m in ("post", "put") and ("/cmd" in _p or "gcode" in _p or "script" in _p or "macro" in _p):
        _cmd_routes.add(_p)
check("M2. публичный командный маршрут ровно один: %s" % (", ".join(sorted(_cmd_routes)) or "—"),
      _cmd_routes == {"/api/printer/{pid}/cmd"})

# Raw-консоли нет: cmd сверяется с фиксированными строками, а не пропускается как G-code.
_p = src_of("p_cmd")
check("M3. raw G-code console отсутствует (нет прямой отправки cmd как команды)",
      "gcode_line', 'param': data.cmd" not in _p and "script={urllib.parse.quote(data.cmd" not in _p)
check("M4. allowlist не подменён регуляркой вида [GMT]\\d+",
      "[GMT]" not in _p and "re.match" not in _p)

# ═══ ЧАСТЬ 2. Чистый модуль политики ═══
print("--- чистый модуль политики ---")

try:
    from app import printer_command_policy as pol
    _has = True
except Exception as _e:
    pol, _has = None, False
    print("  (app/printer_command_policy.py недоступен: %s)" % _e)
check("P0. app/printer_command_policy.py импортируется", _has)

if _has:
    _POL = open(os.path.join(REPO, "app", "printer_command_policy.py"), encoding="utf-8").read()
    check("P1. модуль не тянет server.py / фреймворк / БД / сеть",
          all(x not in _POL for x in ("import server", "FastAPI", "sqlite3", "urllib", "socket", "paho")))
    check("P2. модуль ничего не журналирует", "log." not in _POL and "print(" not in _POL)

    UI_ACTIONS = ("pause", "resume", "stop", "nozzle", "nozzle_l", "nozzle_r", "bed", "chamber")
    # 1. Каждое штатное действие UI принимается. Значение — в пределах своего действия
    #    (у стола и камеры пределы ниже, чем у сопла).
    _VAL = {"bed": "60", "chamber": "50"}
    for a in UI_ACTIONS:
        t = "bambu"
        ok, norm, _r = pol.parse_command(a, _VAL.get(a, "210"), t)
        check("A. штатное действие %-9s принимается" % a, ok)
    #  R-104 (2.983): термокамера — только у типов с подтверждённым контрактом.
    check("C. камера: bambu принимается", pol.parse_command("chamber", "60", "bambu")[0])
    check("C. камера: klipper принимается", pol.parse_command("chamber", "60", "klipper")[0])
    check("C. камера: виртуальный принтер принимается", pol.parse_command("chamber", "60", "demo")[0])
    check("C. камера: flashforge отклонён как unsupported",
          (not pol.parse_command("chamber", "60", "flashforge")[0])
          and pol.parse_command("chamber", "60", "flashforge")[2] == pol.R_UNSUPPORTED)
    check("C. камера: выше 65° отклонено", not pol.parse_command("chamber", "66", "bambu")[0])
    check("C. камера: граница 65° проходит", pol.parse_command("chamber", "65", "bambu")[0])
    check("C. камера: ноль (выключить) проходит", pol.parse_command("chamber", "0", "klipper")[0])
    _okc, _lc, _ = pol.gcode_lines({"action": "chamber", "temp_c": 50})
    check("C. камера: каноническая строка M141 S50", _okc and _lc == ["M141 S50"])
    # 2-5. Неизвестное/пустое/не-строка.
    for bad_a, label in ((SENTINEL, "sentinel-строка"), ("M112", "сырой G-code"),
                         ("", "пустое"), (None, "None"), (123, "число"),
                         ("NOZZLE", "другой регистр"), (" nozzle", "с пробелом"),
                         ("nozzle_", "префикс"), ("nozzlex", "похожее имя")):
        ok, _n, r = pol.parse_command(bad_a, "210", "bambu")
        check("A. отклонено action: %-16s" % label, (not ok) and r == pol.R_UNKNOWN_ACTION)

    # 7-9. Числовой контракт.
    for bad_v, label in ((True, "bool True"), (False, "bool False"), ("nan", "NaN"),
                         ("inf", "Infinity"), ("2.1e2", "экспонента"), ("21,5", "запятая"),
                         ("210 C", "единицы измерения"), ("2 1 0", "лишние токены"),
                         ("0x21", "hex"), ("", "пустое"), (None, "None"), ("+210", "плюс"),
                         ("210.0", "дробное")):
        ok, _n, r = pol.parse_command("nozzle", bad_v, "bambu")
        check("V. отклонено значение: %-18s" % label, (not ok) and r == pol.R_BAD_VALUE)

    # 10-12. Диапазоны и границы.
    check("V. ниже минимума отклонено", not pol.parse_command("nozzle", "-1", "bambu")[0])
    check("V. выше максимума отклонено", not pol.parse_command("nozzle", "351", "bambu")[0])
    check("V. граница min проходит", pol.parse_command("nozzle", "0", "bambu")[0])
    check("V. граница max проходит", pol.parse_command("nozzle", "350", "bambu")[0])
    check("V. стол: выше максимума отклонён", not pol.parse_command("bed", "121", "bambu")[0])
    check("V. стол: граница max проходит", pol.parse_command("bed", "120", "bambu")[0])
    check("V. выход за диапазон НЕ подрезается молча",
          pol.parse_command("nozzle", "999", "bambu")[2] == pol.R_OUT_OF_RANGE)

    # 15-23. Инъекции разделителей.
    for ch, label in ((LF, "\\n"), (CR, "\\r"), (CR + LF, "\\r\\n"), (NUL, "\\x00"),
                      (VT, "\\x0b"), (FF, "\\x0c"), (NEL, "U+0085"), (LS, "U+2028"), (PS, "U+2029")):
        ok, _n, r = pol.parse_command("nozzle", "100" + ch + "M112", "bambu")
        check("I. инъекция через %-8s отклонена" % label, (not ok) and r == pol.R_BAD_VALUE)
        check("I. готовая строка с %-8s небезопасна" % label,
              not pol.is_safe_command_line("M104 S100" + ch + "M112"))

    # 24-26. Комментарии и довески.
    for bad_v, label in (("100;M112", "комментарий ;"), ("100 ;M112", "комментарий с пробелом"),
                         ("100(M112)", "скобочный комментарий"), ("100 M112", "вторая команда"),
                         ("100 T1", "лишний параметр"), (SENTINEL, "sentinel")):
        check("I. отклонено: %-24s" % label, not pol.parse_command("nozzle", bad_v, "bambu")[0])

    # 27-29. Длина и кодирование.
    check("I. очень длинное значение отклонено", not pol.parse_command("nozzle", "1" * 5000, "bambu")[0])
    check("I. %0A после декодирования отклонено",
          not pol.parse_command("nozzle", "100" + LF, "bambu")[0])
    check("I. вложенная JSON-строка не интерпретируется",
          not pol.parse_command("nozzle", '{"cmd":"M112"}', "bambu")[0])

    # 13-14. Итоговая команда и неизменность входа.
    _src_val = "210"
    _ok, _norm, _ = pol.parse_command("nozzle", _src_val, "bambu")
    check("F. исходное значение не мутировано", _src_val == "210")
    _ok2, _lines, _ = pol.gcode_lines(_norm, 1)
    check("F. formatter отдаёт ровно одну строку", _ok2 and len(_lines) == 1)
    check("F. строка канонична и безопасна",
          _lines == ["M104 S210"] and pol.is_safe_command_line(_lines[0]))
    check("F. длина команды ограничена", pol.MAX_COMMAND_LEN <= 256)
    _ok3, _lines2, _ = pol.gcode_lines(_norm, 2)
    check("F. двухсопельная модель: две строки определяются ЖЕЛЕЗОМ, а не запросом",
          _ok3 and _lines2 == ["M104 S210 T0", "M104 S210 T1"])
    check("F. formatter не принимает словарь запроса",
          not pol.gcode_lines({"cmd": "nozzle", "val": "210" + LF + "M112"}, 1)[0])
    check("F. pause/resume/stop не превращаются в G-code",
          not pol.gcode_lines({"action": "pause", "temp_c": None}, 1)[0])

    # Поддержка по типам принтеров.
    check("T. nozzle_l только для bambu", pol.parse_command("nozzle_l", "210", "bambu")[0]
          and pol.parse_command("nozzle_l", "210", "klipper")[2] == pol.R_UNSUPPORTED
          and pol.parse_command("nozzle_l", "210", "flashforge")[2] == pol.R_UNSUPPORTED)
    check("T. неизвестный тип принтера -> unsupported",
          pol.parse_command("nozzle", "210", "unknown_type")[2] == pol.R_UNSUPPORTED)
    check("T. sentinel не встречается в модуле политики", SENTINEL not in _POL)

# ═══ ЧАСТЬ 3. Исполнение production-обработчика со шпионами ═══
print("--- production-путь /api/printer/{pid}/cmd ---")


def run_cmd(ptype, cmd, val, nozzle_count=1):
    """Исполнить настоящий p_cmd со стабами. Возвращает (result, шпионы)."""
    mqtt_spy, ff_spy, ws_spy, url_spy = Spy(), Spy(result=(True, "")), Spy(result=True), Spy()
    row = Row(id="p1", name="P", type=ptype, ip="10.0.0.9", port=None, token="t:c")

    class _Cur(object):
        def execute(self, *a, **k):
            return self

        def fetchone(self):
            return row

    class _UrlReq(object):
        Request = staticmethod(lambda *a, **k: ("REQ", a, k))
        urlopen = staticmethod(url_spy)

    ns = {
        "os": os, "json": __import__("json"), "time": __import__("time"),
        "lock_pr": threading.Lock(), "conn_pr": _Cur(),
        "mqtt_cls": {"p1": object()}, "bambu_serials": {"p1": "SER"},
        "p_states": {"p1": {"nozzle_count": nozzle_count}},
        "_bambu_publish": mqtt_spy,
        "_flashforge_control": ff_spy, "_flashforge_print": Spy(),
        "_creality_ws_send": ws_spy,
        "urllib": type("U", (), {"request": _UrlReq, "parse": __import__("urllib.parse", fromlist=["x"])})(),
        "server_print": {}, "_server_print_ts": {}, "_user_stopped": {},
        "print_source": {}, "_send_mgr": None, "_hold_block": (lambda p: None),
        "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                              "info": staticmethod(lambda *a, **k: None),
                              "warning": staticmethod(lambda *a, **k: None),
                              "error": staticmethod(lambda *a, **k: None)})(),
        "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code}),
        # 16.10.2026 (R-145): журнал аудита команд — здесь без запроса (req=None), ответ как есть.
        "_printer_cmd_audit": (lambda req, p, act, val, res: res),
    }
    if _has:
        ns["_printer_cmd_policy"] = pol
    exec(grab("p_cmd"), ns)
    # Исключение — тоже наблюдаемое поведение: до 2.782 FlashForge падал на int(data.val),
    # то есть отвечал 500 вместо отказа. Тест обязан это показать, а не умереть сам.
    try:
        res = ns["p_cmd"]("p1", PCmdStub(cmd, val))
    except Exception as e:
        res = {"_raised": type(e).__name__}
    return res, {"mqtt": mqtt_spy, "ff": ff_spy, "ws": ws_spy, "url": url_spy}


INJECT = "100" + LF + "M112"

# 31. Вредоносный запрос -> адаптер не вызван, sentinel никуда не ушёл.
for ptype in ("bambu", "klipper", "flashforge"):
    res, sp = run_cmd(ptype, "nozzle", INJECT)
    any_called = sp["mqtt"].called or sp["url"].called or sp["ff"].called
    check("R31. %-10s: инъекция -> адаптер НЕ вызван" % ptype, not any_called)
    blob = " ".join(sp["mqtt"].payloads() + sp["url"].payloads() + sp["ff"].payloads())
    check("R31b. %-10s: перевод строки не достиг транспорта" % ptype, LF not in blob or not blob)

for ptype in ("bambu", "klipper", "flashforge"):
    res, sp = run_cmd(ptype, "nozzle", SENTINEL)
    blob = " ".join(sp["mqtt"].payloads() + sp["url"].payloads() + sp["ff"].payloads())
    check("SENT. %-10s: sentinel не достиг адаптера" % ptype, SENTINEL not in blob)
    check("SENT. %-10s: sentinel не отражён в ответе" % ptype, SENTINEL not in repr(res))

# 32-34. Валидный запрос -> адаптер вызван один раз, каноничной командой.
res, sp = run_cmd("bambu", "nozzle", "210")
check("R32. bambu, валидный запрос -> ровно один вызов транспорта", len(sp["mqtt"].calls) == 1)
_blob = " ".join(sp["mqtt"].payloads())
check("R33. в транспорт ушла КАНОНИЧНАЯ команда M104 S210", "M104 S210" in _blob)
check("R34. один запрос — одна команда (нет второй M-команды)", _blob.count("M104") == 1)

res, sp = run_cmd("bambu", "bed", "60")
check("R32b. bambu, стол -> один вызов с M140 S60",
      len(sp["mqtt"].calls) == 1 and "M140 S60" in " ".join(sp["mqtt"].payloads()))

res, sp = run_cmd("klipper", "nozzle", "210")
check("R32c. klipper, валидный запрос -> транспорт вызван", sp["url"].called)

res, sp = run_cmd("flashforge", "nozzle", "210")
check("R32d. flashforge, валидный запрос -> транспорт вызван", sp["ff"].called)

# 36. Неподдерживаемое действие для типа принтера.
for ptype in ("klipper", "flashforge"):
    res, sp = run_cmd(ptype, "nozzle_l", "210")
    check("R36. %-10s: nozzle_l не поддержан -> адаптер не вызван" % ptype,
          not (sp["mqtt"].called or sp["url"].called or sp["ff"].called))

# 2. Неизвестное действие не достигает адаптера.
for ptype in ("bambu", "klipper", "flashforge"):
    res, sp = run_cmd(ptype, "M112", "")
    check("R7. %-10s: неизвестное действие -> адаптер не вызван" % ptype,
          not (sp["mqtt"].called or sp["url"].called or sp["ff"].called))

# 10-11. Диапазон на production-пути.
res, sp = run_cmd("bambu", "nozzle", "999")
check("R10. значение вне диапазона -> транспорт не вызван", not sp["mqtt"].called)

# Штатные действия без параметра по-прежнему работают.
res, sp = run_cmd("bambu", "pause", "")
check("R. bambu pause -> команда протокола отправлена", sp["mqtt"].called)
res, sp = run_cmd("flashforge", "pause", "")
check("R. flashforge pause -> команда протокола отправлена", sp["ff"].called)

# ═══ ЧАСТЬ 3b. 16.10.2026 (R-145): двухсопельный Bambu (H2D) и подтверждение доставки ═══
print("--- H2D: левое и правое сопло, QoS 1 ---")
if hasattr(pol, "bambu_nozzle_commands"):
    _ok, _cmds, _ = pol.bambu_nozzle_commands({"action": "nozzle_l", "temp_c": 210}, 2)
    check("N1. «Сопло L» двухсопельного Bambu — set_nozzle_temp с extruder_index 1 (левое у прошивки)",
          _ok and _cmds == [{"print": {"sequence_id": "0", "command": "set_nozzle_temp",
                                       "extruder_index": 1, "target_temp": 210}}])
    _ok, _cmds, _ = pol.bambu_nozzle_commands({"action": "nozzle_r", "temp_c": 0}, 2)
    check("N2. «Сопло R» — extruder_index 0 (основное, правое), ноль = выключить",
          _ok and [c["print"]["extruder_index"] for c in _cmds] == [0] and _cmds[0]["print"]["target_temp"] == 0)
    _ok, _cmds, _ = pol.bambu_nozzle_commands({"action": "nozzle", "temp_c": 200}, 2)
    check("N3. «Сопло» на двух соплах — обе команды, правое и левое",
          _ok and sorted(c["print"]["extruder_index"] for c in _cmds) == [0, 1])
    check("N4. одно сопло — команд протокола нет (идёт G-code, как раньше)",
          pol.bambu_nozzle_commands({"action": "nozzle", "temp_c": 200}, 1)[0] is False
          and pol.bambu_nozzle_commands({"action": "bed", "temp_c": 60}, 2)[0] is False)
    check("N5. только нормализованные данные: строка, логическое и выход за предел — отказ",
          not pol.bambu_nozzle_commands({"action": "nozzle_l", "temp_c": "210"}, 2)[0]
          and not pol.bambu_nozzle_commands({"action": "nozzle_l", "temp_c": True}, 2)[0]
          and not pol.bambu_nozzle_commands({"action": "nozzle_l", "temp_c": 999}, 2)[0]
          and not pol.bambu_nozzle_commands({"action": "nozzle_l", "temp_c": 210}, True)[0])
else:
    check("N0. в политике команд есть bambu_nozzle_commands", False)

res, sp = run_cmd("bambu", "nozzle_l", "215", nozzle_count=2)
_c = sp["mqtt"].calls
check("N6. настоящий p_cmd: «Сопло L» H2D ушло ОДНОЙ командой set_nozzle_temp, extruder_index 1, QoS 1",
      len(_c) == 1 and '"set_nozzle_temp"' in _c[0][0][2] and '"extruder_index": 1' in _c[0][0][2]
      and '"target_temp": 215' in _c[0][0][2] and _c[0][1].get("qos") == 1 and "M104" not in _c[0][0][2])
res, sp = run_cmd("bambu", "nozzle_r", "215", nozzle_count=2)
_c = sp["mqtt"].calls
check("N7. настоящий p_cmd: «Сопло R» H2D — extruder_index 0",
      len(_c) == 1 and '"extruder_index": 0' in _c[0][0][2])
res, sp = run_cmd("bambu", "nozzle", "200", nozzle_count=2)
_c = sp["mqtt"].calls
check("N8. настоящий p_cmd: «Сопло» на H2D — две команды, правое и левое, обе QoS 1",
      len(_c) == 2 and sorted(('"extruder_index": 0' in c[0][2], '"extruder_index": 1' in c[0][2]) for c in _c)
      == [(False, True), (True, False)] and all(c[1].get("qos") == 1 for c in _c))
res, sp = run_cmd("bambu", "nozzle", "200", nozzle_count=1)
_c = sp["mqtt"].calls
check("N9. одно сопло — по-прежнему G-code M104, QoS 0", len(_c) == 1 and "M104 S200" in _c[0][0][2]
      and _c[0][1].get("qos", 0) == 0)
for _a in ("pause", "resume", "stop"):
    res, sp = run_cmd("bambu", _a, "")
    _c = sp["mqtt"].calls
    check("N10. %s Bambu — QoS 1, как у Bambu Studio (подтверждение приёма = доставка)" % _a,
          len(_c) == 1 and _c[0][1].get("qos") == 1)


def _run_publish(qos, published):
    """Настоящий _bambu_publish с подставным MQTT-клиентом: принтер подтвердил приём или нет."""
    class _Info(object):
        rc = 0

        def wait_for_publish(self, timeout=None):
            return None

        def is_published(self):
            return published

    class _Cli(object):
        def __init__(self):
            self.pub = []

        def is_connected(self):
            return True

        def publish(self, topic, payload, qos=0):
            self.pub.append(qos)
            return _Info()

    cli = _Cli()
    ns = {"mqtt_cls": {"p1": cli}, "time": __import__("time"), "_exc_brief": lambda: "e",
          "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                                "warning": staticmethod(lambda *a, **k: None)})()}
    exec(grab("_bambu_publish"), ns)
    return ns["_bambu_publish"]("p1", "t", "{}", attempts=2, delay=0.01, qos=qos), cli.pub


_r, _pub = _run_publish(1, False)
check("N11. QoS 1 без подтверждения от принтера — False, и повторной отправки нет (не задвоить команду)",
      _r is False and _pub == [1])
_r, _pub = _run_publish(1, True)
check("N12. QoS 1 с подтверждением — True", _r is True and _pub == [1])
_r, _pub = _run_publish(0, False)
check("N13. прочие вызовы (QoS 0) — как раньше: принято клиентом = True", _r is True and _pub == [0])

# ═══ ЧАСТЬ 4. Порядок и статические инварианты ═══
print("--- порядок проверок и инварианты ---")

_p = src_of("p_cmd")
check("O1. валидация выполняется ДО обращения к транспорту",
      "_printer_cmd_policy" in _p
      and _p.index("_printer_cmd_policy") < min(
          [_p.index(x) for x in ("_bambu_publish", "_flashforge_control", "urllib.request.urlopen") if x in _p] or [10**9]))
check("O2. значение val больше не подставляется в G-code напрямую",
      "S{data.val}" not in _p and "{data.val}" not in _p.replace("quote(data.val)", ""))
check("O3. formatter получает нормализованные данные, а не data",
      "gcode_lines(data" not in _p)
check("O4. пользовательское значение не журналируется",
      "data.val" not in "\n".join(l for l in _p.splitlines() if "log." in l))
check("O5. start_print (файловая печать) остался отдельной веткой",
      "start_print" in _p)
check("O6. sentinel отсутствует в server.py", SENTINEL not in SRC)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
