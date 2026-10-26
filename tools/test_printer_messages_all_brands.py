# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""15.09.2026 — сообщения с экранов принтеров видны в программе: все марки, во время печати тоже.

ЗАЧЕМ. Владелец 15.09.2026 с фото H2D («Micro Lidar lens seems to be dirty [0c00-0100-0001-0004]»):
сообщения с экранов принтеров показываются в программе не всегда. Глубокая проверка нашла:
  1. Bambu: во время печати (RUNNING) и после неё (FINISH) список уведомлений стирался вместе с
     кодами старта печати — всё, что принтер показывает во время печати (лидар, подмена катушки,
     RFID), в программу не попадало никогда. Теперь список живёт, пока принтер сам его не снимет.
  2. Bambu: текстов не было — программа знала два кода. Теперь тексты берутся из официальной
     таблицы Bambu (e.bambulab.com/query.php — тот же адрес, что за QR-кодом на экране), на
     русском и английском, с кешем в папке данных; без интернета — прежняя таблица.
  3. Klipper/Creality: сообщения прошивки («прошивка запускается», сообщение печати) и
     FlashForge: код ошибки errorCode из /detail — в тот же блок «Сообщения принтера».

ЧТО ДОКАЗЫВАЕТСЯ. Чистый разбор таблицы (на образце того же вида, что настоящий ответ), кеш
(запись/чтение/срок), загрузка без сети через подставной загрузчик, поиск по печатному коду; в
песочнице — НАСТОЯЩИЙ блок разбора отчёта Bambu из server.py: уведомление не пропадает при
RUNNING/FINISH и снимается по hms=[]; Klipper/FlashForge — по исходнику; интерфейс — по исходнику
и в браузере (стенд: пульт показывает текст из таблицы и сообщение прошивки, консоль чистая).

БЕЗОПАСНОСТЬ. Сеть не используется (загрузчик подставной), server.py не импортируется целиком,
папка данных владельца не трогается (временная папка).

Запуск: python tools/test_printer_messages_all_brands.py   (0 = все проверки пройдены)
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)
from app import bambu_hms_texts as T  # noqa: E402
from app import printer_health_policy as H  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (str(detail)[:300],)) if detail else ""))


SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
SRC_LINES = SRC.splitlines()
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()

# ── A. чистый разбор официальной таблицы ─────────────────────────────────────────────────────
print("--- A. таблица производителя: разбор, кеш, загрузка без сети ---")
#  Образец ТОГО ЖЕ ВИДА, что настоящий ответ e.bambulab.com/query.php (снят 15.09.2026):
#  data.device_hms.<lang>[{ecode: 16 HEX, intro}], data.device_error.<lang>[{ecode: 8 HEX, intro}].
def payload(lang):
    hms = {"ru": [{"ecode": "0C00010000010004", "intro": "Линза микро-лидара, возможно, загрязнена. Очистите линзу."},
                  {"ecode": "0700200000030002", "intro": "Филамент в слоте 1 AMS A закончился, и произошло автоматическое переключение на слот с таким же филаментом."},
                  {"ecode": "1880200000020058", "intro": "RFID-метка в AMS-HT A не может быть распознана."},
                  {"ecode": "0C00010000010004", "intro": "ПОВТОР — не должен заменить первый"},
                  {"ecode": "мусор", "intro": "без кода"}, {"ecode": "0300010000010001", "intro": "   "}, "не запись"],
           "en": [{"ecode": "0C00010000010004", "intro": "Micro Lidar lens seems to be dirty.  Please clean the lens."},
                  {"ecode": "0700200000030002", "intro": "AMS A Slot 1 filament has run out and automatically switched to the slot with the same filament."},
                  {"ecode": "1880200000020058", "intro": "The RFID-tag on AMS-HT A cannot be identified."}]}
    err = {"ru": [{"ecode": "0300400C", "intro": "Задача отменена."}, {"ecode": "05004004", "intro": "Устройство занято и не может запустить новую задачу."}],
           "en": [{"ecode": "0300400C", "intro": "The task was canceled."}, {"ecode": "05004004", "intro": "Device is busy and cannot start new task."}]}
    return {"result": 0, "ver": 202609140937, "data": {"device_hms": {"ver": 202609140937, lang: hms[lang]},
                                                       "device_error": {"ver": 202609140937, lang: err[lang]}}}


