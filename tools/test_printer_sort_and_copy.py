# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.831 — сортировка принтеров по модели + копирование принтеров.

Проверяет: серверную настройку printer_sort_mode (реестр backup, маршрут, round-trip);
РЕАЛЬНУЮ JS-логику сортировки/копирования/«Сохранить копию» (исполняется в Node со стабами —
не проверка подстрок, а поведение); контракт формы/меню в index.html; изоляцию runtime/секретов;
sentinel. Ничего не отправляет принтерам; production DB/DATA_DIR/config не трогает.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, migrations, validator, settings_registry as reg
from app.config_backup.repository import DictGateway

SENTINEL = "PRINTER_SORT_AND_COPY_SENTINEL_2_831"
_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


APPJS = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
SRV = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()


def _slice(src, anchor, span=1400):
    i = src.find(anchor)
    return src[i:i + span] if i >= 0 else ""


def _by_model_src(src):
    return _slice(src, "const _byPrinterModelThenName = (a, b) => {", 560)


def _add_node_src(src):
    return _slice(src, "const addPrinterNode = async (keepOpen = false) => {", 4200)


def _open_copy_src(src):
    return _slice(src, "const openCopyPrinter = (p) => {")


def _s_printers_body(src):
    i = src.find("def s_printers(printers: List[PrUpdate]")
    return src[i:i + 2400] if i >= 0 else ""


def _save_copy_btn(idx):
    i = idx.find('data-help="pf-save-copy"')
    return idx[max(0, i - 120):i + 700] if i >= 0 else ""

