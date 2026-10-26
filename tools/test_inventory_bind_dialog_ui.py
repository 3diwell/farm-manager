# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Окно привязки катушки в складском учёте — inventory 1.7.28.
#
# ДЕФЕКТ, КОТОРЫЙ ЗАКРЫТ. В разделе «Склад → В работе» кнопки «+ Привязать внешняя» и «+»
# у свободного слота подачи роняли ВЕСЬ модуль: окно склада исчезало и больше не открывалось
# без перезагрузки страницы. Воспроизводилось на Bambu P2S, Bambu H2S и Creality K2 Plus;
# на FlashForge AD5M всё работало.
#
# ПРИЧИНА (найдена измерением, а не чтением). Шаблон окна привязки просит у компонента два
# имени, которых компонент не отдавал:
#   * `bindSlotName(sl)` — функция объявлена в setup, но её не было в объекте return;
#   * `bindSlotsTitle`   — не была объявлена вовсе.
# Ветка со списком слотов строится по условию `bindSlots.length > 1`, поэтому у принтера
# с одной позицией подачи (AD5M — только внешняя) она не строилась, и он работал. У принтеров
# с коробом слотов больше одного: ветка строилась, обращение к отсутствующему имени прерывало
# отрисовку панели, и телепортированное окно склада заменялось пустым узлом.
#
# ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ — поведением в НАСТОЯЩЕМ браузере, а не строками:
#   1. настоящий модуль монтируется настоящим Vue, окно склада отрисовано;
#   2. по НАСТОЯЩЕМУ клику по кнопке «+ Привязать внешняя» открывается окно привязки;
#   3. то же по клику «+» у свободного слота подачи;
#   4. окно склада при этом остаётся на месте (в этом и был дефект);
#   5. после «Отмена» человек возвращается в склад и может нажать снова;
#   6. подпись над списком слотов называет систему подачи принтера: CFS у Creality, AMS у Bambu;
#   7. имена слотов подписаны так, как их показывает сам принтер (T1A…T1D у CFS);
#   8. НЕ ВАКУУМ: тот же сценарий на версии модуля БЕЗ `bindSlotName` в return — окно склада
#      гибнет. То есть проверка ловит именно тот дефект, о котором написана.
#
# Ядро Farm Manager не изменялось: страница поднимается штатной сценой UI-тестов, модуль
# грузится с того же адреса, что и в работе.
#
# Запуск:  python tools/test_inventory_bind_dialog_ui.py      (0 = всё в порядке)
# ============================================================================
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                              # noqa: E402

PANEL = io.open(os.path.join(REPO, "modules", "inventory", "web", "InventoryPanel.js"),
                encoding="utf-8").read()

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


# ── Состав фермы ровно той формы, что отдаёт backend модуля ─────────────────────────────────
def _slots(n, feed, labels=None):
    return [{"index": i, "unit": 0, "tray": i, "type": "", "color": "",
             "label": (labels[i] if labels else ""), "feed": feed, "spool": None}
            for i in range(n)]


def _ext():
    return {"index": -1, "unit": None, "tray": None, "type": "", "color": "",
            "external": True, "spool": None}


PRINTERS = [
    {"printer_id": "AD5M", "printer_name": "FlashForge AD5M", "has_ams": False, "feed": "",
     "slots": [_ext()]},
    {"printer_id": "P2S", "printer_name": "Bambu P2S", "has_ams": True, "feed": "ams",
     "slots": [_ext()] + _slots(4, "ams")},
    {"printer_id": "H2S", "printer_name": "Bambu H2S", "has_ams": True, "feed": "ams",
     "slots": [_ext()] + _slots(4, "ams")},
    {"printer_id": "K2P", "printer_name": "Creality K2 Plus", "has_ams": True, "feed": "cfs",
     "slots": [_ext()] + _slots(4, "cfs", ["T1A", "T1B", "T1C", "T1D"])},
    #  16.10.2026 (R-137): H2D без AMS — две внешние катушки, левая (-2) и правая (-1); backend
    #  отдаёт их по возрастанию номера, с пометкой стороны.
    {"printer_id": "H2D", "printer_name": "Bambu H2D", "has_ams": False, "feed": "",
     "slots": [dict(_ext(), index=-2, ext_side="left"), dict(_ext(), ext_side="right")]},
]
SPOOL = {"id": 101, "material": "PETG", "color_hex": "#9ea7ae", "color_name": "серый",
         "vendor_name": "Generic", "weight_remaining_g": 900, "status": "in_stock",
         "ams_printer_id": None, "ams_slot": None}

