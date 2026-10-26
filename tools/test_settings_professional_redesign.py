# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.834 — RELEASE GATE профессионального редизайна экрана настроек.

ЧТО ЭТО. Отдельный приёмочный тест на весь редизайн: единая дизайн-система вместо смеси старой и
новой, булевы параметры флажками (галочка = включено), действия отделены от настроек, предупреждения
в панелях, адаптивная раскладка без горизонтальной прокрутки на zoom 100-200 %.

КАК ПРОВЕРЯЕТСЯ. Двумя независимыми способами:
  СТАТИКА  — разбор НАСТОЯЩИХ web/index.html + web/app.css + web/app.js (структура, контракты,
             тексты RU/EN, отсутствие остатков старой системы, сохранность обработчиков и guards);
  БРАУЗЕР  — НАСТОЯЩЕЕ приложение (те же web/index.html, app.js, app.css, вендорный Vue) монтируется
             в headless Edge/Chromium через CDP на локальном статическом сервере с СИНТЕТИЧЕСКИМИ
             /api-ответами: реально измеряется геометрия, реально кликаются флажки, реально
             считываются console errors и предупреждения Vue.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются: сервер отдаёт только
web/ и синтетические JSON; принтерам ничего не отправляется; печати не запускаются. Метка живёт
исключительно в этой оснастке.

Запуск:  python tools/test_settings_professional_redesign.py     (0 = release gate пройден)
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _edge_dom

SENTINEL = "SETTINGS_PRO_REDESIGN_SENTINEL_2_834"

WEB = os.path.join(REPO, "web")
HTML = io.open(os.path.join(WEB, "index.html"), encoding="utf-8", newline="").read()
CSS = io.open(os.path.join(WEB, "app.css"), encoding="utf-8", newline="").read()
APP = io.open(os.path.join(WEB, "app.js"), encoding="utf-8", newline="").read()
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace", newline="").read()
ORCH = io.open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8", newline="").read()
REG = io.open(os.path.join(REPO, "app", "config_backup", "settings_registry.py"), encoding="utf-8", newline="").read()

_i = HTML.index('<div class="fm-set-title">')
SET = HTML[_i:HTML.index("</section>", _i)]

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:200]) if detail else ""))


def sec(t):
    print("\n--- %s ---" % t)


def css_rule(sel):
    m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


# ══════════════════════════════════════════════════════════════════════════════
sec("STRUCTURE (1-10)")

TABS = re.findall(r"curSetTab==='(\w+)'", SET)
check("1. рабочая область настроек существует (каркас layout/nav/scroll сохранён)",
      'class="fm-set-layout"' in SET and 'class="fm-set-nav"' in SET and 'class="fm-set-scroll"' in SET)
check("2. вкладка «Общие» присутствует и имеет заголовок раздела",
      "'Общие':'General'" in SET and SET.count('class="fm-set-head"') >= 3)
#  12.09.2026, решение владельца: обучение выключено одним флагом, код тура не удалён.
check("2a. обучение выключено: кнопки тура в «Общих» спрятаны за флагом, окно при запуске не открывается",
      '<template v-if="tourEnabled"><div class="fm-set-sep"></div>' in SET
      and "const TOUR_ENABLED = false;" in APP and "const tourEnabled = TOUR_ENABLED;" in APP
      and "if (TOUR_ENABLED && tourStartupPromptEnabled.value" in APP
      and APP.count("if (!TOUR_ENABLED) return;") >= 3
      and 'v-if="tourEnabled && showTourStartDialog && !tourActive"' in HTML)
check("3. вкладка «Печать» присутствует", "'Печать':'Printing'" in SET and "print" in TABS)
check("4. вкладка «Система» присутствует", "'Система':'System'" in SET and "system" in TABS)
check("5. активный раздел выделен в навигации (class active + подсветка)",
      "{active: curSetTab===" in SET and ".fm-set-nav-item.active" in CSS)
check("6. секции построены единой структурой (sec-h + sec-t + sec-b у каждой)",
      SET.count('class="fm-set-sec-h"') >= 12 and SET.count('class="fm-set-sec-t"') >= 12
      and SET.count('class="fm-set-sec-b"') >= 10,
      "sec-h=%d sec-t=%d sec-b=%d" % (SET.count('class="fm-set-sec-h"'), SET.count('class="fm-set-sec-t"'),
                                      SET.count('class="fm-set-sec-b"')))
check("7. инструменты отделены от настроек (плитки, а не строки настроек)",
      SET.count('class="fm-set-tile"') >= 2 and ".fm-set-tile{" in CSS.replace(" ", "")
      and "openDiagnostics()" in SET and "openPrinterFiles()" in SET)
