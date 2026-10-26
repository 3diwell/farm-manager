# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.840 — РЕКУРСИВНЫЙ КОНТРАКТ КАЛИБРОВКИ СТОЛА: решение принимается по
#  фактическому графу вызовов принтера, а недосказанность закрывает автомат.
#
#  ЧТО ЗАКРЫВАЕТ. Клиент прислал диагностический отчёт 2.839 с реального Creality
#  K2 Plus. Из него следует ровно одно, и оно неприятно: START_PRINT паркует оси и
#  вызывает несколько vendor-макросов, а их ТЕЛА отчёт v1 не выгружал. Значит, что
#  произойдёт с сеткой стола ПОСЛЕ нашей калибровки — очистят её, заменят профилем
#  или измерят заново — из отчёта НЕ СЛЕДУЕТ. До 2.840 такого вопроса вообще не
#  задавалось: «команда BED_MESH_CALIBRATE существует» считалось достаточным.
#
#  ЧЕСТНО О ГРАНИЦАХ. Здесь НЕ проверяется, какие именно макросы у K2 Plus и что
#  внутри них: живой разведки не было, а сам клиентский отчёт в репозиторий не
#  копировался (он только читался). Проверяется КОНТРАКТ на синтетических данных,
#  воспроизводящих ФОРМУ той ситуации: тела не прочитаны -> risk=unknown ->
#  автоматический путь закрыт. Имя vendor-макроса доказательством не считается.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * ни одного сетевого сокета: разбор идёт по синтетическим структурам;
#   * server.py НЕ импортируется;
#   * реальному принтеру не отправляется НИ ОДНОЙ команды;
#   * фикстура полностью синтетическая — проверяется отдельно (раздел A).
#
#  Запуск:  python tools/test_k2_plus_real_contract.py    (0 = всё пройдено)
# ============================================================================
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "K2_REAL_CONTRACT_SENTINEL_2_840"        # ТОЛЬКО в этой оснастке

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


from app import klipper_contract_probe as K   # noqa: E402

FIXP = os.path.join(REPO, "tools", "fixtures", "klipper", "k2_plus_bed_mesh_contract_v2.json")
FIX = json.load(io.open(FIXP, encoding="utf-8"))
PC = FIX["printer_class"]
G = FIX["graphs"]

print("=== Alpha 2.840: рекурсивный контракт калибровки Klipper ===")
print("МЕТКА ОСНАСТКИ: %s" % SENTINEL)

# ════════════════════════════════════════════════════════════════════════════
section("A. Фикстура синтетическая: клиентские данные в репозиторий не попали")

RAWFIX = io.open(FIXP, encoding="utf-8").read()