stage.set_api({
    "/api/mod/inventory/ams": {"printers": PRINTERS},
    "/api/mod/inventory/filament": {"vendors": [{"id": 1, "name": "Generic"}],
                                    "filaments": [], "spools": [SPOOL]},
    "/api/mod/inventory/items": {"items": []},
    #  Разделы отдаём в той же форме, что backend: пустой объект вместо списков роняет
    #  отрисовку ещё до нажатий, и проверка меряла бы не то.
    "/api/mod/inventory/cost": {"by_material": [], "by_file": [], "spent": 0,
                               "filament_value": 0, "parts_value": 0, "total_value": 0},
    "/api/mod/inventory/settings": {"currency": "RUB", "low_filament_g": 100},
    "/api/mod/inventory/forecast": {"spools": []},
    "/api/mod/inventory/locations": {"locations": []},
})

#  Сценарий в браузере. Модуль берётся по тому же адресу, что и в работе; вариант BREAK —
#  тот же файл с вырезанным именем в return: так проверяется, что проверка не пустая.
JS = r"""
return new Promise(function(res){
  (async function(){
    var out = { rows: [], errs: [], fatal: '', broken: false };
    try {
      var V = await import('/vendor/vue.esm-browser.js');
      var url = '/modules/inventory/InventoryPanel.js';
      if (__BREAK__) {
        var src = await (await fetch(url)).text();
        var cut = src.replace('bindSlots, bindSlotName, bindSlotsTitle,', 'bindSlots,');
        out.broken = (cut !== src);
        // 1.7.36: окно склада подключает соседние файлы модуля (./InventoryI18n.js). Из blob:-адреса
        // ссылка не разрешается ни относительная, ни от корня сайта — даём полный адрес модуля.
        cut = cut.split("from './").join("from '" + location.origin + "/modules/inventory/");
        url = URL.createObjectURL(new Blob([cut], { type: 'text/javascript' }));
      }
      var M = await import(url);
      var host = document.createElement('div');
      document.body.appendChild(host);
      var app = V.createApp(M.default, { open: true, lang: 'ru', startTab: 'filament',
                                         access: { contractVersion: 1, can: function(){ return true; } } });
      app.config.errorHandler = function(e){ out.errs.push(String((e && e.message) || e)); };
      var vm = app.mount(host);
      var tick = function(ms){ return new Promise(function(r){ setTimeout(r, ms || 160); }); };
      await tick(700);                                   // даём модулю догрузить свои разделы
      vm.tab = 'warehouse'; vm.wmode = 'work';           // «Склад -> В работе»
      await tick(300);
      out.mounted = !!document.querySelector('.fm-inv-root');
      out.rowsSeen = document.querySelectorAll('[data-recpid]').length;

      var PIDS = __PIDS__;
      for (var i = 0; i < PIDS.length; i++) {
        for (var mode = 0; mode < 2; mode++) {
          var rec = { pid: PIDS[i], mode: mode ? 'slot' : 'external' };
          var row = document.querySelector('[data-recpid="' + PIDS[i] + '"]');
          var btn = row && (mode === 0 ? row.querySelector('.fm-inv-pfree')
                                       : row.querySelector('.fm-inv-pslot.add'));
          rec.button = !!btn;
          if (btn) {
            btn.click();
            await tick();
            var dlg = document.querySelector('.fm-inv-dlg-back');
            rec.dialog = !!dlg;
            var t = dlg && dlg.querySelector('.fm-inv-dlg-title');
            rec.title = t ? t.textContent.trim() : '';
            var box = dlg && dlg.querySelector('.fm-inv-slots');
            rec.slotsTitle = '';
            rec.slotNames = [];
            if (box) {
              var lab = box.parentNode.querySelector('label');
              rec.slotsTitle = lab ? lab.textContent.trim() : '';
              rec.slotNames = [].slice.call(box.querySelectorAll('.fm-inv-slot-n'))
                                .map(function(x){ return x.textContent.trim(); });
            }
            rec.panelAlive = !!document.querySelector('.fm-inv-root');
            //  «Отмена» — человек должен вернуться в склад, а не остаться ни с чем
            var cancel = dlg && dlg.querySelector('.fm-inv-dlg-actions button');
            if (cancel) { cancel.click(); await tick(); }
            rec.afterCancelDialog = !!document.querySelector('.fm-inv-dlg-back');
            rec.afterCancelPanel = !!document.querySelector('.fm-inv-root');
            rec.afterCancelRows = document.querySelectorAll('[data-recpid]').length;
          }
          out.rows.push(rec);
        }
      }
      //  Повторное открытие того же окна — без перезагрузки страницы
      var again = document.querySelector('[data-recpid="K2P"]');
      var b2 = again && again.querySelector('.fm-inv-pslot.add');
      if (b2) { b2.click(); await tick(); }
      out.reopen = !!document.querySelector('.fm-inv-dlg-back');
      out.reopenPanel = !!document.querySelector('.fm-inv-root');
    } catch (e) { out.fatal = String((e && e.stack) || e); }
    res(dump(out));
  })();
});
""".replace("__PIDS__", json.dumps([p["printer_id"] for p in PRINTERS]))


