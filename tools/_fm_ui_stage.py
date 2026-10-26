# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835 — общая сцена для UI-тестов: НАСТОЯЩЕЕ приложение в headless-браузере через CDP.

ЗАЧЕМ. Тестам раскладки и верхнего бара нужен один и тот же стенд: локальный статический сервер
отдаёт РЕАЛЬНЫЕ web/index.html + app.js + app.css + вендорный Vue, /api-ответы синтетические,
браузер поднимается мостом tools/_edge_cdp.mjs. Рабочая БД, DATA_DIR, config и production-рантайм
не используются; принтерам ничего не отправляется; печати не запускаются.

ВАЖНО ПРО СЦЕНУ (выяснено измерениями в 2.835):
  * в свежем профиле приложение показывает окно тура — оно загораживает экран, его надо закрыть;
  * режим интерфейса (бывшая «редакция») берётся из localStorage и по умолчанию 'advanced'.
    У владельца включён «Корпоративный»/pro, поэтому сцена сама переводит приложение в pro —
    так измеряется полный набор разделов. (До R-132 в 'advanced' вырезался и раздел «Доступ и
    аудит»; теперь он виден в любом режиме.);
  * смена редакции ЗАКРЫВАЕТ настройки (так задумано в setEdition), поэтому настройки
    открываются ПОСЛЕ неё;
  * интерфейс может быть на английском (язык тоже per-browser), поэтому элементы ищутся по
    русскому И английскому тексту.