check("A1. в фикстуре нет IP-адресов",
      not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", RAWFIX))
check("A2. в фикстуре нет MAC-адресов и серийных номеров",
      not re.search(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b", RAWFIX)
      and "serial" not in RAWFIX.lower())
check("A3. в фикстуре нет полных путей и домашней папки",
      ":\\" not in RAWFIX and "/home/" not in RAWFIX and "C:" not in RAWFIX)
check("A4. в фикстуре нет ключей/токенов/паролей",
      not re.search(r"(?i)(api[_-]?key|token|password|access[_-]?code)", RAWFIX))
check("A5. фикстура не является копией клиентского отчёта (нет полей v1-выгрузки)",
      "generated_at" not in RAWFIX and "report_schema_version" not in RAWFIX
      and "endpoints_read" not in RAWFIX)
check("A6. фикстура прямо помечена как синтетическая",
      "СИНТЕТИЧЕСКАЯ" in RAWFIX.upper() and FIX["fixture_version"] == 2)
check("A7. модель названа классом, а не жёстко зашитым именем принтера",
      PC["model_class"] == "synthetic_k2_like"
      and "K2 Plus" not in RAWFIX and "Creality" not in RAWFIX)

# ════════════════════════════════════════════════════════════════════════════
section("B. Граф вызовов: предохранители работают, а не декларируются")

# Пределы закрепляются ЛИТЕРАЛАМИ. Сравнивать глубину с той же переменной, которую проверка
# должна пинать, бессмысленно: подними её до 9999 — и проверка останется зелёной сама с собой.
LIM_DEPTH, LIM_NODES, LIM_BODY = 6, 120, 24000
check("B0. объявленные пределы совпадают с закреплёнными в тесте",
      (K.GRAPH_MAX_DEPTH, K.GRAPH_MAX_NODES, K.BODY_MAX_CHARS) == (LIM_DEPTH, LIM_NODES, LIM_BODY),
      (K.GRAPH_MAX_DEPTH, K.GRAPH_MAX_NODES, K.BODY_MAX_CHARS))

_deep = {}
for i in range(30):
    _deep["M%02d" % i] = "M%02d\n" % (i + 1)
gd = K.build_call_graph("M00", _deep, PC["builtins"])
check("B1. глубина ограничена объявленным лимитом",
      gd["depth_reached"] <= LIM_DEPTH and gd["truncated"] is True,
      (gd["depth_reached"], gd["truncated"]))
check("B2. упёрлись в лимит -> риск unknown (недосказанность закрывает автомат)",
      K.analyze_mesh_risk(gd)[0] == K.RISK_UNKNOWN)

_wide = {"ROOT": "".join("W%03d\n" % i for i in range(200))}
for i in range(200):
    _wide["W%03d" % i] = "G1 X0\n"
gw = K.build_call_graph("ROOT", _wide, PC["builtins"])
check("B3. число узлов ограничено объявленным лимитом",
      len(gw["nodes"]) <= LIM_NODES and gw["truncated"] is True, len(gw["nodes"]))

gc = K.build_call_graph(G["cyclic"]["start_macro"], G["cyclic"]["macros"], PC["builtins"])
check("B4. взаимная рекурсия обнаружена и обход завершился",
      bool(gc["cycles"]) and len(gc["nodes"]) <= 8, (gc["cycles"], len(gc["nodes"])))

gt = K.build_call_graph("BIG", {"BIG": "G1 X0\n" * (LIM_BODY // 4)}, PC["builtins"])
check("B5. слишком длинное тело помечено обрезанным",
      gt["truncated"] is True and gt["nodes"]["BIG"]["truncated"] is True)
check("B6. обрезанное тело -> риск unknown", K.analyze_mesh_risk(gt)[0] == K.RISK_UNKNOWN)

gu = K.build_call_graph(G["unknown_vendor_body"]["start_macro"],
                        G["unknown_vendor_body"]["macros"], PC["builtins"])
check("B7. непрочитанный макрос назван поимённо, а не молча пропущен",
      sorted(gu["unknown"]) == ["BOX_START_PRINT", "PRINT_PREPARE_CLEAR"], gu["unknown"])
check("B8. у непрочитанного узла тело честно помечено недоступным",
      gu["nodes"]["BOX_START_PRINT"]["body_available"] is False
      and gu["nodes"]["BOX_START_PRINT"]["kind"] == "unknown")
check("B9. у прочитанного узла перечислены флаги, а не одно «есть/нет»",
      all(k in gu["nodes"]["START_PRINT"] for k in
          ("calls_homing", "calls_bed_mesh_calibrate", "calls_bed_mesh_clear",
           "loads_mesh_profile", "calls_save_config", "calls_restart", "calls_shutdown")))
check("B10. пустой граф -> unknown, а не «ничего страшного не найдено»",
      K.analyze_mesh_risk({})[0] == K.RISK_UNKNOWN
      and K.analyze_mesh_risk(None)[0] == K.RISK_UNKNOWN)
# Проверять «нет ли IF среди вызовов» бессмысленно: такой токен и так не пройдёт формат имени.
# Пинать надо результат: в графе реального макроса с Jinja узлов-мусора быть не должно вовсе.
_gj = K.build_call_graph("START_PRINT", G["safe_standard"]["macros"], PC["builtins"])
check("B11. строки Jinja не превращаются в узлы графа и не делают его недоказанным",
      _gj["unknown"] == [] and all(re.fullmatch(r"[A-Z_][A-Z_0-9.]*", n) for n in _gj["nodes"])
      and "G28" in _gj["nodes"], (_gj["unknown"], sorted(_gj["nodes"])))

# ════════════════════════════════════════════════════════════════════════════
section("C. Резолвер: все сценарии фикстуры разрешаются в объявленный план")

for _name in sorted(G):
    _sc = G[_name]
    _exp = _sc["expected"]
    _plan = K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"], _sc["macros"],
                                    (), _sc["start_macro"])
    _got = {"risk": _plan["post_start_mesh_risk"], "mode": _plan["mode"],
            "reason_code": _plan["reason_code"], "commands": _plan["commands"],
            "requires_homing": _plan["requires_homing"],
            "cycle_detected": bool((_plan.get("graph") or {}).get("cycles"))}
    check("C[%s]. %s" % (_name, _sc["describe"]),
          all(_got.get(k) == v for k, v in _exp.items()),
          {k: _got.get(k) for k in _exp})

# ════════════════════════════════════════════════════════════════════════════
section("D. Урок клиентского отчёта: имя — не доказательство, тишина — не «да»")

_kl = G["unknown_vendor_body"]
_pu = K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"], _kl["macros"], (), "START_PRINT")
# ── Alpha 2.841: недоказуемость больше не отдаёт калибровку принтеру ──────────────────────
# Риск по-прежнему unknown — это НЕ изменилось и не должно: доказать поведение стартового
# макроса нельзя. Изменился ВЫВОД из этого. Прежний отказ выглядел осторожным, а на практике
# означал, что стол не измерит никто: файл команды не содержит, мы её не шлём, а vendor-макрос
# принтера снимает карту только при отсутствии активной сетки. Теперь замер делает Farm Manager
# ДО запуска файла. Доказанные «очистит»/«подменит» остаются закрытыми — см. D1b.
check("D1(2.841). тела vendor-макросов не прочитаны -> риск unknown, но калибруем САМИ",
      _pu["mode"] == K.MODE_STANDARD and _pu["commands"] == ["BED_MESH_CALIBRATE"]
      and _pu["post_start_mesh_risk"] == K.RISK_UNKNOWN, _pu["reason_code"])
check("D1b(2.841). ДОКАЗАННЫЙ вред по-прежнему закрывает автоматический путь",
      all(K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"], G[_n]["macros"], (),
                                  G[_n]["start_macro"])["mode"] == K.MODE_UNSAFE
          for _n in ("clears_mesh", "replaces_mesh")))
check("D2. решение объяснено пользователю на обоих языках, а не кодом",
      len(_pu["explanation_ru"]) > 30 and len(_pu["explanation_en"]) > 30
      and _pu["reason_code"] not in _pu["explanation_ru"])
check("D3. одно только имя vendor-макроса автоматику НЕ открывает",
      K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"],
                              G["vendor_name_only"]["macros"], (),
                              "START_PRINT")["mode"] == K.MODE_STANDARD)
check("D4. vendor-макрос из списка кандидатов, но с SAVE_CONFIG, не считается доказанным",
      K._vendor_is_safe("PRINT_CALIBRATION", G["unsafe_vendor_save_config"]["macros"],
                        PC["builtins"])[1] == "vendor_state_changing")
check("D5. доказанный vendor-макрос, который паркуется сам, не требует нашего G28",
      K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"], G["safe_vendor"]["macros"],
                              (), "START_PRINT")["requires_homing"] is False)
check("D6. решение НЕ опирается на имя модели принтера",
      "K2" not in K.VENDOR_CALIBRATION_CANDIDATES
      and not any("CREALITY" in c.upper() for c in K.VENDOR_CALIBRATION_CANDIDATES))
_src = io.open(os.path.join(REPO, "app", "klipper_contract_probe.py"), encoding="utf-8").read()
_code = re.sub(r'"""[\s\S]*?"""', "", _src)
_code = re.sub(r"(?m)^\s*#.*$", "", _code)
check("D7. имя модели не зашито в КОДЕ резолвера (ни K2, ни Creality)",
      "K2 Plus" not in _code and "Creality" not in _code)
check("D8. операцию делает сам файл -> команд ноль и это НЕ ошибка",
      (lambda p: p["mode"] == K.MODE_FILE and p["commands"] == [])(
          K.resolve_bed_mesh_plan(PC["objects"], PC["builtins"], G["safe_standard"]["macros"],
                                  ("bed_mesh_calibrate",), "START_PRINT")))
check("D9. нет объекта bed_mesh -> unsupported, а не «попробуем»",
      K.resolve_bed_mesh_plan(["toolhead"], PC["builtins"], {}, (), "")["mode"]
      == K.MODE_UNSUPPORTED)
check("D10. резолвер не бросает на мусоре любого вида",
      all(isinstance(K.resolve_bed_mesh_plan(*a), dict) for a in (
          (None, None, None, None, None), (1, 2, 3, 4, 5), ("x", "y", {"A": None}, (), "A"))))
check("D11. отпечаток сетки — форма и хеш, но НЕ сами значения",
      (lambda f: f["present"] and f["rows"] == 2 and f["cols"] == 2 and len(f["sha256"]) == 64)(
          K.mesh_fingerprint({"profile_name": "default",
                              "probed_matrix": [[0.1, 0.2], [0.3, 0.4]]})))
check("D12. разные сетки дают разный отпечаток (иначе проверка была бы пустой)",
      K.mesh_fingerprint({"probed_matrix": [[0.1]]})["sha256"]
      != K.mesh_fingerprint({"probed_matrix": [[0.2]]})["sha256"])
check("D13. отсутствующая сетка отпечатка не имеет",
      K.mesh_fingerprint({})["present"] is False and K.mesh_fingerprint(None)["sha256"] == "")

# ════════════════════════════════════════════════════════════════════════════
section("E. Отчёт v2 добавляет разделы и не ломает читателя v1")


def _raw_scene(macros, objects=None, commands=None):
    """Синтетический ответ Moonraker. Никаких адресов, ключей и клиентских данных."""
    _o = objects if objects is not None else PC["objects"]
    _c = commands if commands is not None else PC["builtins"]
    _settings = {}
    for _n, _b in macros.items():
        _settings["gcode_macro %s" % _n.lower()] = {"gcode": _b}
    return {
        "/server/info": {"ok": True, "data": {"result": {"moonraker_version": "synthetic"}}},
        "/printer/info": {"ok": True, "data": {"result": {"software_version": "synthetic"}}},
        "/printer/objects/list": {"ok": True, "data": {"result": {"objects": _o}}},
        "/printer/gcode/help": {"ok": True, "data": {"result": {k: "" for k in _c}}},
        "/printer/objects/query?configfile": {
            "ok": True, "data": {"result": {"status": {"configfile": {"settings": _settings}}}}},
        "/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout": {
            "ok": True, "data": {"result": {"status": {
                "toolhead": {"homed_axes": ""}, "print_stats": {"state": "standby"},
                "webhooks": {"state": "ready"}, "idle_timeout": {"state": "Ready"}}}}},
        "/printer/objects/query?bed_mesh": {
            "ok": True, "data": {"result": {"status": {"bed_mesh": {"profile_name": "default"}}}}},
    }


REP = K.build_report(_raw_scene(G["unknown_vendor_body"]["macros"]),
                     app_version="Alpha 2.840", model_label="synthetic",
                     generated_at="2026-07-30", adapter="klipper")
SEC = REP["sections"]

check("E1. версия схемы НЕ менялась — читатель v1 продолжает работать",
      REP["report_schema_version"] == K.REPORT_SCHEMA)
check("E2. все разделы v1 на месте (ни один не переименован и не удалён)",
      all(k in SEC for k in ("objects_present", "relevant_commands", "relevant_macros",
                             "start_macro_analysis", "bed_mesh_analysis", "homing_analysis",
                             "completion_evidence_candidates", "current_safe_state",
                             "file_controlled_analysis")))
check("E3. поля верхнего уровня v1 сохранены",
      all(k in REP for k in ("generated_at", "farm_manager_version", "adapter", "printer_model",
                             "klipper_version", "moonraker_version", "probe_warnings",
                             "unresolved_questions", "endpoints_read", "endpoints_failed")))
check("E4. добавлены ВСЕ объявленные разделы 2.840",
      all(k in SEC for k in ("vendor_calibration_candidates", "recursive_start_call_graph",
                             "recursive_calibration_call_graph", "mesh_clear_or_replace_analysis",
                             "resolved_bed_mesh_plan")),
      sorted(SEC))
check("E5. добавлены объявленные поля верхнего уровня 2.840",
      all(k in REP for k in ("post_start_mesh_risk", "unresolved_graph_nodes",
                             "graph_limits_reached", "graph_limits")))
check("E6. на форме клиентского контракта отчёт говорит unknown, а не «всё хорошо»",
      REP["post_start_mesh_risk"] == K.RISK_UNKNOWN
      and SEC["resolved_bed_mesh_plan"]["mode"] == K.MODE_STANDARD
      and SEC["resolved_bed_mesh_plan"]["reason_code"] == "start_macro_unproven_self_calibrate",
      (REP["post_start_mesh_risk"], SEC["resolved_bed_mesh_plan"]["reason_code"]))
check("E7. непрочитанные узлы перечислены поимённо",
      sorted(REP["unresolved_graph_nodes"]) == ["BOX_START_PRINT", "PRINT_PREPARE_CLEAR"],
      REP["unresolved_graph_nodes"])
check("E8. недоказанность попала в открытые вопросы, а не потерялась",
      any("не доказана" in q.lower() or "не прочитана" in q.lower()
          for q in REP["unresolved_questions"]), REP["unresolved_questions"])
check("E9. в отчёт не попали ТЕЛА макросов графа (только имена вызовов и флаги)",
      all("body" not in n and "gcode" not in n
          for n in SEC["recursive_start_call_graph"]["graph"]["nodes"].values()))
check("E10. самопроверка утечек чистая на синтетической сцене",
      K.find_leaks(json.dumps(REP, ensure_ascii=False)) == [],
      K.find_leaks(json.dumps(REP, ensure_ascii=False)))
check("E11. сводка называет главный вывод, а не только версии",
      (lambda s: s["post_start_mesh_risk"] == K.RISK_UNKNOWN
       and s["bed_mesh_plan_mode"] == K.MODE_STANDARD
       and "klipper_version" in s)(K.summarize(REP)))

REP2 = K.build_report(_raw_scene(G["safe_standard"]["macros"]), app_version="Alpha 2.840",
                      model_label="synthetic", generated_at="2026-07-30")
check("E12. доказанный безопасный контракт даёт standard_builtin и ровно одну команду",
      REP2["post_start_mesh_risk"] == K.RISK_NONE
      and REP2["sections"]["resolved_bed_mesh_plan"]["mode"] == K.MODE_STANDARD
      and REP2["sections"]["resolved_bed_mesh_plan"]["commands"] == ["BED_MESH_CALIBRATE"],
      REP2["sections"]["resolved_bed_mesh_plan"])
check("E13. кандидаты в vendor-калибровку перечислены с вердиктом каждому",
      {c["name"] for c in SEC["vendor_calibration_candidates"]["candidates"]}
      == set(K.VENDOR_CALIBRATION_CANDIDATES)
      and all("proven" in c and "reason" in c
              for c in SEC["vendor_calibration_candidates"]["candidates"]))
check("E14. недоступная конфигурация не выдаётся за доказанный контракт",
      (lambda r: r["post_start_mesh_risk"] == K.RISK_UNKNOWN)(
          K.build_report({p: {"ok": False, "data": {}, "error": "x"} for p in K.ALLOWED_PATHS})))
check("E15. build_report не бросает на мусоре",
      isinstance(K.build_report({}), dict) and isinstance(K.build_report({"x": None}), dict))

# ════════════════════════════════════════════════════════════════════════════
section("G. Интерфейс называет стадии и источники теми же словами, что и сервер")

APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8",
                errors="surrogateescape").read()
SRVSRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8",
                 errors="surrogateescape").read()

check("G1. все стадии подготовки подписаны по-русски",
      all(s in APPJS for s in ("Проверка состояния принтера…", "Проверка конфигурации принтера…",
                               "Парковка осей…", "Калибровка стола…", "Проверка сетки стола…",
                               "Калибровка завершена", "Запуск файла…")))
check("G2. те же стадии переведены на английский",
      all(s in APPJS for s in ("Checking the printer state…", "Reading the printer configuration…",
                               "Homing the axes…", "Bed mesh calibration…",
                               "Verifying the bed mesh…", "Calibration finished",
                               "Starting the file…")))
check("G3. четыре источника автоматического пути названы в интерфейсе",
      all(s in APPJS for s in ("Встроенная команда Klipper", "Макрос принтера",
                               "Управляется стартовым макросом или файлом",
                               "Автоматический путь не подтверждён")))
_stages_ui = set()
for _line in APPJS.splitlines():
    if "const ru = { queued:" in _line:
        _stages_ui = {p.split(":")[0].strip() for p in _line.split("{", 1)[1].split(",")}
_emitted = set()
for _m in re.finditer(r'(?:_pcb_pre|_pcb|pcb)\(stage="([a-z_]+)"', SRVSRC):
    _emitted.add(_m.group(1))
