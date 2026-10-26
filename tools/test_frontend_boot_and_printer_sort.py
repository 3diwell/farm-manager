# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.832 — регрессия пустого экрана: НАСТОЯЩИЙ boot приложения в Edge/Chromium через CDP,
с production DOM/JS/CSS и реальным Vue. Плюс prod-подобные данные (null/пустая/неизвестная модель),
отказы sort-endpoint, аварийный boot-fallback. Плюс source-гварды именно для root cause 2.832.

Root cause 2.831: инлайн `//`-комментарий на строке setup-return «съел» продолжение той же
физической строки (enterSpotlight … sendJobsView … viewMode … setTheme) → эти биндинги не
возвращались → template `sendJobsView.length` падал на первом render → пустой экран.

БЕЗОПАСНОСТЬ: статический сервер отдаёт КОПИЮ web/ (source, read-only) на изолированном порту;
API застаблены; production backend не трогается; принтеры не создаются; сокетов к принтерам нет.
Если Edge недоступен — браузерная часть помечается SKIP (не FAIL), source-гварды выполняются всегда.
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SENTINEL = "FRONTEND_BOOT_SORT_SENTINEL_2_832"
WEB = os.path.join(ROOT, "web")
_n = {"pass": 0, "fail": 0, "skip": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def skip(label):
    print("SKIP — " + label)
    _n["skip"] += 1


APPJS = open(os.path.join(WEB, "app.js"), encoding="utf-8").read()
IDX = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _find_edge():
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(c):
            return c
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.isfile(c):
            return c
    return None


# ── статический сервер, отражающий routing backend (/assets /vendor /design + /api-стабы) ──
import http.server


def make_server(port, control):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def do_GET(self):
            p = self.path.split("?", 1)[0]
            if p in ("/", "/index.html"):
                return self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
            if p == "/assets/app.js" and control.get("broken_appjs"):
                # СЛОМАННАЯ версия: воспроизводим root cause 2.831 (comment-eaten return).
                # Якорь БЕЗ точного текста комментария: 2.866 показал, что правка комментария
                # в setup-return молча отключала инъекцию, и FB1 краснел на исправном коде.
                # 2.977: якорь — строка экспорта с tr(...). Прежний якорь (modelHeaderLabel …
                # enterSpotlight) съедал имена, которые в интерфейсе 2.0 разыменовываются только
                # под условием ui3Mode, — страница всё равно собиралась, и проверка краснела на
                # исправном коде. tr(...) зовётся в шаблоне безусловно: без него сборка падает
                # гарантированно — ровно то, что и должна изображать «съеденная» строка return.
                _j = APPJS.index("tr, lang, setLang,")
                _i = APPJS.rindex("\n", 0, _j) + 1
                assert "return {" in APPJS[max(0, _j - 6000):_j], "якорь инъекции устарел: setup-return изменился"
                bad = APPJS[:_i] + "        // comment eats the rest: " + APPJS[_i:]
                return self._send(200, bad.encode("utf-8"), "text/javascript")
            if p == "/api/printer-sort-mode":
                sm = control.get("sortmode", {"status": 200, "body": {"printer_sort_mode": "manual", "modes": ["manual", "model"]}})
                st = sm.get("status", 200)
                if sm.get("raw") is not None:
                    return self._send(st, sm["raw"].encode("utf-8"), "application/json")
                return self._send(st, json.dumps(sm.get("body", {})).encode("utf-8"), "application/json")
            if p == "/api/printers":
                # prod-подобные принтеры: null/пустая/неизвестная/отсутствующая модель + X2/X10.
                pr = control.get("printers", [])
                return self._send(200, json.dumps(pr).encode("utf-8"), "application/json")
            if p == "/api/parts":
                return self._send(200, b"[]", "application/json")
            if p.startswith("/api/"):
                return self._send(200, b"[]", "application/json")
            rel = p.lstrip("/")
            if rel.startswith("assets/"):
                rel = rel[len("assets/"):]
            cand = os.path.join(WEB, rel.replace("/", os.sep))
            if os.path.isfile(cand):
                ext = os.path.splitext(cand)[1]
                ct = {".js": "text/javascript", ".css": "text/css", ".json": "application/json",
                      ".svg": "image/svg+xml", ".png": "image/png", ".html": "text/html"}.get(ext, "application/octet-stream")
                return self._file(cand, ct)
            return self._send(404, b"404", "text/plain")

        def _file(self, path, ctype):
            try:
                with open(path, "rb") as f:
                    self._send(200, f.read(), ctype)
            except Exception:
                self._send(404, b"404", "text/plain")

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv


# ── Node CDP-драйвер: навигация + сбор console-error + eval + DOM-факты ──
CDP_DRIVER = r"""
const PORT=process.argv[2], DBG=process.argv[3], EVAL=process.argv[4]||'', WAIT=+(process.argv[5]||7000);
let nt; try{ nt=await(await fetch('http://127.0.0.1:'+DBG+'/json/new?about:blank',{method:'PUT'})).json(); }
catch(e){ const l=await(await fetch('http://127.0.0.1:'+DBG+'/json/list')).json(); nt=l.find(t=>t.type==='page')||l[0]; }
const ws=new WebSocket(nt.webSocketDebuggerUrl); let id=0,pend={},cerr=[];
const cmd=(m,p={})=>new Promise(r=>{const _id=++id;pend[_id]=r;ws.send(JSON.stringify({id:_id,method:m,params:p}));});
ws.onmessage=e=>{const d=JSON.parse(e.data);
  if(d.id&&pend[d.id]){pend[d.id](d.result||d.error);delete pend[d.id];return;}
  if(d.method==='Runtime.consoleAPICalled'&&(d.params.type==='error')){cerr.push((d.params.args||[]).map(a=>a.description||a.value||('['+a.type+']')).join(' '));}
  if(d.method==='Runtime.exceptionThrown'){const ed=d.params.exceptionDetails;cerr.push('EXC:'+((ed.exception&&(ed.exception.description||ed.exception.value))||ed.text));}
};
await new Promise(r=>ws.onopen=r);
await cmd('Runtime.enable'); await cmd('Page.enable');
await cmd('Page.navigate',{url:'http://127.0.0.1:'+PORT+'/'});
await new Promise(r=>setTimeout(r,WAIT));
const ev=async x=>{try{const r=await cmd('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true}); return r&&r.result?r.result.value:null;}catch(e){return null;}};
const out={};
if(EVAL){ out.evalResult = await ev(EVAL); await new Promise(r=>setTimeout(r,700)); }   // сначала инъекция/форс, потом чтение DOM
out.mounted = await ev("!!(document.getElementById('app')&&document.getElementById('app').__vue_app__)");
out.mainCols = await ev("!!document.querySelector('#app .main-cols')");
out.sidebar = await ev("!!document.querySelector('#app .pc-scroll, #app [data-tour=\\'add-printer\\']')");
out.vcloak = await ev("!!document.querySelector('#app [v-cloak]')");
out.appChildren = await ev("(document.getElementById('app')||{}).childElementCount||0");
out.fallbackDisplay = await ev("(function(){var f=document.getElementById('fm-boot-fallback');return f?getComputedStyle(f).display:'(none-el)';})()");
out.splashGone = await ev("!document.getElementById('fm-boot-splash')");
out.consoleErrors = cerr.filter(c=>/length|undefined|TypeError|ReferenceError|is not a function|\[Vue\]/i.test(c)).slice(0,5);
console.log('__CDP__'+JSON.stringify(out));
process.exit(0);
"""


def _kill_by_profile(profile_dir):
    """Снять процессы движка, которые держат ИМЕННО этот временный профиль.

    Alpha 2.864. Реализация одна на весь проект — в tools/_edge_dom.py. Здесь только вызов:
    два разных способа закрывать браузер уже привели к тому, что один из них молча не работал
    полгода. Если общий драйвер по какой-то причине не импортируется, набор не падает —
    он просто не сможет прибрать за собой, и это видно в выводе.
    """
    if not profile_dir:
        return
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import _edge_dom
        _edge_dom._kill_by_profile(profile_dir)
    except Exception as e:
        print("    ! не удалось снять процессы движка для %s: %s" % (profile_dir, e))


def run_cdp(edge, port, eval_expr="", wait_ms=7000):
    dbg = _free_port()
    prof = tempfile.mkdtemp(prefix="edgeboot_")
    ep = subprocess.Popen([edge, "--headless=new", "--disable-gpu", "--no-sandbox",
                           "--user-data-dir=" + prof, "--remote-debugging-port=" + str(dbg), "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2.0)
        drv = os.path.join(prof, "drv.mjs"); open(drv, "w", encoding="utf-8").write(CDP_DRIVER)
        r = subprocess.run(["node", drv, str(port), str(dbg), eval_expr, str(wait_ms)],
                           capture_output=True, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        for ln in out.splitlines():
            if ln.startswith("__CDP__"):
                return json.loads(ln[len("__CDP__"):])
        return {"error": (r.stderr.decode("utf-8", "replace")[-400:] or out[-400:])}
    finally:
        try:
            ep.terminate()
        except Exception:
            pass
        # Alpha 2.864. ЗДЕСЬ БЫЛ ДЕФЕКТ, И ОН НЕ СРАБАТЫВАЛ НИ РАЗУ.
        # Стояло: Where-Object { $_.Path -like '*edgeboot_*' }. `$_.Path` — путь к самому
        # исполняемому файлу движка (C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe),
        # метка профиля в нём не встречается НИКОГДА. Условие не совпадало ни с одним процессом,
        # и не закрывался ни один. Измерено 22.08.2026: 1035 брошенных процессов msedge, самый
        # старый прожил шесть суток; они держали 115 профилей edgeboot_* в TEMP на 15 ГБ, из-за
        # чего rmtree ниже молча не срабатывал.
        # Профиль встречается в СТРОКЕ ЗАПУСКА (--user-data-dir=...), поэтому фильтровать надо по
        # CommandLine. Точное совпадение с путём именно этого профиля: обычный браузер владельца
        # задеть невозможно. Ровно так уже делает общий драйвер tools/_edge_dom.py.
        _kill_by_profile(prof)
        import shutil
        time.sleep(0.3); shutil.rmtree(prof, ignore_errors=True)


# ═══════════════════ SOURCE-ГВАРДЫ (всегда, без браузера) ═══════════════════
print("--- source-гварды root cause 2.832 ---")
# ТОЧНО: извлекаем setup-return, УДАЛЯЕМ '//'-комментарии, и проверяем, что «съеденные» в 2.831
# биндинги существуют как реальные ключи возврата (а не спрятаны за инлайн-комментарием).
_ri = APPJS.rfind("return {", 0, APPJS.find("printerSortMode, setPrinterSortMode, printerSortMenu"))
_re = APPJS.find("};", _ri)
_ret_block = APPJS[_ri:_re] if (_ri >= 0 and _re > _ri) else ""
_ret_nocmt = re.sub(r"//[^\n]*", "", _ret_block)   # то, что переживает удаление комментариев = реальные ключи
_swallowed = ("enterSpotlight", "exitSpotlight", "sendJobsView", "sendReserved", "viewMode",
              "printQueue", "theme", "toggleTheme", "setTheme")
check("1. setup-return найден и содержит sort-биндинги (printerSortMode/sortedPrinters)",
      "printerSortMode" in _ret_block and "sortedPrinters" in _ret_block)
check("2. «съеденные» 2.831 биндинги реально возвращаются (переживают удаление комментариев)",
      all(re.search(r"[\s,{]" + b + r"\s*[,}]", _ret_nocmt) for b in _swallowed))
check("2b. sendJobsView НЕ находится ВНУТРИ '//'-комментария setup-return (именно это был root cause)",
      re.search(r"[\s,{]sendJobsView\s*,", _ret_nocmt) is not None)
check("3. ни одна строка setup-return не 'съедает' продолжение инлайн-комментарием",
      not re.search(r"^\s+[A-Za-z_][\w, ]*,\s+//[^\n]*[A-Za-z_]+,\s*$", APPJS, re.M))
check("4. onMounted ставит window.__fmBooted (сигнал успешного монтирования)",
      "window.__fmBooted = true" in APPJS and "onMounted(() => {" in APPJS)
check("5. аварийный boot-fallback присутствует в index.html (независим от Vue) и раскрывается по timeout",
      'id="fm-boot-fallback"' in IDX and "window.__fmBooted=false" in IDX
      and "querySelector('.main-cols')" in IDX and "show();" in IDX)
check("6. fallback имеет кнопки Обновить/Повторить/Журнал + error id, БЕЗ stack",
      'id="fmbf-reload"' in IDX and 'id="fmbf-retry"' in IDX and 'id="fmbf-log"' in IDX
      and "'FM-'+Date.now()" in IDX and "stack" not in IDX.split('id="fm-boot-fallback"')[1][:2000])
check("7. fallback без reload-loop: авто-перезагрузки нет, показ не более одного раза (shown-guard)",
      "if(shown) return; shown=true;" in IDX and "setTimeout" in IDX
      and "location.reload()" in IDX)   # reload только по клику пользователя
check("8. fallback RU и EN", "Не удалось загрузить интерфейс Farm Manager" in IDX
      and "Could not load the Farm Manager interface" in IDX)
check("9. loadPrinterSortMode устойчив к отказу endpoint (try/catch, не блокирует mount)",
      "const loadPrinterSortMode = async () => {" in APPJS
      and re.search(r"loadPrinterSortMode = async \(\) => \{\s*try \{", APPJS) is not None)
check("10. null/пустая/неизвестная модель безопасны (_printerModelDisplay = String((p && p.model) || ''))",
      "String((p && p.model) || '').trim()" in APPJS)
check("11. sorting computed возвращает строго массив принтеров (не смесь group/printer)",
      "const sortedPrinters = computed(() =>" in APPJS
      and "const arr = [...printers.value];" in APPJS
      and "arr.sort((a, b) => sign * cmp(a, b));" in APPJS
      and "        return arr;" in APPJS)
# Alpha 2.866: плоское меню из трёх ключей + направление по повторному клику.
check("11b. три ключа сортировки в одном месте (model/name/status) + направление asc|desc",
      "const printerSortKey = computed(() =>" in APPJS
      and "const printerSortDir = ref('asc');" in APPJS
      and "printerSortDir.value === 'desc' ? -1 : 1" in APPJS)
check("11c. повторный клик по активному пункту переворачивает порядок (а не пересортировывает заново)",
      "const pickPrinterSortKey = (k) => {" in APPJS
      and "if (printerSortKey.value === k) { setPrinterSortDir(printerSortDir.value === 'asc' ? 'desc' : 'asc'); return; }" in APPJS)
check("11d. меню принтеров зовёт только pickPrinterSortKey (старых pickPrinterSortMode/pickPrinterSort нет)",
      IDX.count("pickPrinterSortKey('model')") == 1 and IDX.count("pickPrinterSortKey('status')") == 1
      and IDX.count("pickPrinterSortKey('name')") == 1
      and "pickPrinterSortMode(" not in IDX and "pickPrinterSort(" not in IDX
      and "pickPrinterSortMode" not in APPJS)
check("12. заголовки групп отдельны от карточек (modelHeaderBefore — по type guard режима)",
      "modelHeaderBefore = (pidx)" in APPJS and "printerSortMode.value !== 'model'" in APPJS)

# копирование 2.831 сохранено
check("13. copy/save-copy 2.831 сохранены (openCopyPrinter/savePrinterCopy/keepOpen)",
      "const openCopyPrinter = (p) => {" in APPJS and "const savePrinterCopy = () => addPrinterNode(true);" in APPJS
      and "const addPrinterNode = async (keepOpen = false) => {" in APPJS)
check("14. DISPATCH_ENABLED = False",
      re.search(r"^DISPATCH_ENABLED = False", open(os.path.join(ROOT, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("15. TRANSPORT_ENABLED = False",
      re.search(r"^TRANSPORT_ENABLED = False", open(os.path.join(ROOT, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)

# sentinel
leaks = []
for base in ("server.py", "app", "web", "docs", "modules", "tools/fixtures", "3diwell-setup.iss", "3diwell-client-setup.iss"):
    pth = os.path.join(ROOT, base)
    files = [pth] if os.path.isfile(pth) else []
    if os.path.isdir(pth):
        for r, _d, fs in os.walk(pth):
            for fn in fs:
                if fn.endswith((".py", ".js", ".html", ".json", ".md", ".iss", ".txt", ".css")):
                    files.append(os.path.join(r, fn))
    for fp in files:
        try:
            if SENTINEL.encode() in open(fp, "rb").read():
                leaks.append(os.path.relpath(fp, ROOT))
        except Exception:
            pass
check("16. SENTINEL только в этом тесте (нет в проде/фикстурах/модулях): %s" % (leaks or "нигде"), not leaks)

# ── ЗАСТАВКА ЗАГРУЗКИ (17.09.2026, по слову владельца) ─────────────────────────────────────
#  Слово владельца: «в окне программы есть заставка с 3DIWELL и кружком, а если открыть ФМ в
#  браузере, вместо неё примерно на секунду появляются какие-то непонятные окна по середине».
#  Это был голый шаблон до монтирования Vue: модальные окна лежат в разметке и прячутся только
#  первым рендером. Заставка закрывает это время — и ОБЯЗАНА сниматься, иначе закроет интерфейс.
_i_body, _i_splash, _i_app = IDX.index("<body"), IDX.index("id=" + chr(34) + "fm-boot-splash"), IDX.index("id=" + chr(34) + "app")
check("17. ЗАСТАВКА есть и стоит В САМОМ НАЧАЛЕ body — до разметки приложения",
      _i_body < _i_splash < _i_app)
check("18. накрывает весь экран непрозрачно, выше любых окон интерфейса и ниже аварийного экрана",
      "position:fixed;inset:0;z-index:899000;background:#0b1118" in IDX
      and _i_splash < IDX.index("id=" + chr(34) + "fm-boot-fallback"))
check("19. снимается ровно там, где интерфейс объявляет себя смонтированным (__fmBooted)",
      "window.__fmHideBootSplash" in APPJS and "window.__fmBooted = true" in APPJS
      and abs(APPJS.index("window.__fmHideBootSplash") - APPJS.index("window.__fmBooted = true")) < 400)
check("20. КЛЮЧЕВОЕ: не остаётся навсегда — страховочный отсчёт снимает её и без Vue",
      "window.__fmHideBootSplash=function" in IDX and "}, 8000);" in IDX)
check("21. вид тот же, что у окна программы (логотип, кружок, строка состояния)",
      "3DIWELL" in IDX.split("fm-boot-splash")[1][:1200] and "fm-boot-spin" in IDX
      and "Загрузка интерфейса" in IDX and "Loading the interface" in IDX)

# ═══════════════════ БРАУЗЕРНЫЕ ПРОВЕРКИ (Edge/CDP) ═══════════════════
# FM_SKIP_BROWSER=1 — ЯВНОЕ отключение браузерной части для mutation proof (source-гварды
# ловятся статикой). Это НЕ то же самое, что «движка нет»: отсутствующий движок — красный тест.
_NO_BROWSER = bool(os.environ.get("FM_SKIP_BROWSER"))
EDGE = None if _NO_BROWSER else _find_edge()
# prod-подобные принтеры (реальный поток данных: /api/printers -> printers.value): null/пустая/
# неизвестная/отсутствующая модель + X2/X10 (natural sort) + дубли имён.
PROD_PRINTERS = [
    {"id": "a", "name": "X10", "type": "bambu", "model": "Bambu Lab X1 Carbon"},
    {"id": "b", "name": "X2", "type": "bambu", "model": "Bambu Lab X1 Carbon"},
    {"id": "c", "name": "FF-A", "type": "flashforge", "model": None},
    {"id": "d", "name": "EmptyM", "type": "klipper", "model": ""},
    {"id": "e", "name": "Unk", "type": "klipper", "model": "Totally Unknown 9000"},
    {"id": "f", "name": "NoField", "type": "bambu"},
    {"id": "g", "name": "Dup", "type": "bambu", "model": "Bambu Lab A1"},
    {"id": "h", "name": "Dup", "type": "bambu", "model": "Bambu Lab A1"},
]
# порядок карточек в DOM (data-pid) — для проверки natural sort X2<X10 и «неизвестные в конце»
ORDER_EVAL = "Array.prototype.map.call(document.querySelectorAll('#app [data-pid]'),function(e){return e.getAttribute('data-pid');}).join(',')"
if _NO_BROWSER:
    print("(браузерная часть отключена FM_SKIP_BROWSER=1 — режим mutation proof)")
elif not EDGE:
    # Alpha 2.835: недоступный движок больше НЕ пропуск — без него boot доказать нечем.
    print("--- Edge недоступен: браузерные проверки КРАСНЫЕ ---")
    for lbl in ("boot success mount", "console errors 0", "sort endpoint 500 -> mount",
                "prod-like null/unknown model -> mount", "boot fallback shows", "fallback hidden on success"):
        check("browser: " + lbl + " — движок рендера недоступен", False)
else:
    print("--- НАСТОЯЩИЙ boot в Edge (CDP) ---")
    port = _free_port()
    control = {}
    srv = make_server(port, control)
    try:
        # 1) успешный boot (fixed source, manual, с prod-подобными принтерами)
        control.clear(); control.update({"sortmode": {"status": 200, "body": {"printer_sort_mode": "manual", "modes": ["manual", "model"]}}, "printers": PROD_PRINTERS})
        r = run_cdp(EDGE, port, eval_expr=ORDER_EVAL, wait_ms=7000)
        check("BOOT1. Vue смонтирован (data-v-app)", r.get("mounted") is True)
        check("BOOT2. .main-cols отрисован (топ-уровень интерфейса)", r.get("mainCols") is True)
        check("BOOT3. sidebar/колонка принтеров присутствует", r.get("sidebar") is True)
        check("BOOT4. v-cloak снят", r.get("vcloak") is False)
        check("BOOT5. console errors = 0 (нет sendJobsView.length и пр.)", r.get("consoleErrors") == [])
        check("BOOT6. manual boot с prod-подобными принтерами (null/''/unknown/missing) отрисован без ошибок",
              r.get("consoleErrors") == [] and r.get("mainCols") is True and ("a" in (r.get("evalResult") or "")))
        check("BOOT7. аварийный fallback скрыт при успехе", r.get("fallbackDisplay") in ("none", "(none-el)"))
        check("BOOT7b. ЗАСТАВКА загрузки снята после монтирования (интерфейс не закрыт навсегда)",
              r.get("splashGone") is True)

        # 1b) РЕЖИМ MODEL с prod-подобными принтерами: null/unknown/missing НЕ ломают render
        control.clear(); control.update({"sortmode": {"status": 200, "body": {"printer_sort_mode": "model", "modes": ["manual", "model"]}}, "printers": PROD_PRINTERS})
        rm = run_cdp(EDGE, port, eval_expr=ORDER_EVAL, wait_ms=7000)
        order = (rm.get("evalResult") or "").split(",")
        check("MODEL1. режим model с null/пустой/неизвестной/отсутствующей моделью — mount без ошибок",
              rm.get("mainCols") is True and rm.get("consoleErrors") == [])
        check("MODEL2. все 8 принтеров сохранены (ни один не потерян)", len([x for x in order if x]) == 8)
        check("MODEL3. natural sort: X2 (b) идёт перед X10 (a) внутри модели",
              ("b" in order and "a" in order and order.index("b") < order.index("a")))
        check("MODEL4. неизвестные/пустые модели (c/d/e/f) — после известных (a/b/g/h)",
              max(order.index("a"), order.index("b"), order.index("g"), order.index("h"))
              < min(order.index("c"), order.index("d"), order.index("e"), order.index("f")))

        # 2) отказ sort-endpoint 500 -> всё равно монтируется
        control.clear(); control.update({"sortmode": {"status": 500, "raw": "err"}})
        r2 = run_cdp(EDGE, port, wait_ms=6000)
        check("ENDP1. sort endpoint 500 -> приложение всё равно смонтировано (main-cols)",
              r2.get("mounted") is True and r2.get("mainCols") is True)
        check("ENDP2. sort endpoint 500 -> нет фатальных console-error", r2.get("consoleErrors") == [])

        # 3) malformed JSON от endpoint -> всё равно монтируется, manual fallback
        control.clear(); control.update({"sortmode": {"status": 200, "raw": "{not json"}})
        r3 = run_cdp(EDGE, port, wait_ms=6000)
        check("ENDP3. malformed sort JSON -> mount ok, нет фатальной ошибки",
              r3.get("mounted") is True and r3.get("mainCols") is True and r3.get("consoleErrors") == [])

        # 4) СЛОМАННЫЙ app.js (root cause) -> пусто + аварийный fallback показан
        control.clear(); control.update({"broken_appjs": True})
        r4 = run_cdp(EDGE, port, eval_expr="(function(){window.__fmShowBootFallback&&window.__fmShowBootFallback();return 'forced';})()", wait_ms=6000)
        check("FB1. СЛОМАННЫЙ app.js воспроизводит пустой интерфейс (нет .main-cols)", r4.get("mainCols") is not True)
        check("FB2. аварийный boot-fallback показан (не бесконечный пустой фон)", r4.get("fallbackDisplay") == "flex")
    finally:
        srv.shutdown()

print("\n" + "=" * 64)
print("Итого: PASS=%d FAIL=%d SKIP=%d" % (_n["pass"], _n["fail"], _n["skip"]))
sys.exit(1 if _n["fail"] else 0)