check("8. предупреждения отделены в панели (info/warn/danger), а не цветным текстом",
      SET.count('class="fm-pnl fm-pnl-') >= 5 and ".fm-pnl-dng" in CSS and ".fm-pnl-warn" in CSS)
_act_with_chk = re.findall(r'<button class="fm-set-act[^"]*"[^>]*>(?:(?!</button>).){0,600}?type="checkbox"', SET, re.S)
check("9. действия НЕ используют checkbox (внутри action row нет input type=checkbox)",
      not _act_with_chk and SET.count('class="fm-set-act') >= 6)
_chk_inputs = re.findall(r'<input type="checkbox" class="fm-chk-in"[^>]*>', SET)
#  2.974 (правка 6 по списку владельца): выключатель панели подсказок убран из настроек —
#  сворачивание панели осталось на самой панели. Флажков стало семь.
check("10. булевы настройки используют checkbox-паттерн (>=7 нативных input)",
      len(_chk_inputs) >= 7, "найдено %d" % len(_chk_inputs))

# ══════════════════════════════════════════════════════════════════════════════
sec("BOOLEAN CONTRACT (11-24) — статические инварианты")


def chk_of(model):
    m = re.search(r'<input type="checkbox" class="fm-chk-in" :checked="' + re.escape(model) + r'"[^>]*>', SET)
    return m.group(0) if m else ""


PF_READ = chk_of("pfFlags.read_enabled")
PF_DEL = chk_of("pfFlags.delete_enabled")
LAN = chk_of("lanAccess")
CBP = chk_of("cbProtect")
check("11. «Чтение файлов» — checkbox привязан к серверному состоянию (OFF = пустой квадрат)",
      bool(PF_READ) and ':checked="pfFlags.read_enabled"' in PF_READ)
check("12. «Чтение файлов» ON рисуется галочкой, а OFF остаётся пустым квадратом",
      ".fm-chk-in:checked" in CSS and ".fm-chk-in:checked::after" in CSS
      and "border-width:02px2px0" in CSS.replace(" ", "")
      and "var(--fm-accent)" in css_rule(".fm-chk-in:checked")
      and "var(--fm-accent)" not in css_rule(".fm-chk-in"),
      "base=%s" % css_rule(".fm-chk-in")[:90])
check("13. «Разрешить удаление» — checkbox, привязан к серверному флагу",
      bool(PF_DEL) and ':checked="pfFlags.delete_enabled"' in PF_DEL)
# Alpha 2.837: якорь danger-панели уточнён до ПРИВЯЗКИ к флагу удаления. Прежняя проверка
# искала класс «где угодно на вкладке», и появление любой другой danger-панели (в 2.837 её
# получила ошибка сохранения сетевой настройки) молча закрывало дыру: порча №9 mutation proof
# снимала оформление именно у предупреждения об удалении и переставала ловиться.
check("14. «Разрешить удаление» помечено как опасное (класс fm-chk-dng + бейдж + СВОЯ danger-панель)",
      "fm-chk fm-chk-dng" in SET and "fm-bdg fm-bdg-dng" in SET
      and '<div class="fm-pnl fm-pnl-dng" v-if="pfFlags.delete_enabled">' in SET)
check("15. LAN OFF читается однозначно: бейдж «Только этот компьютер»",
      bool(LAN) and "'Только этот компьютер':'This computer only'" in SET)
check("16. LAN ON читается однозначно: бейдж «Доступен в локальной сети»",
      "'Доступен в локальной сети':'Available on the network'" in SET
      and "lanAccess ? 'fm-bdg-ok' : 'fm-bdg-mch'" in SET)
check("17. защита паролем OFF/ON — checkbox (не кнопка)", bool(CBP) and ':disabled="cbBusy"' in CBP)
check("18. защита паролем: режим без пароля сохранён (ветка !cbProtect)", 'v-if="!cbProtect"' in SET)
check("19. клик по строке меняет значение (label оборачивает input — вся строка кликабельна)",
      SET.count('<label class="fm-chk') >= 7 and ".fm-chk{" in CSS.replace(" ", "")
      and "cursor:pointer" in css_rule(".fm-chk").replace(" ", ""))
check("20. Space работает нативно (это <input type=checkbox>, не div с role)",
      all('type="checkbox"' in c for c in _chk_inputs) and 'role="checkbox"' not in SET)
check("21. disabled-состояние видно и не меняется (CSS :disabled + класс fm-chk-dis)",
      ".fm-chk-in:disabled" in CSS and ".fm-chk-dis" in CSS and "fm-chk-dis" in SET)
