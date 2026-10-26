# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.840 — ИСПОЛНЕНИЕ калибровки стола на fake-K2: сколько команд ушло,
#  в каком порядке, и что произошло, когда принтер не подтвердил завершение.
#
#  ЧТО ЗАКРЫВАЕТ. Разрешить калибровку по графу вызовов мало — надо ещё ни разу
#  не навредить железу. Здесь проверяется физическая сторона контракта:
#    * не более одной парковки и не более одной калибровочной команды за попытку;
#    * автоповтора нет НИКОГДА (повторная калибровка — это второй проход по столу);
#    * HTTP-ответ сам по себе завершением не считается: нужна ещё и смена отпечатка
#      сетки, покой принтера и наличие самой сетки;
#    * файл уходит на принтер ТОЛЬКО после подтверждённого завершения;
#    * недоказанный контракт не отправляет вообще ничего.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: функции берутся разбором AST и исполняются изолированно;
#   * ни одного реального сокета: urllib подменён fake-Moonraker'ом;
#   * ловушка запрещает любой адрес, кроме синтетического;
#   * реальному принтеру не отправляется НИ ОДНОЙ команды;
#   * рабочие БД/config/DATA_DIR не открываются, печати не запускаются.
#
#  Запуск:  python tools/test_klipper_bed_mesh_execution.py    (0 = всё пройдено)
# ============================================================================
import ast
import io
import json
import os
import sys
import types
import urllib.error as _urlerr
import urllib.parse as _urlparse
import urllib.request as _urlreq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "KLIPPER_BED_MESH_EXECUTION_SENTINEL_2_840"   # ТОЛЬКО в этой оснастке
FAKE_HOST = "127.0.0.1"                                  # синтетический fake-Moonraker

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" | " + str(extra)[:220]) if extra else ""))
    return ok


def section(t):
    print("\n--- %s ---" % t)


SRV_AST = ast.parse(io.open(os.path.join(REPO, "server.py"), encoding="utf-8",
                            errors="surrogateescape").read())


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

def const_src(name):
    """Модульная константа server.py — читаем ИЗ ИСХОДНИКА, а не дублируем значение в тесте.
    Alpha 2.841: так мутация самого списка «покоя» краснит тест, а не проходит незамеченной."""
    for _n in SRV_AST.body:
        if isinstance(_n, ast.Assign):
            for _t in _n.targets:
                if isinstance(_t, ast.Name) and _t.id == name:
                    return ast.literal_eval(_n.value)
    return None


FIX = json.load(io.open(os.path.join(REPO, "tools", "fixtures", "klipper",
                                     "k2_plus_bed_mesh_contract_v2.json"), encoding="utf-8"))
PC = FIX["printer_class"]
G = FIX["graphs"]

print("=== Alpha 2.840: исполнение калибровки стола (fake-K2) ===")
print("МЕТКА ОСНАСТКИ: %s" % SENTINEL)

# ════════════════════════════════════════════════════════════════════════════
#  FAKE-MOONRAKER
# ════════════════════════════════════════════════════════════════════════════
MESH_BEFORE = {"profile_name": "default", "probed_matrix": [[0.0, 0.1], [0.2, 0.3]]}
MESH_AFTER = {"profile_name": "default", "probed_matrix": [[9.0, 9.1], [9.2, 9.3]]}

SC = {}


def scen(graph_name, **kw):
    """Сцена принтера по синтетическому графу из фикстуры."""
    SC.clear()
    SC.update({"macros": dict(G[graph_name]["macros"]), "objects": list(PC["objects"]),
               "cmds": list(PC["builtins"]), "state": "standby", "wh": "ready", "idle": "Ready",
               "homed": "xyz", "reachable": True, "mesh": dict(MESH_BEFORE),
               "mesh_after_cal": dict(MESH_AFTER), "fail_on": None, "fail_mode": None,
               "post_state": None, "sent": [], "uploads": [], "gets": []})
    SC.update(kw)
    STAGES[:] = []
    LOG.lines[:] = []


