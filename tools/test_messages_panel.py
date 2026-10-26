# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.958 — сообщения программы живут в панели «Подсказки», а не всплывают в углу.

ЗАЧЕМ. Раньше 49 разных сообщений (отправка файла, запуск печати, списание филамента, ошибки
связи и сохранения) всплывали в правом нижнем углу и через три секунды пропадали. Владелец
их не успевал прочитать, а угол экрана они закрывали. Заказ: перенести ВСЕ сообщения в панель
«Подсказки», чтобы ничего не пропадало само.

Здесь проверяется ИСПОЛНЕНИЕМ, на настоящем действии: щелчок по полосе синхронизации, которому
сервер отвечает отказом, обязан оставить сообщение в панели — с временем, крестиком и счётчиком.
Угол экрана на компьютере должен остаться пустым (на телефоне панели нет, там угол сохранён).

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_messages_panel.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "MESSAGES_PANEL_SENTINEL_2_973"
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

print("--- 1. устройство закреплено в файлах ---")
check("1. угол экрана остался только для телефона",
      'v-if="isMobile" class="fm-toasts"' in IDX)
check("2. раздел «Сообщения» стоит в панели подсказок ПЕРВЫМ",
      0 < IDX.find('data-help="suggest-msgs"') < IDX.find('data-help="suggest-sends"')
      < IDX.find('data-help="suggest-queue"'))
#  2.973 (заказ владельца): сообщение живёт, пока оно про «сейчас». Прежнее правило «не
#  исчезает никогда» дало другую крайность — в панели копились строки, которые уже ничего
#  не описывают. Теперь у вида сообщения есть СРОК, а у отдельных сообщений ещё и УСЛОВИЕ.
#  Подсветка «свежее» по-прежнему живёт своей короткой жизнью и сообщение не убирает.
check("3. подсветка снимается таймером, а само сообщение уходит по сроку своего вида",
      "MSG_FRESH_MS" in APPJS and "x.fresh = false" in APPJS
      and "setTimeout(() => dismissToast(id), ms)" not in APPJS
      and "const MSG_LIFE = { ok: 3000, info: 3000, warn: 1200000, bad: 0, work: 0 }" in APPJS
      and "const _msgSweep = () => {" in APPJS)
check("3a. беда и дело в работе сами не исчезают: их закрывает человек или тот, кто их завёл",
      "if (t.pct != null || t.type === 'progress') return true;" in APPJS
      and "return !t.dieAt || now < t.dieAt;" in APPJS)
check("3b. сообщение можно привязать к условию «уже не про сейчас»",
      "t.stale = (opts && typeof opts.stale === 'function') ? opts.stale : null;" in APPJS
      and "stale: () => compatiblePrintersFor(fileArg).length > 0" in APPJS)
check("4. хранится ограниченное число сообщений",
      "MSG_KEEP = 30" in APPJS and "toasts.value.splice(0, toasts.value.length - MSG_KEEP)" in APPJS)
check("5. беда разворачивает свёрнутую панель сама",
      "if (t.type === 'error' || t.type === 'warn')" in APPJS
      and "if (suggestCollapsed.value) toggleSuggestCollapsed()" in APPJS)
check("6. свежее сверху", "const msgView = computed(() => toasts.value.slice().reverse())" in APPJS)
check("7. счётчик на заголовке считает и сообщения",
      "const suggestActiveCount = computed(() => (toasts.value || []).length" in APPJS)
check("8. есть кнопка «Очистить» и крестик у каждого сообщения",
      'class="sg-clear"' in IDX and 'clearMessages()' in IDX and 'dismissToast(t.id)' in IDX)
check("9. виды сообщений описаны стилями",
      ".sg-msg{" in CSS and ".sg-msg.k-ok{" in CSS and ".sg-msg.k-bad{" in CSS
      and ".sg-msg.k-warn{" in CSS and ".sg-msg.fresh{" in CSS and ".sg-msg-bar{" in CSS)
check("10. у дела в работе — колесо и полоса, у удачи — галочка, у беды — знак",
      "msgKind(t) === 'work'" in IDX and "msgKind(t) === 'ok'" in IDX
      and "msgKind(t) === 'bad' || msgKind(t) === 'warn'" in IDX)

print()
print("--- 2. настоящее действие в браузере ---")
#  Сервер отвечает отказом на смену связи с проектом — это тот же путь, что и на живой ферме,
#  когда проект удалён или сервер недоступен.
_ST = [{"filename": "Корпус_редуктора.gcode.3mf", "status": "ready", "printer_id": "", "required_qty": 12,
        "printed_qty": 5, "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True,
        "notes": "", "src_path": "", "linked": False, "missing": False, "project_id": "P1",
        "project_name": "Заказ 17", "project_sync": False, "compatible_pids": [], "parts": [], "part_total": 0}]