"""
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _edge_dom  # noqa: E402

WEB = os.path.join(REPO, "web")

# Синтетические ответы: ровно столько, сколько нужно, чтобы экран настроек отрисовался целиком.
API = {
    "/api/printers": [], "/api/state": {}, "/api/projects2": [], "/api/projects": [], "/api/tasks": [],
    "/api/staging": [], "/api/modules": {"modules": []},
    # /api/parts обязан быть СПИСКОМ: ядро грузит принтеры в одном Promise.all с деталями и
    # выходит раньше, если ответ по деталям не список — тогда список принтеров остаётся пустым.
    "/api/parts": [],
    "/api/network": {"lan_access_enabled": False, "requested_enabled": False, "restart_required": False,
                     "can_enable": True, "port": 8000, "port_can_change": True},
    "/api/printer-files/settings": {"status": "ok", "read_enabled": True, "delete_enabled": False},
    "/api/printer-files/capabilities": {"status": "ok", "adapters": []},
    "/api/storage": {"data_dir": "D:/FarmData", "archive_dir": "D:/FarmArchive",
                     "data_dir_is_default": False, "archive_dir_is_default": True},
    "/api/send-jobs": {"jobs": [], "reserved_printer_ids": []},
    "/api/slicer/list": {"slicers": [], "choice": ""},
    "/api/printer-sort-mode": {"printer_sort_mode": "manual", "modes": ["manual", "model"]},
    "/api/config-backup/status": {"status": "ok", "sections": []},
    # список моделей принтеров — ядро делает list.unshift(...), поэтому обязан быть СПИСКОМ
    "/api/printer-models": [],
    "/api/printer-badges": {}, "/api/printer-filament": {},
}


# Дополнительные/переопределяющие ответы конкретного теста (stage.set_api). Нужны, чтобы один и
# тот же стенд мог показать принтеры, проекты, отправки и установленный модуль, не меняя базовую
# сцену остальных тестов.
API_EXTRA = {}


#  Живые состояния принтеров для вебсокета стенда (Alpha 2.905): pid -> состояние, ровно в том
#  виде, в каком их присылает настоящий сервер. Пусто — вебсокет молчит, как и прежде.
LIVE_STATES = {}


def set_live(states):
    """Задать живые состояния, которые стенд отдаст по /ws (None/{} — молчать)."""
    global LIVE_STATES
    LIVE_STATES = dict(states or {})


def set_api(overrides):
    """Переопределить ответы /api для последующих прогонов (None/{} — вернуть базовую сцену)."""
    global API_EXTRA
    API_EXTRA = dict(overrides or {})


class _H(BaseHTTPRequestHandler):
    #  13.10.2026: HTTP/1.1 — соединения браузера переиспользуются. При HTTP/1.0 (по умолчанию) каждый
    #  запрос страницы шёл новым соединением, и после закрытия оно ещё минуты висит в Windows
    #  (TIME_WAIT): замер — один 40-секундный набор оставлял 243 таких соединения, полный прогон —
    #  тысячи. Отсюда плавающие net::ERR_NO_BUFFER_SPACE в консоли на полном прогоне (12-13.10.2026:
    #  test_task_sending_status, test_ui3_overlay, test_network_access_settings) без дефекта страницы.
    #  Каждый ответ идёт с Content-Length (_send), поэтому держать соединение можно.
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain_body(self):
        """Тело запроса надо дочитать: на переиспользуемом соединении непрочитанный хвост
        приняли бы за начало следующего запроса."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > 0:
            self.rfile.read(n)

    def do_POST(self):
        self._drain_body()
        self.do_GET()

    def do_PATCH(self):
        self._drain_body()
        self.do_GET()

    def do_PUT(self):
        self._drain_body()
        self.do_GET()

    def do_DELETE(self):
        self._drain_body()
        self.do_GET()

    def _ws_upgrade(self):
        """Рукопожатие WebSocket на /ws и отдача ЖИВЫХ СОСТОЯНИЙ принтеров.

        Приложение подключается к /ws сразу после монтирования. Без ответа браузер печатает
        ошибку в консоль — и проверка «консоль чиста» краснела бы на свойстве СТЕНДА, а не на
        дефекте продукта.

        Alpha 2.905: стенд научился ПРИСЫЛАТЬ состояния (stage.set_live({...})). Раньше он молча
        держал соединение, и экран, живущий на телеметрии, приходилось проверять подсадкой данных
        внутрь страницы — то есть проверять не тот путь, которым данные ходят у владельца. Теперь
        путь настоящий: сервер -> вебсокет -> разбор JSON -> экран. Пустой набор состояний
        сохраняет прежнее поведение: соединение просто держится открытым.
        """
        key = self.headers.get("Sec-WebSocket-Key") or ""
        acc = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
        self.wfile.flush()
        try:
            self.connection.settimeout(1.0)
            ticks = 0
            while ticks < 90:
                ticks += 1
                if LIVE_STATES:
                    #  Повторяем раз в секунду: экран может подписаться позже первой отправки,
                    #  да и живой сервер шлёт снимок постоянно, а не однажды.
                    self._ws_send_text(json.dumps(LIVE_STATES))
                try:
                    if not self.connection.recv(4096):
                        break
                except socket.timeout:
                    continue
        except Exception:
            pass
        self.close_connection = True

    def _ws_send_text(self, text):
        """Один текстовый кадр WebSocket от сервера (без маскирования — так требует протокол)."""
        payload = text.encode("utf-8")
        n = len(payload)
        if n < 126:
            head = bytes([0x81, n])
        elif n < (1 << 16):
            head = bytes([0x81, 126, (n >> 8) & 0xFF, n & 0xFF])
        else:
            head = bytes([0x81, 127] + [(n >> (8 * i)) & 0xFF for i in range(7, -1, -1)])
        self.wfile.write(head + payload)
        self.wfile.flush()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/ws" and (self.headers.get("Upgrade") or "").lower() == "websocket":
            return self._ws_upgrade()
        if p in ("/", "/index.html"):
            #  26.09.2026: `?ls=ключ:значение` и для интерфейса 2.0 — сохранённый выбор (размер текста,
            #  шрифт) обязан действовать с первого показа, а это проверяется только загрузкой с ним.
            _pre = ""
            for _pair in re.findall(r"(?:^|[?&])ls=([^&]+)", self.path):
                _k, _, _v = _pair.partition(":")
                if _k:
                    _pre += "try{localStorage.setItem(%s,%s)}catch(e){}" % (json.dumps(_k), json.dumps(_v))
            body = io.open(os.path.join(WEB, "index.html"), "rb").read()
            if _pre:
                body = body.replace(b"<head>", ("<head><script>" + _pre + "</script>").encode("utf-8"), 1)
            return self._send(body, "text/html; charset=utf-8")
        #  Alpha 2.903: вторая страница интерфейса (UI 3.0). Её файлы (.js/.css) отдаёт общая
        #  ветка ниже — она читает из web/ по прямому пути; сюда попадает только сама страница.
        if p in ("/ui3", "/ui3/", "/ui3/index.html"):
            #  Alpha 2.911: /ui3 — ТА ЖЕ страница index.html с флагом режима и листом раскладки,
            #  ровно как отдаёт сервер (home_ui3). Отдельной страницы UI 3.0 больше нет.
            body = io.open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
            #  Alpha 2.921: `?ls=ключ:значение` кладёт значение в localStorage ДО загрузки
            #  скриптов страницы. Нужно, чтобы проверять именно ЗАПУСК с прошлым выбором
            #  владельца (например, страница открыта на вкладке «Очередь»): такие поломки
            #  живут в порядке инициализации и после загрузки уже не воспроизводятся.
            _pre = ""
            for _pair in re.findall(r"(?:^|[?&])ls=([^&]+)", self.path):
                _k, _, _v = _pair.partition(":")
                if _k:
                    _pre += "try{localStorage.setItem(%s,%s)}catch(e){}" % (
                        json.dumps(_k), json.dumps(_v))
            inject = ('<script>window.__UI3_MODE__=true;'
                      "try{localStorage.setItem('farm_ui_version','3')}catch(e){}"
                      + _pre + "</script>"
                      '<link rel="stylesheet" href="/ui3/ui3.css">')
            body = body.replace("<head>", "<head>" + inject, 1)
            return self._send(body.encode("utf-8"), "text/html; charset=utf-8")
        for pref, root in (("/assets/", WEB), ("/vendor/", os.path.join(WEB, "vendor")),
                           ("/design/", os.path.join(WEB, "design")),
                           # исходники модулей репозитория: ядро импортирует /modules/<id>/<файл>,
                           # срезая префикс web/ из entry, — значит файл лежит в modules/<id>/web/
                           ("/modules/", os.path.join(REPO, "modules"))):
            if p.startswith(pref):
                rest = p[len(pref):]
                cands = [os.path.join(root, rest)]
                if pref == "/modules/" and "/" in rest:
                    mid, _, tail = rest.partition("/")
                    cands.insert(0, os.path.join(root, mid, "web", tail))
                for fp in cands:
                    if os.path.isfile(fp):
                        return self._send(io.open(fp, "rb").read(), _ctype(fp))
        fp = os.path.join(WEB, p.lstrip("/").replace("/", os.sep))
        if os.path.isfile(fp) and os.path.commonpath([os.path.abspath(fp), WEB]) == WEB:
            return self._send(io.open(fp, "rb").read(), _ctype(fp))
        body = API_EXTRA[p] if p in API_EXTRA else API.get(p, {"status": "ok"})
        return self._send(json.dumps(body).encode("utf-8"),
                          "application/json; charset=utf-8")