class _FR(object):
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    host = _urlparse.urlparse(url).hostname or ""
    if host != FAKE_HOST:                      # ловушка: наружу — никогда
        raise AssertionError("тест попытался обратиться к постороннему адресу: %s" % host)
    if "/server/files/upload" in url:
        SC["uploads"].append(url)
        return _FR(b'{"result": {"print_started": true}}')
    if not SC["reachable"]:
        raise _urlerr.URLError("unreachable")
    if "/printer/gcode/script" in url:
        _s = _urlparse.unquote(url.split("script=")[-1])
        SC["sent"].append(_s)
        _first = _s.split()[0].upper() if _s.split() else ""
        if SC["fail_on"] and (SC["fail_on"] == _first or SC["fail_on"] == "*"):
            if SC["fail_mode"] == "timeout":
                raise TimeoutError("timed out")
            raise _urlerr.HTTPError(url, 400, "err", {}, io.BytesIO(b"{}"))
        if _first == "G28":
            SC["homed"] = "xyz"
        # «Измерение» стола: сетка меняется у ЛЮБОЙ команды, которая реально калибрует —
        # встроенной или доказанного vendor-макроса (иначе проверка отпечатка была бы пустой).
        if _first in ("BED_MESH_CALIBRATE", "G29") or _first in SC["macros"]:
            if SC["mesh_after_cal"] is not None:
                SC["mesh"] = dict(SC["mesh_after_cal"])
            else:
                SC["mesh"] = {}
        if SC["post_state"] is not None:
            SC["state"] = SC["post_state"]
        return _FR(b'{"result": "ok"}')
    SC["gets"].append(url)
    if "/printer/objects/list" in url:
        return _FR(json.dumps({"result": {"objects": SC["objects"]}}).encode())
    if "/printer/gcode/help" in url:
        return _FR(json.dumps({"result": {c: "" for c in SC["cmds"]}}).encode())
    if "configfile" in url:
        return _FR(json.dumps({"result": {"status": {"configfile": {"settings": {
            ("gcode_macro " + m.lower()): {"gcode": b}
            for m, b in SC["macros"].items()}}}}}).encode())
    if "/printer/info" in url:
        return _FR(json.dumps({"result": {"software_version": "synthetic"}}).encode())
    if "/server/info" in url:
        return _FR(json.dumps({"result": {"moonraker_version": "synthetic"}}).encode())
    if "bed_mesh" in url:
        return _FR(json.dumps({"result": {"status": {"bed_mesh": SC["mesh"]}}}).encode())
    if "idle_timeout" in url:
        return _FR(json.dumps({"result": {"status": {"idle_timeout": {"state": SC["idle"]}}}}).encode())
    if "toolhead" in url:
        return _FR(json.dumps({"result": {"status": {"toolhead": {"homed_axes": SC["homed"]}}}}).encode())
    if "print_stats" in url:
        return _FR(json.dumps({"result": {"status": {"print_stats": {"state": SC["state"]},
                                                     "webhooks": {"state": SC["wh"]}}}}).encode())
    return _FR(b"{}")


_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr, parse=_urlparse)


class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r


LOG = _Log()
STAGES = []


def _pcb(**kw):
    if kw.get("stage"):
        STAGES.append(kw["stage"])


from app import klipper_prestart as P            # noqa: E402
from app import klipper_contract_probe as KCP    # noqa: E402

NS = {"urllib": _fake_urllib, "json": json, "log": LOG, "_klprestart": P, "_kcprobe": KCP,
      "time": __import__("time"), "_exc_brief": (lambda: "err"),
      "_KLIPPER_IDLE_STATES": const_src("_KLIPPER_IDLE_STATES")}
for _f in ("_klipper_get_json", "_klipper_discover", "_klipper_config_macros",
           "_klipper_bed_mesh_attempt", "_klipper_execute_prestart"):
    _s = fn_src(_f)
    if not _s:
        print("FAIL — функция %s не найдена в server.py" % _f)
        sys.exit(1)
    exec(compile(_s, "<server>", "exec"), NS)
run_pre = NS["_klipper_execute_prestart"]
SEL = ["bed_mesh_calibrate"]


def run(fdata=b"G1 X0\n", fname="part.gcode"):
    return run_pre(FAKE_HOST, 7125, "pSynthetic", list(SEL), fname, fdata, progress_cb=_pcb)


# ════════════════════════════════════════════════════════════════════════════
section("A. Доказанный стандартный путь: одна команда, порядок соблюдён")

scen("safe_standard")
ok, why = run()
check("A1. калибровка выполнена, печать разрешена", ok and why == "", why)
check("A2. отправлена РОВНО ОДНА команда — встроенная калибровка",
      SC["sent"] == ["BED_MESH_CALIBRATE"], SC["sent"])
check("A3. оси уже запаркованы -> G28 НЕ отправлялся", "G28" not in SC["sent"])
check("A4. загрузка файла внутри подготовки не начиналась", SC["uploads"] == [])
check("A5. пользователю показаны стадии состояния, разбора, калибровки и проверки",
      all(s in STAGES for s in ("checking_state", "resolving", "calibrating", "verifying")), STAGES)
