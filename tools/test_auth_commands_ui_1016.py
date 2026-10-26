# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  16.10.2026 — интерфейс к правкам R-150 (замена подписанного модуля) и R-145 (команды принтеру).
#
#  ЧТО ПРОВЕРЯЕТСЯ НАЖАТИЕМ на настоящей странице (стенд tools/_fm_ui_stage.py: настоящие
#  web/index.html и app.js, ответы /api синтетические, сервер программы не запускается):
#    M. установка модуля поверх подписанного: сервер ответил «нужно подтверждение» — программа
#       спрашивает «Заменить подписанный модуль?», по «Заменить» повторяет запрос с
#       confirm_provenance: true; по «Отмена» второго запроса нет;
#    H. «Остыть» во время печати: сервер отказал 409 heater_off_while_printing на каждую из
#       команд — окно вопроса ОДНО на всю серию, по «Выключить нагрев» каждая команда повторена
#       с force: true; по «Отмена» повторов нет;
#    N. двухсопельный Bambu (H2D): «Сопло L» показывает сопло с номером 1, «Сопло R» — сопло 0
#       (у прошивки и Bambu Studio 0 — основное, правое) — в пульте UI 3.0 и на карточке 2.0;
#       раскладка без горизонтальной прокрутки и с чистой консолью на четырёх размерах окна.
#
#  Ответы сервера на команды подменяются в самой странице (window.fetch): синтетический стенд
#  всегда отвечает 200, а здесь нужны 409 и «нужно подтверждение». Код страницы при этом настоящий.
#
#  Запуск:  python tools/test_auth_commands_ui_1016.py   (0 = пройдено)
# ============================================================================
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (extra,))[:700] if extra != "" else ""))


if not stage.engine_ready():
    check("0. браузерный движок для стенда доступен", False, stage.last_diag())
    print("FAIL: стенд не поднят")
    sys.exit(1)

# ── M. замена подписанного модуля ───────────────────────────────────────────────
JS_MOD = r"""
return new Promise(function(res){
  var calls = [];
  var _f = window.fetch;
  window.fetch = function(u, o){
    if (String(u).indexOf('/api/modules/install-path') >= 0) {
      var b = {}; try { b = JSON.parse((o && o.body) || '{}'); } catch(e) {}
      calls.push(b);
      var out = b.confirm_provenance === true
        ? {status:'ok', id:'demo_free', name:'Демо', version:'1.0.1', restart_required:true, package:'unsigned', replaced_signed:true}
        : {status:'confirm_required', reason:'signed_replaced', id:'demo_free', name:'Демо', version:'1.0.1', installed_version:'1.0.0', new_signed:false};
      return Promise.resolve(new Response(JSON.stringify(out), {status:200, headers:{'Content-Type':'application/json'}}));
    }
    return _f.apply(this, arguments);
  };
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function row(){ return qa('.ex-row').filter(function(r){ return /demo_free\.zip/.test(r.textContent); })[0]; }
  function dbl(el){ if(el) el.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true,view:window})); }
  var out = {};
  openStage('modules', function(){
    steps([
      function(){ click(q('[data-help="set-mod-pick"]')); },
      function(done){ setTimeout(done, 900); },
      function(){ out.rowFound = !!row(); dbl(row()); },
      function(done){ setTimeout(done, 700); },
      function(){ out.asks = qa('.fm-ask').length; out.title = (q('.fm-ask-title')||{}).textContent;
                  out.text = (q('.fm-ask-text')||{}).textContent; out.okText = (q('.fm-ask-ok')||{}).textContent;
                  out.callsBefore = calls.length; click(q('.fm-ask-ok')); },
      function(done){ setTimeout(done, 900); },
      function(){ out.calls1 = calls.slice(); out.asksAfter = qa('.fm-ask').length;
                  out.msg1 = document.body.innerText.indexOf('Модуль установлен') >= 0; },
      function(){ click(q('[data-help="set-mod-pick"]')); },
      function(done){ setTimeout(done, 900); },
      function(){ dbl(row()); },
      function(done){ setTimeout(done, 700); },
      function(){ out.asks2 = qa('.fm-ask').length;
                  var c = qa('.fm-ask-btn').filter(function(b){ return !b.classList.contains('fm-ask-ok'); })[0]; click(c); },
      function(done){ setTimeout(done, 900); },
      function(){ out.calls2 = calls.length - out.calls1.length;
                  out.msg2 = document.body.innerText.indexOf('Установка отменена') >= 0; }
    ], function(){ out.log = FM_LOG; res(dump(out)); });
  }, 'ru');
});
"""
stage.set_api({
    "/api/fs/roots": {"home": "C:/FM_TEST", "quick": [{"name": "FM_TEST", "path": "C:/FM_TEST"}], "drives": []},
    "/api/fs/list": {"status": "ok", "path": "C:/FM_TEST", "parent": "", "crumbs": [],
                     "items": [{"name": "demo_free.zip", "path": "C:/FM_TEST/demo_free.zip", "is_dir": False,
                                "ext": ".zip", "size": 1234, "mtime": 1760000000}]},
})
R = stage.run(JS_MOD, window_size=(1600, 1000), settle_ms=2200, path="/") or {}
stage.set_api(None)
check("M1. файл найден в проводнике и установка запрошена", R.get("rowFound") is True and R.get("callsBefore") == 1, R)
check("M2. ответ «нужно подтверждение» — окно «Заменить подписанный модуль?» с понятным текстом",
      R.get("asks") == 1 and "Заменить подписанный модуль" in str(R.get("title"))
      and "подписанный поставщиком" in str(R.get("text")) and "без подписи" in str(R.get("text"))
      and str(R.get("okText")).strip() == "Заменить", (R.get("title"), R.get("text"), R.get("okText")))