def _ctype(fp):
    if fp.endswith(".css"):
        return "text/css; charset=utf-8"
    if fp.endswith(".js") or fp.endswith(".mjs"):
        return "application/javascript; charset=utf-8"
    if fp.endswith(".svg"):
        return "image/svg+xml"
    if fp.endswith(".png"):
        return "image/png"
    return "application/octet-stream"


_srv = None
_port = 0


class _StageServer(ThreadingHTTPServer):
    #  29.09.2026: очередь подключений по умолчанию — 5. Windows при переполненной очереди не ждёт,
    #  а сразу сбрасывает подключение, и страница пишет в консоль ERR_CONNECTION_REFUSED: приложение
    #  при запуске шлёт больше запросов разом (плюс WebSocket). Так дважды подряд краснел набор окна
    #  склада на полном прогоне — в разных местах, без дефекта страницы.
    request_queue_size = 128


def start():
    """Поднять локальный сервер (один на процесс) и вернуть его порт."""
    global _srv, _port
    if _srv is None:
        _srv = _StageServer(("127.0.0.1", 0), _H)
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        _port = _srv.server_address[1]
    return _port


def stop():
    global _srv
    if _srv is not None:
        try:
            _srv.shutdown()
        except Exception:
            pass
        _srv = None


# Пролог сценария: утилиты + приведение приложения в нужное состояние.
#   openStage(tab, done) — закрыть тур, включить редакцию pro, открыть настройки, выбрать вкладку.
#   Вкладка ищется по русскому и английскому названию; шаги идут с паузой на перерисовку Vue.
PRELUDE = r"""
function dump(o){ var d=document.getElementById('__fmres')||(function(){var x=document.createElement('div');
    x.id='__fmres'; x.style.display='none'; document.body.appendChild(x); return x;})();
  d.textContent='@@RES@@'+JSON.stringify(o)+'@@END@@'; return true; }
function click(el){ if(el) el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window})); }
function byText(sel,list){ var n=[].slice.call(document.querySelectorAll(sel));
  for(var i=0;i<n.length;i++){ var tx=(n[i].textContent||'');
    for(var j=0;j<list.length;j++){ if(tx.indexOf(list[j])>=0) return n[i]; } } return null; }
var FM_TABS={system:['Система','System'], general:['Общие','General'], print:['Печать','Printing'],
             modules:['Модули','Modules']};
var FM_LOG=[];
function gear(){ return document.querySelector('[data-tour="settings"],[data-help="settings"]'); }
// Переключатель языка живёт в шапке (SVG): первая вкладка — EN, вторая — RU. Кликаем как пользователь.
function langTabs(){ return [].slice.call(document.querySelectorAll('[data-tour="lang"] .ltab')); }
function setUiLang(l){ var t=langTabs();
  if(t.length>=2) click(l==='en'?t[0]:t[1]); else FM_LOG.push('переключатель языка не найден'); }
function uiLang(){ var n=[].slice.call(document.querySelectorAll('.fm-set-nav-item'))
    .map(function(e){ return (e.textContent||'').trim(); }).join('|');
  if(/Общие|Печать|Система/.test(n)) return 'ru';
  if(/General|Printing|System/.test(n)) return 'en';
  return ''; }
// НАСТОЯЩАЯ смена размера окна: мост (tools/_edge_cdp.mjs) видит запрос и применяет
// Emulation.setDeviceMetricsOverride. Синтетический resize-эвент вьюпорт не меняет и дефект не ловит.
function setViewport(w,h,dsf,cb){
  var seq=(window.__fmViewportSeq||0)+1; window.__fmViewportSeq=seq;
  window.__fmViewport={w:w,h:h,dsf:dsf||1,seq:seq};
  var t0=Date.now();
  (function wait(){
    if(window.__fmViewportApplied===seq) return setTimeout(cb,420);
    if(Date.now()-t0>20000){ FM_LOG.push('смена вьюпорта не применена мостом'); return cb(); }
    setTimeout(wait,100); })(); }
function steps(fns, done){
  (function nx(i){ if(i>=fns.length) return done();
    var f=fns[i], waited=false;
    try { if(f.length>0){ waited=true; f(function(){ nx(i+1); }); } else f(); }
    catch(e){ FM_LOG.push('шаг'+i+': '+String(e&&e.message||e)); }
    if(!waited) setTimeout(function(){ nx(i+1); }, 320); })(0); }
function openStage(tab, done, lang){
  steps([
    function(){ var b=byText('button',['Позже','Later']); if(b) click(b); },   // окно тура
    function(){ if(lang) setUiLang(lang); },                                   // язык — как у владельца
    function(){ var sel=[].slice.call(document.querySelectorAll('select.fm-set-select')).filter(function(s){
        return [].slice.call(s.options).some(function(o){return o.value==='pro';}); })[0];
      if (!sel){ click(gear()); FM_LOG.push('редакция: селектор ещё не в DOM, открываю настройки'); }
      else { sel.value='pro'; sel.dispatchEvent(new Event('change',{bubbles:true})); } },
    function(){ var sel=[].slice.call(document.querySelectorAll('select.fm-set-select')).filter(function(s){
        return [].slice.call(s.options).some(function(o){return o.value==='pro';}); })[0];
      if (sel && sel.value!=='pro'){ sel.value='pro'; sel.dispatchEvent(new Event('change',{bubbles:true})); } },
    function(){ if(!document.querySelector('.fm-set-scroll')) click(gear()); },
    function(){ if(!document.querySelector('.fm-set-scroll')) { click(gear()); FM_LOG.push('повторное открытие настроек'); } },
    function(){ var t=byText('.fm-set-nav-item', FM_TABS[tab]||[tab]);
      if(!t) FM_LOG.push('вкладка не найдена: '+tab); click(t); }
  ], done);
}
function activeTabText(){ var a=document.querySelector('.fm-set-nav-item.active');
  return a ? (a.textContent||'').trim() : ''; }
function rectOf(e){ if(!e) return null; var b=e.getBoundingClientRect();
  return {top:Math.round(b.top*10)/10, left:Math.round(b.left*10)/10,
          w:Math.round(b.width*10)/10, h:Math.round(b.height*10)/10,
          bottom:Math.round(b.bottom*10)/10}; }
"""


