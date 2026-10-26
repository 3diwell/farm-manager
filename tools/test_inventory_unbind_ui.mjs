// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Инварианты действия «Отвязать от принтера» (Склад → В работе) — inventory 1.7.5.
// Статические проверки web/InventoryPanel.js + backend.py + КОМПИЛЯЦИЯ шаблона вендорным Vue.
// Запуск: node tools/test_inventory_unbind_ui.mjs   (0 = все инварианты выполнены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const panel = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const backend = readFileSync(join(REPO, 'modules', 'inventory', 'backend.py'), 'utf8');
const mj = JSON.parse(readFileSync(join(REPO, 'modules', 'inventory', 'module.json'), 'utf8'));

let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };
const has = (s) => panel.includes(s);

// Alpha 2.795: с 2.793 состав меню карточки гейтится правами модуля (капабилити-контракт окна).
// «Отвязать» появляется, только когда катушка привязана И у пользователя есть право `project`.
// 1-2. «Отвязать» — для привязанной катушки (внешней и AMS одинаково) под правом project
check('1-2. spoolMenu добавляет «Отвязать» для привязанной катушки И при праве project (2.793)',
  /const bound = !!\(s && s\.ams_printer_id\);/.test(panel)
  && /const cProj = can\('project'\)/.test(panel)
  && /if \(bound && cProj\) items\.push\(\{ icon: 'undo', label: L\('Отвязать', 'Unbind'\), action: \(\) => openUnbind\(s\) \}\)/.test(panel));

