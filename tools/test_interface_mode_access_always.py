# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-132 (решение владельца 29.09.2026) — «Режим интерфейса» вместо «Редакции»; «Доступ и аудит» всегда.

ЧТО ЗАЩИЩАЕТ. Выбор «Индивидуальный / Коллективный / Корпоративный» в настройках выглядел как платные
редакции ядра и по умолчанию («Коллективный») прятал раздел «Доступ и аудит» — а вместе с ним окно
«Пользователи», журнал аудита и отзыв запомненных телефонов. Это защита фермы, а не платная
возможность. Теперь:
  1. раздел «Доступ и аудит» показывается при ЛЮБОМ режиме: в списке скрываемого ни у одного режима
     нет 'security', а у раздела нет условия edHas(...);
  2. подпись выбора — «Режим интерфейса» / «Interface mode», у выбора подсказка «Меняет только набор
     видимых разделов. Все функции программы бесплатны; платными бывают только отдельные модули.»
     (и английская); названия трёх вариантов прежние; тур и карточка «О программе» не называют выбор
     редакцией и не обещают, что «старшая открывает больше»; инструкции к телефону (docs/user/android.md,
     docs/ANDROID_REMEMBER_DEVICE.md) не отправляют в «Редакцию» и ведут через вкладку «Система»;
  3. остальное поведение прежнее: «Индивидуальный» по-прежнему прячет проекты и сроки, панель
     подсказок видна в любом режиме, по умолчанию — «Коллективный».

В НАСТОЯЩЕМ браузере на стенде (настоящие web/index.html, app.js, app.css; /api синтетический, вход
включён, пользователь — администратор) для каждого режима в интерфейсах 2.0 и 3.0: вкладка «Система»
показывает раздел «Доступ и аудит» с «Пользователями» и «Журналом аудита»; окно «Пользователи»
открывается, в нём список телефонов с кнопкой «Отозвать»; во вкладке «Общие» подпись «Режим
интерфейса»; ошибок консоли и предупреждений Vue нет.

Запуск:  python tools/test_interface_mode_access_always.py      (0 = всё в порядке)
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))


def _read(*p):
    return io.open(os.path.join(REPO, *p), encoding="utf-8").read()


APP = _read("web", "app.js")
IDX = _read("web", "index.html")
HH = _read("web", "composables", "helpHints.js")
TOUR = _read("web", "composables", "tourSteps.js")

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:500]) if detail else ""))


HINT_RU = "Меняет только набор видимых разделов. Все функции программы бесплатны; платными бывают только отдельные модули."
HINT_EN = "Only changes which sections are visible. All program features are free; only some separate modules are paid."

print("--- 1. Что прячет режим ---")
m = re.search(r"const _editionRemoved = (\{[^}]*\});", APP)
removed = None
if m:
    try:
        removed = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)).replace("'", '"'))
    except Exception as e:  # noqa: BLE001
        removed = None
check("1.1 список скрываемого по режимам найден и разобран", isinstance(removed, dict)
      and set(removed) == {"basic", "advanced", "pro"}, m.group(1) if m else "нет _editionRemoved")
removed = removed or {}
check("1.2 ни один режим не прячет «Доступ и аудит» ('security')",
      all("security" not in (v or []) for v in removed.values()), removed)
check("1.3 остальное прежнее: «Индивидуальный» прячет проекты и сроки, «Корпоративный» — ничего",
      removed.get("basic") == ["projects", "dates"] and removed.get("pro") == [], removed)
check("1.4 панель подсказок и модули не прячутся ни в одном режиме",
      all(("suggestions" not in v and "modules" not in v) for v in removed.values()), removed)
check("1.5 по умолчанию режим «Коллективный», выбор хранится в этом браузере",
      "const appEdition = ref('advanced');" in APP and "localStorage.getItem('farm_edition')" in APP)

sec = re.search(r'<div class="fm-set-group" id="fm-sec-acc"[^>]*>', IDX)
check("1.6 у раздела «Доступ и аудит» нет условия по режиму", sec is not None and "edHas" not in sec.group(0)
      and "v-if" not in sec.group(0), sec.group(0) if sec else "нет #fm-sec-acc")
check("1.7 в разметке нигде нет edHas('security')", "edHas('security')" not in IDX and "edHas('security')" not in APP)