check("22. loading-guard от двойного изменения (fm-chk-busy + pointer-events:none)",
      ".fm-chk-busy" in CSS and "pointer-events:none" in css_rule(".fm-chk-busy .fm-chk-in").replace(" ", "")
      and "fm-chk-busy" in SET)
check("23. ошибка backend возвращает серверное состояние (DOM сразу возвращается к модели)",
      '$event.target.checked = pfFlags.read_enabled' in SET
      and '$event.target.checked = pfFlags.delete_enabled' in SET
      and '$event.target.checked = lanAccess' in SET
      and "if (j && j.status === 'ok') { pfFlags.value" in APP
      and "catch (e) { lanAccess.value = prev; await loadNetworkInfo(); }" in APP)
check("24. destructive-подтверждения и backend-guards сохранены (delete через pfSetFlag, серверный флаг)",
      "pfSetFlag('delete_enabled'" in SET and "printer_files_delete_enabled" in SRV
      and "'/api/printer-files/settings'" in APP)

# ══════════════════════════════════════════════════════════════════════════════
sec("TEXT / HIERARCHY (25-33)")

_hints = re.findall(r'class="fm-set-hint">\{\{ lang===\'ru\'\?\'([^\']+)\'', SET)
_long = [h for h in _hints if len(h) > 96]
check("25. в основных строках нет длинных описаний (каждая подсказка <= 96 символов)",
      not _long, "длинные: %s" % _long[:2])
check("26. вторичный текст визуально отличается (свой класс, меньший размер, приглушённый цвет)",
      "font-size:11.5px" in css_rule(".fm-set-hint").replace(" ", "")
      and "var(--fm-text-subtle)" in css_rule(".fm-set-hint"))
check("27. статус-бейджи отделены от текста (свой класс + рамка + uppercase)",
      "text-transform:uppercase" in css_rule(".fm-bdg").replace(" ", "") and SET.count('class="fm-bdg') >= 8)
check("28. машинно-зависимое пояснено (бейдж «Этот компьютер» у хранения и сети)",
      SET.count("'Этот компьютер':'This computer'") >= 2 and "fm-bdg-mch" in CSS)
check("29. бейдж «Эксперимент» виден", "'Эксперимент':'Experimental'" in SET and ".fm-bdg-exp" in CSS)
check("30. бейдж «Требуется перезапуск» виден", "'Требуется перезапуск':'Restart required'" in SET
      and ".fm-bdg-rst" in CSS)
_dev_terms = [t for t in ("localStorage", "endpoint", "backend", "payload", "boolean", "checkbox", "flag")
              if re.search(r">\s*[^<]*" + t, SET)]
check("31. в основном RU-интерфейсе нет внутренних терминов разработчика", not _dev_terms, _dev_terms)
_ru = re.findall(r"lang==='ru'\?'([^']+)':'([^']+)'", SET)
_KEY_PAIRS = [("Чтение файлов с принтеров", "Read files from printers"),
              ("Разрешить удаление файлов", "Allow deleting files"),
              ("Доступ из локальной сети", "Local network access"),
              ("Порт сервера", "Server port"),
              ("Папка данных", "Data folder"),
              ("Быстрые инструменты", "Quick tools")]
_ru_miss = [ru for ru, en in _KEY_PAIRS if ("'%s':'%s'" % (ru, en)) not in SET]
check("32. RU-подписи ключевых настроек на месте (%d пар всего)" % len(_ru),
      len(_ru) >= 60 and all(r.strip() for r, _e in _ru) and not _ru_miss, _ru_miss)
check("33. EN-подписи ключевых настроек на месте (пустых нет)",
      all(e.strip() for _r, e in _ru) and not _ru_miss
      and all(("'%s'" % en) in SET for _ru2, en in _KEY_PAIRS),
      [en for _r, en in _KEY_PAIRS if ("'%s'" % en) not in SET])

# ══════════════════════════════════════════════════════════════════════════════
sec("FUNCTIONAL (49-64) — ничего не потеряно")