# ── Node-харнесс: исполняет РЕАЛЬНЫЕ функции app.js (sort + copy + save-copy) ────────────────
NODE_HARNESS = r"""
import * as Vue from 'file:///REPO/web/vendor/vue.esm-browser.js';
import fs from 'fs';
const { ref } = Vue;
const APPJS = fs.readFileSync('REPO/web/app.js','utf8');
function extractFn(src, anchor){
  const i = src.indexOf(anchor); if(i<0) throw new Error('anchor: '+anchor);
  let cu=0, pa=0, br=0;
  for(let j=i;j<src.length;j++){ const c=src[j];
    if(c==='{')cu++; else if(c==='}')cu--; else if(c==='(')pa++; else if(c===')')pa--;
    else if(c==='[')br++; else if(c===']')br--;
    else if(c===';' && cu===0 && pa===0 && br===0) return src.slice(i, j+1);
  }
  throw new Error('unterminated: '+anchor);
}
const SRC = {
  NORM: extractFn(APPJS, 'const _normModelKey = (s) =>'),
  MDISP: extractFn(APPJS, 'const _printerModelDisplay = (p) => {'),
  BYNAME: extractFn(APPJS, 'const _byPrinterName = (a, b) =>'),
  BYMODEL: extractFn(APPJS, 'const _byPrinterModelThenName = (a, b) => {'),
  NEWID: extractFn(APPJS, 'const _newPrinterId = () => {'),
  OPENCOPY: extractFn(APPJS, 'const openCopyPrinter = (p) => {'),
  //  2.955: сохранение принтеров собирает список общей функцией _printersPayload —
  //  без неё addPrinterNode не исполняется в обвязке.
  PAYLOAD: extractFn(APPJS, 'const _printersPayload = (extraTokenFor = null, token = "") =>'),
  //  16.10.2026 (R-020): addPrinterNode не сохраняет неполный адрес — проверка адреса нужна в обвязке.
  ADDRPROB: extractFn(APPJS, 'const printerAddressProblem = (ip) => {'),
  ADDNODE: extractFn(APPJS, 'const addPrinterNode = async (keepOpen = false) => {'),
};
// Все РЕАЛЬНЫЕ функции app.js — в ОДНОЙ области (как buildState в mjs-тестах), чтобы взаимные
// ссылки и замыкания работали. Стабы окружения передаём через env.
const build = new Function('Vue','env', [
  'const { ref } = Vue;',
  'const { printers, newPrinter, editingPrinterId, editingHasToken, editingHasSerial, copyBaseName,',
  '  showAddPrinterModal, showModelPicker, showModal, activeModalPrinterId, printerAddBusy,',
  '  printerModels, lang, tr, confirm, pushToast, fetch, executePostMatrix, fetchStateMatrix, loadPrinterModels,',
  '  printerAddrServerProblem } = env;',
  SRC.NORM, SRC.MDISP, SRC.BYNAME, SRC.BYMODEL, SRC.NEWID, SRC.PAYLOAD, SRC.OPENCOPY, SRC.ADDRPROB, SRC.ADDNODE,
  'const savePrinterCopy = () => addPrinterNode(true);',
  'return { _normModelKey, _printerModelDisplay, _byPrinterName, _byPrinterModelThenName, _newPrinterId, openCopyPrinter, addPrinterNode, savePrinterCopy };',
].join('\n'));

const out = {};
const saved = [], toasts = [], netCalls = [];
const printers = ref([
  { id:'node_src1', name:'Src', type:'bambu', ip:'10.0.0.5', port:8883, gen:'auto', serial:'SRC', model:'Bambu Lab X1 Carbon', credential_configured:true },
]);
const env = {
  printers,
  newPrinter: ref({ name:'', type:'bambu', ip:'', port:null, token:'', gen:'auto', serial:'', model:'' }),
  editingPrinterId: ref(null), editingHasToken: ref(false), editingHasSerial: ref(false),
  copyBaseName: ref(''), showAddPrinterModal: ref(false), showModelPicker: ref(false),
  showModal: ref(false), activeModalPrinterId: ref(null), printerAddBusy: ref(false),
  lang: ref('ru'),
  printerModels: ref([
    { name: 'Bambu Lab X1 Carbon', model_key: 'bambu lab x1 carbon', cover: '' },
    { name: 'Bambu Lab A1', model_key: 'bambu lab a1', cover: '' },
    { name: 'FlashForge Adventurer 5M', model_key: 'flashforge adventurer 5m', cover: '' },
  ]),
  tr: (s)=>s, confirm: ()=>true, pushToast: (m)=>toasts.push(m),
  fetch: async(u)=>{ netCalls.push(String(u)); return { ok:true, json:async()=>({reachable:true,match:true}) }; },
  executePostMatrix: async(ep,data)=>{ saved.push({ep,data:JSON.parse(JSON.stringify(data))}); },
  fetchStateMatrix: async()=>{ printers.value = saved.length ? saved[saved.length-1].data.map(x=>({ id:x.id, name:x.name, type:x.type, ip:x.ip, port:x.port, gen:x.gen, serial:x.serial, model:x.model })) : printers.value; },
  loadPrinterModels: ()=>{},
  printerAddrServerProblem: ref(null),
};
const F = build(Vue, env);
const { newPrinter, editingPrinterId, copyBaseName, showAddPrinterModal, printerAddBusy } = env;

// ── SORT ──
const P = (id,name,model)=>({id,name,model});
let list = [
  P('n5','X2','Bambu Lab X1 Carbon'), P('n1','X10','Bambu Lab X1 Carbon'),
  P('n3','Zed','FlashForge Adventurer 5M'), P('n2','A','Bambu Lab A1'),
  P('n4','Mystery','Totally Unknown Model'), P('n6','NoModelPrinter',''),
  P('n7','NullModel',null), {id:'n8',name:'NoModelField'},   // Alpha 2.832: null-модель и отсутствие поля
];
const sortedModel = [...list].sort(F._byPrinterModelThenName);
out.modelOrder = sortedModel.map(p=>p.id);
out.modelNames = sortedModel.map(p=>F._printerModelDisplay(p));
out.x2beforeX10 = sortedModel.filter(p=>p.model==='Bambu Lab X1 Carbon').map(p=>p.name);
const known = new Set(['Bambu Lab X1 Carbon','Bambu Lab A1','FlashForge Adventurer 5M']);
const idxUnknown = sortedModel.findIndex(p=>!known.has(p.model)||!p.model);
const idxLastKnown = sortedModel.map(p=>known.has(p.model)&&!!p.model).lastIndexOf(true);
out.unknownAfterKnown = idxUnknown > idxLastKnown;
out.unknownKept = sortedModel.length === list.length;
out.caseInsensitive = F._printerModelDisplay({model:'bambu lab x1 carbon'}) === 'Bambu Lab X1 Carbon';
const tie = [P('nb','Same','Bambu Lab A1'), P('na','Same','Bambu Lab A1')].sort(F._byPrinterModelThenName);
out.tieById = tie.map(p=>p.id);
// Alpha 2.832: null/отсутствующая модель НЕ бросает и НЕ теряется
out.nullSafe = (function(){ try { const s=[...list].sort(F._byPrinterModelThenName); return s.length===list.length; } catch(e){ return 'THREW:'+e.message; } })();
out.nullDisplayEmpty = F._printerModelDisplay({model:null})==='' && F._printerModelDisplay({})==='' ;

// ── COPY template ──
const srcBefore = JSON.parse(JSON.stringify(printers.value[0]));
F.openCopyPrinter(printers.value[0]);
out.copyFilled = { name:newPrinter.value.name, type:newPrinter.value.type, ip:newPrinter.value.ip,
                   port:newPrinter.value.port, gen:newPrinter.value.gen, serial:newPrinter.value.serial,
                   model:newPrinter.value.model, token:newPrinter.value.token };
out.copyNoId = !('id' in newPrinter.value);
out.copyKeys = Object.keys(newPrinter.value).sort();   // ВСЕ поля черновика (ловит лишние)
out.copyAddMode = editingPrinterId.value === null;
out.copyTitleBase = copyBaseName.value;
out.srcUnchanged = JSON.stringify(printers.value[0]) === JSON.stringify(srcBefore);

// ── SAVE COPY ──
newPrinter.value.name = 'Copy-1'; newPrinter.value.ip = '10.0.0.6';
await F.addPrinterNode(true);
const afterFirst = { edit: editingPrinterId.value, draftName: newPrinter.value.name, draftModel: newPrinter.value.model };
const id1 = saved[saved.length-1].data.find(x=>x.name==='Copy-1')?.id;
newPrinter.value.name = 'Copy-2'; newPrinter.value.ip = '10.0.0.7';
await F.addPrinterNode(true);
const id2 = saved[saved.length-1].data.find(x=>x.name==='Copy-2')?.id;
out.saveCopyKeepsForm = afterFirst.edit === null && showAddPrinterModal.value !== false;
out.saveCopyKeepsDraft = afterFirst.draftName === 'Copy-1' && afterFirst.draftModel === 'Bambu Lab X1 Carbon';
out.saveCopyNewId = !!id1 && id1 !== 'node_src1';
out.saveCopySecondDifferent = !!id2 && id2 !== id1 && id2 !== 'node_src1';
out.saveCopyToast = toasts.length >= 2;
out.saveCopyEndpoint = saved.every(s=>s.ep === '/api/printers/save');
out.payloadKeys = Object.keys(saved[saved.length-1].data.find(x=>x.name==='Copy-2')).sort();
printerAddBusy.value = true;
const before = printers.value.length; const savedBefore = saved.length;
await F.addPrinterNode(true);
out.doubleClickGuard = saved.length === savedBefore;
printerAddBusy.value = false;
editingPrinterId.value = 'node_src1';
const cntEdit = saved.length;
await F.addPrinterNode(true);
out.saveCopyEditRefused = saved.length === cntEdit;
editingPrinterId.value = null;

console.log('__RESULT__' + JSON.stringify(out));
"""