def run(js_body, window_size=(1440, 900), extra_args=(), settle_ms=1400, timeout=600.0, shot_path=None,
        path="/"):
    """Выполнить сценарий в реальном браузере и вернуть его результат (dict) либо None.

    js_body — выражение JS, которое обязано вызвать dump(результат) (можно асинхронно, вернув
    Promise). Пролог PRELUDE уже подключён.

    Alpha 2.903: параметр path выбирает страницу — "/" (интерфейс 2.0) или "/ui3" (интерфейс 3.0).
    Прежние вызовы без этого параметра работают ровно как раньше.

    Alpha 2.835: в результат добавляется ключ `__diag` — ошибки консоли, предупреждения (в т.ч.
    «[Vue warn]»), необработанные исключения и отказы промисов страницы. Без него браузерная
    проверка не могла краснеть на ошибке приложения. При отказе моста возвращается None, но
    причина видна в `last_diag()` — тест обязан покраснеть с этой причиной, а не пропустить.
    """
    global _LAST_DIAG
    _LAST_DIAG = {}
    port = start()
    js = "(function(){\n" + PRELUDE + "\n" + js_body + "\n})()"
    # ignore_cleanup_errors: движок закрывается асинхронно и может ещё держать файл профиля —
    # уборка временной папки НЕ должна ронять тест (иначе получаем красный по причине оснастки).
    with tempfile.TemporaryDirectory(prefix="fm_stage835_", ignore_cleanup_errors=True) as td:
        diag_path = os.path.join(td, "diag.json")
        _url = "http://127.0.0.1:%d%s" % (port, path if path.startswith("/") else ("/" + path))
        dom = _edge_dom.render_dom(_url, profile_dir=os.path.join(td, "p"),
                                   window_size=window_size, extra_args=tuple(extra_args),
                                   settle_ms=settle_ms, timeout=timeout, eval_js=js,
                                   shot_path=shot_path, diag_path=diag_path)
        try:
            with io.open(diag_path, encoding="utf-8") as fh:
                _LAST_DIAG = json.load(fh)
        except Exception:
            _LAST_DIAG = {}
        #  13.10.2026: нехватка сетевых ресурсов МАШИНЫ (_ENV_NET_ERRORS) отделяется здесь, в одном месте,
        #  а не только в page_problems: часть наборов читает consoleErrors напрямую и краснела от
        #  состояния Windows, а не от страницы (test_ui3_overlay, test_task_sending_status на полном
        #  прогоне 12-13.10.2026). Строки не пропадают: они в envNetErrors и печатаются пометкой.
        if isinstance(_LAST_DIAG, dict) and _LAST_DIAG.get("consoleErrors"):
            _env = [s for s in _LAST_DIAG["consoleErrors"] if any(m in str(s) for m in _ENV_NET_ERRORS)]
            if _env:
                _LAST_DIAG["consoleErrors"] = [s for s in _LAST_DIAG["consoleErrors"] if s not in _env]
                _LAST_DIAG["envNetErrors"] = _env
                print("      (окружение машины, не дефект страницы: %s)" % "; ".join(str(x)[:160] for x in _env[:3]))
    if not dom:
        return None
    m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(1))
    except Exception:
        return None
    if isinstance(out, dict):
        out["__diag"] = _LAST_DIAG
    return out


