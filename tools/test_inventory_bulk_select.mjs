// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Инварианты режима множественного выбора и пакетного удаления катушек — inventory 1.7.0
// (вкладка «Складской учёт → Склад → На складе»). Стиль проекта: статические проверки исходника
// InventoryPanel.js / backend.py + КОМПИЛЯЦИЯ Vue-шаблона реальным компилятором из web/vendor/vue.esm-browser.js
// (браузерный декодер сущностей в Node подменяем identity — на проверку структуры/директив не влияет).
// Запуск: node tools/test_inventory_bulk_select.mjs   (0 = все инварианты выполнены)
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

// 1. Кнопка «Выбрать/Готово» включает/выключает режим
check('1. кнопка «Выбрать»/«Готово» -> toggleSelMode; enter/exit определены',
  has("toggleSelMode()") && has("L('Готово','Done') : L('Выбрать','Select')")
  && has('const enterSelMode') && has('const exitSelMode'));

// 2. Checkbox работает с РЕАЛЬНЫМ физическим spool_id (Set по s.id)
check('2. selected = реактивный Set физических spool_id; чекбокс строки по s.id',
  has('const selected = reactive(new Set())') && has('selected.has(s.id)') && has('toggleSpoolSel'));

// 3. Клик по строке в режиме выбора НЕ открывает историю/редактор
check('3. onRowClick: в режиме выбора — toggleSpoolSel, иначе openHist (редактор не запускается)',
  /onRowClick\s*=\s*\(s,\s*e\)\s*=>\s*\{\s*if\s*\(selMode\.value\)\s*toggleSpoolSel\(s,\s*e\);\s*else\s*openHist\(s\);/.test(panel)
  && has('@click="onRowClick(s, $event)"'));

// 4. Shift-click выбирает диапазон видимых
check('4. Shift-click -> диапазон по visibleSpoolsOrdered между якорем и текущей',
  has('e.shiftKey') && has('visibleSpoolsOrdered') && has('lastClickedId'));

// 5. Ctrl+A в режиме выбора выбирает все видимые (по e.code, не зависит от раскладки)
check('5. Ctrl+A -> selectAllVisible (e.code===KeyA, независимо от раскладки)',
  /e\.ctrlKey\s*\|\|\s*e\.metaKey/.test(panel) && has("e.code === 'KeyA'") && has('selectAllVisible()'));

// 6. Ctrl+A НЕ перехватывается в полях ввода
check('6. Ctrl+A игнорируется в input/textarea/select/contentEditable',
  /tag === 'input' \|\| tag === 'textarea' \|\| tag === 'select' \|\| \(el && el\.isContentEditable\)/.test(panel));

// 7. Группа: all / none / indeterminate
check('7. groupSelState даёт all/some; шаблон рисует on(all)+ind(some), клик .stop не разворачивает',
  /all:\s*n\s*>\s*0\s*&&\s*n\s*===\s*y,\s*some:\s*n\s*>\s*0\s*&&\s*n\s*<\s*y/.test(panel)
  && has('{on: groupSelState(g).all, ind: groupSelState(g).some}')
  && has('@click.stop="toggleGroupSel(g)"'));

// 8. «Выбрать пустые» — по ФАКТИЧЕСКОМУ критерию (статус empty ИЛИ остаток ≤ 0), не по округлённому %
check('8. selectEmpty использует isEmptySpool (status empty || remaining<=0), НЕ округлённый pct',
  /isEmptySpool\s*=\s*\(s\)\s*=>[^;]*status === 'empty'[^;]*weight_remaining_g[^;]*<=\s*0/.test(panel)
  && /selectEmpty\s*=\s*\(\)\s*=>[^;]*isEmptySpool\(s\)/.test(panel));

// 9. Скрытые фильтром выбранные — учитываются и показываются
check('9. hiddenSelectedCount + панель показывает «скрыто фильтром M»',
  has('const hiddenSelectedCount = computed') && has("L('скрыто фильтром','hidden by filter')"));

// 10. Escape: снять выбор -> выйти из режима -> (далее закрыть окно) через перерегистрацию слоя escapeLayer
check('10. Escape поэтапно: selected>0 -> снять и перевзвести слой; иначе выйти из режима',
  has('{ clearSelection(); _armSelEsc(); }') && has('else { selMode.value = false; }')
  && has('_escApi.register(_selEscClose)'));

// 11. Удаление вызывает PREVIEW (авторитетная backend-проверка) до подтверждения
check('11. openBulkDelete -> POST spools/bulk-delete/preview',
  /openBulkDelete[\s\S]{0,400}\/api\/mod\/inventory\/spools\/bulk-delete\/preview/.test(panel));

// 12. Confirmation показывает total / deletable / blocked
check('12. диалог подтверждения: Выбрано(total) / Будет удалено(deletable) / Нельзя удалить(blocked)',
  has('bulkConfirm.total') && has('bulkConfirm.deletable.length') && has('bulkConfirm.blocked.length')
  && has("L('Будет удалено','Will delete')") && has("L('Нельзя удалить','Cannot delete')"));

// 13. Двойной клик не создаёт два запроса (busy-guard в обоих вызовах)
check('13. busy-guard: openBulkDelete (selBusy) и confirmBulkDelete (bulkConfirm.saving) отсекают повтор',
  /openBulkDelete\s*=\s*async[\s\S]{0,120}if\s*\(selBusy\.value/.test(panel)
  && /confirmBulkDelete\s*=\s*async[\s\S]{0,120}if\s*\(bulkConfirm\.saving/.test(panel));

// 14. Partial success: удалённые/отсутствующие уходят из выбора, ЗАБЛОКИРОВАННЫЕ остаются
check('14. после удаления: deleted_ids/not_found_ids сняты с выбора, blocked остаются; выход из режима только при пустом выборе',
  /for\s*\(const id of deleted\)\s*selected\.delete\(id\)/.test(panel)
  && /for\s*\(const id of \(j\.not_found_ids[\s\S]{0,40}selected\.delete\(id\)/.test(panel)
  && /if\s*\(selected\.size\s*===\s*0\)\s*exitSelMode\(\)/.test(panel)
  && !/selected\.delete\([^)]*blocked/.test(panel));

// 15. KPI/счётчики обновляются (перезагрузка данных после удаления)
check('15. confirmBulkDelete вызывает load() -> KPI/группы/нижние счётчики пересчитываются',
  /const confirmBulkDelete = async[\s\S]*?await load\(\)/.test(panel));

// 16. Режим «В работе» (wmode==='work') не тронут (1.7.7: единая таблица принтеров workRows)
check('16. режим «В работе» цел (wmode work/stock; таблица workRows, обработчики позиций живы)',
  has("wmode==='work'") && has("wmode==='stock'")
  && has('v-for="sec in workSections"') && has('v-for="r in sec.rows"') && has('onSlotClick(r.ext)') && has('sl.spool ? onSlotClick(sl)'));

// 17. Одиночное удаление продолжает работать (функция del + пункт меню «Удалить»)
check('17. одиночное удаление живо: del(s) + пункт ПКМ «Удалить» -> del(s)',
  /const del = async \(s\)/.test(panel)
  && has("fetch('/api/mod/inventory/spool/' + s.id, { method: 'DELETE' })")
  && has("label: L('Удалить', 'Delete'), danger: true, action: () => del(s)"));

// 18. Контекстное меню не сломано (spoolMenu + @contextmenu.prevent на строке)
check('18. контекстное меню катушки цело (spoolMenu, @contextmenu.prevent на строке)',
  has('const spoolMenu') && has('@contextmenu.prevent="spoolMenu($event, s)"') && has('ctxLocalOpen'));

// 19. Нет горизонтального overflow: панель массовых действий — flex-wrap (адаптивна)
check('19. sticky-панель массовых действий переносится (flex-wrap), destructive-кнопка отделена',
  /\.fm-inv-bulkbar\{[^}]*flex-wrap:wrap/.test(panel) && /\.fm-inv-bulkbar\{[^}]*position:sticky/.test(panel)
  && has("class=\"fm-inv-abtn dng\""));

// 20. Backend: роуты preview и bulk-delete зарегистрированы
check('20. backend: роуты spools/bulk-delete/preview и spools/bulk-delete зарегистрированы',
  /add_route\(\s*["']spools\/bulk-delete\/preview["']/.test(backend)
  && /add_route\(\s*["']spools\/bulk-delete["']/.test(backend));

// 21. Версия модуля 1.7.0
check('21. версия inventory 1.7.x (множественный выбор появился в 1.7.0)', /^1\.7\.\d+$/.test(mj.version));

// 22. Vue-шаблон КОМПИЛИРУЕТСЯ реальным компилятором (вендорный Vue с identity-декодером сущностей)
let compileOk = false, compileErr = '';
try {
  if (!globalThis.document) globalThis.document = { createElement: () => ({ style: {} }), querySelector: () => null, head: {} };
  if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
  const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
  const compile = Vue.compile || (Vue.default && Vue.default.compile);
  const m = panel.match(/template:\s*`([\s\S]*)`,\s*\};\s*$/);
  if (typeof compile !== 'function') compileErr = 'no compile()';
  else if (!m) compileErr = 'template block not found';
  else { const r = compile(m[1], { decodeEntities: (x) => x }); compileOk = (typeof r === 'function'); }
} catch (e) { compileErr = (e && e.message) || String(e); }
check('22. Vue-шаблон компилируется без ошибок' + (compileOk ? '' : ' [' + compileErr + ']'), compileOk);

// ── Унификация безопасности одиночного удаления (ПКМ → «Удалить») с bulk ──
// 23. del(s) сначала делает preview для ОДНОГО spool_id (через общий bulk-preview endpoint)
check('23. одиночный del(s): preview одного id через bulk-preview endpoint',
  /const del = async \(s\)[\s\S]*?spools\/bulk-delete\/preview[\s\S]*?spool_ids:\s*\[s\.id\]/.test(panel));

// 24. Заблокированная (bound/pending): DELETE не вызывается, показывается понятное сообщение
check('24. del(s): blocked -> flash(_delBlockMsg) и return (DELETE не вызывается), тексты bound/pending заданы',
  has('if ((pj.blocked || []).length) { flash(_delBlockMsg(pj.blocked[0].reason)')
  && has('Катушка привязана к принтеру или AMS. Сначала отвяжите её.')
  && has('Катушка участвует в незавершённой печати и пока не может быть удалена.'));

// 25. Существующее подтверждение «Удалить катушку …?»
check('25. del(s): подтверждение window.confirm перед DELETE',
  has("window.confirm(L('Удалить катушку «'"));

// 26. Гонка/409 при DELETE обрабатывается (причина показывается, карточка остаётся)
check('26. del(s): DELETE-ответ 409/blocked -> _delBlockMsg(j.reason), карточка остаётся',
  /if \(r\.status === 409 \|\| j\.blocked\)\s*\{\s*flash\(_delBlockMsg\(j\.reason\)/.test(panel));

// 27. Busy-защита одиночного удаления (двойной клик не создаёт два запроса; флаг сбрасывается)
check('27. del(s): busy-guard delBusy (ранний return + сброс в finally)',
  has('const delBusy = ref(false)')
  && /const del = async \(s\)\s*=>\s*\{\s*(?:if \(!guard\('project'\)\) return;[^\r\n]*\s*)?if \(delBusy\.value\) return;/.test(panel)
  && /finally\s*\{\s*delBusy\.value = false;/.test(panel));

// 28. Отмена подтверждения ничего не удаляет (return до DELETE)
check('28. del(s): отмена confirm -> return до DELETE',
  /window\.confirm\([\s\S]{0,120}\)\)\s*return;[\s\S]*?method:\s*'DELETE'/.test(panel));

// 29. Одиночное и bulk берут причины из ОДНИХ кодов (bound/pending)
check('29. причины bound/pending: _delBlockMsg (single) и blockReasonText (bulk) на одних кодах',
  /_delBlockMsg = \(reason\) => \(reason === 'bound'/.test(panel)
  && /blockReasonText = \(reason\) => \(reason === 'bound'/.test(panel));

// 30. Backend: одиночный DELETE проходит проверяемый helper и отдаёт 409 при блокировке
check('30. backend: api_inv_spool_delete -> inv_delete_spool_checked + JSONResponse 409',
  /api_inv_spool_delete[\s\S]*?inv_delete_spool_checked/.test(backend)
  && /status_code=409[\s\S]*?blocked/.test(backend));

// 31. Backend: единый _classify_spool_for_delete используется и одиночным, и пакетным путём
check('31. backend: единый _classify_spool_for_delete у single (inv_delete_spool_checked) и bulk (_inv_classify_bulk_nolock)',
  /def _classify_spool_for_delete/.test(backend)
  && /def inv_delete_spool_checked[\s\S]*?_classify_spool_for_delete/.test(backend)
  && /def _inv_classify_bulk_nolock[\s\S]*?_classify_spool_for_delete/.test(backend));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: множественный выбор + пакетное удаление — все frontend-инварианты выполнены'));
process.exit(fail ? 1 : 0);