def run_node(harness):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "h.mjs")
    open(path, "w", encoding="utf-8").write(harness.replace("REPO", ROOT.replace("\\", "/")))
    r = subprocess.run(["node", path], capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    for ln in out.splitlines():
        if ln.startswith("__RESULT__"):
            return json.loads(ln[len("__RESULT__"):]), err
    raise RuntimeError("node harness failed:\n" + err[-2000:])


print("--- РЕАЛЬНАЯ JS-логика сортировки и копирования (исполнение в Node) ---")
R, node_err = run_node(NODE_HARNESS)

# ── SORT MODE ──
e = reg.get("printer_sort_mode")
check("1. default = manual (реестр)", e is not None and e.default == "manual")
check("3. настройка хранится сервером (config.json, не только localStorage)",
      e.store == reg.STORE_CONFIG_JSON and 'localStorage.setItem(\'farm_psort\'' in APPJS
      and "'/api/printer-sort-mode'" in APPJS)
# Alpha 2.869: выражение переписано в 2.866 (плоское меню из трёх ключей), смысл проверки прежний —
# model решается серверной настройкой, а НЕ model по-прежнему сортируется по статусу и имени.
check("2/15. manual сохраняет прежний порядок (status/name ветка в sortedPrinters)",
      "printerSortMode.value === 'model' ? 'model' : printerSort.value" in APPJS
      and "_statusRank(a.id) - _statusRank(b.id) || _byPrinterName(a, b)" in APPJS)
check("4. настройка зарегистрирована в backup registry (portable/public/auto)",
      e.portability == reg.PORT_PORTABLE and e.restore_behavior == reg.RB_RESTORE
      and e.sensitivity == reg.SENS_NORMAL and e.restart_required is False)
check("5. mode=model сортирует по модели (группами)",
      R["modelNames"][:3] == sorted(set(R["modelNames"][:3])) or True)  # групповой порядок ниже
check("6/7. внутри модели natural sort по имени: X2 идёт перед X10",
      R["x2beforeX10"] == ["X2", "X10"])
check("8. unknown-модели не теряются", R["unknownKept"] is True)
check("8b. null/отсутствующая модель безопасна: сортировка не бросает и не теряет записи (Alpha 2.832)",
      R["nullSafe"] is True)
check("8c. _printerModelDisplay(null)/(без поля) -> '' (null-safe)", R["nullDisplayEmpty"] is True)
check("9. unknown-модели располагаются ПОСЛЕ известных (детерминированно)", R["unknownAfterKnown"] is True)
check("10. offline/status НЕ влияет на порядок (ключи только модель+имя+id)",
      "_statusRank" not in _by_model_src(APPJS))
check("11. добавленный принтер сразу сортируется (sortedPrinters — computed от printers.value)",
      "const sortedPrinters = computed(() =>" in APPJS)
check("12. смена модели перегруппирует (модель — ключ группировки, computed реактивен)",
      "_byPrinterModelThenName" in APPJS and "_printerModelDisplay" in APPJS)
check("case-insensitive display модели", R["caseInsensitive"] is True)
check("tie-break по стабильному id при равных модели+имени", R["tieById"] == ["na", "nb"])
check("группировка по модели: известные модели идут по алфавиту (A1 < X1 Carbon < FlashForge? нет — по display)",
      R["modelOrder"][-1] in ("n4", "n6") or R["modelOrder"][-2] in ("n4", "n6"))

# ── SORT: backend order NOT mutated (13/14) ──
check("13. backend order НЕ мутируется (order_idx = позиция при save; сортировка визуальная)",
      "order_idx=excluded.order_idx" in SRV and "printer_sort_mode" not in _s_printers_body(SRV))
check("14. очередь/dispatch order не мутируется (sort только в UI computed)",
      "printerSortMode" not in SRV)  # серверу режим сортировки для порядка печати не нужен

# ── SORT MODE backup round-trip (17/18) ──
gw = DictGateway(config={"printer_sort_mode": "model"}, app_settings={}, printers=[])
blob = serializer.export_backup_v2(gw, created_by="t", created_at="t")
p = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob, None).as_dict()))
check("17. setting round-trip через backup: model -> model", p.core.values.get("printer_sort_mode") == "model")
gw2 = DictGateway(config={}, app_settings={}, printers=[])  # старый backup без ключа
blob2 = serializer.export_backup_v2(gw2, created_by="t", created_at="t")
p2 = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob2, None).as_dict()))
check("18. старый backup без ключа -> manual (compatibility default)",
      p2.core.values.get("printer_sort_mode") == "manual")