_LAST_DIAG = {}


def last_diag():
    """Диагностика последнего прогона (в т.ч. bridgeError, если движок не поднялся)."""
    return _LAST_DIAG


#  18.09.2026: нехватка сетевых ресурсов Windows — это состояние МАШИНЫ, а не дефект страницы.
#  На длинном полном прогоне браузер не может открыть очередной сокет к СВОЕМУ ЖЕ стенду, и в
#  консоль падает ERR_NO_BUFFER_SPACE. Дважды за ночь это красило наборы вслепую (набор раскладки
#  настроек и базовую линию набора-подменыша), а к продукту отношения не имеет. Такие строки больше
#  не краснят проверку, но и не исчезают: набор печатает их отдельной пометкой.
_ENV_NET_ERRORS = ("ERR_NO_BUFFER_SPACE", "ERR_INSUFFICIENT_RESOURCES")


def page_problems(res):
    """Список проблем страницы, которые ОБЯЗАНЫ краснить проверку.

    Предупреждения Vue приходят как console.warn — они здесь тоже проблема: молчаливое
    предупреждение шаблона однажды уже означало, что часть интерфейса не отрисовалась.
    """
    d = (res or {}).get("__diag") or {}
    out, env = [], []
    for key, label in (("pageErrors", "исключение"), ("consoleErrors", "console.error"),
                       ("consoleWarnings", "console.warn"), ("unhandled", "unhandledrejection")):
        for s in (d.get(key) or []):
            line = "%s: %s" % (label, str(s)[:200])
            if any(m in str(s) for m in _ENV_NET_ERRORS):
                env.append(line)
                continue
            out.append(line)
    if env:
        print("      (окружение машины, не дефект страницы: %s)" % "; ".join(env[:3]))
    if d.get("bridgeError"):
        out.append("мост: %s" % str(d["bridgeError"])[:200])
    return out


def engine_ready():
    """Есть ли рабочий движок и Node (иначе браузерная часть теста пропускается честно)."""
    try:
        return bool(_edge_dom.engine_usable())
    except Exception:
        return False
