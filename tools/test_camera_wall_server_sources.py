# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Видеостена: IP-камеры хранятся на сервере, а не только в браузере (16.10.2026).

ЗАЧЕМ. Список IP-камер видеостены жил только в localStorage браузера: добавили камеру на одном
компьютере — на другом её нет, переустановили браузер — список пропал. Теперь список лежит в настройке
фермы на сервере (module_ui.camera_wall.ip_sources, общий механизм настроек модулей), а браузер его
зеркалит. Старая программа, которая module_ui не знает, — молча остаётся список этого браузера.

ЧТО ПРОВЕРЯЕТСЯ (настоящий модуль в настоящем интерфейсе на стенде, нажатиями):
  1. на сервере есть камера — стена показывает её и кладёт копию в браузер;
  2. добавили или удалили камеру — правка ложится на СВЕЖИЙ список сервера: камера, которую тем временем
     добавили на другом компьютере, не пропадает (стена могла быть открыта весь день); две быстрые правки
     подряд не перетирают друг друга;
  3. сервер о списке не знает (старая программа или сорвалось чтение) — стена показывает камеры этого
     браузера и ничего на сервер не пишет, ошибок нет.
Сервер с памятью изображает сама страница (перехват fetch): стенд отдаёт один и тот же ответ и правок не помнит.