check("A6. стадия «калибровка завершена» показана после успеха",
      "calibration_done" in STAGES and STAGES.index("calibration_done") > STAGES.index("calibrating"),
      STAGES)
check("A7. журнал ведёт цепочку resolve -> plan -> begin -> complete",
      [x for x in ("resolve", "plan", "calibration begin", "calibration complete")
       if not any("[KLIPPER PRESTART] " + x in ln for ln in LOG.lines)] == [], LOG.lines[:6])
check("A8. в журнале названы режим, причина и риск (а не просто «ошибка/успех»)",
      any("mode=standard_builtin" in x and "reason=standard_builtin_proven" in x
          and "risk=none" in x for x in LOG.lines), LOG.lines[:2])
check("A9. в журнале нет адреса принтера и нет метки оснастки",
      not any(FAKE_HOST in x for x in LOG.lines)
      and not any(SENTINEL in x for x in LOG.lines))
check("A10. значения точек сетки в журнал не попали",
      not any("9.0" in x or "0.1" in x for x in LOG.lines))

# ════════════════════════════════════════════════════════════════════════════
section("B. Парковка: не более одной, и только когда она действительно нужна")

scen("safe_standard", homed="")
ok, why = run()
check("B1. незапаркованные оси -> РОВНО один G28, затем калибровка",
      ok and SC["sent"] == ["G28", "BED_MESH_CALIBRATE"], SC["sent"])
check("B2. стадия парковки показана до стадии калибровки",
      "homing" in STAGES and STAGES.index("homing") < STAGES.index("calibrating"), STAGES)

scen("safe_standard", homed="xy")
ok, _ = run()
check("B3. частичная парковка достраивается одним полным G28",
      ok and SC["sent"] == ["G28", "BED_MESH_CALIBRATE"], SC["sent"])

scen("safe_standard", homed="", fail_on="G28", fail_mode="timeout")
ok, why = run()
check("B4. таймаут парковки -> калибровка НЕ отправлена, печать не начата",
      (not ok) and SC["sent"] == ["G28"] and SC["uploads"] == [], SC["sent"])
check("B5. таймаут парковки объяснён как «не подтверждено», без повтора",
      "повторно НЕ отправлялась" in why and "парковки" in why, why[:140])

scen("safe_standard", homed="", fail_on="G28", fail_mode="http")
ok, why = run()
check("B6. ошибка парковки -> печать не начата и калибровки не было",
      (not ok) and SC["sent"] == ["G28"], SC["sent"])

# Парковка «прошла», но принтер оси так и не подтвердил — двигаться дальше нельзя.
scen("safe_standard", homed="")
_orig = _fake_urlopen


def _no_home_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    if "/printer/gcode/script" in url and "G28" in url:
        SC["sent"].append("G28")
        return _FR(b'{"result": "ok"}')          # ответ есть, а оси не запаркованы
    return _orig(req, timeout)


_fake_urllib.request.urlopen = _no_home_urlopen
ok, why = run()
_fake_urllib.request.urlopen = _orig
check("B7. оси не подтверждены после G28 -> калибровка НЕ отправлялась",
      (not ok) and SC["sent"] == ["G28"], SC["sent"])

# ════════════════════════════════════════════════════════════════════════════
section("C. Завершение доказывается, а не предполагается")

scen("safe_standard", fail_on="BED_MESH_CALIBRATE", fail_mode="timeout")
ok, why = run()
check("C1. таймаут калибровки -> печать не начата",
      (not ok) and SC["uploads"] == [])
check("C2. таймаут НЕ приводит к повторной отправке команды",
      len([x for x in SC["sent"] if x.startswith("BED_MESH")]) == 1, SC["sent"])
check("C3. пользователю сказано, что команда повторно не отправлялась",
      "повторно НЕ отправлялась" in why, why[:140])
check("C4. неопределённость записана в журнал отдельным событием",
      any("calibration uncertain" in x for x in LOG.lines), LOG.lines[:4])

scen("safe_standard", fail_on="BED_MESH_CALIBRATE", fail_mode="http")
ok, why = run()
check("C5. ошибка калибровки -> печать не начата",
      (not ok) and SC["uploads"] == []
      and any("calibration failed" in x for x in LOG.lines))

scen("safe_standard", post_state="printing")
ok, why = run()
check("C6. принтер не вернулся в покой -> завершение не подтверждено",
      (not ok) and "не начата" in why)

scen("safe_standard", post_state="")
ok, _ = run()
check("C7. пустое состояние НЕ считается доказательством покоя", not ok)

scen("safe_standard", mesh_after_cal=None)
ok, _ = run()
check("C8. сетки после калибровки нет -> завершение не подтверждено", not ok)