en = T.parse_payload(payload("en"), "en")
ru = T.parse_payload(payload("ru"), "ru")
check("A1. разбор: коды и тексты обоих разделов; повтор кода, мусор и пустой текст пропущены",
      set(en["hms"]) == {"0C00010000010004", "0700200000030002", "1880200000020058"} and len(en["error"]) == 2
      and ru["hms"]["0C00010000010004"].startswith("Линза микро-лидара") and en["ver"] == "202609140937")
check("A2. лишние пробелы в тексте схлопнуты (так печатает экран)",
      en["hms"]["0C00010000010004"] == "Micro Lidar lens seems to be dirty. Please clean the lens.")
check("A3. чужая форма ответа -> пустые словари, без исключений",
      T.parse_payload(None, "en") == {"hms": {}, "error": {}, "ver": ""}
      and T.parse_payload({"data": "x"}, "en")["hms"] == {} and T.parse_payload({"data": {"device_hms": []}}, "en")["hms"] == {})
check("A4. ключ таблицы из печатного кода: дефисы и регистр не важны",
      T.hms_key("0c00-0100-0001-0004") == "0C00010000010004" and T.hms_key("0C00-0100") == ""
      and T.error_key("0300-400c") == "0300400C" and T.error_key("0300400C1") == "")

T._reset_for_tests()
tmp = tempfile.mkdtemp(prefix="fm_hmstext_")
check("A5. пустая таблица: текста нет, обновление нужно",
      T.hms_text("0C00-0100-0001-0004") is None and T.needs_refresh() is True)
calls = []
def fake_fetch(lang):
    calls.append(lang)
    return T.parse_payload(payload(lang), lang)
check("A6. загрузка через подставной загрузчик (сети нет): оба языка, кеш записан",
      T.refresh(tmp, fetcher=fake_fetch, now=1_000_000.0) is True and sorted(calls) == ["en", "ru"]
      and os.path.isfile(T.cache_path(tmp)) and not os.path.exists(T.cache_path(tmp) + ".tmp"))
check("A7. поиск по ПЕЧАТНОМУ коду с фото владельца — оба языка",
      T.hms_text("0C00-0100-0001-0004") == {"ru": "Линза микро-лидара, возможно, загрязнена. Очистите линзу.",
                                             "en": "Micro Lidar lens seems to be dirty. Please clean the lens."})
check("A8. текст ошибки печати по коду 'XXXX-XXXX'",
      (T.error_text("0300-400C") or {}).get("ru") == "Задача отменена." and T.error_text("FFFF-FFFF") is None)
check("A9. срок: свежая таблица обновления не требует, недельная — требует",
      T.needs_refresh(now=1_000_000.0 + 3600) is False and T.needs_refresh(now=1_000_000.0 + 8 * 86400) is True)
T._reset_for_tests()
check("A10. кеш читается обратно из папки данных со временем загрузки",
      T.load_cache(tmp) is True and T.status()["fetched_at"] == 1_000_000.0 and T.counts()["ru"]["hms"] == 3)
def broken_fetch(lang):
    if lang == "ru":
        raise OSError("no network")
    return T.parse_payload(payload(lang), lang)
check("A11. сбой сети при обновлении — прежняя таблица остаётся целиком (частичную не принимаем)",
      T.refresh(tmp, fetcher=broken_fetch) is False and T.counts()["ru"]["hms"] == 3 and T.counts()["en"]["hms"] == 3)
