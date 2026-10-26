# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.959 — вопросы задаёт программа, а не браузер.

ЗАЧЕМ. «Удалить принтер?», «Остановить печать?», «Печатать всё равно?» — в двадцати с лишним
местах спрашивал сам браузер голым confirm(): чужое серое окно, всегда по центру, кнопки «ОК»
и «Отмена» без объяснения, что именно произойдёт. Заказ владельца: оставить вопросы вопросами,
но дать им наш вид — заголовок, понятный текст, список затрагиваемого и кнопку, названную
действием.

Здесь проверяется ИСПОЛНЕНИЕМ на настоящем пути: правое меню задачи -> «Удалить». Должно
открыться НАШЕ окно; Esc отменяет и ничего не удаляет; кнопка действия удаляет.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_ask_dialog.py
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "ASK_DIALOG_SENTINEL_2_959"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8").read()

print("--- 1. браузерных окон вопросов не осталось ---")
_left = []
for _i, _ln in enumerate(APPJS.splitlines(), 1):
    _t = _ln.strip()
    if _t.startswith("//") or _t.startswith("*"):
        continue
    for _m in re.finditer(r"(?<![.\w])confirm\(", _ln):
        near = _ln[max(0, _m.start() - 16):_m.start() + 12]
        if "askConfirm" in near or "_confirmDelete" in near:
            continue
        _left.append((_i, _t[:80]))
check("1. ни одного вызова confirm() браузера в приложении", not _left, _left[:4])
check("2. и ни одного window.confirm", "window.confirm" not in APPJS)
check("3. вопрос задаётся через askConfirm и возвращает обещание",
      "const askConfirm = (opts) => new Promise((resolve) => {" in APPJS
      and "const confirmAnswer = (yes) => {" in APPJS)
_n = APPJS.count("askConfirm({")
check("4. на своё окно переведены все места (их больше двадцати)", _n >= 20, _n)
check("5. окно есть в разметке: заголовок, текст, список, две кнопки",
      'data-help="ask-confirm"' in IDX and 'class="fm-ask-title"' in IDX
      and 'class="fm-ask-text"' in IDX and 'class="fm-ask-list"' in IDX
      and 'class="fm-ask-btn fm-ask-ok"' in IDX)
check("6. Esc отказывается, щелчок мимо окна тоже",
      '@keydown.esc.prevent="confirmAnswer(false)"' in IDX and '@click.self="confirmAnswer(false)"' in IDX)
check("7. опасное действие отличается видом (красная кнопка и значок корзины)",
      "confirmBox.danger ? 'trash' : 'alert'" in IDX and ".fm-ask-btn.danger{" in CSS)
check("8. стили окна описаны", ".fm-ask-back{" in CSS and ".fm-ask{" in CSS and ".fm-ask-foot{" in CSS)
check("9. удаления отмечены как опасные", APPJS.count("danger: true") >= 6, APPJS.count("danger: true"))
check("10. кнопка названа действием, а не «ОК»",
      "okText: _L('Удалить', 'Delete')" in APPJS and "okText: _L('Запустить', 'Start')" in APPJS
      and "okText: _L('Остановить', 'Stop')" in APPJS)

print()
print("--- 2. настоящее действие в браузере ---")
_ST = [{"filename": "Корпус_редуктора.gcode.3mf", "status": "ready", "printer_id": "", "required_qty": 12,
        "printed_qty": 5, "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True,
        "notes": "", "src_path": "", "linked": False, "missing": False, "project_id": "",
        "project_name": "", "project_sync": False, "compatible_pids": [], "parts": [], "part_total": 0}]