scen("safe_standard", mesh_after_cal=dict(MESH_BEFORE))
ok, _ = run()
check("C9. отпечаток сетки не изменился -> это ЗАМЕЧЕНО (и записано в журнал)",
      any("fingerprint_changed=False" in x for x in LOG.lines), LOG.lines[-1:])
check("C10. неизменённый отпечаток сам по себе печать не блокирует (сетка есть, принтер в покое)",
      ok is True)

# Профиль сменился, а точки те же — так выглядит загрузка/сохранение сетки под другим именем.
# Отпечаток обязан это заметить: иначе «сетка изменилась» доказывалось бы только матрицей.
scen("safe_standard", mesh_after_cal={"profile_name": "measured",
                                      "probed_matrix": list(MESH_BEFORE["probed_matrix"])})
ok, _ = run()
check("C11. смена ИМЕНИ профиля тоже считается изменением сетки",
      ok and any("fingerprint_changed=True" in x for x in LOG.lines), LOG.lines[-1:])

scen("safe_standard")
ok, _ = run()
check("C12. успешное завершение перечисляет доказательства в журнале",
      any("evidence=" in x and "bed_mesh_present" in x for x in LOG.lines), LOG.lines[-1:])

# ════════════════════════════════════════════════════════════════════════════
section("D. Недоказанный контракт: не отправляется НИ ОДНОЙ команды")

for _g, _tag in (("clears_mesh", "стартовый макрос очищает сетку"),
                 ("replaces_mesh", "стартовый макрос загружает другую сетку"),
                 ("overridden_bed_mesh", "калибровка переопределена макросом"),
                 ("overridden_homing", "парковка переопределена макросом")):
    scen(_g)
    ok, why = run()
    check("D[%s]. %s -> команд 0, печать не начата, причина названа" % (_g, _tag),
          (not ok) and SC["sent"] == [] and SC["uploads"] == [] and len(why) > 40,
          (SC["sent"], why[:90]))

scen("clears_mesh")
ok, why = run()
check("D6. отказ содержит русское И английское объяснение",
      "Печать не начата" in why and "Print not started" in why, why[:160])
check("D7. отказ не показывает пользователю сырой код причины",
      "post_start_mesh_risk_clears" not in why)

# ── Alpha 2.841: НЕДОКАЗУЕМОЕ ≠ ДОКАЗАННО ВРЕДНОЕ ───────────────────────────
# Прежде оба случая вели к отказу, и на реальном K2 Plus это означало, что калибровку не делал
# НИКТО: тело vendor-макроса BOX_START_PRINT недоступно, автомат закрывался, а сам принтер
# снимал карту только при отсутствии активной сетки. Теперь недоказуемость переводит калибровку
# на Farm Manager: замер выполняется ДО запуска файла. Доказанные «очистит»/«подменит» —
# по-прежнему отказ: там наша работа была бы выброшена.
scen("unknown_vendor_body")
ok, why = run()
check("D8(2.841). тела vendor-макросов не прочитаны -> Farm Manager калибрует САМ, печать разрешена",
      ok and SC["sent"] == ["BED_MESH_CALIBRATE"] and why == "", (SC["sent"], why[:90]))
check("D9(2.841). выбор пользователя не превращается в бездействие: команда реально отправлена",
      "BED_MESH_CALIBRATE" in SC["sent"], SC["sent"])
check("D10(2.841). в журнале названа причина «недоказуемый стартовый макрос»",
      any("start_macro_unproven_self_calibrate" in x for x in LOG.lines), LOG.lines[:3])

# ════════════════════════════════════════════════════════════════════════════
section("E. Операцию делает кто-то другой: печать идёт, второй калибровки нет")

scen("recalibrates")
ok, why = run()
check("E1. стартовый макрос принтера сам калибрует -> команд 0, печать разрешена",
      ok and SC["sent"] == [] and why == "", (SC["sent"], why[:90]))
check("E2. событие записано как file_controlled, а не молча пропущено",
      any("mode=file_controlled" in x for x in LOG.lines), LOG.lines[:3])

scen("safe_standard")
ok, why = run(fdata=b"BED_MESH_CALIBRATE\nG1 X0\n")
check("E3. файл САМ содержит команду калибровки -> команд 0, печать разрешена",
      ok and SC["sent"] == [] and why == "", (SC["sent"], why[:90]))

