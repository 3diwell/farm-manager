# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Модуль «Оформление и темы» (appearance) — выпуск 3.0, 12.09.2026, по слову владельца.

ЗАЧЕМ. Владелец положил в папку модулей обновлённое «Оформление и темы» 0.17.2 и попросил
поставить его в выпуск. Модуль — только интерфейс, но он меняет вид ВСЕЙ программы: цвета,
шрифт, фон, карточки, контур хода печати. Поэтому проверяется не только его сборка, но и то,
что с ним программа остаётся рабочей, а без него (или с отключённым) выглядит как прежде.

ЧТО ДОКАЗЫВАЕТСЯ:
  A. манифест согласован с кодом модуля; бэкенда и маршрутов у модуля нет;
  B. сборка zip: только исполняемые файлы, документы автора не входят, каждый относительный
     импорт разрешается в файл архива, содержимое побайтно равно исходникам;
  C. рантайм: модуль не ходит в чужие маршруты и во внешнюю сеть, не исполняет строк как кода,
     хранит темы только в браузере под своими ключами, сверяет своё включение и убирает стиль,
     если модуль выключен; аварийный выход ?appearance=off есть;
  D. все Vue-шаблоны модуля компилируются настоящим Vue из web/vendor;
  E. стенд UI 3.0 (настоящий интерфейс программы, headless Edge): модуль включён — тема
     применена, кнопка модуля на баре открывает редактор, редактор в окне, «Закрыть»
     закрывает, принтеры видны, консоль чиста; модуль отключён — тема не применена, кнопки нет;
  F. вид «Дашборд» (0.17.4): стрелки температуры без мигания, цвет «нагреватель включён», читаемость;
  G. 0.17.5: темы, которые версия показать не может (новее или испорчены), не прячут остальные, не
     стираются и названы в редакторе; образец карточки открывает настройки карточки.