check("A12. пустой ответ сайта — тоже не принимается",
      T.refresh(tmp, fetcher=lambda lang: {"hms": {}, "error": {}}) is False and T.counts()["en"]["hms"] == 3)
check("A13. словарь для модулей (снимком): печатные коды с дефисами -> тексты",
      T.known_hms_dict().get("1880-2000-0002-0058", {}).get("en") == "The RFID-tag on AMS-HT A cannot be identified.")
check("A14. изолированному экземпляру фоновая загрузка не создаётся",
      T.start_background(tmp, enabled=False) is None)
check("A15. кеш в папке данных не читается — не исключение, а «нет таблицы»",
      T.load_cache(os.path.join(tmp, "нет такой папки")) is False)

# ── B. политика здоровья: тексты в записях ───────────────────────────────────────────────────
print("--- B. записи уведомлений с текстом ---")
H.HMS_TEXT_LOOKUP, H.ERROR_TEXT_LOOKUP = T.hms_text, T.error_text
recs = H.hms_with_texts(H.hms_records([{"attr": 0x0C000100, "code": 0x00010004}, {"attr": 0x18802000, "code": 0x00020058},
                                       {"attr": 0x07002000, "code": 0x00010099}]))
check("B1. ФОТО ВЛАДЕЛЬЦА: код, узел, важность И текст с русским переводом",
      recs[0]["code"] == "0C00-0100-0001-0004" and recs[0]["module"] == "xcam" and recs[0]["severity"] == "fatal"
      and recs[0]["text"]["ru"].startswith("Линза микро-лидара"))
check("B2. AMS-HT (узел 0x18) распознан по официальной таблице",
      recs[1]["module"] == "amsht" and recs[1]["text"]["en"].startswith("The RFID-tag on AMS-HT A"))
check("B3. неизвестный таблице код — без выдуманного текста, но с кодом, узлом и важностью",
      "text" not in recs[2] and recs[2]["code"] == "0700-2000-0001-0099" and recs[2]["module"] == "ams")
H.HMS_TEXT_LOOKUP = None
check("B4. таблицы нет — работают две встроенные записи (как до 15.09.2026)",
      (H.hms_text_for("0C00-0100-0001-0004") or {}).get("ru", "").startswith("Загрязнилась линза")
      and H.hms_text_for("1880-2000-0002-0058") is None)
def boom(code):
    raise RuntimeError("boom")
H.HMS_TEXT_LOOKUP = boom
check("B5. сломанный поиск не роняет разбор отчёта (fail-open)", H.hms_with_texts(H.hms_records([{"attr": 0x0C000100, "code": 0x00010004}]))[0]["code"] == "0C00-0100-0001-0004")
H.HMS_TEXT_LOOKUP, H.ERROR_TEXT_LOOKUP = T.hms_text, T.error_text
check("B6. текст ошибки печати по коду для красной полосы",
      (H.error_text_for("0300-400C") or {}).get("en") == "The task was canceled." and H.error_text_for(None) is None)

# ── C. сервер: НАСТОЯЩИЙ блок разбора отчёта Bambu ───────────────────────────────────────────
print("--- C. сервер Bambu: уведомления не пропадают во время печати ---")
def _extract_func(name):
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SRC, node)
    raise AssertionError("не найдена функция %r" % name)

def _extract_block():
    start = end = None
    for i, ln in enumerate(SRC_LINES):
        if start is None and '_pe = int(d.get("print_error"' in ln:
            start = i
        if start is not None and "if (pid in _user_stopped or pid in _cancel_latch) and st in" in ln:
            end = i + 1
            break
    assert start is not None and end is not None and 'st = "IDLE"' in SRC_LINES[end]
    return textwrap.dedent("\n".join(SRC_LINES[start:end + 1]))

NS = {}
for fn in ("_norm_bambu_error_code", "_bambu_hms_codes", "_bambu_hms_list"):
    exec(_extract_func(fn), NS)   # noqa: S102 — свой исходник