check("G4. КАЖДАЯ стадия, которую шлёт сервер, имеет подпись в интерфейсе",
      _emitted and _emitted <= _stages_ui, sorted(_emitted - _stages_ui))
check("G5. КАЖДАЯ стадия, которую шлёт сервер, разрешена реестром отправок",
      (lambda al: _emitted <= al)(set(re.findall(
          r'"([a-z_]+)"', re.search(r"_SEND_STATES = \(([\s\S]*?)\)", SRVSRC).group(1)))),
      sorted(_emitted - set(re.findall(
          r'"([a-z_]+)"', re.search(r"_SEND_STATES = \(([\s\S]*?)\)", SRVSRC).group(1)))))
check("G6. флажок активен только у доказанной автоматики",
      ":disabled=\"c.state !== 'supported_automatic'\"" in
      io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read())

# ════════════════════════════════════════════════════════════════════════════
section("F. Метка оснастки не течёт в production")

_prod = []
for _p in ("server.py", os.path.join("app", "klipper_contract_probe.py"),
           os.path.join("app", "klipper_prestart.py"), os.path.join("web", "app.js")):
    if SENTINEL in io.open(os.path.join(REPO, _p), encoding="utf-8",
                           errors="surrogateescape").read():
        _prod.append(_p)
check("F1. sentinel отсутствует в production-исходниках", _prod == [], _prod)
check("F2. артефакт _e2e_payload.json не создан",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  RED: %s" % f)
sys.exit(1 if FAILED else 0)