Запуск: python tools/test_appearance_module.py   (0 = все проверки пройдены)
"""
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
MID = "appearance"
MOD_DIR = os.path.join(REPO, "modules", MID)
WEB = os.path.join(MOD_DIR, "web")
SENTINEL = "APPEARANCE_MODULE_SENTINEL_3_0"
NODE = r"C:\Program Files\nodejs\node.exe" if os.path.isfile(r"C:\Program Files\nodejs\node.exe") else (shutil.which("node") or "node")

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:500]) if detail else ""))


def section(t):
    print("\n--- %s ---" % t)


def rd(path):
    return io.open(path, encoding="utf-8").read()


TMP = tempfile.mkdtemp(prefix="fm_appearance_test_")
JS_FILES = sorted(f for f in os.listdir(WEB) if f.endswith(".js"))
JS = {f: rd(os.path.join(WEB, f)) for f in JS_FILES}

# ════════════════════════════════════════════════════════════════════════════
section("A. манифест и устройство модуля")

MJ = json.load(open(os.path.join(MOD_DIR, "module.json"), encoding="utf-8"))
check("A1. манифест: id appearance, «Оформление и темы», версия, окно модуля на месте",
      MJ.get("id") == MID and MJ.get("ru") == "Оформление и темы" and bool(MJ.get("version"))
      and MJ.get("entry") == "web/AppearancePanel.js" and os.path.isfile(os.path.join(WEB, "AppearancePanel.js")), MJ)
_schema = JS.get("theme-schema.js", "")
check("A2. код модуля знает свой id и версию так же, как манифест (%s)" % MJ.get("version"),
      "export const MODULE_ID = 'appearance';" in _schema
      and ("export const MODULE_VERSION = '%s';" % MJ.get("version")) in _schema)
from app import route_policy_registry as reg   # noqa: E402

check("A3. модуль только интерфейс: бэкенда нет, в карте прав ядра маршрутов appearance нет",
      not os.path.exists(os.path.join(MOD_DIR, "backend.py"))
      and not [p for p in reg.ALL_POLICIES if getattr(p, "module_id", None) == MID])
from app.config_backup import module_providers as MP   # noqa: E402

_prov = MP.get_provider(MID)
check("A5. резервная копия знает модуль: «пользовательских данных нет», его установка не блокирует полный экспорт",
      _prov is not None and _prov.data_class == MP.DATA_CLASS_NO_DATA and _prov.table_specs == ()
      and MP.check_export_completeness(["inventory", "cost", "quality", "messengers", MID]) == [])
_rel = rd(os.path.join(REPO, "tools", "build_release.py"))
check("A4. модуль входит в выпуск: его сборщик и архив названы в списке модулей выпуска",
      '("build_appearance_zip.py", "3diwell-module-appearance.zip", "appearance")' in _rel)

# ════════════════════════════════════════════════════════════════════════════
section("B. сборка zip")

_bspec = importlib.util.spec_from_file_location("fm_build_appearance_zip_test", os.path.join(REPO, "tools", "build_appearance_zip.py"))
_b = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(_b)
_b.OUT = os.path.join(TMP, "appearance.zip")                  # во временную папку, не в modules/
_old_stdout, sys.stdout = sys.stdout, io.StringIO()
try:
    _b.main()
    _built = True
except BaseException as e:   # noqa: BLE001 — AssertionError/SystemExit сборщика — провал проверки
    _built = repr(e)
finally:
    sys.stdout = _old_stdout
_names = zipfile.ZipFile(_b.OUT).namelist() if _built is True else []
_want = ["appearance/module.json"] + ["appearance/web/" + f for f in JS_FILES]
check("B1. в архиве манифест и все скрипты web/ — и ничего больше", _built is True and sorted(_names) == sorted(_want),
      (_built, sorted(set(_names) ^ set(_want))[:6]))
_docs = [f for f in os.listdir(MOD_DIR) if f.lower().endswith((".md", ".json")) and f != "module.json"]
check("B2. документы автора (%s) лежат в исходниках, но в архив не попали" % ", ".join(sorted(_docs)),
      _docs and not [n for n in _names if os.path.basename(n) in _docs])
check("B3. каждый относительный импорт скриптов разрешается в файл архива (иначе модуль упадёт на загрузке)",
      _built is True and _b.verify(_b.OUT) is not None)
check("B4. содержимое архива побайтно равно исходникам",
      _built is True and all(zipfile.ZipFile(_b.OUT).read(n) == open(os.path.join(MOD_DIR, *n.split("/")[1:]), "rb").read()
                             for n in _names))

# ════════════════════════════════════════════════════════════════════════════
section("C. безопасность рантайма")

_fetches = sorted({m.group(0) for s in JS.values() for m in re.finditer(r"fetch\(\s*[^,)]{1,60}", s)})
check("C1. сеть: только состояние своего модуля (/api/modules) и собственные файлы модуля для экспорта темы",
      _fetches == ["fetch('/api/modules'", "fetch(url"]
      and "new URL(`./${fileName}`, import.meta.url)" in JS.get("theme-package.js", ""), _fetches)
#  Строки-комментарии со ссылками на спецификации (w3.org) — пояснение для разработчика, не адрес запроса.
_CODE = {f: re.sub(r"(?m)^\s*//.*$", "", s) for f, s in JS.items()}
check("C2. чужих маршрутов модулей и адресов вне программы нет (кроме пространства имён SVG)",
      not any("/api/mod/" in s for s in _CODE.values())
      and {m for s in _CODE.values() for m in re.findall(r"https?://[^'\"`\s)]+", s)} <= {"http://www.w3.org/2000/svg"},
      sorted({m for s in _CODE.values() for m in re.findall(r"https?://[^'\"`\s)]+", s)}))
check("C3. строки не исполняются как код: нет eval, new Function, document.write, присваивания innerHTML",
      not any(re.search(r"\beval\(|new Function\(|document\.write|\.innerHTML\s*=", s) for s in JS.values()))
_keys = set()
for s in JS.values():
    _keys.update(re.findall(r"['\"`](fm_[a-z_0-9]+)['\"`]", s))
_storage_consts = set(re.findall(r"export const [A-Z_]*KEY[A-Z_]* = '([^']+)'", _schema))
check("C4. темы хранятся только в браузере и только под ключами модуля fm_appearance_*",
      _storage_consts and all(k.startswith("fm_appearance_") for k in _storage_consts)
      and all(k.startswith("fm_appearance_") for k in _keys if "storage" not in k), sorted(_keys)[:12])
_rt = JS.get("theme-runtime.js", "")
check("C5. включение сверяется по /api/modules: отключён или нет ответа — стиль темы убирается; есть ?appearance=off",
      "own && !own.disabled && (!own.state || own.state === 'loaded')" in _rt
      and ".get('appearance') === 'off'" in _rt and _rt.count("removeStyle()") >= 3
      and "window.setInterval(() => { if (!document.hidden) refreshModuleState(); }, 10000)" in _rt)

# ════════════════════════════════════════════════════════════════════════════
section("D. шаблоны Vue")

_MJS = os.path.join(TMP, "compile_appearance.mjs")
io.open(_MJS, "w", encoding="utf-8").write(r"""
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [REPO, TMP] = process.argv.slice(2);
if (!globalThis.document) globalThis.document = { createElement: () => ({ style: {} }), querySelector: () => null, head: {} };
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
const vendor = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;
const Vue = await import(vendor);
const WEB = join(REPO, 'modules', 'appearance', 'web');
const out = [];
const compileOne = (name, tpl) => {
  const errors = [];
  try {
    const fn = Vue.compile(tpl, { decodeEntities: (x) => x, onError: (e) => errors.push(String(e.message || e)), onWarn: () => {} });
    out.push({ name, ok: typeof fn === 'function' && errors.length === 0, errors });
  } catch (e) { out.push({ name, ok: false, errors: [String(e && e.message || e)] }); }
};
for (const f of ['editor-unified-template.js', 'editor-template.js', 'editor-simple-template.js']) {
  const mod = await import(pathToFileURL(join(WEB, f)).href);
  for (const [k, v] of Object.entries(mod)) if (typeof v === 'string' && v.includes('<') && /v-|\{\{/.test(v)) compileOne(f + ' → ' + k, v);
}
const raw = readFileSync(join(WEB, 'editor-components.js'), 'utf8').replace(/from\s+['"]vue['"]/g, `from '${vendor}'`);
const tmpFile = join(TMP, 'editor-components.mjs');
writeFileSync(tmpFile, raw, 'utf8');
const comps = await import(pathToFileURL(tmpFile).href);
for (const [k, v] of Object.entries(comps)) if (v && typeof v === 'object' && typeof v.template === 'string') compileOne('editor-components.js → ' + k, v.template);
process.stdout.write(JSON.stringify(out));
""")
try:
    _r = subprocess.run([NODE, _MJS, REPO, TMP], capture_output=True, timeout=180)
    _compiled = json.loads(_r.stdout.decode("utf-8", "replace") or "[]")
    _cerr = _r.stderr.decode("utf-8", "replace")[-400:]
except Exception as e:   # noqa: BLE001
    _compiled, _cerr = [], repr(e)
_names_c = [c["name"] for c in _compiled]
check("D1. найдены шаблоны редактора (основной, простой, прежний) и шаблон поля: %d" % len(_compiled),
      any("editor-unified-template.js → PANEL_TEMPLATE" == n for n in _names_c)
      and any(n.startswith("editor-components.js → AppearanceField") for n in _names_c), (_names_c, _cerr))
check("D2. все шаблоны компилируются настоящим Vue без ошибок",
      _compiled and all(c["ok"] for c in _compiled), [c for c in _compiled if not c["ok"]][:2])
check("D3. окно модуля берёт именно основной шаблон редактора",
      "import { PANEL_TEMPLATE } from './editor-unified-template.js';" in JS.get("AppearancePanel.js", "")
      and "template:PANEL_TEMPLATE" in JS.get("AppearancePanel.js", ""))

# ════════════════════════════════════════════════════════════════════════════
section("E. стенд UI 3.0: программа с модулем и без него")

import _fm_ui_stage as st   # noqa: E402

PRINTERS = [{"id": "b1", "name": "H2D_01", "type": "bambu", "model": "Bambu Lab H2D", "ip": "10.0.0.11", "port": 8883},
            {"id": "k1", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus", "ip": "10.0.0.12", "port": 7125}]
LIVE = {"b1": {"status": "RUNNING", "percent": 43, "nozzle_count": 1, "nozzle_temp": 220, "bed_temp": 60, "hms": [],
               "gcode_file": "bracket_v3.gcode", "remaining_time": 55},
        "k1": {"status": "IDLE", "percent": 0, "nozzle_count": 1, "nozzle_temp": 25, "bed_temp": 25, "hms": []}}


def modules_payload(disabled):
    return {"modules": [{"id": MID, "ru": MJ["ru"], "en": MJ.get("en", ""), "version": MJ["version"], "icon": MJ.get("icon", "module"),
                         "entry": MJ["entry"], "settings_entry": "", "launchers": [], "source": "user",
                         "disabled": disabled, "state": "disabled" if disabled else "loaded",
                         "installed_version": MJ["version"], "expected_version": ""}], "restart_needed": False}


STAGE_JS = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) {}
    setTimeout(function(){
      var root = document.documentElement, txt = document.body.innerText || '';
      out.themeStyle = !!document.getElementById('fm-appearance-theme-style');
      out.activeAttr = root.getAttribute('data-fm-appearance-active');
      out.printersVisible = txt.indexOf('H2D_01') >= 0 && txt.indexOf('K2-02') >= 0;
      var mods = qa('.ui3-rtabs .ui3-rtabs-mod');
      out.barMods = mods.map(function(b){ return b.getAttribute('aria-label'); });
      out.hscroll = root.scrollWidth > root.clientWidth + 1;
      var btn = mods.filter(function(b){ return /Оформление/.test(b.getAttribute('aria-label') || ''); })[0];
      if (!btn) { res(dump(out)); return; }
      click(btn);
      setTimeout(function(){
        var ed = document.getElementById('fm-appearance-editor');
        out.editor = !!ed;
        if (ed) {
          var r = ed.getBoundingClientRect();
          out.editorRect = [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)];
          out.editorInWindow = r.width > 300 && r.height > 300 && r.left >= -1 && r.top >= -1
            && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1;
          var bs = qa('#fm-appearance-editor button');
          out.tabs = bs.map(function(b){ return (b.textContent || '').trim(); })
            .filter(function(t){ return /^(Темы|Цвета и текст|Фон|Карточки и эффекты)$/.test(t); });
          out.apply = bs.some(function(b){ return (b.textContent || '').trim() === 'Применить'; });
          out.overflowBtns = bs.filter(function(b){ var s = getComputedStyle(b);
            return b.clientWidth > 0 && b.scrollWidth > b.clientWidth + 2 && s.overflowX === 'visible'; })
            .map(function(b){ return (b.textContent || '').trim().slice(0, 30); });
          var close = bs.filter(function(b){ return (b.textContent || '').trim() === 'Закрыть'; })[0];
          out.closeBtn = !!close;
          if (close) click(close);
        }
        setTimeout(function(){
          out.editorAfterClose = !!document.getElementById('fm-appearance-editor');
          out.themeAfterClose = !!document.getElementById('fm-appearance-theme-style');
          res(dump(out));
        }, 1000);
      }, 3000);
    }, 3500);
  }, 1500);
});
"""

for disabled, size in ((False, (1600, 900)), (False, (1280, 800)), (True, (1600, 900))):
    st.set_api({"/api/printers": PRINTERS, "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                "/api/modules": modules_payload(disabled), "/api/farm-settings": {"ok": True, "settings": {}}})
    st.set_live(LIVE)
    tag = "%s %dx%d" % ("отключён" if disabled else "включён", size[0], size[1])
    r = st.run(STAGE_JS, window_size=size, settle_ms=6000, path="/ui3")
    if r is None:
        check("E0. стенд поднялся (%s)" % tag, False, st.last_diag())
        continue
    d = r.pop("__diag", {}) or {}
    errs = (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])
    check("E1. %s: ошибок в консоли нет, горизонтальной прокрутки нет, принтеры на экране" % tag,
          not errs and not r.get("hscroll") and r.get("printersVisible"), (errs[:2], r))
    if disabled:
        check("E2. %s: оформление модуля НЕ применено и кнопки модуля на баре нет" % tag,
              not r.get("themeStyle") and r.get("activeAttr") is None and not r.get("barMods"), r)
        continue
    check("E3. %s: тема модуля применена ко всей программе" % tag, r.get("themeStyle") and r.get("activeAttr") == "1", r)
    check("E4. %s: кнопка «Оформление и темы» на баре открывает редактор с разделами и кнопкой «Применить»" % tag,
          MJ["ru"] in (r.get("barMods") or []) and r.get("editor")
          and r.get("tabs") == ["Темы", "Цвета и текст", "Фон", "Карточки и эффекты"] and r.get("apply"), r)
    check("E5. %s: редактор целиком в окне, надписи не вылезают из кнопок" % tag,
          r.get("editorInWindow") and not r.get("overflowBtns"), (r.get("editorRect"), r.get("overflowBtns")))
    check("E6. %s: «Закрыть» закрывает редактор, применённая тема остаётся" % tag,
          r.get("closeBtn") and not r.get("editorAfterClose") and r.get("themeAfterClose"), r)

# ════════════════════════════════════════════════════════════════════════════
#  09.10.2026, 0.17.4: оформление вида «Дашборд» (второй разработчик, 0.17.3) и дефекты, подтверждённые
#  независимой проверкой: мигание стрелок температуры от округления, пропавший цвет «нагреватель
#  включён», полоска выбранного принтера под «водой», пересчёт всех карточек от блика, нечитаемые
#  подписи состояния на заливке.
section("F. вид «Дашборд» (0.17.4)")

_dc_url = "file:///" + os.path.join(WEB, "dashboard-cards.js").replace("\\", "/")
_dt_url = "file:///" + os.path.join(WEB, "default-theme.js").replace("\\", "/")
_fjs = r"""
const m = await import(%s), dt = await import(%s);
const run = (vals, step) => { let p = null, out = []; vals.forEach((v, i) => { p = m.temperatureTrend(p, Math.round(v), i * step); out.push(p.trend); }); return out; };
const D = dt.DEFAULT_THEME || Object.values(dt).find(x => x && x.dashboard);
const css = m.dashboardCss(D);
console.log(JSON.stringify({
  jitter: run([219.6, 219.4, 219.6, 219.5, 219.4, 219.6, 219.4, 219.6, 219.4, 219.6], 1500),
  ramp: run([25, 28, 32, 37, 43, 50, 58, 66], 1500),
  cool: run([220, 216, 211, 205, 198, 190], 1500),
  settle: run([25, 30, 35, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40], 1500).slice(-1)[0],
  hot: css.includes('.pcd-temps>span.hot{color:var(--fm-ap-dash-heating)!important;}'),
  sel: css.includes('.ui3-sel::before{z-index:1;}'),
  state: css.includes('.pcd-paused .pcd-st{color:var(--fm-ap-dash-state)!important;}'),
}));
""" % (json.dumps(_dc_url), json.dumps(_dt_url))
_fp = os.path.join(TMP, "f_dash.mjs")
io.open(_fp, "w", encoding="utf-8").write(_fjs)
_fr = subprocess.run([NODE, _fp], capture_output=True, text=True, encoding="utf-8", timeout=60)
try:
    F = json.loads(_fr.stdout.strip().splitlines()[-1])
except Exception:
    F = {"__error__": (_fr.stderr or _fr.stdout)[-400:]}
check("F1. неизменная температура около x.5 (на экране 219↔220) — без стрелок: всё «стабильно»",
      F.get("jitter") and set(F["jitter"]) == {"stable"}, F.get("jitter") or F)
check("F2. настоящий нагрев (25→66°) — стрелка ↑, настоящее остывание (220→190°) — ↓",
      F.get("ramp") and F["ramp"][1:] == ["heating"] * 7 and F.get("cool") and F["cool"][1:] == ["cooling"] * 5,
      (F.get("ramp"), F.get("cool")))
check("F3. после остановки нагрева стрелка гаснет через 12 с", F.get("settle") == "stable", F.get("settle"))
check("F4. оформление сохраняет цвет «нагреватель включён» (.hot), полоску выбранного принтера поверх заливки "
      "и читаемый цвет подписи состояния", F.get("hot") and F.get("sel") and F.get("state"), F)
check("F5. блик при наведении не запускает пересчёт карточек (наблюдатель его пропускает, как glass-layer.js)",
      "closest('.'+OWN+',.'+HOVER_GLINT_CLASS)" in JS["dashboard-cards.js"]
      and "import { HOVER_GLINT_CLASS } from './theme-schema.js';" in JS["dashboard-cards.js"])

DASH_PRINTERS = [{"id": "d%d" % i, "name": n, "type": "bambu", "model": "Bambu Lab P1S", "ip": "10.0.0.%d" % (20 + i), "port": 8883}
                 for i, n in enumerate(["ERR", "PAUSE", "DONE", "PRINT91", "PRINT43", "IDLE", "OFF"])]
DASH_LIVE = {
    "d0": {"status": "FAILED", "percent": 30, "file_name": "a.gcode", "nozzle_count": 1, "nozzle_temp": 40, "bed_temp": 30, "hms": []},
    "d1": {"status": "PAUSED", "percent": 40, "remaining_time": 50, "file_name": "b.gcode", "nozzle_count": 1, "nozzle_temp": 200, "bed_temp": 60, "hms": []},
    "d2": {"status": "FINISH", "percent": 100, "file_name": "c.gcode", "nozzle_count": 1, "nozzle_temp": 90, "bed_temp": 40, "hms": []},
    "d3": {"status": "RUNNING", "percent": 91, "remaining_time": 5, "file_name": "d.gcode", "nozzle_count": 1, "nozzle_temp": 215,
           "bed_temp": 55, "nozzle_target": 220, "bed_target": 60, "hms": []},
    "d4": {"status": "RUNNING", "percent": 43, "remaining_time": 84, "file_name": "e.gcode", "nozzle_count": 1, "nozzle_temp": 220,
           "bed_temp": 60, "nozzle_target": 220, "bed_target": 60, "hms": []},
    "d5": {"status": "IDLE", "percent": 0, "nozzle_count": 1, "nozzle_temp": 25, "bed_temp": 25, "hms": []},
}
DASH_JS = r"""
return new Promise(function(res){
  function qa(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }
  function rgb(s){ var m = String(s).match(/rgba?\(([^)]+)\)/); return m ? m[1].split(',').map(parseFloat) : null; }
  function hex(h){ h = String(h).trim(); if (h[0] !== '#') return rgb(h); return [1,3,5].map(function(i){ return parseInt(h.slice(i,i+2),16); }); }
  function lum(c){ var a = c.slice(0,3).map(function(v){ v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }); return .2126*a[0]+.7152*a[1]+.0722*a[2]; }
  function ratio(a, b){ var x = lum(a), y = lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
  function blend(fg, bg){ var al = fg.length > 3 ? fg[3] : 1; return [0,1,2].map(function(i){ return fg[i]*al + bg[i]*(1-al); }); }
  var out = { low: [] };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) {}
    setTimeout(function(){
      var cards = qa('.printer-card.pc-dashcard');
      out.cards = cards.length; out.active = qa('.printer-card.pc-dashcard[data-fm-dash-active]').length;
      out.water = qa('.printer-card.pc-dashcard[data-fm-dash-water="true"]').length;
      cards.forEach(function(c){
        var cs = getComputedStyle(c), base = hex(cs.getPropertyValue('--fm-ap-dash-base')), water = hex(cs.getPropertyValue('--fm-ap-dash-water'));
        if (!base) return;
        var lay = c.querySelector('.fm-ap-dash-water'), path = c.querySelector('.fm-ap-dash-wave path');
        var top = (lay && !lay.hidden && path) ? path.getBoundingClientRect().top : 1e9;
        qa('.pc-dash *', c).forEach(function(el){
          if (el.closest('svg') || !el.childNodes.length) return;
          if (![].slice.call(el.childNodes).some(function(n){ return n.nodeType === 3 && n.textContent.trim(); })) return;
          var s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden') return;
          var r = el.getBoundingClientRect(); if (r.width < 2) return;
          var under = (r.top + r.height / 2) > top + 4 ? water : base, k = ratio(blend(rgb(s.color), under), under);
          if (k < 4.5) out.low.push(el.textContent.trim().slice(0, 20) + ' ' + k.toFixed(2));
        });
      });
      res(dump(out));
    }, 6000);
  }, 3500);
});
"""
for theme in ("dark", "light"):
    st.set_api({"/api/printers": DASH_PRINTERS, "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                "/api/modules": modules_payload(False), "/api/farm-settings": {"ok": True, "settings": {}}})
    st.set_live(DASH_LIVE)
    r = st.run(DASH_JS, window_size=(1600, 1000), settle_ms=7000, path="/ui3?ls=farm_view:dash&ls=farm_theme:" + theme)
    if r is None:
        check("F6. стенд «Дашборда» поднялся (%s)" % theme, False, st.last_diag())
        continue
    d = r.pop("__diag", {}) or {}
    errs = (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])
    check("F6. %s: оформление легло на все 7 карточек «Дашборда», «вода» у печати, паузы и готового, консоль чиста" % theme,
          r.get("cards") == 7 and r.get("active") == 7 and r.get("water") == 4 and not errs, (r, errs[:2]))
    check("F7. %s: каждая строка карточки читаема на своей заливке (не ниже 4.5:1)" % theme, not r.get("low"), r.get("low"))

# ════════════════════════════════════════════════════════════════════════════
#  10.10.2026, 0.17.5 (слово владельца по замечаниям проверки 0.17.3):
#  1) версия модуля, которая не может показать часть тем (их сохранила версия новее), говорит об этом
#     словами, а не показывает пустой «Мои темы» молча; такие темы при сохранении не стираются;
#  4) щелчок по образцу карточки в редакторе открывает настройки карточки, «Dashboard» — только по
#     цифрам и подписям Dashboard;
#  5) одна испорченная тема прячет только себя, а не весь список «Мои темы».
#  Версии до 0.17.5 сами ничего сказать не могут — при установке старой версии поверх новой об этом
#  говорит программа (web/app.js).
section("G. скрытые темы и образец карточки (0.17.5)")

_web_fwd = WEB.replace("\\", "/")
_g_storage = r"""
import { pathToFileURL } from 'node:url';
const WEB = process.argv[2];
const mem = new Map();
globalThis.localStorage = { getItem: k => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) };
const S = await import(pathToFileURL(WEB + '/editor-storage.js').href);
const V = await import(pathToFileURL(WEB + '/theme-validator.js').href);
const D = await import(pathToFileURL(WEB + '/default-theme.js').href);
const R = await import(pathToFileURL(WEB + '/theme-runtime.js').href);
const KEY = 'fm_appearance_library_v4', base = V.cloneTheme(D.default), out = {};
const good = S.themeEntry(base, 'Good'), bad = S.themeEntry(base, 'Bad'); bad.theme.dashboard.percentSize = 12;
const img = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
const future = { id: 'future-1', name: 'Future', theme: { ...V.cloneTheme(base), schemaVersion: D.THEME_SCHEMA_VERSION + 1, futureSection: { x: 1 } } };
future.theme.background = { ...future.theme.background, mode: 'image', imageDataUrl: { asset: 'a777_1' } };
const futureHist = { id: 'future-h', name: 'FutureH', appliedAt: 1000, theme: { ...V.cloneTheme(base), schemaVersion: D.THEME_SCHEMA_VERSION + 1 } };
const put = obj => { mem.clear(); mem.set(KEY, JSON.stringify(obj)); };
const lib = (entries, history = [], assets = {}) => ({ format: '3diwell-appearance-collection', version: 2, entries, history, assets });
const pk = e => S.packCollection([e]).entries[0];
put(lib([pk(good), pk(bad)]));
out.badList = S.readCollection().map(e => e.name); out.badState = S.readLibraryState();
out.badWrite = S.writeCollection([...S.readCollection(), S.themeEntry(base, 'New')]);
out.badKept = JSON.parse(mem.get(KEY)).entries.map(e => e.name);
put(lib([pk(good), future], [futureHist], { a777_1: img }));
const before = JSON.stringify(future), beforeH = JSON.stringify(futureHist);
out.newList = S.readCollection().map(e => e.name); out.newState = S.readLibraryState();
out.newWrite = S.writeCollection([...S.readCollection(), S.themeEntry(base, 'Added')]);
let stored = JSON.parse(mem.get(KEY));
out.futureSame = JSON.stringify(stored.entries.find(e => e.id === 'future-1')) === before;
out.futureAsset = stored.assets.a777_1 === img;
out.newList2 = S.readCollection().map(e => e.name);
out.delWrite = S.writeCollection(S.readCollection().filter(e => e.name !== 'Good'));
out.afterDel = JSON.parse(mem.get(KEY)).entries.map(e => e.name);
out.hist = S.recordAppliedTheme(V.cloneTheme(base));
stored = JSON.parse(mem.get(KEY));
out.histNames = stored.history.map(e => e.name);
out.histFutureSame = JSON.stringify(stored.history.find(e => e.id === 'future-h')) === beforeH;
put(lib([...Array.from({ length: 19 }, (_, i) => pk(S.themeEntry(base, 'T' + i))), future], [], { a777_1: img }));
out.limitWrite = S.writeCollection([...S.readCollection(), S.themeEntry(base, 'Over')]);
put({ ...lib([pk(good)]), version: 3 }); const v3 = mem.get(KEY);
out.v3List = S.readCollection().length; out.v3State = S.readLibraryState();
out.v3Write = S.writeCollection([S.themeEntry(base, 'X')]); out.v3Untouched = mem.get(KEY) === v3;
mem.clear(); mem.set(KEY, '{broken');
out.brokenState = S.readLibraryState(); out.brokenWrite = S.writeCollection([S.themeEntry(base, 'X')]);
out.brokenUntouched = mem.get(KEY) === '{broken';
put(lib([pk(good)]));
const r = S.importCollection(lib([pk(S.themeEntry(base, 'Imp')), future], [], { a777_1: img }));
out.importNames = r.entries.map(e => e.name); out.importSkipped = r.skipped;
try { S.importCollection(lib([future], [], { a777_1: img })); out.importNewer = 'no-throw'; } catch (e) { out.importNewer = e.message; }
mem.clear(); mem.set(KEY, '{broken');
try { S.importCollection(lib([pk(good)])); out.importStore = 'no-throw'; } catch (e) { out.importStore = e.message; }
put(lib([pk(good), future], [], { a777_1: img }));
const exp = S.exportLibrary(S.readCollection());
out.exportNames = exp.entries.map(e => e.name);
out.exportFutureSame = JSON.stringify(exp.entries.find(e => e.id === 'future-1')) === before && exp.assets.a777_1 === img;
const DK = 'fm_appearance_draft_v7', newerDraft = JSON.stringify({ draftVersion: 1, base: 'x', savedAt: 1, theme: { ...base, schemaVersion: D.THEME_SCHEMA_VERSION + 1 } });
mem.set(DK, newerDraft); S.writeDraft(base, base); out.newerDraftKept = mem.get(DK) === newerDraft;
mem.set(DK, JSON.stringify({ draftVersion: 1, base: 'x', savedAt: 1, theme: base })); S.writeDraft(base, base); out.ownDraftCleared = mem.get(DK) === 'null';
mem.clear(); S.writeCollection([good]);
const plain = JSON.parse(mem.get(KEY));
out.plainShape = Object.keys(plain).join(',') + ' ' + plain.entries.length + ' ' + plain.history.length;
const AK = 'fm_appearance_applied_v7', applied = [];
mem.set(AK, JSON.stringify({ ...base, schemaVersion: D.THEME_SCHEMA_VERSION + 1, futureSection: {} })); R.loadAppliedTheme(); applied.push(R.getRuntimeState().appliedHidden);
const badA = V.cloneTheme(base); badA.dashboard.timeSize = '22';
mem.set(AK, JSON.stringify(badA)); R.loadAppliedTheme(); applied.push(R.getRuntimeState().appliedHidden);
mem.set(AK, JSON.stringify(base)); R.loadAppliedTheme(); applied.push(R.getRuntimeState().appliedHidden);
out.applied = applied;
console.log(JSON.stringify(out));
"""
_gp = os.path.join(TMP, "g_storage.mjs")
io.open(_gp, "w", encoding="utf-8").write(_g_storage)
_gr = subprocess.run([NODE, _gp, _web_fwd], capture_output=True, text=True, encoding="utf-8", timeout=60)
try:
    G = json.loads(_gr.stdout.strip().splitlines()[-1])
except Exception:
    G = {"__error__": (_gr.stderr or _gr.stdout)[-600:]}
check("G1. одна испорченная тема прячет только себя: остальные видны, редактор знает «скрыта 1, ошибка»",
      G.get("badList") == ["Good"] and G.get("badState") == {"newer": 0, "invalid": 1, "unreadable": ""}, G)
check("G2. тема из более новой версии не видна, но при сохранении и удалении других остаётся байт в байт, с картинкой фона",
      G.get("newList") == ["Good"] and G.get("newState") == {"newer": 1, "invalid": 0, "unreadable": ""}
      and G.get("newWrite") and G.get("futureSame") and G.get("futureAsset") and G.get("newList2") == ["Good", "Added"]
      and G.get("delWrite") and G.get("afterDel") == ["Added", "Future"] and G.get("badWrite")
      and G.get("badKept") == ["Good", "New", "Bad"], G)
check("G3. история применений хранит скрытую запись; предел в 20 тем считает и скрытые",
      G.get("hist") and G.get("histFutureSame") and len(G.get("histNames") or []) == 2 and G.get("limitWrite") is False, G)
check("G4. весь список в формате новой версии или повреждён: не перезаписывается, редактор знает причину",
      G.get("v3List") == 0 and (G.get("v3State") or {}).get("unreadable") == "newer" and G.get("v3Write") is False
      and G.get("v3Untouched") and (G.get("brokenState") or {}).get("unreadable") == "invalid"
      and G.get("brokenWrite") is False and G.get("brokenUntouched"), G)
check("G5. импорт коллекции — по одной теме: из новой версии не добавляется и называется причина",
      G.get("importNames") == ["Good", "Imp"] and G.get("importSkipped") == {"newer": 1, "invalid": 0}
      and G.get("importNewer") == "newer" and G.get("importStore") == "store", G)
check("G5б. выгрузка «Мои темы» — полная копия: скрытая тема идёт в файл байт в байт, с картинкой",
      G.get("exportNames") == ["Good", "Future"] and G.get("exportFutureSame"), G)
check("G5в. незаконченный черновик более новой версии не затирается при закрытии редактора; свой — как прежде",
      G.get("newerDraftKept") and G.get("ownDraftCleared"), G)
check("G6. без скрытых тем запись в прежнем формате (её читают и прежние версии модуля)",
      G.get("plainShape") == "format,version,entries,history,assets 1 0", G.get("plainShape"))
check("G7. применённая тема: «новее» / «повреждена» / нормальная различаются", G.get("applied") == ["newer", "invalid", ""], G.get("applied"))
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
check("G8. при установке «Оформления» старее прежнего (и после удаления модуля) программа говорит, что темы новой версии могут быть не видны и не удалены",
      "j.id === 'appearance' && (j.older_than_replaced || j.newer_version)" in APPJS
      and "Темы, сохранённые новой версией, старая может не показать — они не удалены и вернутся после установки новой версии." in APPJS)

G_JS = r"""
return new Promise(function(res){
  function qa(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }
  function txt(n){ return (n && n.textContent || '').replace(/\s+/g, ' ').trim(); }
  var out = {}, LANG = '__LANG__', RU = LANG === 'ru', lastSel = null;
  window.addEventListener('message', function(e){ if (e.data && e.data.type === 'fm-appearance-sample-select') lastSel = e.data.target; });
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang(LANG); } catch (e) {}
    var base = location.origin + '/modules/appearance/';
    Promise.all(['editor-storage.js','theme-validator.js','default-theme.js','theme-runtime.js'].map(function(f){ return import(base + f); })).then(function(m){
      var S = m[0], V = m[1], D = m[2], R = m[3], t = V.cloneTheme(D.default);
      var packed = S.packCollection([S.themeEntry(t, 'A1'), S.themeEntry(t, 'A2')]);
      var fut = { id: 'future-1', name: 'Future', theme: Object.assign(V.cloneTheme(t), { schemaVersion: D.THEME_SCHEMA_VERSION + 1, futureSection: { x: 1 } }) };
      var bad = S.themeEntry(t, 'Broken'); bad.theme.dashboard.percentSize = 12;
      packed.entries.push(fut, S.packCollection([bad]).entries[0]);
      localStorage.setItem('fm_appearance_library_v4', JSON.stringify(packed));
      localStorage.setItem('fm_appearance_applied_v7', JSON.stringify(fut.theme));
      R.loadAppliedTheme();
      var btn = qa('.ui3-rtabs .ui3-rtabs-mod').filter(function(b){ return /Оформление|Appearance/.test(b.getAttribute('aria-label') || ''); })[0];
      if (!btn) { out.err = 'no module button'; res(dump(out)); return; }
      click(btn);
      setTimeout(function(){
        var ed = document.getElementById('fm-appearance-editor');
        if (!ed) { out.err = 'no editor'; res(dump(out)); return; }
        out.notices = qa('.ap-storage-notice', ed).map(function(n){
          var r = n.getBoundingClientRect(), p = n.parentElement.getBoundingClientRect();
          return { t: txt(n).slice(0, 40), bad: n.scrollWidth > n.clientWidth + 1 || r.left < p.left - 1 || r.right > p.right + 1 };
        });
        var my = ed.querySelector('details.ap-my-themes');
        out.summary = my ? txt(my.querySelector('summary')) : null;
        if (my) my.open = true;
        setTimeout(function(){
          out.saved = my ? qa('.ap-saved strong', my).map(txt) : [];
          var doc = ed.querySelector('iframe') && ed.querySelector('iframe').contentDocument;
          if (!doc) { out.err = 'no sample'; res(dump(out)); return; }
          var card = doc.querySelector('[data-sample="card"]');
          out.dashActive = card.getAttribute('data-fm-dash-active');
          function at(sel, fx, fy){ var n = doc.querySelector(sel); if (!n) return null; var r = n.getBoundingClientRect(); return [r.left + (fx < 0 ? r.width + fx : fx === 'c' ? r.width / 2 : fx), r.top + (fy === 'c' ? r.height / 2 : fy < 0 ? r.height + fy : fy)]; }
          var steps = [['time', at('.fm-ap-dash-time>strong', 4, 'c')], ['percent', at('#sample-percent', 'c', 'c')], ['temps', at('.pcd-temps>span', 'c', 'c')],
                       ['timeRowEmpty', at('.pcd-line', -6, -4)], ['tempsRowEmpty', at('.pcd-temps', -6, 'c')], ['name', at('#sample-printer-name', 6, 'c')],
                       ['status', at('[data-sample="status"]', 'c', 'c')]];
          var cr = card.getBoundingClientRect();
          for (var gy = 0; gy < 10; gy++) for (var gx = 0; gx < 8; gx++) steps.push(['grid', [cr.left + 4 + (cr.width - 8) * (gx + .5) / 8, cr.top + 4 + (cr.height - 8) * (gy + .5) / 10]]);
          out.clicks = {}; out.grid = {};
          (function next(i){
            if (i >= steps.length) { res(dump(out)); return; }
            lastSel = null; var xy = steps[i][1], el = xy && doc.elementFromPoint(xy[0], xy[1]);
            if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            setTimeout(function(){
              var k = lastSel || 'none';
              if (steps[i][0] === 'grid') out.grid[k] = (out.grid[k] || 0) + 1; else out.clicks[steps[i][0]] = k;
              next(i + 1);
            }, 70);
          })(0);
        }, 700);
      }, 3000);
    }).catch(function(e){ out.err = String(e); res(dump(out)); });
  }, 3500);
});
"""
for lang, size in (("ru", (1280, 800)), ("en", (853, 533))):
    st.set_api({"/api/printers": DASH_PRINTERS, "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                "/api/modules": modules_payload(False), "/api/farm-settings": {"ok": True, "settings": {}}})
    st.set_live(DASH_LIVE)
    tag = "%s %dx%d" % (lang, size[0], size[1])
    r = st.run(G_JS.replace("__LANG__", lang), window_size=size, settle_ms=7000, path="/ui3?ls=farm_view:dash")
    if r is None:
        check("G9. стенд редактора поднялся (%s)" % tag, False, st.last_diag())
        continue
    d = r.pop("__diag", {}) or {}
    errs = (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])
    word = "скрыто" if lang == "ru" else "hidden"
    check("G9. %s: редактор предупреждает о скрытых темах (новее, ошибка, применённая), текст в рамке, счёт «4 / 20 · %s 2», видны 2 темы, консоль чиста" % (tag, word),
          len(r.get("notices") or []) == 3 and not any(n.get("bad") for n in r["notices"])
          and (r.get("summary") or "").endswith("4 / 20 · %s 2" % word) and r.get("saved") == ["A1", "A2"] and not errs,
          (r.get("notices"), r.get("summary"), r.get("saved"), errs[:2], r.get("err")))
    c, g = r.get("clicks") or {}, r.get("grid") or {}
    check("G10. %s: образец — время, процент и температуры открывают «Dashboard», пустое место строк — карточку, имя — текст, подпись состояния — состояние" % tag,
          r.get("dashActive") == "1" and c.get("time") == c.get("percent") == c.get("temps") == "dashboard"
          and c.get("timeRowEmpty") == c.get("tempsRowEmpty") == "card" and c.get("name") == "text" and c.get("status") == "status", c)
    check("G11. %s: большая часть карточки образца ведёт к настройкам карточки (в 0.17.3 — 19%%)" % tag,
          g.get("card", 0) >= 60 and g.get("dashboard", 0) <= 12, g)
st.stop()

# ════════════════════════════════════════════════════════════════════════════
#  16.10.2026 (R-144): чистые функции вида «Дашборд» против НАСТОЯЩЕГО формата ядра. Модуль читает
#  карточку ядра как текст: состояние — по классу pcd-<состояние>, процент — из «42%», крупное время —
#  из строки «{{ dashEta }} {{ tr('left') }}». Сменит ядро формат времени, порядок слов или добавит
#  состояние — крупное время или заливка пропадут молча. Здесь функции ядра (dashState, dashPct,
#  dashEta, convertSecondsToReadable, словарь RU) вынимаются из web/app.js и исполняются вместе с
#  функциями модуля в node.
section("H. «Дашборд»: функции модуля на настоящем выводе ядра (R-144)")

_core = rd(os.path.join(REPO, "web", "app.js"))
_idx = rd(os.path.join(REPO, "web", "index.html"))
_cs = re.search(r"const convertSecondsToReadable = [^\n]*;", _core)
_ds = re.search(r"const dashState = \(pid\) => \{[\s\S]*?\n    \};", _core)
_dp = re.search(r"const dashPct = \(pid\) => [^\n]*;", _core)
_de = re.search(r"const dashEta = \(pid\) => [^\n]*;", _core)
_left = re.search(r'"left": "([^"]*)"', _core)
#  Строка карточки ядра: процент «<b>{{ dashPct }}%</b>», за ним время и слово «осталось/left».
_line = re.search(r"<b>\{\{ dashPct\(p\.id\) \}\}%</b><span v-if=\"dashEta\(p\.id\)\">\{\{ dashEta\(p\.id\) \}\}"
                  r"(\s+)\{\{ tr\('left'\) \}\}</span>", _idx)
check("H0. в ядре найдены функции и разметка строки «Дашборда» (dashState, dashPct, dashEta, время, «осталось»)",
      all((_cs, _ds, _dp, _de, _left, _line)),
      [n for n, v in (("convertSecondsToReadable", _cs), ("dashState", _ds), ("dashPct", _dp), ("dashEta", _de),
                      ("RU left", _left), ("строка pcd-line", _line)) if not v])
if all((_cs, _ds, _dp, _de, _left, _line)):
    _hjs = (
        "const m = await import(%s);\n" % json.dumps(_dc_url)
        + "const wsData = {value: {}}; let LANG = 'ru'; const RU = {left: %s};\n" % json.dumps(_left.group(1))
        + "const tr = (s) => (LANG === 'ru' && RU[s] !== undefined) ? RU[s] : s;\n"
        + "const cardTopAlert = () => null;\n"
        + _cs.group(0) + "\n" + _ds.group(0) + "\n" + _dp.group(0) + "\n" + _de.group(0) + "\n"
        #  Между «}}» и «{{» в шаблоне пробел; Vue (whitespace: condense) выводит один пробел.
        + "const SEP = ' ';\n"
        + r"""
const cls = (state) => ({ classList: { contains: (c) => c === 'pcd-' + state || c === 'printer-card' } });
const line = (pid) => { const e = dashEta(pid); return e ? (e + SEP + tr('left')) : ''; };
const out = { time: {}, pct: {}, state: {}, coreStates: [] };
const TIMES = { m84: 84, m5: 5, m600: 600, m59: 59 };
for (const L of ['ru', 'en']) {
  LANG = L;
  for (const [k, minutes] of Object.entries(TIMES)) {
    wsData.value = { p: { status: 'RUNNING', remaining_time: minutes, percent: 42.4 } };
    const t = line('p');
    out.time[L + ':' + k] = { line: t, split: m.splitDashboardTime(t) };
  }
  wsData.value = { p: { status: 'RUNNING', remaining_time: 0, percent: 42.4 } };
  out.time[L + ':none'] = { line: line('p'), split: m.splitDashboardTime(tr('Printing')) };
}
//  Процент: строка ядра «<b>42%</b>» -> заливка модуля.
for (const [st, p] of [['RUNNING', 42.4], ['PAUSED', 40], ['FINISH', 100], ['IDLE', 0], ['RUNNING', 150], ['RUNNING', -3]]) {
  wsData.value = { p: { status: st, percent: p } };
  const s = dashState('p');
  out.pct[st + ':' + p] = { state: s, text: dashPct('p') + '%', fill: m.dashboardPercent(s, dashPct('p') + '%') };
}
out.pct.garbage = m.dashboardPercent('print', 'abc');
//  Состояния ядра -> состояние модуля (по классу карточки, как в живой разметке).
for (const st of ['RUNNING', 'PREPARE', 'SLICING', 'PAUSED', 'FINISH', 'FAILED', 'OFFLINE', 'IDLE', 'BUSY']) {
  wsData.value = { p: { status: st } };
  const core = dashState('p');
  out.state[st] = { core, mod: m.dashboardState(cls(core)) };
}
//  Стрелки температуры: показание ядра округлено до градуса.
const run = (vals, step) => { let p = null; return vals.map((v, i) => (p = m.temperatureTrend(p, Math.round(v), i * step)).trend); };
out.trend = {
  jitter: run([219, 220, 219, 220, 219, 220, 219, 220], 1500),
  up: run([200, 210, 210, 210, 210, 210, 210, 210, 210, 210], 1500),
};
console.log(JSON.stringify(out));
""")
    _hp = os.path.join(TMP, "h_dash.mjs")
    io.open(_hp, "w", encoding="utf-8").write(_hjs)
    _hr = subprocess.run([NODE, _hp], capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        H = json.loads(_hr.stdout.strip().splitlines()[-1])
    except Exception:
        H = {"__error__": (_hr.stderr or _hr.stdout)[-500:]}
    T = H.get("time") or {}
    _want = {"m84": "1h 24m", "m5": "0h 5m", "m600": "10h 0m", "m59": "0h 59m"}
    _bad_t = []
    for L, word in (("ru", _left.group(1)), ("en", "left")):
        for k, v in _want.items():
            got = (T.get(L + ":" + k) or {}).get("split")
            if got != {"value": v, "label": word}:
                _bad_t.append("%s %s: «%s» -> %s" % (L, k, (T.get(L + ":" + k) or {}).get("line"), got))
    check("H1. крупное время: строка ядра «1h 24m осталось / left» делится модулем на время и подпись "
          "(часы, минуты, только минуты; RU и EN)", not _bad_t and not H.get("__error__"), _bad_t or H.get("__error__"))
    check("H2. без оценки времени (Klipper) ядро пишет состояние — модуль крупное время не рисует, без ошибки",
          (T.get("ru:none") or {}).get("line") == "" and (T.get("ru:none") or {}).get("split") is None
          and (T.get("en:none") or {}).get("split") is None, (T.get("ru:none"), T.get("en:none")))
    P = H.get("pct") or {}
    check("H3. заливка = процент ядра: печать 42%, пауза 40%, готово 100%, свободен 0, больше 100 — 100, мусор — 0",
          (P.get("RUNNING:42.4") or {}).get("fill") == 42 and (P.get("PAUSED:40") or {}).get("fill") == 40
          and (P.get("FINISH:100") or {}).get("fill") == 100 and (P.get("IDLE:0") or {}).get("fill") == 0
          and (P.get("RUNNING:150") or {}).get("fill") == 100 and (P.get("RUNNING:-3") or {}).get("fill") == 0
          and P.get("garbage") == 0, P)
    S = H.get("state") or {}
    #  Модуль знает пять состояний; остальное — «свободен» (заливки нет). «busy» (12.10.2026, «Занят»)
    #  ядро рисует своей подписью, модуль показывает его как свободную карточку — допустимо.
    _bad_s = ["%s: ядро %s, модуль %s" % (k, v.get("core"), v.get("mod")) for k, v in S.items()
              if v.get("mod") != (v.get("core") if v.get("core") in ("offline", "error", "paused", "done", "print") else "idle")
              or v.get("core") not in ("offline", "error", "paused", "done", "print", "idle", "busy")]
    check("H4. каждое состояние ядра (класс pcd-*) понимается модулем; незнакомого ядру модулю состояния нет",
          len(S) == 9 and not _bad_s, _bad_s or S)
    TR = H.get("trend") or {}
    check("H5. температура 219↔220 (округление ядра) — без стрелок; 200→210 — ↑, гаснет через 12 с",
          set(TR.get("jitter") or ["x"]) == {"stable"}
          and (TR.get("up") or [])[1:9] == ["heating"] * 8 and (TR.get("up") or [None])[-1] == "stable", TR)
    #  Непустота: строка с другим порядком слов («осталось 1h 24m») модулю не по зубам — набор это видит.
    _np = os.path.join(TMP, "h_dash_neg.mjs")
    io.open(_np, "w", encoding="utf-8").write(
        "const m = await import(%s);\n" % json.dumps(_dc_url)
        + "console.log(JSON.stringify([m.splitDashboardTime('осталось 1h 24m'), m.splitDashboardTime('1:24 left')]));\n")
    _nr = subprocess.run([NODE, _np], capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        _neg = json.loads(_nr.stdout.strip().splitlines()[-1])
    except Exception:
        _neg = ["ошибка", _nr.stderr[-200:]]
    check("H6. непустота: сменись в ядре порядок слов («осталось 1h 24m»), крупное время пропало бы — набор это ловит",
          _neg[0] is None and _neg[1] == {"value": "1:24", "label": "left"}, _neg)

# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка и уборка")

check("K1. метка-ловушка не попала в код модуля и сборщика",
      not any(SENTINEL in s for s in JS.values()) and SENTINEL not in rd(os.path.join(REPO, "tools", "build_appearance_zip.py")))
shutil.rmtree(TMP, ignore_errors=True)
check("K2. временная папка теста убрана", not os.path.isdir(TMP))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
