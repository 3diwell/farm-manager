# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.978 — исправления по итогам полной проверки программы.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ. Десять подтверждённых дефектов, найденных сплошной проверкой кода
(24 области, 132 находки, каждая перепроверена двумя независимыми проверяющими). Там, где
функцию можно исполнить в песочнице, проверяется ПОВЕДЕНИЕ настоящего кода; там, где
дефект живёт внутри большого обработчика, — устройство самого кода: и наличие защиты,
и ОТСУТСТВИЕ прежнего опасного образца (иначе проверка позеленела бы на откате).

server.py НЕ импортируется (правило проекта): нужные функции вырезаются разбором исходника
и исполняются в изолированном пространстве имён.
"""
import ast
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "AUDIT_FIXES_SENTINEL_2_978"
PASS = FAIL = 0


def check(name, ok, extra=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("   [%r]" % (extra,)) if extra is not None else ""))


def rd(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read()


SRC = rd("server.py")
REG = rd("app/route_policy_registry.py")
TREE = ast.parse(SRC)
FUNCS = {}
for _n in ast.walk(TREE):
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNCS.setdefault(_n.name, ast.get_source_segment(SRC, _n))


def body(name):
    return FUNCS.get(name) or ""


print("--- 1. Bambu: обрыв связи переводит принтер в «не на связи» ---")
_dis = body("on_disconnect")
check("1. on_disconnect найден в исходнике", bool(_dis))
check("2. при разрыве по вине принтера состояние становится OFFLINE",
      "p_states[pid] = dict(OFFLINE_STATE)" in _dis, _dis[:0])
check("3. пометка ставится только для чужого разрыва и своей эпохи",
      "rc not in (0, None) and worker_epoch == epoch" in _dis)

print("--- 2. Имя печати сравнивается и без расширения ---")
_ns = {"norm": None, "re": __import__("re"), "os": os}
exec("import re\nNORM_RE = re.compile(r'[^a-zA-Z0-9]')\nnorm = lambda s: NORM_RE.sub('', s).lower() if s else ''", _ns)
_exts = None
for _n in ast.walk(TREE):
    if isinstance(_n, ast.Assign) and any(getattr(t, "id", "") == "_PRINT_EXTS" for t in _n.targets):
        _exts = ast.literal_eval(_n.value)
check("4. список расширений печати найден", bool(_exts), _exts)
_ns["_PRINT_EXTS"] = _exts
exec(body("_name_stem"), _ns)
exec(body("_print_name_eq"), _ns)
_eq = _ns["_print_name_eq"]
check("5. полное имя совпадает само с собой", _eq("Holder.gcode.3mf", "Holder.gcode.3mf"))
check("6. имя с экрана принтера (без расширения) совпадает с задачей",
      _eq("Holder.gcode.3mf", "Holder"), "печать с экрана обязана попадать в ту же задачу")
check("7. имя с другим расширением совпадает", _eq("Holder.gcode.3mf", "Holder.gcode"))
check("8. разные детали не путаются", not _eq("Holder.gcode.3mf", "Bracket"))
check("9. пустое имя ничему не равно", not _eq("Holder.gcode.3mf", ""))
check("10. сравнение нечувствительно к регистру и разделителям", _eq("Cover_v2.gcode.3mf", "cover v2"))
_hs = body("handle_state")
check("11. handle_state сравнивает задачи новым правилом",
      '_print_name_eq(r["filename"], raw_fn)' in _hs)
check("12. прежнее сравнение «только norm» из handle_state убрано",
      'if norm(r["filename"]) == fn:\n' not in _hs)
check("13. поиск задачи для проектного пути получает и сырое имя",
      "_staging_task_for_print(norm(obs.filename_raw), obs.filename_raw)" in SRC)

print("--- 3. Одинаковые «нормализованные» имена не залипают ---")
check("14. помечается одна задача, а не все совпавшие",
      "if len(_st_hits) > 1:" in _hs and "считаем первой подходящей" in _hs)
check("15. цикл пометки завершается после первой задачи",
      "staging_print[pid] = _st_name" in _hs and _hs.count("break") >= 1)

print("--- 4. Автоподбор ячеек AMS не отдаёт один слот двум филаментам ---")
_map_src = body("_bambu_auto_slot_map")
check("16. функция подбора найдена", bool(_map_src))


class _Orch:
    REL_EXACT, REL_CLOSE, REL_OTHER = 0, 1, 2

    @staticmethod
    def norm_material(m):
        return (str(m).strip().upper() or "") if m else ""

    @staticmethod
    def color_relation(a, b):
        return (0 if (a and b and a == b) else 2), 0


_AMS = {"p_states": {}, "_orch": _Orch(), "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                                                                "info": staticmethod(lambda *a, **k: None)})(),
        "_exc_brief": lambda: "test"}
_AMS["_3mf_filament_requirements"] = lambda data: data      # в тесте fdata сразу словарь требований
_AMS["_3mf_plate_used"] = lambda data: {"ok": False}       # 16.10.2026 (R-136): плита не описана — все филаменты
#  16.10.2026 (R-006): раскладка — общий чистый модуль (тот же для запуска и очереди), остаток слота
#  считает модуль состояния AMS; сопла филаментов файл не описывает.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app import bambu_slot_match as _bslot_mod, bambu_ams_state as _bams_mod   # noqa: E402
_AMS["_bslot"], _AMS["_bams"] = _bslot_mod, _bams_mod
_AMS["_3mf_filament_sides"] = lambda data: {"ok": False}
#  2.991: подбор смотрит на остаток в слоте и на порог «скоро кончится». Кладём обе
#  функции ДОСЛОВНО: без них подбор молча падал бы в свой except и возвращал None.
exec(body("_tray_remain"), _AMS)
exec(body("_ams_low_pct"), _AMS)
exec(_map_src, _AMS)
_auto = _AMS["_bambu_auto_slot_map"]

#  Тот самый сценарий: файл на два филамента, PETG лежит в слоте 1, PLA нет нигде.
_AMS["p_states"]["p1"] = {"ams_trays": [{"index": 0, "type": "PLA-НЕТ"}, {"index": 1, "type": "PETG"}]}
_AMS["p_states"]["p1"]["ams_trays"][0]["type"] = "ABS"       # чужой материал: PLA не найдётся
_fd = {"filaments": [{"material": "PETG"}, {"material": "PLA"}]}
_res = _auto("p1", _fd, [0, 1])
check("17. один слот не достаётся двум филаментам",
      _res is None or len(set(_res)) == len(_res), _res)
check("18. при спорном подборе остаётся карта из файла", _res in (None, [0, 1]), _res)

#  Честный случай: обоим филаментам есть свой слот — подбор работает как прежде.
_AMS["p_states"]["p2"] = {"ams_trays": [{"index": 0, "type": "PLA"}, {"index": 1, "type": "PETG"}]}
_res2 = _auto("p2", {"filaments": [{"material": "PETG"}, {"material": "PLA"}]}, [0, 1])
check("19. верный подбор по материалам сохранён", _res2 == [1, 0], _res2)
check("20. подбор без слотов принтера ничего не выдумывает",
      _auto("нет-такого", _fd, [0, 1]) is None)

print("--- 5. Сторож отправок не гасит идущую печать ---")
_tick = body("tick")
check("21. решение принимается по неискажённому снимку состояния",
      "_get_printer_safety_snapshot" in _tick)
check("22. при идущей печати или незавершённой отмене отправка не гасится",
      'user_stopped_pending' in _tick and 'printing_active' in _tick)
check("23. новая печать от сервера снимает прежнюю маску отмены",
      "_user_stopped.pop(pid, None)   # 2.978" in SRC)

print("--- 6. Смена папки данных: путь и право ---")
_sd = body("set_storage_data")
check("24. форма пути проверяется до создания каталога",
      "_fs_policy.check_client_path(new).allow" in _sd)
check("25. проверка стоит РАНЬШЕ проверки на запись",
      _sd.index("check_client_path") < _sd.index("_writable_dir"))
check("26. маршрут закрыт правом администратора",
      '"POST /api/storage/data":' in REG and REG.split('"POST /api/storage/data":')[1].split("\n")[0].strip().startswith("(EnforcedAccess.CAPABILITY, \"admin\")"))

print("--- 7. Загрузка файла в проект не затирает одноимённый ---")
_up = body("up_project2_file")
check("27. имя проходит через безопасное приведение", "_safe_managed_filename(fname)" in _up)
check("28. при другом содержимом файл кладётся рядом", "_unique_dest(pdir, _safe)" in _up)
check("29. тот же файл переиспользуется, а не пишется заново", "_reuse" in _up)
check("30. в базу пишется имя, реально лежащее на диске",
      "add_file_to_project(project_id, os.path.basename(dest), stored_path=dest)" in _up)
check("31. прежнее безусловное затирание убрано",
      'dest = os.path.join(pdir, fname)\n        try:\n            with open(dest, "wb")' not in _up)

print("--- 8. Bambu: одна команда печати вместо двух ---")
_bsp = body("_bambu_start_print")
#  2.988: проверка занятости стала шире — статус, код 0500-4004 и стадия работы
#  (stg_cur) сведены в _bambu_busy_now. Смысл прежний: занятому принтеру второй
#  вариант имени не уходит; теперь занятость видно ещё и когда статус запаздывает.
check("32. второй вариант имени не уходит ЗАНЯТОМУ принтеру (статус, код занятости или стадия)",
      "_bambu_busy_now(pid)" in _bsp)
check("33. ответ прошивки читается перед следующей попыткой",
      "_bambu_print_outcome(" in _bsp)
check("34. перед второй командой выдерживается пауза ожидания старта",
      "_bambu_wait_started(pid, 15.0)" in _bsp)
check("35. неотправленная команда — это отказ, а не тишина",
      "no connection to the printer" in _bsp and "if not _bambu_publish(" in _bsp)
check("36. прежний слепой цикл по двум кандидатам убран",
      "for _u, _sub in _print_cmds:" not in _bsp)

print("--- 9. FlashForge: отказ запуска — это отказ ---")
_c1 = body("_cmd_start_print_send")
check("37. ответ принтера принимается в переменные", "_ff_ok, _ff_msg = _flashforge_print(" in _c1)
check("38. при отказе возвращается ошибка", 'if not _ff_ok:' in _c1 and '"status": "error"' in _c1)
_ff_i = _c1.index("_ff_ok, _ff_msg")
_hook_i = _c1.index("_c1_after_dispatch", _ff_i)
check("39. списание филамента стоит ПОСЛЕ проверки ответа",
      _c1.index("if not _ff_ok:") < _hook_i)
check("40. прежний вызов без проверки убран",
      "_flashforge_print(pip, pport, ptoken, data.val.lstrip(\"/\"))\n                progress(command_ok=True)" not in _c1)

print("--- 10. «Стоп» не считается выполненным, пока не доставлен ---")
_cmd = body("p_cmd")
check("41. пометка отмены ставится после доставки, а не до",
      "_user_stopped[pid] = time.monotonic()" in _cmd and "_cmd_sent" in _cmd)
check("42. прежняя пометка до обращения к принтеру убрана",
      "server_print.pop(pid, None); _server_print_ts.pop(pid, None); _user_stopped[pid] = time.monotonic()" not in _cmd)
check("43. при недоставленной команде состояние печати возвращается", "_stop_prev" in _cmd)
check("44. клиенту уходит отказ, а не «ок»", "stop_not_delivered" in _cmd)
check("45. отказ Klipper считается недоставкой", "_cmd_sent = False" in _cmd)
check("46. ответ FlashForge на «стоп» принимается", "_cmd_sent = bool(_flashforge_control(" in _cmd)
check("47. публикация Bambu проверяется", "_cmd_sent = _bambu_publish(" in _cmd)
check("48. виртуальный принтер тоже подтверждает доставку", "_cmd_sent = True" in _cmd)

print("--- 12. виртуальный принтер списывает филамент на ОБОИХ путях ---")
_sf = body("_send_file_to_printer")
check("51. отправка файла виртуальному принтеру зовёт хуки списания",
      "_run_after_dispatch_hooks(pid, [0], fdata, fname)" in _sf)
check("52. назначение слота тоже запоминается", "_stash_run_assignments(pid, [0], fdata, True)" in _sf)
check("53. запуск файла С ПРИНТЕРА зовёт те же хуки (не разошлись пути)",
      "_run_after_dispatch_hooks(pid, [0], _fd, fname)" in body("_c1_after_dispatch"))

print("--- 13. на плите считаются штуки, а не строки ---")
_pv = body("get_project_parts_view")
check("54. количество на плите суммируется", 'total_by_file.get(l["file_id"], 0) + _q' in _pv)
check("55. прежний счёт «по одной за строку» убран",
      'total_by_file.get(l["file_id"], 0) + 1' not in _pv)

print("--- 14. отмена удаления возвращает и сам файл (исполнение) ---")
import shutil as _shutil
import tempfile as _tempfile
import time as _time

_TR = {"os": os, "time": _time,
       "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                             "warning": staticmethod(lambda *a, **k: None)})(),
       "_exc_brief": lambda: "test"}
_root = _tempfile.mkdtemp(prefix="fmtrash978")
_TR["PROJECT_FILES_DIR"] = os.path.join(_root, "project_files")
_TR["UPLOAD_DIR"] = os.path.join(_root, "slicer_uploads")
_TR["TEMP_FILES_DIR"] = os.path.join(_root, "temp_files")
for _d in (_TR["PROJECT_FILES_DIR"], _TR["UPLOAD_DIR"], _TR["TEMP_FILES_DIR"]):
    os.makedirs(_d, exist_ok=True)
for _fn in ("_unique_dest", "_prune_trash_dir", "_trash_managed_copy", "_untrash_managed_copy",
            "_unlink_in_managed"):
    exec(body(_fn), _TR)
_trash = _TR["_trash_managed_copy"]
_untrash = _TR["_untrash_managed_copy"]

_pdir = os.path.join(_TR["PROJECT_FILES_DIR"], "Проект 1")
os.makedirs(_pdir, exist_ok=True)
_src = os.path.join(_pdir, "plate.gcode")
io.open(_src, "w", encoding="utf-8").write("G28\n")
_hidden = _trash(_src)
check("56. копия убрана с прежнего места", not os.path.isfile(_src))
check("57. копия цела в служебной папке", bool(_hidden) and os.path.isfile(_hidden), _hidden)
check("58. служебная папка лежит рядом с файлом проекта",
      os.path.basename(os.path.dirname(_hidden or "")) == "_removed", _hidden)
check("59. отмена возвращает файл на прежнее место",
      _untrash(_hidden, _src) and os.path.isfile(_src)
      and io.open(_src, encoding="utf-8").read() == "G28\n")

#  Файл ВНЕ управляемых папок — чужой оригинал владельца: его не трогают никогда.
_out = os.path.join(_root, "оригинал.gcode")
io.open(_out, "w", encoding="utf-8").write("G28\n")
check("60. оригинал вне управляемых папок не прячется",
      _trash(_out) == "" and os.path.isfile(_out))

#  Второе удаление того же имени не затирает первое.
io.open(_src, "w", encoding="utf-8").write("G28\n")
_h1 = _trash(_src)
io.open(_src, "w", encoding="utf-8").write("G1 X1\n")
_h2 = _trash(_src)
check("61. две удалённые копии с одним именем сохраняются обе",
      _h1 and _h2 and _h1 != _h2 and os.path.isfile(_h1) and os.path.isfile(_h2), (_h1, _h2))
check("62. возврат не портит уже лежащий на месте файл",
      _untrash(_h1, _out) and io.open(_out, encoding="utf-8").read() == "G28\n")
_shutil.rmtree(_root, ignore_errors=True)

check("63. удаление файла проекта прячет копию, а не стирает",
      'file_snap["trashed_copy"] = _trash_managed_copy(sp)' in body("delete_project_file"))
check("64. отмена удаления возвращает копию", "_untrash_managed_copy(f.get" in body("restore_project_file"))
check("65. неправда в описании отката исправлена",
      "Физические файлы при удалении не трогались" not in body("restore_project_file"))

print("--- 15. повторная связь файл-деталь ---")
check("66. штуки суммируются, а не заменяются",
      SRC.count("on_plate_qty=COALESCE(on_plate_qty,0)+?") == 2)
check("67. наверх уходит настоящий id связи",
      body("_insert_parsed_file").count("SELECT id, on_plate_qty FROM project_file_parts") == 1
      and body("add_manual_part").count("SELECT id, on_plate_qty FROM project_file_parts") == 1)
check("68. прежняя замена количества убрана",
      "UPDATE project_file_parts SET on_plate_qty=?, updated_at=CURRENT_TIMESTAMP WHERE file_id=?" not in SRC)

print("--- 16. печатающаяся задача не сбрасывается в «готова» ---")
check("69. состояние «печатается» сохраняется при повторном добавлении файла",
      SRC.count("status=CASE WHEN staging_files.status='printing' THEN staging_files.status ELSE 'ready' END") == 2)
check("70. прежний безусловный сброс убран",
      "ON CONFLICT(filename) DO UPDATE SET status='ready'" not in SRC)

print("--- 17. сохранение задачи и удаление задачи ---")
_ss = body("save_staging")
check("71. сохранение несуществующей задачи отвечает отказом",
      "_cur.rowcount < 1" in _ss and "unknown_task" in _ss)
_sd = body("staging_delete")
check("72. перед удалением файла проверяется и каталог деталей",
      "FROM parts_catalog WHERE is_deleted=0" in _sd)
check("73. деталь с пустым src_path опознаётся по имени файла",
      "COALESCE(src_path,'')='' AND gcode_file=?" in _sd)

print("--- 11. версия и журнал ---")
#  Сравниваем ЧИСЛОМ, а не началом строки: «2.980» не начинается с «2.97».
_m = __import__("re").search(r'APP_VERSION = "(?:Alpha|Beta) (\d+)\.(\d+)"', SRC)
check("49. версия поднята (2.978 и выше)",
      bool(_m) and (int(_m.group(1)), int(_m.group(2))) >= (2, 978), _m.group(0) if _m else None)
#  3.0: журнал сжат в одну запись, отдельной записи 2.978 больше нет — но главная починка того
#  выпуска (H2D «Device is busy») обязана остаться в сводном тексте для пользователя.
_cl_start = SRC.index("CHANGELOG = [")
_cl_text = SRC[_cl_start:SRC.index("\n]\n", _cl_start)]
check("50. в журнале «Что нового» осталась починка 2.978: H2D и «Device is busy»",
      "Device is busy" in _cl_text and "H2D" in _cl_text)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