print("--- 2. Подписи и подсказка ---")
prog = IDX[IDX.find('data-tour="set-edition"'):IDX.find('data-tour="set-about"')]
check("2.1 подпись выбора — «Режим интерфейса» / «Interface mode»",
      "{{ lang==='ru'?'Режим интерфейса':'Interface mode' }}" in prog, prog[:300])
check("2.2 прежней подписи «Версия программы» / «Edition» у выбора нет",
      "'Версия программы':'Edition'" not in IDX and "'Редакция':'Edition'" not in IDX)
line = re.search(r'<div class="fm-set-line" data-help="set-edition">.*?</select>', prog, re.S)
check("2.3 подсказка навешена на строку выбора", line is not None and "setEdition(" in line.group(0))
opts = re.findall(r'<option value="(\w+)">\{\{ lang===\'ru\'\?\'([^\']+)\':\'([^\']+)\' \}\}</option>', line.group(0) if line else "")
check("2.4 три варианта с прежними названиями",
      opts == [("basic", "Индивидуальный", "Personal"), ("advanced", "Коллективный", "Team"),
               ("pro", "Корпоративный", "Business")], opts)
hh = re.search(r'"set-edition": \{(.*?)\n  \}', HH, re.S)
hh = hh.group(1) if hh else ""
check("2.5 подсказка по-русски — ровно решение владельца",
      'title: "Режим интерфейса"' in hh and ('text: "%s"' % HINT_RU) in hh, hh)
check("2.6 подсказка по-английски", 'title: "Interface mode"' in hh and ('text: "%s"' % HINT_EN) in hh, hh)
check("2.7 карточка «О программе» называет выбор режимом интерфейса",
      "<span class=\"k\">{{ lang==='ru'?'Режим интерфейса':'Interface mode' }}</span>" in IDX)
tour = re.search(r'"id": "settings-edition".*?\n    \}', TOUR, re.S)
tour = tour.group(0) if tour else ""
check("2.8 шаг тура: «Interface mode», без обещания «старшая редакция открывает больше»",
      '"title": "Interface mode"' in tour and "unlock" not in tour and "edition" not in tour.replace("settings-edition", "")
      .replace("set-edition", ""), tour)
check("2.9 у шага тура есть русский перевод",
      '"Interface mode": "Режим интерфейса",' in APP
      and '"Choose the interface mode. It only changes which sections are visible. All program features are free; '
          'only some separate modules are paid.": "Выберите режим интерфейса.' in APP)
check("2.10 подсказки и тур больше не говорят «старшая редакция открывает больше разделов»",
      "Старшая редакция открывает больше разделов." not in HH and "A higher edition unlocks" not in HH
      and "Higher editions unlock" not in TOUR)
DOC_USER = _read("docs", "user", "android.md")
DOC_DEV = _read("docs", "ANDROID_REMEMBER_DEVICE.md")
check("2.11 инструкции к телефону не отправляют в «Редакцию» и не говорят «виден в редакции «Корпоративный»»",
      not re.search(r"редакц|Корпоратив|Общие → Редакция", DOC_USER + DOC_DEV),
      [l for l in (DOC_USER + DOC_DEV).splitlines() if re.search(r"редакц|Корпоратив", l)])
check("2.12 путь к отзыву телефона — через вкладку «Система»",
      "Настройки → Система → Доступ и аудит" in DOC_USER
      and "Настройки → Система → Доступ и аудит → Пользователи" in DOC_DEV
      and "Настройки → Доступ и аудит" not in DOC_DEV.replace("\n", " ").replace("  ", " "))

print("--- 3. Настоящий браузер ---")
import _fm_ui_stage as stage  # noqa: E402

AUTH = {"enabled": True, "user": {"username": "admin", "role": "admin"}}
USERS = {"users": [{"id": "u1", "username": "admin", "role": "admin", "is_active": True},
                   {"id": "u2", "username": "operator1", "role": "operator", "is_active": True}],
         "me": "u1",
         "devices": [{"id": "d1", "name": "Pixel 8", "username": "operator1", "last_seen": 1759100000, "current": False}]}