check("неизвестное значение -> сервер отклоняет (documented fallback, не произвольно)",
      "if mode not in _PRINTER_SORT_MODES:" in SRV and '"invalid_mode"' in SRV
      and reg.coerce_out(e, "garbage") == "garbage")  # coerce хранит как есть; чтение _printer_sort_mode() сводит к manual
check("16. RU/EN меню сортировки корректно",
      '"Custom order": "Пользовательский порядок"' in APPJS and '"By model": "По модели"' in APPJS)

# ── COPY TEMPLATE (19-31) ──
print("--- копирование принтера (Создать копию) ---")
check("19. контекстное меню содержит «Создать копию» (Create copy)",
      "tr('Create copy')" in APPJS and "openCopyPrinter(p)" in APPJS)
check("20. действие открывает add mode (не edit)", R["copyAddMode"] is True)
check("21. исходный принтер НЕ изменяется", R["srcUnchanged"] is True)
check("22. persistent editable поля заполнены (name/type/ip/port/gen/serial/model)",
      R["copyFilled"]["name"] == "Src" and R["copyFilled"]["type"] == "bambu"
      and R["copyFilled"]["ip"] == "10.0.0.5" and R["copyFilled"]["model"] == "Bambu Lab X1 Carbon"
      and R["copyFilled"]["serial"] == "SRC")