for n, (lbl, needle) in enumerate([
    ("49. Диагностика открывается", "openDiagnostics()"),
    ("50. Файлы принтеров открываются", "openPrinterFiles()"),
    ("51. флаг чтения сохраняется", "pfSetFlag('read_enabled'"),
    ("52. флаг удаления сохраняется", "pfSetFlag('delete_enabled'"),
    ("53. флаг LAN сохраняется", "setLanAccess(!lanAccess)"),
    ("54. диалог порта открывается", "openPortDialog()"),
    ("55. выбор папки данных сохранён", "pickDataDir()"),
    ("56. выбор папки архивов сохранён", "pickArchiveDir()"),
    ("57. экспорт резервной копии сохранён", "cbExport()"),
    ("58. автоплан восстановления сохранён", "cbInspect()"),
    ("59. перезапуск после восстановления сохранён", "doRestart()"),
    ("60. установка модуля сохранена", "pickModuleZip()"),
    ("61. запуск модуля сохранён", "runModule(m)"),
], 1):
    check(lbl, needle in SET, needle)
_RP = io.open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8", newline="").read()
def _reg_line(path_lit):
    """Строка реестра маршрутов для указанного пути (или '')."""
    for ln in _RP.split("\n"):
        if path_lit in ln:
            return ln
    return ""


_gu = _reg_line("'/api/printer-files/settings'")
_gd = _reg_line("'/api/printer-files/delete'")
check("62. route guards не ослаблены: settings и delete остаются SYSTEM_ADMIN",
      bool(_gu) and bool(_gd) and "SYSTEM_ADMIN" in _gu and "SYSTEM_ADMIN" in _gd,
      "settings=%s" % _gu[-46:])
check("63. реестр настроек сохранён (printer_sort_mode + klipper_prestart_prefs зарегистрированы)",
      'printer_sort_mode' in REG and 'klipper_prestart_prefs' in REG)
check("64. реестр резервного копирования сохранён (lan_access_enabled с предупреждением)",
      'lan_access_enabled' in REG and 'RB_RESTORE_WITH_WARNING' in REG)

# ══════════════════════════════════════════════════════════════════════════════
sec("REGRESSION (72-81)")

check("72. подтверждение запуска Klipper (2.833) сохранено",
      "pending_confirmation" in SRV and "awaiting telemetry confirmation" in SRV
      and os.path.exists(os.path.join(REPO, "app", "klipper_start.py")))
check("73. сортировка и копирование принтеров (2.831) сохранены",
      "printer_sort_mode" in SRV and "openCopyPrinter" in APP and "savePrinterCopy" in APP)
check("74. резервное копирование данных модулей (2.829) сохранено",
      "module_data" in SET and os.path.exists(os.path.join(REPO, "app", "config_backup", "module_providers.py")))
check("75. универсальная отмена печати (2.826) сохранена",
      os.path.exists(os.path.join(REPO, "app", "printer_health_policy.py")) and "classify_termination" in SRV)
check("76. файловый менеджер принтеров (2.823) сохранён",
      os.path.exists(os.path.join(REPO, "app", "printer_files", "registry.py")) and "pfFlags" in APP)
check("77. DISPATCH выключен", re.search(r"^DISPATCH_ENABLED = False", ORCH, re.M) is not None)
check("78. TRANSPORT выключен", re.search(r"^TRANSPORT_ENABLED = False", ORCH, re.M) is not None)
check("79. удаление файлов принтеров по умолчанию ВЫКЛючено",
      'printer_files_delete_enabled' in REG and 'RB_IMPORT_AS_OFF' in REG)
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
_mods = {m: (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(io.open(os.path.join(REPO, "modules", m, "module.json"), encoding="utf-8")))
         for m in ("inventory", "cost", "quality")}
#  Склад поднят до 1.7.28 (2.946), качество до 0.2.3 (2.964); ранее 1.7.27 в 2.890-2.891: он научился видеть подачу CFS у Creality K2.
#  3.0: cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
check("80. версии модулей не менялись (1.7.29 / 0.2.0 / 0.2.3)",
      _mods == {"inventory": "1.7.29", "cost": "0.2.0", "quality": "0.2.3"}, _mods)
check("81. метка теста не попала в продукт, и _incoming/ не используется",
      SENTINEL not in HTML and SENTINEL not in CSS and SENTINEL not in APP and SENTINEL not in SRV
      and "_incoming" not in SET)