_c1 = R.get("calls1") or []
check("M3. «Заменить» — повторный запрос с confirm_provenance: true, модуль установлен",
      len(_c1) == 2 and "confirm_provenance" not in _c1[0] and _c1[1].get("confirm_provenance") is True
      and R.get("msg1") is True and R.get("asksAfter") == 0, (_c1, R.get("msg1")))
check("M4. «Отмена» — второго запроса нет, программа говорит, что прежний модуль на месте",
      R.get("asks2") == 1 and R.get("calls2") == 1 and R.get("msg2") is True, (R.get("asks2"), R.get("calls2"), R.get("msg2")))
check("M5. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── H и N. двухсопельный Bambu в пульте UI 3.0 ─────────────────────────────────────
PRINTERS = [{"id": "h2d", "name": "H2D-01", "type": "bambu", "model": "Bambu Lab H2D",
             "ip": "192.0.2.21", "port": 8883, "serial": "FIXTURE_SN_H2D", "access_code": ""}]
LIVE = {"h2d": {"status": "RUNNING", "status_raw": "RUNNING", "percent": 30, "remaining_time": 40,
                "nozzle_count": 2, "nozzles": [{"id": 0, "temp": 201, "target": 210},
                                               {"id": 1, "temp": 152, "target": 0}],
                "nozzle_temp": 201, "nozzle_target": 210, "bed_temp": 60, "bed_target": 60,
                "file_name": "korpus", "ams_trays": [], "ext_trays": {}, "new_gen": True}}

JS_PP = r"""
return new Promise(function(res){
  var calls = [];
  var _f = window.fetch;
  window.fetch = function(u, o){
    if (/\/api\/printer\/h2d\/cmd/.test(String(u))) {
      var b = {}; try { b = JSON.parse((o && o.body) || '{}'); } catch(e) {}
      calls.push(b);
      var off = String(b.val) === '0' && /^(nozzle|nozzle_l|nozzle_r|bed)$/.test(b.cmd);
      if (off && !b.force)
        return Promise.resolve(new Response(JSON.stringify({status:'error', reason:'heater_off_while_printing'}), {status:409, headers:{'Content-Type':'application/json'}}));
      return Promise.resolve(new Response(JSON.stringify({status:'ok'}), {status:200, headers:{'Content-Type':'application/json'}}));
    }
    return _f.apply(this, arguments);
  };
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  function rowOf(lb){ return qa('.ui3-pp-temp').filter(function(r){ var l = r.querySelector('.lb'); return l && l.textContent.trim() === lb; })[0]; }
  var out = {};
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0]; if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('H2D-01') >= 0; })[0]; click(card);
      setTimeout(function(){
        var L = rowOf('Сопло L'), Rr = rowOf('Сопло R');
        out.panel = vis(q('.ui3-pp'));
        out.L = L ? (L.querySelector('.cur b')||{}).textContent : null;
        out.R = Rr ? (Rr.querySelector('.cur b')||{}).textContent : null;
        out.Lhot = L ? L.classList.contains('hot') : null;
        out.Rhot = Rr ? Rr.classList.contains('hot') : null;
        out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        if (!window.__fmLayoutOnly) {
          var cool = qa('.ui3-pp button.off').filter(function(b){ return /Остыть/.test(b.textContent); })[0];
          out.coolFound = !!cool; click(cool);
        }
        setTimeout(function(){
          if (window.__fmLayoutOnly) return res(dump(out));
          out.asks = qa('.fm-ask').length; out.title = (q('.fm-ask-title')||{}).textContent;
          out.first = calls.length; click(q('.fm-ask-ok'));
          setTimeout(function(){
            out.calls = calls.slice(); out.asksAfter = qa('.fm-ask').length;
            setTimeout(function(){
              var cool2 = qa('.ui3-pp button.off').filter(function(b){ return /Остыть/.test(b.textContent); })[0];
              var n0 = calls.length; click(cool2);
              setTimeout(function(){
                out.asks2 = qa('.fm-ask').length;
                var c = qa('.fm-ask-btn').filter(function(b){ return !b.classList.contains('fm-ask-ok'); })[0]; click(c);
                setTimeout(function(){
                  out.calls2 = calls.slice(n0);
                  res(dump(out));
                }, 900);
              }, 900);
            }, 1400);
          }, 1200);
        }, 1200);
      }, 1500);
    }, 900);
  }, 1900);
});
"""
stage.set_api({"/api/printers": PRINTERS})
stage.set_live(LIVE)
R = stage.run(JS_PP, window_size=(1600, 1000), settle_ms=2600, path="/ui3") or {}
check("N1. пульт UI 3.0 двухсопельного Bambu: «Сопло L» — сопло 1 (152°), «Сопло R» — сопло 0 (201°)",
      R.get("panel") is True and str(R.get("L")).startswith("152") and str(R.get("R")).startswith("201"),
      (R.get("panel"), R.get("L"), R.get("R")))
check("N2. отметка «греется» — у того сопла, у которого цель задана (правое, сопло 0)",
      R.get("Rhot") is True and R.get("Lhot") is False, (R.get("Lhot"), R.get("Rhot")))
_c = R.get("calls") or []
_first = R.get("first") or 0
_firsts = _c[:_first]
_forced = _c[_first:]
check("H1. «Остыть» во время печати: сервер отказал каждой команде — окно «Выключить нагрев?» ОДНО на серию",
      R.get("coolFound") is True and R.get("asks") == 1 and "Выключить нагрев" in str(R.get("title"))
      and _first >= 3 and all(not x.get("force") for x in _firsts), (R.get("asks"), R.get("title"), _firsts))
check("H2. «Выключить нагрев» — каждая отклонённая команда повторена с force: true, окно закрыто",
      len(_forced) == _first and all(x.get("force") is True and str(x.get("val")) == "0" for x in _forced)
      and sorted(x.get("cmd") for x in _forced) == sorted(x.get("cmd") for x in _firsts)
      and R.get("asksAfter") == 0, (_forced, R.get("asksAfter")))
_c2 = R.get("calls2") or []
check("H3. «Отмена» — повторов с force нет", R.get("asks2") == 1 and _c2 and all(not x.get("force") for x in _c2),
      (R.get("asks2"), _c2))
check("H4. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── N. раскладка на четырёх размерах окна: пульт UI 3.0 и карточка 2.0 ─────────────
JS_CARD = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0]; if (l) l.click();
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('H2D-01') >= 0; })[0];
      var out = {card: !!card};
      if (card) {
        var marks = [].slice.call(card.querySelectorAll('span.font-mono')).filter(function(s){ return /^[LR]$/.test(s.textContent.trim()); });
        marks.forEach(function(m){ var box = m.nextElementSibling; var c = box && box.querySelector('.temp-cell');
                                   out[m.textContent.trim()] = c ? c.textContent.trim() : null; });
      }
      out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      res(dump(out));
    }, 1500);
  }, 1900);
});
"""
for _w, _h in ((1600, 1000), (1280, 800), (1024, 640), (853, 533)):
    _shot = os.environ.get("FM_UI_SHOTS")
    R2 = stage.run(JS_CARD, window_size=(_w, _h), settle_ms=2600, path="/",
                   shot_path=(os.path.join(_shot, "card_%dx%d.png" % (_w, _h)) if _shot else None)) or {}
    check("N3. %dx%d: карточка 2.0 — L = сопло 1 (152°), R = сопло 0 (201°), без горизонтальной прокрутки, консоль чистая"
          % (_w, _h), R2.get("card") is True and str(R2.get("L")).startswith("152") and str(R2.get("R")).startswith("201")
          and R2.get("hscroll") is False and not stage.page_problems(R2), (R2, stage.page_problems(R2)))
    R3 = stage.run("window.__fmLayoutOnly = true;\n" + JS_PP, window_size=(_w, _h), settle_ms=2600, path="/ui3",
                   shot_path=(os.path.join(_shot, "ui3_%dx%d.png" % (_w, _h)) if _shot else None)) or {}
    check("N4. %dx%d: пульт UI 3.0 — L/R по номерам сопел, без горизонтальной прокрутки, консоль чистая" % (_w, _h),
          R3.get("panel") is True and str(R3.get("L")).startswith("152") and str(R3.get("R")).startswith("201")
          and R3.get("hscroll") is False and not stage.page_problems(R3), (R3, stage.page_problems(R3)))
stage.set_api(None)
stage.set_live(None)
stage.stop()

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for f in FAILED:
        print("   - %s" % f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % PASSED[0])
sys.exit(0)