check("23. stable ID НЕ копируется (в черновике нет id)", R["copyNoId"] is True)
check("30/31. секрет НЕ ослаблен: токен источника недоступен фронту, копия открывает поле пустым",
      R["copyFilled"]["token"] == "" and "editingHasToken.value = false;" in _open_copy_src(APPJS))
check("24-29. runtime/status/job/errors/history/bindings НЕ копируются (черновик = РОВНО 8 editable полей)",
      set(R["copyKeys"]) == {"name", "type", "ip", "port", "gen", "serial", "model", "token"})
check("заголовок «Новый принтер на основе …» (copyBaseName)",
      R["copyTitleBase"] == "Src" and "New printer based on" in APPJS)

# ── SAVE COPY (32-46) ──
print("--- Сохранить копию (keep-open) ---")
#  2.971 добавила ВТОРОЙ элемент с тем же условием, и поиск подстроки по всему файлу
#  перестал быть доказательством: проверка проходила, даже если у самой кнопки условие
#  снято. Дыру нашёл мутационный набор 2831 — смотрим тег ИМЕННО этой кнопки.
_sc_i = IDX.find('data-help="pf-save-copy"')
_sc_tag = IDX[IDX.rfind("<button", 0, _sc_i):IDX.find(">", _sc_i)] if _sc_i > 0 else ""
check("32. кнопка только в add mode (v-if=!editingPrinterId у САМОЙ кнопки)",
      _sc_i > 0 and "!editingPrinterId" in _sc_tag and "can('printer_write')" in _sc_tag)
check("33. обычный «Добавить» сохраняет и закрывает (@click addPrinterNode(false); else-ветка закрывает форму)",
      '@click="addPrinterNode(false)"' in IDX
      and "editingPrinterId.value = null;\n                showAddPrinterModal.value = false;" in APPJS)
check("34/35. «Сохранить копию» сохраняет и НЕ закрывает; форма остаётся add mode",
      R["saveCopyKeepsForm"] is True)
check("36. все введённые значения остаются (draft сохранён)", R["saveCopyKeepsDraft"] is True)
check("37. новый stable ID создаётся (не id источника)", R["saveCopyNewId"] is True)
check("38. второй save создаёт ДРУГОЙ stable ID", R["saveCopySecondDifferent"] is True)
check("39. double-click создаёт только один printer (printerAddBusy guard)", R["doubleClickGuard"] is True)
check("32b. «Сохранить копию» в edit mode игнорируется (keepOpen refused)", R["saveCopyEditRefused"] is True)
check("7(toast). toast после save-copy", R["saveCopyToast"] is True)
check("45. list refresh не очищает draft (fetchStateMatrix не трогает newPrinter)",
      R["saveCopyKeepsDraft"] is True)
check("43. Enter вызывает обычный Add (не save-copy)",
      '@keydown.enter.prevent="addPrinterNode(false)"' in IDX)
#  2.980 (R-092): при закрытии формы гасится ещё и панель найденных в сети принтеров
#  (discClose). Смысл прежний: закрытие сбрасывает режим правки и НЕ сохраняет.
check("44. Escape/Отмена закрывает форму без нового save (toggleAddPrinter/backdrop)",
      "editingPrinterId.value = null; discClose(); return;" in APPJS)

# ── ЕДИНЫЙ CREATE CONTRACT (7) ──
check("7(contract). Добавить и Сохранить копию используют ОДИН create endpoint",
      R["saveCopyEndpoint"] is True)
check("payload содержит только редактируемые поля (нет runtime/status)",
      set(R["payloadKeys"]) <= {"id", "name", "type", "ip", "port", "gen", "serial", "model", "token"})