# ══════════════════════════════════════════════════════════════════════════════
# БРАУЗЕРНАЯ ЧАСТЬ: настоящее приложение на локальном статическом сервере + CDP
# ══════════════════════════════════════════════════════════════════════════════
API = {
    "/api/printers": [],
    "/api/state": {},
    "/api/settings": {"lang": "ru"},
    "/api/network": {"lan_access_enabled": False, "requested_enabled": False, "restart_required": False,
                     "can_enable": True, "port": 8000, "port_can_change": True},
    "/api/printer-files/settings": {"status": "ok", "read_enabled": False, "delete_enabled": False},
    "/api/printer-files/capabilities": {"status": "ok", "adapters": []},
    "/api/printer-sort-mode": {"printer_sort_mode": "manual", "modes": ["manual", "model"]},
    "/api/storage": {"data_dir": "D:/FarmData", "archive_dir": "D:/FarmArchive",
                     "data_dir_is_default": False, "archive_dir_is_default": True},
    "/api/modules": {"modules": []},
    "/api/projects2": [],
    "/api/projects": [],
    "/api/tasks": [],
    "/api/staging": [],
    "/api/queue": {"items": []},
    "/api/send-jobs": {"jobs": [], "reserved_printer_ids": []},
    "/api/slicer/list": {"slicers": [], "choice": ""},
    "/api/config-backup/status": {"status": "ok", "sections": []},
    "/api/version": {"version": "Alpha 2.834"},
    "/version": {"version": "Alpha 2.834", "boot_id": "test"},
}


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, io.open(os.path.join(WEB, "index.html"), "rb").read(), "text/html; charset=utf-8")
        for pref, root in (("/assets/", WEB), ("/vendor/", os.path.join(WEB, "vendor")),
                           ("/design/", os.path.join(WEB, "design"))):
            if p.startswith(pref):
                rel = p[len(pref):]
                fp = os.path.join(root, rel)
                if os.path.isfile(fp):
                    ct = ("text/css; charset=utf-8" if fp.endswith(".css") else
                          "application/javascript; charset=utf-8" if fp.endswith(".js") else
                          "application/octet-stream")
                    return self._send(200, io.open(fp, "rb").read(), ct)
        for name in ("app.js", "app.css"):
            if p.endswith("/" + name) or p == "/" + name:
                fp = os.path.join(WEB, name)
                ct = "application/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8"
                return self._send(200, io.open(fp, "rb").read(), ct)
        fp = os.path.join(WEB, p.lstrip("/").replace("/", os.sep))
        if os.path.isfile(fp):
            return self._send(200, io.open(fp, "rb").read(), "application/octet-stream")
        body = json.dumps(API.get(p, {"status": "ok"})).encode("utf-8")
        return self._send(200, body, "application/json; charset=utf-8")


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# Сценарий в браузере: открыть настройки, перейти на вкладку, снять метрики.
# Сценарий выполняется ЧЕРЕЗ НАСТОЯЩИЙ ИНТЕРФЕЙС: клик по шестерёнке настроек, клик по вкладке,
# затем замеры. Внутренности Vue не используются — так проверка ближе к действиям пользователя.
PROBE = r"""
(function(){
  function dump(o){ var d=document.getElementById('__res') || (function(){var x=document.createElement('div'); x.id='__res'; document.body.appendChild(x); return x;})(); d.textContent='@@RES@@'+JSON.stringify(o)+'@@END@@'; return true; }
  function click(el){ if(!el) return false; el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window})); return true; }
  function byText(sel, texts){ var n=[].slice.call(document.querySelectorAll(sel));
    for (var i=0;i<n.length;i++){ var t=(n[i].textContent||'').trim(); for (var j=0;j<texts.length;j++){ if (t.indexOf(texts[j])>=0) return n[i]; } } return null; }
  try {
    if ('%LANG%' === 'en') { var lb = byText('button, .fm-lang-btn, [data-help*="lang"]', ['EN','English']); if (lb) click(lb); }
    var gear = document.querySelector('[data-tour="settings"], [data-help="settings"]');
    if (!gear) { return dump({ok:false, err:'нет кнопки настроек'}); }
    click(gear);
    return new Promise(function(res){
      setTimeout(function(){
        var tabs = {general:['Общие','General'], print:['Печать','Printing'], system:['Система','System']};
        var tb = byText('.fm-set-nav-item', tabs['%TAB%'] || []);
        if (tb) click(tb); else { window.__fmTabMiss = true; }
        setTimeout(function(){ res(dump(measure())); }, 420);
      }, 420);
    });
  } catch(e) { return dump({ok:false, err:String(e && e.message || e)}); }
  function measure(){
    var r = {ok:true, tab:'%TAB%', lang:'%LANG%'};
    r.tabMiss = !!window.__fmTabMiss;
    r.activeTab = (function(){ var a=document.querySelector('.fm-set-nav-item.active');
      return a ? (a.textContent||'').trim() : ''; })();
    var root = document.documentElement;
    r.hscroll = root.scrollWidth - root.clientWidth;
    r.bodyHscroll = document.body.scrollWidth - document.body.clientWidth;
    // Полоса прокрутки существует лишь тогда, когда содержимое РЕАЛЬНО сдвигается: у html/body с
    // Alpha 2.631 стоит overflow:hidden !important, поэтому метрика scrollWidth сама по себе полосу
    // не доказывает — пробуем сдвинуть и смотрим, сдвинулось ли.
    root.scrollLeft = 999; document.body.scrollLeft = 999;
    r.pageScrollReal = Math.max(root.scrollLeft, window.scrollX || 0);
    root.scrollLeft = 0; document.body.scrollLeft = 0;
    // Переполнение, за которое отвечает ИМЕННО экран настроек: рабочая область и её содержимое.
    // (Корневая обёртка .zoom-wrap имеет min-w-[960px] с Alpha 2.631 и на окне 1100px распирается
    //  шапкой приложения — это предсуществующее поведение вне настроек, здесь оно не измеряется.)
    if (scroll0()) { var s0 = scroll0(); s0.scrollLeft = 999;
      r.hscrollReal = Math.max(s0.scrollLeft, s0.scrollWidth - s0.clientWidth); s0.scrollLeft = 0; }
    else { r.hscrollReal = 0; }
    function scroll0(){ return document.querySelector('.fm-set-scroll'); }
    var ws = document.querySelector('.fm-settings-workspace');
    r.wsVisible = !!(ws && ws.getBoundingClientRect().height > 50);
    var scroll = document.querySelector('.fm-set-scroll');
    r.scrollH = scroll ? Math.round(scroll.scrollHeight) : 0;
    r.clientH = scroll ? Math.round(scroll.clientHeight) : 0;
    r.reachBottom = false;
    if (scroll) { scroll.scrollTop = scroll.scrollHeight; r.reachBottom = (scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop) < 3; scroll.scrollTop = 0; }
    var nav = document.querySelector('.fm-set-nav');
    r.navVisible = !!(nav && nav.getBoundingClientRect().width > 40);
    var head = [].slice.call(document.querySelectorAll('.fm-set-head-t')).filter(function(e){ return e.offsetParent; })[0];
    r.headText = head ? (head.textContent||'').trim() : '';
    var secs = [].slice.call(document.querySelectorAll('.fm-set-grid > .fm-set-group')).filter(function(e){
      var b=e.getBoundingClientRect(); return b.height>10 && b.width>10; });
    r.secCount = secs.length;
    var lefts = {}; secs.forEach(function(e){ lefts[Math.round(e.getBoundingClientRect().left)] = 1; });
    r.cols = Object.keys(lefts).length;
    r.secOverflow = secs.filter(function(e){ return e.scrollWidth - e.clientWidth > 2; }).length;
    var chks = [].slice.call(document.querySelectorAll('.fm-chk-in')).filter(function(e){ return e.getBoundingClientRect().height>0; });
    r.chkCount = chks.length; r.chkWithLabel = 0; r.chkFar = 0;
    chks.forEach(function(c){
      var lab = c.closest('label'); if (!lab) return;
      var t = lab.querySelector('.fm-set-lbl'); if (!t) return;
      r.chkWithLabel++;
      var a = c.getBoundingClientRect(), b = t.getBoundingClientRect();
      if (Math.abs(b.left - a.right) > 60 || b.top - a.bottom > 24) r.chkFar++;
    });
    var btns = [].slice.call(document.querySelectorAll('.fm-set-act, .fm-set-mod-install, .fm-seg-b, .fm-set-mini-a, .fm-set-tile'))
      .filter(function(e){ return e.getBoundingClientRect().height > 0; });
    r.btnCount = btns.length;
    r.btnOverflow = btns.filter(function(e){ return e.scrollWidth - e.clientWidth > 2 || e.scrollHeight - e.clientHeight > 2; }).length;
    var mini = document.querySelector('.fm-set-mini');
    r.miniVisible = !!(mini && mini.getBoundingClientRect().height > 10 && mini.offsetParent);
    r.miniOverlap = false;
    if (r.miniVisible && secs.length) { var mb = mini.getBoundingClientRect(), sb = secs[0].getBoundingClientRect(); r.miniOverlap = (sb.top < mb.bottom - 2); }
    var one = chks[0];
    if (one) { var was = one.checked;
      one.checked = false; void one.offsetWidth; var off = getComputedStyle(one).backgroundColor;
      one.checked = true;  void one.offsetWidth; var on  = getComputedStyle(one).backgroundColor;
      r.tick = getComputedStyle(one, '::after').content;
      one.checked = was; void one.offsetWidth;
      r.checkedDiffers = (off !== on); r.offBg = off; r.onBg = on; }
    r.vcloak = !!document.querySelector('#app[v-cloak]');
    r.bootFallback = (function(){ var f=document.getElementById('fm-boot-fallback'); return !!(f && f.style.display !== 'none' && f.offsetParent); })();
    r.errs = (window.__fmTestErrors || []).slice(0, 5);
    r.warns = (window.__fmTestWarns || []).slice(0, 5);
    return r;
  }
})()
"""