JS = r"""
return new Promise(function(res){
  var out = {};
  var done = function(){ try { res(dump(out)); } catch (e) { res(dump({fatal: String(e)})); } };
  var tab = function(re){ return [].slice.call(document.querySelectorAll('.ui3-rtabs .fm-seg-b')).filter(function(b){ return re.test(b.textContent); })[0]; };
  var menuItem = function(re){ return [].slice.call(document.querySelectorAll('.fm-ctx-item, .ctx-item, [role="menuitem"], .fm-menu-item')).filter(function(b){ return re.test(b.textContent || ''); })[0]; };
  var ask = function(){ return document.querySelector('.fm-ask'); };
  //  Свой список обращений к серверу: стенд их не записывает, а нам нужно знать, ушло ли удаление.
  try {
    window.__calls = [];
    var _f = window.fetch;
    window.fetch = function(u, o){ try { window.__calls.push(String((u && u.url) || u)); } catch (e) {} return _f.apply(this, arguments); };
  } catch (e) {}
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      try { click(tab(/Задачи/)); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        //  Правое меню задачи -> «Удалить»: тот же путь, которым удаляет владелец.
        try {
          var row = document.querySelector('.pvrow.qtpvrow.pvpart .pvname');
          out.hasRow = !!row;
          if (row) row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
        } catch (e) { out.e2 = String(e); }
        setTimeout(function(){
          try {
            var it = menuItem(/Удалить|Delete/);
            out.hasMenuItem = !!it;
            if (it) click(it);
          } catch (e) { out.e3 = String(e); }
          setTimeout(function(){
            try {
              var a = ask();
              out.opened = !!a;
              out.title = a ? ((a.querySelector('.fm-ask-title')||{}).textContent||'').trim() : '';
              out.text = a ? ((a.querySelector('.fm-ask-text')||{}).textContent||'').trim() : '';
              out.okText = a ? ((a.querySelector('.fm-ask-ok')||{}).textContent||'').trim() : '';
              out.danger = a ? /danger/.test(((a.querySelector('.fm-ask-ok')||{}).className||'')) : null;
              out.native = false;   // окно браузера остановило бы сценарий целиком
              out.focusOk = a ? (document.activeElement === a.querySelector('.fm-ask-ok')) : null;
            } catch (e) { out.e4 = String(e); }
            //  Esc — отказ: окно закрывается, задача остаётся.
            try { var a2 = ask(); if (a2) a2.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); } catch (e) { out.e5 = String(e); }
            setTimeout(function(){
              try {
                out.closedByEsc = !ask();
                out.rowsAfterEsc = document.querySelectorAll('.pvrow.qtpvrow.pvpart').length;
              } catch (e) { out.e6 = String(e); }
              //  Повторно открываем и соглашаемся.
              try {
                var row2 = document.querySelector('.pvrow.qtpvrow.pvpart .pvname');
                if (row2) row2.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
              } catch (e) { out.e7 = String(e); }
              setTimeout(function(){
                try { var it2 = menuItem(/Удалить|Delete/); if (it2) click(it2); } catch (e) { out.e8 = String(e); }
                setTimeout(function(){
                  try { var ok = document.querySelector('.fm-ask-ok'); out.hasOk = !!ok; if (ok) click(ok); } catch (e) { out.e9 = String(e); }
                  setTimeout(function(){
                    try {
                      out.closedByOk = !ask();
                      out.deleteCalled = (window.__calls || []).some(function(u){ return /staging\/delete/.test(u); });
                    } catch (e) { out.e10 = String(e); }
                    done();
                  }, 700);
                }, 500);
              }, 500);
            }, 400);
          }, 500);
        }, 500);
      }, 1100);
    }, 2200);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("11. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    check("11. браузерный движок доступен", True)
    stage.set_api({"/api/printers": [], "/api/staging": _ST, "/api/projects2": [],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R = stage.run(JS, window_size=(1600, 950), settle_ms=2600, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not R:
        check("12. окно вопроса проверено", False, str(stage.last_diag())[:250])
    else:
        check("12. правое меню задачи открылось и в нём есть «Удалить»",
              R.get("hasRow") is True and R.get("hasMenuItem") is True,
              (R.get("hasRow"), R.get("hasMenuItem")))
        check("13. открылось НАШЕ окно с заголовком и именем файла",
              R.get("opened") is True and "Удал" in (R.get("title") or "")
              and "Корпус_редуктора" in (R.get("text") or ""),
              (R.get("opened"), R.get("title"), R.get("text")))
        check("14. кнопка названа действием и помечена как опасная",
              R.get("okText") == "Удалить" and R.get("danger") is True,
              (R.get("okText"), R.get("danger")))
        check("15. клавиатура сразу на кнопке действия", R.get("focusOk") is True, R.get("focusOk"))
        check("16. Esc закрывает окно и НИЧЕГО не удаляет",
              R.get("closedByEsc") is True and R.get("rowsAfterEsc") == 1,
              (R.get("closedByEsc"), R.get("rowsAfterEsc")))
        check("17. кнопка действия закрывает окно и удаление уходит на сервер",
              R.get("hasOk") is True and R.get("closedByOk") is True and R.get("deleteCalled") is True,
              (R.get("hasOk"), R.get("closedByOk"), R.get("deleteCalled")))
        _d = R.get("__diag") or {}
        check("18. консоль чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:220])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