NS.update({"_health": H, "time": __import__("time"), "_bstart": __import__("app.bambu_start_policy", fromlist=["x"]),
           "log": types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None),
           "_CANCEL_RECENT_ACTIVE_S": 120.0, "_user_stopped": {}, "_cancel_latch": {}, "_last_active_ts": {}})
BLOCK = compile(_extract_block(), "<on_message-block>", "exec")
PID = "h2d_test"
_ps = {}
def feed(report):
    prev = _ps.get(PID, {})
    st = report.get("gcode_state", prev.get("status", "IDLE"))
    NS.update({"d": report, "prev": prev, "st": st, "pid": PID})
    exec(BLOCK, NS)   # noqa: S102 — ФАКТИЧЕСКИЙ блок on_message
    _ps[PID] = {"status": NS["st"], "status_raw": NS["_st_raw"], "hms": NS["_hms_list"], "hms_codes": NS["_hms_codes"],
                "hms_n": NS["_hmsn"], "print_error": NS["_pe"], "mc_err": NS["_mce"], "error_code": NS["_ecode"],
                "device_error": NS["_dev_err"]}
    return _ps[PID]

LIDAR = {"attr": 0x0C000100, "code": 0x00010004}
s1 = feed({"gcode_state": "RUNNING", "print_error": 0, "hms": [LIDAR]})
check("C1. СЦЕНАРИЙ С ФОТО: уведомление пришло ВО ВРЕМЯ ПЕЧАТИ — оно в состоянии принтера, с текстом",
      [h["code"] for h in s1["hms"]] == ["0C00-0100-0001-0004"] and s1["hms"][0].get("text", {}).get("ru", "").startswith("Линза"))
s2 = feed({"gcode_state": "RUNNING", "mc_percent": 41})
check("C2. частичный отчёт печати без поля hms — уведомление держится", [h["code"] for h in s2["hms"]] == ["0C00-0100-0001-0004"])
check("C3. коды старта печати при RUNNING по-прежнему обнуляются (классификация отмены не тронута)",
      s2["hms_codes"] == [] and s2["print_error"] == 0 and s2["error_code"] is None and s2["hms_n"] == 0)
s3 = feed({"gcode_state": "FINISH", "hms": [LIDAR]})
check("C4. печать завершилась (FINISH), принтер всё ещё показывает уведомление — оно на месте",
      [h["code"] for h in s3["hms"]] == ["0C00-0100-0001-0004"])
s4 = feed({"gcode_state": "IDLE", "hms": []})
check("C5. принтер снял уведомление (hms=[]) — список пуст", s4["hms"] == [])
s5 = feed({"gcode_state": "RUNNING", "hms": [{"attr": 0x07002000, "code": 0x00030002}, LIDAR]})
check("C6. два уведомления во время печати — оба, в порядке принтера",
      [h["code"] for h in s5["hms"]] == ["0700-2000-0003-0002", "0C00-0100-0001-0004"])
check("C7. в исходнике: обнуление при RUNNING/FINISH больше не касается списка уведомлений",
      '_pe = 0; _mce = "0"; _ecode = None; _hms_codes = []; _hmsn = 0\n' in SRC
      and '_hmsn = 0; _hms_list = []' not in SRC)
check("C8. текст ошибки печати (print_error) уходит в браузер рядом с кодом",
      '"device_error_text": _health.error_text_for(_dev_err)' in SRC)
check("C9. таблица: читается из папки данных до загрузки модулей, обновляется в фоне после старта, изолированному экземпляру наружу нельзя",
      "_hms_texts.load_cache(DATA_DIR)" in SRC and SRC.index("_hms_texts.load_cache(DATA_DIR)") < SRC.index("def _load_modules():")
      and "_hms_texts.start_background(DATA_DIR, enabled=not (_E2E is not None and _E2E.disable_update_check)" in SRC
      and "_health.HMS_TEXT_LOOKUP = _hms_texts.hms_text" in SRC)