Сети наружу нет: стенд на 127.0.0.1, ответы /api синтетические, рабочие данные не трогаются.
Запуск: python tools/test_camera_wall_server_sources.py   (0 = пройдено)
"""
import json
import os
import sys

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""),
          flush=True)
    if not ok:
        fails.append(name)


MODS = {"modules": [{"id": "camera_wall", "ru": "Видеостена", "en": "Camera Wall", "version": "0.4.4", "icon": "camera",
                     "entry": "web/CameraWallPanel.js", "state": "loaded"}]}

#  Общая часть сценария: перехват записи настроек, открытие стены кнопкой бара, чтение списка.
#  SRV — «сервер» с памятью внутри страницы (чтение отвечает с задержкой, как настоящая сеть); null — ответы стенда.
PRE = r"""
var posts = [];
var SRV = null;
var of = window.fetch;
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
function jsonResp(o){ return new Response(JSON.stringify(o), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
window.fetch = function(u, o){
  if (String(u).indexOf('/api/farm-settings') >= 0) {
    var post = !!(o && o.method === 'POST');
    if (post) { try { posts.push(JSON.parse(o.body)); } catch(e) { posts.push('?'); } }
    if (SRV) {
      if (post) { try { SRV.ip = JSON.parse(o.body).module_ui.camera_wall.ip_sources; } catch(e) {} return Promise.resolve(jsonResp({ ok: true })); }
      var snap = SRV.ip.slice();
      return sleep(250).then(function(){ return jsonResp({ ok: true, settings: { module_ui: { camera_wall: { ip_sources: snap } } } }); });
    }
  }
  return of.apply(this, arguments);
};
async function until(fn, ms){ var t = Date.now(); while (Date.now() - t < ms) { var v = fn(); if (v) return v; await sleep(150); } return null; }
function names(){ return Array.prototype.slice.call(document.querySelectorAll('.cw-root .cw-source-name')).map(function(x){ return x.textContent.trim(); }); }
function selectedNames(){ return Array.prototype.slice.call(document.querySelectorAll('.cw-root .cw-source.selected .cw-source-name')).map(function(x){ return x.textContent.trim(); }); }
function ipIds(list){ return (list || []).map(function(c){ return c.id + ':' + c.name; }); }
function lastIp(){ var p = posts[posts.length - 1]; return p && p.module_ui && p.module_ui.camera_wall ? ipIds(p.module_ui.camera_wall.ip_sources) : null; }
async function openWall(){
  var b = await until(function(){ return document.querySelector('.ui3-rtabs-mod'); }, 15000);
  if (!b) return false;
  b.click();
  return !!(await until(function(){ return document.querySelector('.cw-root .cw-add'); }, 15000));
}
"""

JS1 = PRE + r"""
return new Promise(function(res){ (async function(){
  var out = {};
  try {
    SRV = { ip: [SRV_CAM] };
    out.opened = await openWall();
    await until(function(){ return names().indexOf('Склад камера') >= 0; }, 8000);
    out.names0 = names();
    try { out.mirror = JSON.parse(localStorage.getItem('3diwell.camera_wall.ip_sources.v1') || '[]').map(function(c){ return c.id; }); } catch(e) { out.mirror = 'err'; }
    out.posts0 = posts.length;
    out.seeded0 = localStorage.getItem('3diwell.camera_wall.ip_sources.seeded.v1');
    var inputs = document.querySelectorAll('.cw-root .cw-add input.cw-input');
    var setv = function(el, v){ el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); };
    setv(inputs[0], 'Цех 2');
    setv(inputs[1], location.origin + '/assets/icon_192x192.png');
    await sleep(200);
    document.querySelector('.cw-root .cw-add button[type=submit]').click();
    await until(function(){ return posts.length > out.posts0; }, 5000);
    out.afterAdd = lastIp();
    out.names1 = names();
    //  тем временем на другом компьютере добавили камеру — этот браузер о ней ещё не знает
    SRV.ip = SRV.ip.concat([OTHER_CAM]);
    var row = Array.prototype.slice.call(document.querySelectorAll('.cw-root .cw-source')).filter(function(r){ return (r.textContent || '').indexOf('Склад камера') >= 0; })[0];
    var n1 = posts.length;
    if (row) row.querySelector('.cw-source-delete').click();
    await until(function(){ return posts.length > n1; }, 5000);
    out.afterDelete = lastIp();
    await until(function(){ return names().indexOf('Другой ПК') >= 0; }, 3000);
    out.names2 = names();
    try { out.mirror2 = JSON.parse(localStorage.getItem('3diwell.camera_wall.ip_sources.v1') || '[]').map(function(c){ return c.name; }); } catch(e) { out.mirror2 = 'err'; }
    //  две правки подряд, быстрее, чем сервер отвечает на чтение
    var n2 = posts.length;
    setv(inputs[0], 'Быстрая 1'); setv(inputs[1], location.origin + '/assets/icon_192x192.png?q=1');
    await sleep(60);
    document.querySelector('.cw-root .cw-add button[type=submit]').click();
    await sleep(60);
    setv(inputs[0], 'Быстрая 2'); setv(inputs[1], location.origin + '/assets/icon_192x192.png?q=2');
    await sleep(60);
    document.querySelector('.cw-root .cw-add button[type=submit]').click();
    await until(function(){ return posts.length >= n2 + 2; }, 6000);
    await sleep(400);
    out.srvAfterTwo = (SRV.ip || []).map(function(c){ return c.name; });
    out.names3 = names();
    out.selected3 = selectedNames();
  } catch (e) { out.error = String(e && e.stack || e); }
  dump(out); res(true);
})(); });
"""

JS2 = PRE + r"""
return new Promise(function(res){ (async function(){
  var out = {};
  try {
    var setv = function(el, v){ el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); };
    localStorage.setItem('3diwell.camera_wall.ip_sources.v1', JSON.stringify([{ id: 'ip_loc1', sourceKind: 'ip', name: 'Локальная камера',
      url: location.origin + '/assets/icon_192x192.png', mode: 'snapshot', fit: 'contain' }]));
    out.opened = await openWall();
    await until(function(){ return names().indexOf('Локальная камера') >= 0; }, 8000);
    out.names = names();
    await sleep(600);
    out.seedPosts = posts.map(function(p){ return p && p.module_ui ? ipIds(p.module_ui.camera_wall.ip_sources) : p; });
    out.seeded = localStorage.getItem('3diwell.camera_wall.ip_sources.seeded.v1');
    try { out.local = JSON.parse(localStorage.getItem('3diwell.camera_wall.ip_sources.v1') || '[]').map(function(c){ return c.id; }); } catch(e) { out.local = 'err'; }
    var inputs = document.querySelectorAll('.cw-root .cw-add input.cw-input');
    setv(inputs[0], 'Новая здесь'); setv(inputs[1], location.origin + '/assets/icon_192x192.png?n=1');
    await sleep(200);
    document.querySelector('.cw-root .cw-add button[type=submit]').click();
    await sleep(1200);
    out.postsAfterAdd = posts.length;
    out.namesAfterAdd = names();
    try { out.localAfterAdd = JSON.parse(localStorage.getItem('3diwell.camera_wall.ip_sources.v1') || '[]').map(function(c){ return c.name; }); } catch(e) { out.localAfterAdd = 'err'; }
  } catch (e) { out.error = String(e && e.stack || e); }
  dump(out); res(true);
})(); });
"""


def problems(R):
    d = (R or {}).get("__diag") or {}
    return [x for x in (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])] + \
        [w for w in (d.get("consoleWarnings") or []) if "Vue warn" in str(w)]


if not stage.engine_ready():
    check("0. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    port = stage.start()
    SRV_CAM = {"id": "ip_srv1", "name": "Склад камера", "url": "http://127.0.0.1:%d/assets/icon_192x192.png" % port,
               "mode": "snapshot", "fit": "contain"}
    OTHER_CAM = {"id": "ip_oth1", "name": "Другой ПК", "url": "http://127.0.0.1:%d/assets/icon_192x192.png?o=1" % port,
                 "mode": "snapshot", "fit": "contain"}
    JS1 = JS1.replace("SRV = { ip: [SRV_CAM] };", "SRV = { ip: [%s] };" % json.dumps(SRV_CAM, ensure_ascii=False)) \
             .replace("SRV.ip.concat([OTHER_CAM])", "SRV.ip.concat([%s])" % json.dumps(OTHER_CAM, ensure_ascii=False))
    #  1-2: программа знает module_ui, на сервере уже есть камера
    stage.set_api({"/api/modules": MODS, "/api/printers": [],
                   "/api/farm-settings": {"ok": True, "settings": {"module_ui": {"camera_wall": {"ip_sources": [SRV_CAM]}}}}})
    R = stage.run(JS1, window_size=(1600, 1000), settle_ms=2500, path="/ui3")
    if not R:
        check("1. стенд отработал", False, str(stage.last_diag())[:250])
    else:
        check("1. видеостена открылась кнопкой на баре", R.get("opened") is True, R)
        check("2. камера с сервера показана в стене и скопирована в браузер",
              "Склад камера" in (R.get("names0") or []) and R.get("mirror") == ["ip_srv1"], (R.get("names0"), R.get("mirror")))
        check("3. простое открытие стены ничего на сервер не пишет, а браузер помечает, что со списком сервера сверился "
              "(удалённая на другом компьютере камера не вернётся из его копии)",
              R.get("posts0") == 0 and R.get("seeded0") == "1", (R.get("posts0"), R.get("seeded0")))
        _aa = R.get("afterAdd") or []
        check("4. добавили камеру — на сервере список с ней (серверная и новая)",
              len(_aa) == 2 and _aa[0] == "ip_srv1:Склад камера" and _aa[1].endswith(":Цех 2") and "Цех 2" in (R.get("names1") or []),
              (_aa, R.get("names1")))
        _ad = R.get("afterDelete") or []
        check("5. ГЛАВНОЕ: удалили камеру, а на другом компьютере тем временем добавили свою — на сервере уходит только "
              "удалённая, чужая остаётся и появляется в этой стене; браузер зеркалит итог",
              len(_ad) == 2 and _ad[0].endswith(":Цех 2") and _ad[1] == "ip_oth1:Другой ПК"
              and "Склад камера" not in (R.get("names2") or []) and "Другой ПК" in (R.get("names2") or [])
              and R.get("mirror2") == ["Цех 2", "Другой ПК"], (_ad, R.get("names2"), R.get("mirror2")))
        check("5а. две правки подряд, быстрее ответа сервера, — на сервере обе (правки идут по очереди), и обе камеры "
              "остаются на экране стены (промежуточный ответ сервера не снимает вторую)",
              R.get("srvAfterTwo") == ["Цех 2", "Другой ПК", "Быстрая 1", "Быстрая 2"]
              and "Быстрая 1" in (R.get("names3") or []) and "Быстрая 2" in (R.get("names3") or [])
              and "Быстрая 1" in (R.get("selected3") or []) and "Быстрая 2" in (R.get("selected3") or []),
              (R.get("srvAfterTwo"), R.get("names3"), R.get("selected3")))
        check("6. консоль браузера чистая", not problems(R), problems(R)[:3])
    #  3: старая программа — module_ui в настройках нет, а запись с одним module_ui она отклоняет
    #  ({"ok": false, "error": "no_fields"}). Стенд отдаёт один ответ и на чтение, и на запись — этот.
    stage.set_api({"/api/modules": MODS, "/api/printers": [],
                   "/api/farm-settings": {"ok": False, "error": "no_fields", "settings": {}}})
    R2 = stage.run(JS2, window_size=(1600, 1000), settle_ms=2500, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not R2:
        check("7. стенд отработал", False, str(stage.last_diag())[:250])
    else:
        check("7. старая программа: стена показывает камеры этого браузера и не теряет их",
              R2.get("opened") is True and "Локальная камера" in (R2.get("names") or []) and R2.get("local") == ["ip_loc1"], R2)
        check("8. сервер списка не знает — на сервер ничего не пишется (сбой чтения у новой программы иначе затёр бы "
              "камеры других компьютеров), пометки «перенесено» нет — перенос случится, когда сервер ответит",
              R2.get("seedPosts") == [] and R2.get("seeded") is None, (R2.get("seedPosts"), R2.get("seeded")))
        check("8а. добавили камеру при такой программе — она остаётся в этом браузере, на сервер не пишется",
              R2.get("postsAfterAdd") == 0 and "Новая здесь" in (R2.get("namesAfterAdd") or [])
              and R2.get("localAfterAdd") == ["Локальная камера", "Новая здесь"],
              (R2.get("postsAfterAdd"), R2.get("namesAfterAdd"), R2.get("localAfterAdd")))
        check("9. консоль браузера чистая", not problems(R2), problems(R2)[:3])

print("\n" + "=" * 76)
if fails:
    print("FAIL: провалено %d из %d" % (len(fails), len(names)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % len(names))
sys.exit(0)