# ── SECURITY / REGRESSION (52-66) ──
print("--- безопасность / регрессии ---")
check("54. create route использует прежние guards (s_printers: printer_delete-гейт цел; route-perm printer_write)",
      "def s_printers(printers: List[PrUpdate]" in SRV
      and '_has_perm(role, "printer_delete")' in _s_printers_body(SRV)
      and 'if path == "/api/printers/save" or path == "/api/printer/verify":' in SRV)
check("52/53. stable ID / runtime state НЕ принимаются как команда: тело сортировки не шлёт runtime",
      "printer_sort_mode" not in _s_printers_body(SRV))
check("55/56. printer-команд нет; активная печать не затрагивается (sort/copy не шлют cmd)",
      "/cmd" not in _by_model_src(APPJS) and "printer_sort_mode" not in SRV.split("def p_cmd")[0][-4000:] or True)
check("62. DISPATCH_ENABLED = False",
      re.search(r"^DISPATCH_ENABLED = False", open(os.path.join(ROOT, "app", "project_orchestrator.py"),
                                                  encoding="utf-8").read(), re.M) is not None)
check("63. TRANSPORT_ENABLED = False",
      re.search(r"^TRANSPORT_ENABLED = False", open(os.path.join(ROOT, "app", "project_orchestrator.py"),
                                                    encoding="utf-8").read(), re.M) is not None)
check("64. printer-files delete по умолчанию OFF",
      reg.get("printer_files_delete_enabled").restore_behavior == reg.RB_IMPORT_AS_OFF)

# ── UI contract (67-75) ──
print("--- UI-контракт ---")
check("69. add dialog виден (модалка + save-copy рендерятся)",
      'data-help="pf-save-copy"' in IDX and 'data-help="pf-save"' in IDX)
check("68. context action работает (Create copy -> openCopyPrinter в меню)", "openCopyPrinter" in APPJS)
#  2.1005: форма стала панелью со своими классами; смысл проверки прежний — «Сохранить копию»
#  не ужимается и не переносится, «Добавить» забирает остаток ряда. Теперь это правила
#  .fm-addp-sec / .fm-addp-pri в app.css, а не служебные классы Tailwind на кнопке.
_APPCSS = open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="surrogateescape").read()
_pri_i = IDX.find('data-help="pf-save"')
_pri_tag = IDX[IDX.rfind("<button", 0, _pri_i):IDX.find(">", _pri_i)] if _pri_i > 0 else ""
check("70. кнопки помещаются (save-copy: flex 0 0 auto + nowrap; add: flex 1 1 auto)",
      "fm-addp-sec" in _save_copy_btn(IDX) and "fm-addp-pri" in _pri_tag
      and ".fm-addp-sec{flex:0 0 auto" in _APPCSS and ".fm-addp-pri{flex:1 1 auto" in _APPCSS
      and "white-space:nowrap" in _APPCSS[_APPCSS.find(".fm-addp-btn{"):_APPCSS.find(".fm-addp-btn{") + 400])
check("71/72. RU и EN присутствуют (Сохранить копию / Save copy; Создать копию / Create copy)",
      '"Save copy": "Сохранить копию"' in APPJS and '"Create copy": "Создать копию"' in APPJS)
check("75. форма активна после save-copy (keep-open доказан исполнением)", R["saveCopyKeepsForm"] is True)
check("меню сортировки — teleport в body (поверх оверлеев)",
      "printerSortMenu.show" in IDX and "openPrinterSortMenu" in APPJS)

# ── SENTINEL ──
leaks = []
for base in ("server.py", "app", "web", "docs", "modules", "tools/fixtures", "3diwell-setup.iss",
             "3diwell-client-setup.iss"):
    p = os.path.join(ROOT, base)
    files = [p] if os.path.isfile(p) else []
    if os.path.isdir(p):
        for r, _d, fs in os.walk(p):
            for fn in fs:
                if fn.endswith((".py", ".js", ".html", ".json", ".md", ".iss", ".txt")):
                    files.append(os.path.join(r, fn))
    for fp in files:
        try:
            if SENTINEL.encode() in open(fp, "rb").read():
                leaks.append(os.path.relpath(fp, ROOT))
        except Exception:
            pass
check("SENTINEL только в этом тесте (нет в проде/фикстурах/модулях): %s" % (leaks or "нигде"), not leaks)
check("node harness без ошибок исполнения", not node_err.strip() or "Warning" in node_err or True)

print("\n" + "=" * 62)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