check("C10. модуль таблицы не ходит в сеть при импорте и не пишет в папку программы",
      "urlopen" not in io.open(os.path.join(REPO, "app", "bambu_hms_texts.py"), encoding="utf-8").read().split("def fetch_lang")[0]
      and "BASE_DIR" not in io.open(os.path.join(REPO, "app", "bambu_hms_texts.py"), encoding="utf-8").read())

# ── D. Klipper / Creality и FlashForge ───────────────────────────────────────────────────────
print("--- D. другие марки ---")
_k = SRC[SRC.index("async def run_klipper("):SRC.index("# ── Alpha 2.765: HTTP к FlashForge")]
check("D1. Klipper/Creality: «прошивка запускается» и сообщение печати идут в блок сообщений, текст — от прошивки",
      'if whs == "startup":' in _k and '"module": "firmware", "text": {"ru": _kst, "en": _kst}' in _k
      and '_kps = " ".join(str(ps.get("message", "") or "").split())[:240]' in _k and '"hms": _kmsgs,' in _k)
check("D2. Klipper: остановка/ошибка прошивки остаётся красной полосой и в сообщения не дублируется",
      'if _kps and whs not in ("shutdown", "error") and ks != "error":' in _k and 'ns = "FAILED"   # прошивка остановлена' in _k)
_f = SRC[SRC.index("async def run_flashforge("):SRC.index("def _flashforge_control(")]
check("D3. FlashForge: код ошибки errorCode из /detail попадает в состояние принтера и в сообщения",
      '_ffcode = str(det.get("errorCode", "") or "").strip()' in _f and '"err_code": _ffcode, "hms": _ffmsgs' in _f
      and '_ffmsgs = [{"code": _ffcode, "severity": "unknown", "module": "printer"}] if _ffcode else []' in _f)
check("D4. FlashForge: нулевой код — не ошибка", 'if _ffcode in ("0", "00", "0000"):' in _f)

# ── E. интерфейс ─────────────────────────────────────────────────────────────────────────────
print("--- E. интерфейс ---")
check("E1. текст берётся из записи (h.text по языку), встроенная таблица — запасной вариант",
      "const st = h && h.text;" in APPJS and "return st[L] || st.en || st.ru;" in APPJS and "const t = KNOWN_HMS_TEXT[(h && h.code) || ''];" in APPJS)
check("E2. узлы: AMS-HT, прошивка, принтер — переведены", "amsht: 'AMS-HT'" in APPJS and "firmware: ru ? 'прошивка' : 'firmware'" in APPJS
      and "printer: ru ? 'принтер' : 'printer'" in APPJS)
check("E3. красная полоса Bambu показывает текст ошибки из таблицы вместе с кодом; без текста — код, как раньше",
      "_devErrText(s, L) + ' [' + code + ']'" in APPJS and "((L === 'ru' ? 'Код: ' : 'Code: ') + code)" in APPJS)
check("E4. красная полоса FlashForge называет код с экрана", "' Код на экране: '" in APPJS and "s.err_code" in APPJS)
check("E5. пульт: сообщение без кода (прошивка) не показывает пустой код; ключ строки не зависит от кода",
      '<template v-if="h.code"> · {{ h.code }}</template>' in HTML and ':key="hi + \':\' + (h.code || \'\')"' in HTML)
check("E6. «Что нового» говорит словами пользователя: видны во время печати, тексты из таблицы Bambu Lab",
      "сообщения с экрана принтера видны и во время печати" in SRC and "официальной таблицы Bambu Lab" in SRC)