JS = r"""
function vm(){ var a = document.getElementById('app'); return a && a._vnode && a._vnode.component && a._vnode.component.proxy; }
function vis(e){ if(!e) return false; var b=e.getBoundingClientRect(); return b.width>0 && b.height>0 && getComputedStyle(e).display!=='none'; }
var R = {log: FM_LOG};
return new Promise(function(RES){
  steps([
    function(){ var b = byText('button', ['Позже', 'Later']); if (b) click(b); },
    function(){ setUiLang(__LANG__); },
    function(){ var p = vm(); R.mode = p ? p.appEdition : null;
      R.ed = p ? {projects: p.edHas('projects'), dates: p.edHas('dates'), security: p.edHas('security')} : null; },
    function(){ if(!document.querySelector('.fm-set-scroll')) click(gear()); },
    function(){ if(!document.querySelector('.fm-set-scroll')) click(gear()); },
    function(){ click(byText('.fm-set-nav-item', FM_TABS.general)); },
    function(){ var l = document.querySelector('[data-help="set-edition"].fm-set-line .fm-set-lbl');
      R.label = l ? (l.textContent||'').trim() : null;
      var s = document.querySelector('[data-help="set-edition"].fm-set-line select'); R.selValue = s ? s.value : null; },
    function(){ click(byText('.fm-set-nav-item', FM_TABS.system)); },
    function(d){ setTimeout(d, 300); },
    function(){ var s = document.getElementById('fm-sec-acc'); R.accPresent = !!s; R.accVisible = vis(s);
      R.accText = s ? (s.textContent||'').replace(/\s+/g,' ').trim().slice(0, 300) : '';
      var bs = s ? [].slice.call(s.querySelectorAll('button.fm-set-act')).map(function(b){ return (b.textContent||'').trim(); }) : [];
      R.accButtons = bs;
      var u = s ? [].slice.call(s.querySelectorAll('button.fm-set-act')).filter(function(b){ return /Пользователи|Users/.test(b.textContent||''); })[0] : null;
      R.usersBtn = !!u; if (u) click(u); },
    function(d){ setTimeout(d, 600); },
    function(){ var c = document.querySelector('.fm-users-card'); R.usersOpen = vis(c);
      var rv = document.querySelector('.fm-users-dev-rev'); R.revoke = rv ? (rv.textContent||'').trim() : null; R.revokeVisible = vis(rv); }
  ], function(){ dump(R); RES(true); });
});
"""

LABEL = {"ru": "Режим интерфейса", "en": "Interface mode"}

if not stage.engine_ready():
    check("3.0 браузерный движок доступен", False, stage.last_diag())
else:
    stage.set_api({"/api/auth/status": AUTH, "/api/auth/users": USERS})
    try:
        for path in ("/", "/ui3"):
            for mode, lang in (("basic", "ru"), ("advanced", "en"), ("pro", "ru")):
                tag = "%s, режим %s, %s" % ("интерфейс 3.0" if path == "/ui3" else "интерфейс 2.0", mode, lang.upper())
                res = stage.run(JS.replace("__LANG__", '"%s"' % lang), window_size=(1440, 900), settle_ms=2500,
                                path="%s?ls=farm_edition:%s" % (path, mode)) or {}
                check("%s: прогон состоялся, выбран нужный режим" % tag,
                      res.get("mode") == mode and res.get("selValue") == mode, res.get("log") or res or stage.last_diag())
                check("%s: подпись выбора «%s»" % (tag, LABEL[lang]), res.get("label") == LABEL[lang], res.get("label"))
                check("%s: раздел «Доступ и аудит» на месте и виден" % tag,
                      res.get("accPresent") is True and res.get("accVisible") is True, res.get("accText"))
                btns = " | ".join(res.get("accButtons") or [])
                check("%s: в разделе «Пользователи» и «Журнал аудита»" % tag,
                      re.search(r"Пользователи|Users", btns) and re.search(r"Журнал аудита|Audit log", btns), btns)
                check("%s: окно «Пользователи» открывается, телефон можно отозвать" % tag,
                      res.get("usersOpen") is True and res.get("revokeVisible") is True
                      and res.get("revoke") in ("Отозвать", "Revoke"), (res.get("usersOpen"), res.get("revoke")))
                ed = res.get("ed") or {}
                exp = {"projects": mode != "basic", "dates": mode != "basic", "security": True}
                check("%s: остальное поведение режима прежнее %s" % (tag, exp), ed == exp, ed)
                probs = stage.page_problems(res) if res else ["прогон не состоялся: %s" % stage.last_diag()]
                check("%s: ошибок консоли нет" % tag, not probs, probs)
    finally:
        stage.set_api(None)
        stage.stop()

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for f in _fail:
        print("   - " + f)
sys.exit(1 if _fail else 0)