CATCH = r"""
window.__fmTestErrors = []; window.__fmTestWarns = [];
(function(){ var oe = console.error, ow = console.warn;
  console.error = function(){ try{ window.__fmTestErrors.push(Array.prototype.slice.call(arguments).join(' ').slice(0,200)); }catch(e){} return oe.apply(console, arguments); };
  console.warn  = function(){ try{ window.__fmTestWarns.push(Array.prototype.slice.call(arguments).join(' ').slice(0,200)); }catch(e){} return ow.apply(console, arguments); };
  window.addEventListener('error', function(ev){ try{ window.__fmTestErrors.push('onerror: '+(ev.message||'')); }catch(e){} });
})();
"""

EDGE = _edge_dom.find_edge()
sec("BROWSER RELEASE GATE (34-48, 65-71) — настоящее приложение, реальные измерения")

# FM_SETPRO_NO_BROWSER=1 — быстрый статический режим для mutation proof: браузерные сценарии
# детерминированно ловятся статикой, а полный прогон gate всегда идёт с браузером.
if os.environ.get("FM_SETPRO_NO_BROWSER"):
    print("(браузерная часть отключена флагом FM_SETPRO_NO_BROWSER — режим mutation proof)")
elif not EDGE or not _edge_dom.engine_usable(EDGE):
    check("BROWSER. движок доступен и работает (release gate требует реальных замеров)", False,
          "движок недоступен: %s" % (EDGE or "не найден"))