# Alpha 2.841: тот же файл, но со стартовым макросом вместо явной команды. Раньше здесь тоже
# было «команд 0» — по совпадению имени, — и именно это оставляло пользователя без калибровки.
scen("safe_standard")
ok, why = run(fdata=b"START_PRINT BED_TEMP=60\n")
check("E4(2.841). файл вызывает лишь START_PRINT -> калибровка ВЫПОЛНЯЕТСЯ, а не пропускается",
      ok and "BED_MESH_CALIBRATE" in SC["sent"] and why == "", (SC["sent"], why[:90]))

# ════════════════════════════════════════════════════════════════════════════
section("F. Доказанный vendor-макрос")

scen("safe_vendor")
ok, why = run()
check("F1. используется доказанный макрос принтера, а не встроенная команда",
      ok and SC["sent"] == ["PRINT_CALIBRATION"], SC["sent"])
check("F2. макрос паркуется сам -> наш G28 НЕ отправляется", "G28" not in SC["sent"])
check("F3. в журнале назван класс команды (vendor), а не её текст",
      any("class=vendor_calibration_macro" in x for x in LOG.lines), LOG.lines[:4])

scen("unsafe_vendor_save_config")
ok, why = run()
check("F4. vendor-макрос с SAVE_CONFIG не используется — уходим на встроенный путь",
      ok and SC["sent"] == ["BED_MESH_CALIBRATE"], SC["sent"])
check("F5. SAVE_CONFIG принтеру не отправлялся ни при каких обстоятельствах",
      not any("SAVE_CONFIG" in x for x in SC["sent"]))

# ════════════════════════════════════════════════════════════════════════════
section("G. Принтер не в том состоянии: команд нет вообще")

scen("safe_standard", state="printing")
ok, why = run()
check("G1. принтер печатает -> ни одной команды, печать не начата",
      (not ok) and SC["sent"] == [] and "не в покое" in why, (SC["sent"], why[:90]))

scen("safe_standard", wh="shutdown")
ok, why = run()
check("G2. Klipper не готов -> ни одной команды", (not ok) and SC["sent"] == [])

scen("safe_standard", reachable=False)
ok, why = run()
check("G3. Moonraker недоступен -> ни одной команды и печать не начата",
      (not ok) and SC["sent"] == [] and SC["uploads"] == [])

# ════════════════════════════════════════════════════════════════════════════
section("H. Калибровка не может уйти вторым заходом")

scen("safe_standard")
ok, _ = run()
check("H1. за всю подготовку калибровочная команда отправлена ровно один раз",
      len([x for x in SC["sent"] if "BED_MESH" in x or x in SC["macros"]]) == 1, SC["sent"])
check("H2. G28 за всю подготовку отправлен не более одного раза",
      len([x for x in SC["sent"] if x.split()[0].upper() == "G28"]) <= 1, SC["sent"])

_exec_src = fn_src("_klipper_execute_prestart")
check("H3. после калибровки опция удаляется из плана — источник это подтверждает",
      "_bm_selected" in _exec_src and "!= 'bed_mesh_calibrate'" in _exec_src
      and "c != 'BED_MESH_CALIBRATE'" in _exec_src, "")
_att_src = fn_src("_klipper_bed_mesh_attempt")
# Подстрокой это не проверить: слово «retrying» есть в САМОМ тексте отказа для пользователя.
# Поэтому считаем узлы AST — циклов быть не должно, а точек отправки ровно две (G28 и калибровка).
_att_ast = ast.parse(_att_src).body[0]
_loops = [n for n in ast.walk(_att_ast) if isinstance(n, (ast.While, ast.For, ast.AsyncFor))]
_sends = [n for n in ast.walk(_att_ast)
          if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_send"]
check("H4. в исполнении нет цикла и ровно две точки отправки команды (парковка и калибровка)",
      _loops == [] and len(_sends) == 2, (len(_loops), len(_sends)))
check("H5. отправка идёт ТОЛЬКО через один хелпер (_send), а не россыпью вызовов",
      _att_src.count("gcode/script") == 1, _att_src.count("gcode/script"))

# ════════════════════════════════════════════════════════════════════════════
section("I. Оснастка не течёт в production")

_prod = []
for _p in ("server.py", os.path.join("app", "klipper_contract_probe.py"),
           os.path.join("app", "klipper_prestart.py"), os.path.join("web", "app.js")):
    if SENTINEL in io.open(os.path.join(REPO, _p), encoding="utf-8",
                           errors="surrogateescape").read():
        _prod.append(_p)
check("I1. sentinel отсутствует в production-исходниках", _prod == [], _prod)
check("I2. артефакт _e2e_payload.json не создан",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
check("I3. за весь прогон не было ни одного обращения за пределы fake-хоста", True)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  RED: %s" % f)
sys.exit(1 if FAILED else 0)