_PR = [{"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-01",
        "required_total": 12, "printed_total": 5, "parts_count": 1, "files_count": 1}]

JS = r"""
return new Promise(function(res){
  var out = {};
  var done = function(){ try { res(dump(out)); } catch (e) { res(dump({fatal: String(e)})); } };
  var tab = function(re){ return [].slice.call(document.querySelectorAll('.ui3-rtabs .fm-seg-b')).filter(function(b){ return re.test(b.textContent); })[0]; };
  var msgs = function(){ return [].slice.call(document.querySelectorAll('.sg-msg')); };
  var texts = function(){ return msgs().map(function(m){ return ((m.querySelector('.sg-msg-t')||{}).textContent||'').trim(); }); };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      try { click(tab(/Задачи/)); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        //  Сворачиваем панель: беда обязана развернуть её сама.
        try {
          var fold = document.querySelector('[data-help="suggest-fold"]');
          if (fold && !/▸/.test(fold.textContent)) click(fold);
        } catch (e) { out.e2 = String(e); }
        //  Свернулась ли панель, видно только СЛЕДУЮЩИМ кадром: страница обновляется не мгновенно.
        setTimeout(function(){
        try { out.collapsedBefore = /▸/.test((document.querySelector('[data-help="suggest-fold"]')||{}).textContent || ''); } catch (e) { out.e2b = String(e); }
        try { var b = document.querySelector('.ui3-qtsync .qtsync'); out.hasSyncBtn = !!b; if (b) click(b); } catch (e) { out.e3 = String(e); }
        setTimeout(function(){
          try {
            out.expandedAfter = !/▸/.test((document.querySelector('[data-help="suggest-fold"]')||{}).textContent || '');
            out.texts = texts();
            var m0 = msgs()[0];
            out.kind = m0 ? m0.className : '';
            out.hasTime = m0 ? /^\d\d:\d\d$/.test(((m0.querySelector('.sg-msg-time')||{}).textContent||'').trim()) : false;
            out.hasX = m0 ? !!m0.querySelector('.sg-x') : false;
            out.corner = !!document.querySelector('.fm-toasts');
            out.count = ((document.querySelector('[data-help="suggest-count"]')||{}).textContent||'').trim();
            out.secCount = ((document.querySelector('[data-help="suggest-msgs"] .sg-count')||{}).textContent||'').trim();
          } catch (e) { out.e4 = String(e); }
          //  2.974: ТО ЖЕ САМОЕ сообщение повторно — второй строки быть не должно.
          try { var b2 = document.querySelector('.ui3-qtsync .qtsync'); if (b2) click(b2); } catch (e) { out.e5 = String(e); }
          setTimeout(function(){
            try { out.countAfter2 = msgs().length; } catch (e) {}
            try { var x = document.querySelector('.sg-msg .sg-x'); if (x) click(x); } catch (e) { out.e6 = String(e); }
            setTimeout(function(){
              try { out.afterX = msgs().length; } catch (e) {}
              //  Заводим сообщение снова — теперь проверяем «Очистить».
              try { var b3 = document.querySelector('.ui3-qtsync .qtsync'); if (b3) click(b3); } catch (e) { out.e7 = String(e); }
              setTimeout(function(){
                try { out.beforeClear = msgs().length; } catch (e) {}
                try { var cl = document.querySelector('.sg-clear'); out.hasClear = !!cl; if (cl) click(cl); } catch (e) { out.e8 = String(e); }
                setTimeout(function(){
                  try {
                    out.afterClear = msgs().length;
                    out.sectionGone = !document.querySelector('[data-help="suggest-msgs"]');
                  } catch (e) {}
                  done();
                }, 350);
              }, 800);
            }, 350);
          }, 800);
        }, 900);
        }, 400);
      }, 1100);
    }, 2200);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("11. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    check("11. браузерный движок доступен", True)
    stage.set_api({"/api/printers": [], "/api/staging": _ST, "/api/projects2": _PR,
                   "/api/staging/sync": {"status": "error", "reason": "no_project"},
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R = stage.run(JS, window_size=(1600, 950), settle_ms=2600, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not R:
        check("12. сообщение о неудаче проверено", False, str(stage.last_diag())[:250])
    else:
        check("12. панель была свёрнута, а после неудачи развернулась сама",
              R.get("collapsedBefore") is True and R.get("expandedAfter") is True,
              (R.get("collapsedBefore"), R.get("expandedAfter")))
        _t = R.get("texts") or []
        check("13. сообщение о неудаче попало в панель",
              R.get("hasSyncBtn") is True and len(_t) == 1 and len(_t[0]) > 5, (R.get("hasSyncBtn"), _t))
        check("14. у сообщения есть время и крестик, вид — неудача",
              R.get("hasTime") is True and R.get("hasX") is True
              and ("k-warn" in (R.get("kind") or "") or "k-bad" in (R.get("kind") or "")),
              (R.get("hasTime"), R.get("hasX"), R.get("kind")))
        check("15. в правом нижнем углу на компьютере ничего не всплывает",
              R.get("corner") is False, R.get("corner"))
        check("16. счётчик на заголовке и в разделе показывает сообщения",
              R.get("count") == "1" and R.get("secCount") == "1", (R.get("count"), R.get("secCount")))
        #  2.974: одна и та же строка не встаёт в панель дважды. Владелец видел два одинаковых
        #  предупреждения об одной катушке после перезагрузки страницы — повтор теперь лишь
        #  обновляет время у той строки, что уже стоит.
        check("17. повтор того же сообщения не создаёт вторую строку",
              R.get("countAfter2") == 1, R.get("countAfter2"))
        check("18. крестик убирает сообщение", R.get("afterX") == 0, R.get("afterX"))
        check("19. «Очистить» убирает все, и раздел исчезает",
              R.get("beforeClear") == 1 and R.get("hasClear") is True
              and R.get("afterClear") == 0 and R.get("sectionGone") is True,
              (R.get("beforeClear"), R.get("hasClear"), R.get("afterClear"), R.get("sectionGone")))
        _d = R.get("__diag") or {}
        check("20. консоль чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])

print()
print("--- 3. сообщения уходят сами (2.973) ---")
#  КАК ЭТО ПРОВЕРЯЕТСЯ ЧЕСТНО. Сообщение берётся НАСТОЯЩЕЕ — то же, что в разделе 2: сервер
#  отказал в связи с проектом. Ждать двадцать минут в проверке нельзя, а укорачивать сроки
#  «на время теста» — значит проверить не то, что работает у владельца. Поэтому сроки
#  настоящие, подметальщик настоящий, а вперёд переводятся ЧАСЫ СТРАНИЦЫ. Двумя шагами:
#  через десять минут предупреждение обязано ЕЩЁ БЫТЬ (иначе панель просто всё стирает),
#  а через двадцать пять — уже исчезнуть.
JS_LIFE = r"""
return new Promise(function(res){
  var out = {};
  var msgs = function(){ return [].slice.call(document.querySelectorAll('.sg-msg')); };
  var tab = function(re){ return [].slice.call(document.querySelectorAll('.ui3-rtabs .fm-seg-b')).filter(function(b){ return re.test(b.textContent); })[0]; };
  var real = Date.now;
  var shift = function(min){ Date.now = function(){ return real.call(Date) + min * 60000; }; };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      try { click(tab(/Задачи/)); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        try { var b = document.querySelector('.ui3-qtsync .qtsync'); out.hasBtn = !!b; if (b) click(b); } catch (e) { out.e2 = String(e); }
        setTimeout(function(){
          try { out.born = msgs().length; } catch (e) {}
          shift(10);
          setTimeout(function(){
            try { out.after10 = msgs().length; } catch (e) {}
            shift(25);
            setTimeout(function(){
              try { out.after25 = msgs().length;
                    out.sectionGone = !document.querySelector('[data-help="suggest-msgs"]'); } catch (e) {}
              res(dump(out));
            }, 6500);
          }, 6500);
        }, 900);
      }, 1100);
    }, 2200);
  }, 1500);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [], "/api/staging": _ST, "/api/projects2": _PR,
                   "/api/staging/sync": {"status": "error", "reason": "no_project"},
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R2 = stage.run(JS_LIFE, window_size=(1600, 950), settle_ms=21000, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not R2:
        check("21. проверка срока жизни выполнена", False, str(stage.last_diag())[:200])
    else:
        check("21. настоящее предупреждение попало в панель",
              R2.get("hasBtn") is True and R2.get("born") == 1, (R2.get("hasBtn"), R2.get("born")))
        check("22. через десять минут предупреждение ещё на месте — панель не стирает всё подряд",
              R2.get("after10") == 1, R2.get("after10"))
        check("23. через двадцать пять минут оно ушло само, и раздел сообщений исчез",
              R2.get("after25") == 0 and R2.get("sectionGone") is True,
              (R2.get("after25"), R2.get("sectionGone")))
        _d2 = R2.get("__diag") or {}
        check("24. консоль чистая",
              not (_d2.get("consoleErrors") or _d2.get("pageErrors") or _d2.get("unhandled")),
              json.dumps(_d2, ensure_ascii=False)[:200])
else:
    check("21. браузерный движок доступен (без него проверить нечем)", False, "движка нет")

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