def _run(break_it, size=(1440, 900)):
    return stage.run(JS.replace("__BREAK__", "true" if break_it else "false"),
                     window_size=size, settle_ms=2000)


def _row(res, pid, mode):
    for r in ((res or {}).get("rows") or []):
        if r.get("pid") == pid and r.get("mode") == mode:
            return r
    return {}


print("=" * 78)
print("--- 1. Мост «файл ↔ поведение»: имена действительно отдаются компонентом ---")
_ret = PANEL[PANEL.rindex("\n    return {"):PANEL.index("template: `")]
check("1. bindSlotName отдаётся из setup", "bindSlotName" in _ret, _ret[:120])
check("2. bindSlotsTitle отдаётся из setup", "bindSlotsTitle" in _ret)
check("3. bindSlotsTitle действительно объявлен, а не только возвращён",
      "const bindSlotsTitle = computed(" in PANEL)
check("4. шаблон по-прежнему просит оба имени — правка не «под тест»",
      "{{ bindSlotsTitle }}" in PANEL and "{{ bindSlotName(sl) }}" in PANEL)

if not stage.engine_ready():
    check("5. браузерный движок доступен", False, str(stage.last_diag())[:250])
else:
    print("--- 2. Настоящий браузер: кнопки привязки у всех четырёх принтеров ---")
    R = _run(False)
    _diag = (R or {}).get("__diag") or {}
    _cons = (_diag.get("consoleErrors") or []) + (_diag.get("pageErrors") or [])
    check("5. модуль смонтирован, окно склада отрисовано",
          bool(R) and R.get("mounted") and not R.get("fatal"),
          (R or {}).get("fatal") or str(R)[:200])
    check("6. в разделе «В работе» видны все четыре принтера",
          (R or {}).get("rowsSeen") == len(PRINTERS), (R or {}).get("rowsSeen"))

    for pid, name in (("AD5M", "FlashForge AD5M"), ("P2S", "Bambu P2S"),
                      ("H2S", "Bambu H2S"), ("K2P", "Creality K2 Plus")):
        e = _row(R, pid, "external")
        check("7.%s «+ Привязать внешняя» открывает окно привязки — %s" % (pid, name),
              e.get("button") and e.get("dialog") and e.get("panelAlive"), e)
        check("8.%s окно склада на месте после отмены, строки принтеров целы" % pid,
              e.get("afterCancelPanel") and not e.get("afterCancelDialog")
              and e.get("afterCancelRows") == len(PRINTERS), e)

    for pid in ("P2S", "H2S", "K2P"):
        s = _row(R, pid, "slot")
        check("9.%s «+» у свободного слота подачи открывает окно привязки" % pid,
              s.get("button") and s.get("dialog") and s.get("panelAlive"), s)
        check("10.%s в окне показан список слотов принтера" % pid,
              len(s.get("slotNames") or []) >= 4, s.get("slotNames"))

    check("11. у AD5M слот подачи не предлагается — у него только внешняя катушка",
          not _row(R, "AD5M", "slot").get("button"), _row(R, "AD5M", "slot"))
    check("12. подпись над слотами называет CFS у Creality",
          (_row(R, "K2P", "slot").get("slotsTitle") or "").startswith("CFS"),
          _row(R, "K2P", "slot").get("slotsTitle"))
    check("13. подпись над слотами называет AMS у Bambu",
          (_row(R, "P2S", "slot").get("slotsTitle") or "").startswith("AMS"),
          _row(R, "P2S", "slot").get("slotsTitle"))
    #  Подписи даёт bindSlotName: внешняя позиция названа словами, слоты короба — меткой
    #  самого принтера («Слот T1B»), а не порядковым номером.
    check("14. слоты CFS подписаны так, как их называет принтер",
          (_row(R, "K2P", "slot").get("slotNames") or [])
          == ["Внешняя катушка", "Слот T1A", "Слот T1B", "Слот T1C", "Слот T1D"],
          _row(R, "K2P", "slot").get("slotNames"))
    check("14б. у Bambu слоты пронумерованы, метки принтера там нет",
          (_row(R, "P2S", "slot").get("slotNames") or [])
          == ["Внешняя катушка", "Слот 1", "Слот 2", "Слот 3", "Слот 4"],
          _row(R, "P2S", "slot").get("slotNames"))
    #  16.10.2026 (R-137): у H2D без AMS в окне две внешние катушки. Подпись над ними — «Внешняя
    #  подача», а не «AMS»: AMS у этого принтера нет. Обе кнопки ведут в одно и то же окно.
    for _m in ("external", "slot"):
        _h = _row(R, "H2D", _m)
        check("14в.%s H2D без AMS: подпись над внешними катушками — «Внешняя подача», не «AMS»" % _m,
              _h.get("dialog") and (_h.get("slotsTitle") or "").startswith("Внешняя подача"), _h)
        check("14г.%s H2D: в окне левая и правая внешние катушки" % _m,
              (_h.get("slotNames") or []) == ["Левая внешняя катушка", "Правая внешняя катушка"],
              _h.get("slotNames"))
    check("15. окно привязки открывается повторно, без перезагрузки страницы",
          (R or {}).get("reopen") and (R or {}).get("reopenPanel"), R and R.get("reopen"))
    check("16. ни одной ошибки отрисовки и ни одной ошибки в консоли браузера",
          not (R or {}).get("errs") and not _cons,
          ((R or {}).get("errs") or []) + _cons)

    print("--- 3. НЕ ВАКУУМ: без правки тот же сценарий убивает окно склада ---")
    B = _run(True)
    check("17. подмена применилась (имя вырезано из return)", bool(B) and B.get("broken"),
          (B or {}).get("broken"))
    _be = _row(B, "P2S", "slot")
    check("18. на сломанной версии окно склада гибнет — проверка не пустая",
          bool(B) and (not _be.get("dialog") or not _be.get("panelAlive")
                       or bool(B.get("errs"))),
          {"row": _be, "errs": (B or {}).get("errs")})
    check("19. на сломанной версии страдают ИМЕННО принтеры с коробом, AD5M цел",
          bool(B) and _row(B, "AD5M", "external").get("dialog"),
          _row(B, "AD5M", "external"))
    print("     на сломанной версии браузер сказал: %s"
          % (((B or {}).get("errs") or ["— (ошибок не было)"])[0])[:170])

print("")
print("=" * 78)
print("МЕТКА: INVENTORY_BIND_DIALOG_SENTINEL_1_7_28")
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for n in _fail:
    print("  провалено: %s" % n)
sys.exit(1 if _fail else 0)