// 3. Для пустого слота действия нет (ПКМ по пустому слоту не открывает меню; openUnbind защищён
//    правом project ПЕРЕД проверкой привязки — submit-time guard капабилити-контракта 2.793)
check('3. пустой слот -> нет меню (onSlotMenu только при spool) + openUnbind guard: право project И привязка',
  has('const onSlotMenu = (e, sl) => { const f = slotFull(sl); if (f) spoolMenu(e, f); }')
  && /const openUnbind = \(s\) => \{ if \(!guard\('project'\)\) return;\s*if \(!s \|\| !s\.ams_printer_id\) return;/.test(panel));

// 4. Confirmation показывает правильный принтер
check('4. подтверждение показывает имя принтера (printerName(s.ams_printer_id))',
  has('unbindConfirm.printerName = printerName(s.ams_printer_id)')
  && has('{{ unbindConfirm.printerName }}'));

// 5. Для AMS показывает точный номер слота (index+1); для внешней — без слота
check('5. AMS -> «AMS слот {slot+1}»; внешняя -> без номера слота (isExternal: ams_slot<0 или !has_ams)',
  has('{{ unbindConfirm.slot + 1 }}') && has('v-if="unbindConfirm.isExternal"')
  && has('unbindConfirm.isExternal = (Number(s.ams_slot) < 0) || !!(p && !p.has_ams)'));

// 6. Styled-модалка (НЕ window.confirm); Отмена просто закрывает без запроса
check('6. styled-подтверждение (fm-inv-dlg), Отмена = unbindConfirm.open=false (без fetch)',
  /v-if="unbindConfirm\.open"[\s\S]{0,400}fm-inv-dlg-title/.test(panel)
  && has('@click="unbindConfirm.open=false">{{ L(\'Отмена\',\'Cancel\')')
  && !/openUnbind[\s\S]{0,200}window\.confirm/.test(panel));

// 7. Право project ПЕРЕД запросом (submit-time recheck 2.793) + двойной клик = один запрос
//    (busy-guard) + кнопки disabled + «Отвязка…»
check('7. confirmUnbind: право project до запроса + busy-guard (saving/unbindBusy) + кнопки :disabled + «Отвязка…»',
  /const confirmUnbind = async \(\) => \{\s*if \(!guard\('project'\)\) return;[\s\S]{0,60}if \(unbindConfirm\.saving \|\| unbindBusy\.value/.test(panel)
  && has(':disabled="unbindConfirm.saving"') && has("L('Отвязка…','Unbinding…')"));

// 8. Pending-блокировка -> понятный текст, карточка остаётся
check('8. 409/blocked -> flash «участвует в незавершённой печати…», карточка остаётся',
  /if \(r\.status === 409 \|\| j\.blocked\) \{ unbindConfirm\.open = false; flash\(L\('Катушка участвует в незавершённой печати/.test(panel));

// 9-11. После успеха: load() (карточка исчезает из «В работе», катушка в «На складе», KPI/ams обновляются)
check('9-11. успех: закрытие модалки + flash «отвязана от …» + await load() (карточка исчезает, KPI/ams обновляются)',
  /unbindConfirm\.open = false;\s*flash\(L\('Катушка отвязана от '[\s\S]{0,200}await load\(\)/.test(panel));

// 12. Контекстное меню позиции цело (spoolMenu/ctxLocalOpen; ПКМ на занятых позициях таблицы 1.7.7)
check('12. контекстное меню цело (spoolMenu через ctxLocalOpen; ПКМ занятых позиций -> onSlotMenu)',
  has('ctxLocalOpen(e, items)') && has('@contextmenu.prevent="onSlotMenu($event, r.ext)"')
  && has('sl.spool ? onSlotMenu($event, sl) : null'));

// 13. Escape закрывает только подтверждение (участвует в escapeLayer-стеке)
check('13. подтверждение в Escape-стеке: _bindEsc(\'unbindConfirm\', …)',
  /_bindEsc\('unbindConfirm', \(\) => unbindConfirm\.open, \(\) => \{ if \(!unbindConfirm\.saving\) unbindConfirm\.open = false; \}\)/.test(panel));

// 14. Привязка/замена не сломаны
check('14. привязка/замена целы (applyBind, bindConfirm, confirmBindReplace, selectBindSlot)',
  has('const applyBind') && has('bindConfirm') && has('confirmBindReplace') && has('selectBindSlot'));

// 15. Bulk/single delete не сломаны; удаление привязанной по-прежнему блокируется backend'ом
check('15. bulk/single delete целы; «Отвязать» отдельно от «Удалить»',
  has('openBulkDelete') && /const del = async \(s\)/.test(panel)
  && has("label: L('Удалить', 'Delete'), danger: true, action: () => del(s)")
  && has("label: L('Отвязать', 'Unbind'), action: () => openUnbind(s)"));

// 16. Экспорт в шаблон
check('16. unbindConfirm/confirmUnbind экспортированы из setup()',
  /return \{[\s\S]*?unbindConfirm, confirmUnbind[,}]/.test(panel));

// 17. Backend: endpoint отвязки + общий helper + pending-блок + история/поля не трогаются
check('17. backend: POST spool/{id}/unbind -> inv_unbind_spool (pending->409); общий _inv_unbind_spool_sql',
  /add_route\(\s*["']spool\/\{sid\}\/unbind["'],\s*api_inv_spool_unbind/.test(backend)
  && /def inv_unbind_spool\(sid\)/.test(backend)
  && /def _inv_unbind_spool_sql\(sid\)/.test(backend)
  && /_inv_unbind_spool_sql\(sid\)/.test(backend.replace('def _inv_unbind_spool_sql', ''))   // используется, не только определён
  && /reason": "pending"/.test(backend) && /status_code=409/.test(backend));

// 18. Версия модуля: semver-порог, а не хрупкий точный пин (иначе тест краснел бы после каждого
//     патча — именно эта хрупкость и была причиной ложных падений до Alpha 2.795).
const verGE = (a, b) => { const pa = String(a).split('.').map(Number), pb = b.split('.').map(Number); for (let i = 0; i < 3; i++) { if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0); } return true; };
check('18. версия inventory валидна (semver) и не ниже 1.7.24', /^\d+\.\d+\.\d+$/.test(mj.version) && verGE(mj.version, '1.7.24'));

// 19. Vue-шаблон компилируется реальным компилятором (вставка модалки корректна)
let compileOk = false, compileErr = '';
try {
  if (!globalThis.document) globalThis.document = { createElement: () => ({ style: {} }), querySelector: () => null, head: {} };
  if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
  const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
  const compile = Vue.compile || (Vue.default && Vue.default.compile);
  const m = panel.match(/template:\s*`([\s\S]*)`,\s*\};\s*$/);
  const r = compile(m[1], { decodeEntities: (x) => x });
  compileOk = (typeof r === 'function');
} catch (e) { compileErr = (e && e.message) || String(e); }
check('19. Vue-шаблон компилируется без ошибок' + (compileOk ? '' : ' [' + compileErr + ']'), compileOk);

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: действие «Отвязать от принтера» — все frontend-инварианты выполнены'));
process.exit(fail ? 1 : 0);
