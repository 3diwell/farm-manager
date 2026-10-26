# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Ловец морганий: после каждого действия снимаем кадры и ищем то, что мелькнуло.

Что считается морганием:
  • элемент появился и исчез, прожив 1–3 кадра (вспышка);
  • элемент за один кадр прыгнул больше чем на 40 точек или сменил размер больше чем на 40 %
    в первые 12 кадров после действия (скачок при появлении);
  • элемент появился с прозрачностью 0 и стал видимым лишь через несколько кадров, но при этом
    уже «на месте» — это НЕ моргание (плавное появление), не считаем.
Следим за всем, что плавает над страницей: position fixed/absolute, слои #fm-overlay-root,
меню, всплывашки, а также за самим пультом и сменой вкладок.
"""
import importlib.util, json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # папка проекта, где бы она ни лежала
_s = importlib.util.spec_from_file_location("fm_flicker", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

PR = [{"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""},
      {"id": "k1", "name": "K2_Plus_01", "type": "klipper", "model": "Creality K2 Plus",
       "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": ""},
      {"id": "d1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None, "serial": "", "model": "Виртуальный принтер"}]
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-30",
        "required_total": 12, "printed_total": 7, "parts_count": 3, "files_count": 1}
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "pp%d" % i, "part_name": "Деталь_%02d" % i, "required_qty": 12, "printed_qty": i, "status": "in_progress",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1}], "order_idx": i} for i in range(3)]}
_TREE = {"project": _PRJ, "nodes": [{"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True, "compatible_pids": ["b1"],
                                     "target_model": "Bambu Lab X1 Carbon", "filename": "korpus.gcode.3mf", "stored_path": "C:/tmp/korpus.gcode.3mf",
                                     "children": [{"id": "c%d" % i, "name": "Деталь_%02d" % i, "qty": 1} for i in range(3)]}]}
ST = [{"filename": "Куб_%02d.gcode" % i, "status": "ready", "printer_id": "", "required_qty": 10, "printed_qty": i % 10,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "", "linked": False,
       "missing": False, "project_id": "", "project_name": "", "project_sync": False, "compatible_pids": ["b1", "d1"], "parts": [], "part_total": 0}
      for i in range(6)]
LIVE = {"b1": {"status": "RUNNING", "percent": 40, "remaining_time": 60, "nozzle_count": 1, "file_name": "korpus", "ams_now": 0,
               "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"}, {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "#ef4444"}]},
        "k1": {"status": "IDLE", "nozzle_count": 1, "cfs_now": -1, "cfs_trays": [{"index": 0, "type": "PLA", "color": "#f5f5f5"}]},
        "d1": {"status": "IDLE", "nozzle_count": 1}}
stage.set_api({"/api/printers": PR, "/api/staging": ST, "/api/projects2": [_PRJ],
               "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
               "/api/printer/b1/files": ["a.gcode", "b.gcode"], "/api/printer/k1/files": ["c.gcode"], "/api/printer/d1/files": ["d.gcode"],
               "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
               "/api/printer-files/capabilities": {"status": "ok", "read_enabled": True, "delete_enabled": False, "delete_ui_allowed": False,
                                                   "capabilities": {"supported": True, "list_files": True, "delete_files": False}},
               "/api/printer-files/storages": {"status": "ok", "storages": [{"storage_id": "gcodes", "name": "Память", "read_only": True}]},
               "/api/printer-files/list": {"status": "ok", "entries": [], "next_cursor": None}})
stage.set_live(LIVE)

#  Действия: [подпись, JS-выражение, кадров для наблюдения]
ACTIONS = [
    ["простой 4 с на проектах", "0", 260],
    ["вкладка «Задачи»", "click(tab(/Задачи/))", 30],
    ["простой 4 с на задачах", "0", 260],
    ["вкладка «Очередь»", "click(tab(/Очередь/))", 30],
    ["вкладка «Филамент»", "click(tab(/Филамент/))", 30],
    ["вкладка «Проекты»", "click(tab(/Проекты/))", 30],
    ["раскрыть проект", "click(q('[data-help=\"project-card\"]'))", 40],
    ["свернуть проект (Escape)", "esc()", 40],
    ["открыть пульт принтера с камерой", "click(qa('.printer-card')[0])", 60],
    ["вид «Деталь»", "click(vbtn(/Деталь/))", 40],
    ["вид «Камера»", "click(vbtn(/Камера/))", 60],
    ["список файлов пульта", "click(q('.ui3-pp-fsel .ui3-pp-selbtn'))", 30],
    ["закрыть список (Escape)", "esc()", 20],
    ["пульт другого принтера", "click(qa('.printer-card')[1])", 60],
    ["меню катушки (кнопка Печать)", "(function(){ var f = q('.ui3-pp-fsel .ui3-pp-selbtn'); if (f) click(f); setTimeout(function(){ var it = q('.ui3-pp-fit .nm'); if (it) click(it); setTimeout(function(){ var go = q('.ui3-pp-split .ui3-pp-btn.pri'); if (go) click(go); }, 200); }, 300); })()", 60],
    ["Escape (меню)", "esc()", 20],
    ["правый клик по принтеру", "qa('.printer-card')[2].dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 200, clientY: 300}))", 30],
    ["Escape (меню)", "esc()", 20],
    ["«Файлы принтера» из пульта", "click(q('[data-help=\"pp-pfiles\"]'))", 60],
    ["нажатие на принтер при открытом окне", "click(qa('.printer-card')[0])", 60],
    ["закрыть пульт (Escape)", "esc()", 40],
    ["открыть настройки", "click(q('[data-tour=\"settings\"]') || q('[data-help=\"settings\"]'))", 40],
    ["закрыть настройки (Escape)", "esc()", 40],
    ["свернуть подсказки", "click(q('[data-help=\"suggest-fold\"]'))", 30],
    ["развернуть подсказки", "click(q('[data-help=\"suggest-fold\"]'))", 30],
    ["«Добавить» принтер", "click(q('[data-help=\"add-printer\"]'))", 40],
    ["отмена добавления (Escape)", "esc()", 30],
    ["вид сеткой", "click(qa('[data-help=\"pview\"] button, .fm-view-switch button')[1] || q('[data-help=\"pview\"]'))", 40],
    ["вид списком", "click(qa('[data-help=\"pview\"] button, .fm-view-switch button')[0] || q('[data-help=\"pview\"]'))", 40],
    ["вкладка «Задачи» снова", "click(tab(/Задачи/))", 30],
    ["печать задачи: подсветка принтеров", "click(q('.qt-panel .ui3-qtrail'))", 50],
    ["отмена подсветки (Escape)", "esc()", 30],
    ["меню сортировки принтеров", "click(q('[data-help=\"psort\"]'))", 30],
    ["Escape (сортировка)", "esc()", 20],
    ["отметка для очереди (вкл)", "click(q('.ui3-qpick'))", 30],
    ["отметка для очереди (выкл)", "click(q('.ui3-qpick'))", 30],
    ["правый клик по задаче", "q('.qt-panel .pvrow.pvpart').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 900, clientY: 500}))", 30],
    ["Escape (меню задачи)", "esc()", 20],
    ["удалить принтер: вопрос", "(function(){ qa('.printer-card')[2].dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 200, clientY: 300})); setTimeout(function(){ var it = qa('.ctx-menu button, .ctx-menu .ctx-item').filter(function(b){ return /Удалить|Delete/.test(b.textContent); })[0]; if (it) click(it); }, 250); })()", 50],
    ["отказ в вопросе (Escape)", "esc()", 30],
    ["открыть пульт и «Отправить файл»", "(function(){ click(qa('.printer-card')[2]); setTimeout(function(){ var b = q('[data-help=\"pp-upload\"]'); if (b) click(b); }, 900); })()", 80],
    ["закрыть проводник (Escape)", "esc()", 30],
    ["закрыть пульт (Escape)", "esc()", 30],
    ["панель предупреждений", "click(q('.fm-alert-indicator'))", 30],
    ["Escape (панель)", "esc()", 20],
]

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var vbtn = function(re){ return qa('.ui3-pp-seg button, [data-help="pp-view"] button').filter(function(b){ return re.test(b.textContent); })[0]; };
  var esc = function(){ document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); };
  var ACTIONS = __ACTIONS__;
  var ALL_MODE = __ALL__;
  var PRE = __PRE__;
  var report = [];
  function key(el){
    var id = el.getAttribute('data-help') || el.getAttribute('data-tour') || '';
    return el.tagName.toLowerCase() + '.' + String(el.className && el.className.baseVal !== undefined ? '' : (el.className || '')).split(' ').filter(Boolean).slice(0, 3).join('.') + (id ? '#' + id : '');
  }
  function snapshot(){
    var m = {};
    qa('body *').forEach(function(el){
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
      var cs = getComputedStyle(el);
      var pos = cs.position;
      if (ALL_MODE === 0) {
        var floating = (pos === 'fixed' || pos === 'absolute') || el.closest('#fm-overlay-root') || el.matches('.ui3-pp, .ui3-pp-menu, .ctx-menu, .grid-pop, .ui3-pp-fsel, .fm-set-mini, .ui3-camslot');
        if (!floating) return;
      }
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      var eff = parseFloat(cs.opacity), anc = el.parentElement, depth = 0;
      while (anc && anc !== document.body && depth < 10) { var o = parseFloat(getComputedStyle(anc).opacity); if (!(o > 0)) { eff = 0; break; } if (getComputedStyle(anc).visibility === 'hidden') { eff = 0; break; } anc = anc.parentElement; depth++; }
      if (eff === 0) return;
      var r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 24) return;
      if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return;
      var k = key(el);
      if (ALL_MODE) { var pth = [], x = el, dd = 0; while (x && x !== document.body && dd < 6) { var par = x.parentElement; pth.push(par ? Array.prototype.indexOf.call(par.children, x) : 0); x = par; dd++; } k = k + '@' + pth.join('.'); }
      if (m[k] && m[k].n) { m[k].n += 1; return; }
      m[k] = { n: 1, box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], op: parseFloat(cs.opacity) };
    });
    return m;
  }
  function analyse(frames, label){
    var seen = {};
    frames.forEach(function(f, i){ Object.keys(f).forEach(function(k){ (seen[k] = seen[k] || []).push(i); }); });
    var found = [];
    Object.keys(seen).forEach(function(k){
      var idx = seen[k];
      var first = idx[0], last = idx[idx.length - 1];
      var life = last - first + 1;
      //  вспышка: жил 1-3 кадра и исчез до конца наблюдения (не был в последнем кадре)
      if (life <= 3 && last < frames.length - 1 && frames[first][k].op > 0) found.push({ kind: 'вспышка', el: k, frames: [first, last], box: frames[first][k].box });
      //  скачок: в первых 12 кадрах после появления координаты/размер прыгнули
      for (var j = 1; j < idx.length && idx[j] < first + 12; j++) {
        var a = frames[idx[j - 1]][k], b = frames[idx[j]][k];
        if (!a || !b || a.op === 0 || b.op === 0) continue;
        var dx = Math.abs(a.box[0] - b.box[0]), dy = Math.abs(a.box[1] - b.box[1]);
        var dw = Math.abs(a.box[2] - b.box[2]) / Math.max(1, a.box[2]), dh = Math.abs(a.box[3] - b.box[3]) / Math.max(1, a.box[3]);
        if (dx > 40 || dy > 40 || dw > 0.4 || dh > 0.4) { found.push({ kind: 'скачок', el: k, frames: [idx[j - 1], idx[j]], from: a.box, to: b.box }); break; }
      }
    });
    report.push({ action: label, anomalies: found, frames: frames.length });
  }
  function runAction(i){
    if (i >= ACTIONS.length) { res(dump({ report: report })); return; }
    var a = ACTIONS[i];
    var frames = [];
    try { eval(a[1]); } catch (e) { report.push({ action: a[0], error: 'цель не найдена: ' + String(e).slice(0, 60) }); runAction(i + 1); return; }
    var n = 0;
    function tick(){ frames.push(snapshot()); n++; if (n < a[2]) requestAnimationFrame(tick); else { analyse(frames, a[0]); setTimeout(function(){ runAction(i + 1); }, 500); } }
    requestAnimationFrame(tick);
  }
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) {}
    setTimeout(function(){ try { if (PRE) eval(PRE); } catch (e) { report.push({ action: 'подготовка', error: String(e) }); } setTimeout(function(){ runAction(0); }, 1200); }, 1600);
  }, 1500);
});
"""
ALL = int(os.environ.get("FM_AUDIT_ALL", "0"))
PATH = os.environ.get("FM_AUDIT_PATH", "/ui3")
PRE = os.environ.get("FM_AUDIT_PRE", "")
JS = JS.replace("__ACTIONS__", json.dumps(ACTIONS, ensure_ascii=False)).replace("__ALL__", str(ALL)).replace("__PRE__", json.dumps(PRE))
r = stage.run(JS, window_size=(1920, 1080), settle_ms=90000, path=PATH)
rep = (r or {}).get("report") or []
total = 0
for item in rep:
    an = item.get("anomalies") or []
    if item.get("error"):
        print("!! %-42s ОШИБКА ДЕЙСТВИЯ: %s" % (item["action"], item["error"][:120]))
        continue
    if not an:
        print("   %-42s чисто (%d кадров)" % (item["action"], item.get("frames", 0)))
        continue
    total += len(an)
    print(">> %-42s аномалий: %d" % (item["action"], len(an)))
    for a in an[:6]:
        print("      %s %s кадры %s %s" % (a["kind"], a["el"], a["frames"], a.get("box") or (str(a.get("from")) + " -> " + str(a.get("to")))))
d = (r or {}).get("__diag") or {}
print("итого аномалий:", total, "| консоль:", ((d.get("consoleErrors") or []) + (d.get("pageErrors") or []))[:1] or "чисто")