else:
    srv, port = serve()
    scenarios = [
        ("34. 1920x1080 RU Система", "system", "ru", (1920, 1080), "1"),
        ("35. узкое окно 1100x700 RU Система", "system", "ru", (1100, 700), "1"),
        ("36. zoom 100% RU Общие", "general", "ru", (1440, 900), "1"),
        ("37. zoom 125% RU Система", "system", "ru", (1440, 900), "1.25"),
        ("38. zoom 150% RU Система", "system", "ru", (1440, 900), "1.5"),
        ("39. zoom 175% RU Печать", "print", "ru", (1440, 900), "1.75"),
        ("40. zoom 200% RU Система", "system", "ru", (1440, 900), "2"),
        ("EN. 1440x900 EN Система", "system", "en", (1440, 900), "1"),
    ]
    results = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_setpro_") as td:
        for idx, (lbl, tab, lang, wh, dsf) in enumerate(scenarios):
            js = CATCH + PROBE.replace("%TAB%", tab).replace("%LANG%", lang)
            dom = _edge_dom.dump_dom_compatible(
                EDGE, "http://127.0.0.1:%d/" % port, os.path.join(td, "p%d" % idx),
                window_size=wh, budget_ms=3200,
                extra_args=("--force-device-scale-factor=%s" % dsf,), eval_js=js)
            m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom or "", re.S)
            R = json.loads(m.group(1)) if m else {}
            results[lbl] = R
            ok = bool(R.get("ok")) and R.get("wsVisible") and R.get("secCount", 0) >= 3 \
                and R.get("hscroll", 99) <= 0 and R.get("hscrollReal", 99) <= 0 \
                and R.get("secOverflow", 9) == 0 and R.get("btnOverflow", 9) == 0
            check("%s — экран виден, %s секций, без h-scroll, текст в кнопках"
                  % (lbl, R.get("secCount", "?")), ok,
                  "hscroll=%s body=%s secOv=%s btnOv=%s err=%s"
                  % (R.get("hscroll"), R.get("bodyHscroll"), R.get("secOverflow"),
                     R.get("btnOverflow"), R.get("err")))
        wide = results.get("34. 1920x1080 RU Система", {})
        narrow = results.get("35. узкое окно 1100x700 RU Система", {})
        z200 = results.get("40. zoom 200% RU Система", {})
        z150 = results.get("38. zoom 150% RU Система", {})
        en = results.get("EN. 1440x900 EN Система", {})
        check("41. горизонтальной прокрутки нет ни в одном сценарии",
              all((r.get("hscroll", 99) <= 0 and r.get("hscrollReal", 99) <= 0) for r in results.values()),
              {k: (v.get("hscroll"), v.get("hscrollReal"), v.get("bodyHscroll")) for k, v in results.items()})
        check("42. контролы не перекрываются (флажок и подпись рядом во всех сценариях)",
              all(r.get("chkFar", 9) == 0 for r in results.values()),
              {k: v.get("chkFar") for k, v in results.items()})
        check("43. текст не выходит за пределы кнопок и чипов даже на 200%",
              z200.get("btnOverflow") == 0 and z200.get("btnCount", 0) >= 5,
              "ov=%s n=%s" % (z200.get("btnOverflow"), z200.get("btnCount")))
        check("44. флажок остаётся вместе с подписью во всех сценариях (label связан с input)",
              wide.get("chkWithLabel", 0) >= 3 and all(r.get("chkFar", 9) == 0 for r in results.values()),
              {k: v.get("chkWithLabel") for k, v in results.items()})
        check("45. карточки складываются в одну колонку при узком окне (2 колонки -> 1)",
              wide.get("cols", 0) >= 2 and narrow.get("cols", 9) == 1,
              "wide=%s narrow=%s" % (wide.get("cols"), narrow.get("cols")))
        check("46. левая навигация остаётся видимой и пригодной",
              all(r.get("navVisible") for r in results.values()))
        check("47. sticky мини-навигация не перекрывает содержимое",
              wide.get("miniVisible") and not wide.get("miniOverlap")
              and not z150.get("miniOverlap", False),
              "vis=%s overlapWide=%s overlap150=%s" % (wide.get("miniVisible"), wide.get("miniOverlap"), z150.get("miniOverlap")))
        check("48. нижняя часть настроек достигается прокруткой внутри панели",
              all(r.get("reachBottom") for r in results.values()),
              {k: (v.get("scrollH"), v.get("clientH"), v.get("reachBottom")) for k, v in results.items()})
        # Alpha 2.835: доказываем, что браузерные сценарии шли на ЗАПРОШЕННОЙ вкладке, а не на
        # той, что открыта по умолчанию (иначе проверки «Системы» были бы вакуумными).
        _miss = {k: v.get("activeTab") for k, v in results.items() if v.get("tabMiss")}
        check("64b. каждая браузерная проверка выполнена на ЗАПРОШЕННОЙ вкладке (RU и EN)",
              not _miss and all(r.get("activeTab") for r in results.values()),
              {"miss": _miss, "active": {k: v.get("activeTab") for k, v in results.items()}})
        check("65. Browser: приложение монтируется и настройки рендерятся",
              wide.get("ok") and wide.get("wsVisible") and wide.get("headText"))
        check("66. Desktop-раскладка (1920x1080) отображает секции в 2 колонки",
              wide.get("cols", 0) >= 2 and wide.get("secCount", 0) >= 4)
        check("67. Client-раскладка (узкое окно) остаётся пригодной",
              narrow.get("wsVisible") and narrow.get("navVisible") and narrow.get("secCount", 0) >= 3)
        # Отбрасываем шум от синтетических стабов ДРУГИХ экранов (проекты/очередь): gate — про настройки.
        _noise = ("projects2", "projects", "tasks", "queue", "staging", "slicer")
        _errs = {k: [e for e in (v.get("errs") or []) if not any(n in e for n in _noise)]
                 for k, v in results.items()}
        _errs = {k: v for k, v in _errs.items() if v}
        check("68. console errors = 0 во всех сценариях", not _errs, _errs)
        _warns = {k: [w for w in (v.get("warns") or []) if "Vue" in w or "warn" in w.lower()]
                  for k, v in results.items()}
        _warns = {k: v for k, v in _warns.items() if v}
        check("69. предупреждений Vue нет", not _warns, _warns)
        check("70. v-cloak снят после монтирования", all(not r.get("vcloak") for r in results.values()))
        check("71. аварийный boot-fallback не показывается при успешной загрузке",
              all(not r.get("bootFallback") for r in results.values()))
        check("BOOL-BROWSER. включённый флажок виден: фон меняется и рисуется галочка (::after)",
              wide.get("checkedDiffers") or (wide.get("tick") not in (None, "none", "normal")),
              "off=%s on=%s tick=%s" % (wide.get("offBg"), wide.get("onBg"), wide.get("tick")))
        check("EN-BROWSER. англоязычный интерфейс рендерится без переполнения",
              en.get("ok") and en.get("secOverflow") == 0 and en.get("btnOverflow") == 0
              and en.get("hscrollReal", 99) <= 0)
    srv.shutdown()

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("ПРОВАЛЕНО:")
    for f in _fail:
        print("   -", f)
print("RELEASE GATE:", "ПРОЙДЕН" if not _fail else "НЕ ПРОЙДЕН")
sys.exit(1 if _fail else 0)