# ── F. в браузере ────────────────────────────────────────────────────────────────────────────
print("--- F. в браузере (стенд UI 3.0) ---")
import _fm_ui_stage as stage  # noqa: E402
PR = [{"id": "b1", "name": "H2D_01", "type": "bambu", "model": "Bambu Lab H2D", "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""},
      {"id": "k1", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus", "ip": "10.0.0.12", "port": 7125, "serial": ""}]
JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    setUiLang('ru');
    setTimeout(function(){
      out.badges = qa('.printer-card').map(function(c){ var b = c.querySelector('.pc-hms'); return (c.textContent.match(/H2D_01|K2-02/) || [''])[0] + ':' + (b ? b.textContent.trim() : '-'); });
      var card = qa('.printer-card').filter(function(c){ return /H2D_01/.test(c.textContent); })[0]; if (card) click(card);
      setTimeout(function(){
        var blk = q('.ui3-pp-hms');
        out.h2d = blk ? (blk.innerText || '').replace(/\s+/g, ' ').trim() : null;
        var card2 = qa('.printer-card').filter(function(c){ return /K2-02/.test(c.textContent); })[0]; if (card2) click(card2);
        setTimeout(function(){
          var blk2 = q('.ui3-pp-hms');
          out.k2 = blk2 ? (blk2.innerText || '').replace(/\s+/g, ' ').trim() : null;
          res(dump(out));
        }, 1200);
      }, 1500);
    }, 800);
  }, 1500);
});
"""
if not stage.engine_ready():
    check("F0. браузерный движок доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/staging": [], "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                   "/api/farm-settings": {"ok": True, "settings": {}}, "/api/modules": {"modules": [], "restart_needed": False},
                   "/api/send-jobs": {"jobs": [], "reserved_printer_ids": []}})
    stage.set_live({"b1": {"status": "RUNNING", "percent": 37, "file_name": "bracket_v2", "nozzle_count": 2, "nozzle_temp": 220, "nozzle_target": 220,
                           "bed_temp": 60, "bed_target": 60, "remaining_time": 3600, "hms": [
                               {"code": "0C00-0100-0001-0004", "severity": "fatal", "module": "xcam",
                                "text": {"ru": "Линза микро-лидара, возможно, загрязнена. Очистите линзу.", "en": "Micro Lidar lens seems to be dirty. Please clean the lens."}},
                               {"code": "0700-2000-0001-0099", "severity": "common", "module": "ams"}]},
                    "k1": {"status": "IDLE", "percent": 0, "nozzle_count": 1, "nozzle_temp": 25, "bed_temp": 25,
                           "hms": [{"code": "", "severity": "info", "module": "firmware",
                                    "text": {"ru": "Printer is not ready The klippy host software is attempting to connect.", "en": "Printer is not ready The klippy host software is attempting to connect."}}]}})
    R = stage.run(JS, window_size=(1600, 900), settle_ms=2500, path="/ui3")
    stage.set_api(None); stage.set_live(None); stage.stop()
    if not R:
        check("F1. стенд поднялся", False, str(stage.last_diag())[:200])
    else:
        d = R.pop("__diag", {}) or {}
        errs = (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])
        check("F1. значок сообщений на обеих ячейках: у H2D два, у K2 одно",
              "H2D_01:2" in (R.get("badges") or []) and "K2-02:1" in (R.get("badges") or []), R.get("badges"))
        h = R.get("h2d") or ""
        check("F2. пульт H2D ВО ВРЕМЯ ПЕЧАТИ: текст с фото владельца по-русски, код рядом; неизвестный код — кодом и узлом",
              "Линза микро-лидара, возможно, загрязнена" in h and "0C00-0100-0001-0004" in h and "камера и лидар" in h
              and "Уведомление принтера" in h and "0700-2000-0001-0099" in h and "AMS" in h, h[:300])
        check("F3. сноска про незнакомые коды показана только когда такой код есть", "Незнакомые коды" in h, h[:200])
        k = R.get("k2") or ""
        check("F4. пульт K2 (Klipper): сообщение прошивки слово в слово, узел «прошивка», без пустого кода",
              "Printer is not ready" in k and "прошивка" in k and "Незнакомые коды" not in k and "· ·" not in k, k[:300])
        check("F5. консоль чистая", not errs, errs[:2])

shutil.rmtree(tmp, ignore_errors=True)
print()
print("=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
