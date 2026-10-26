// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Инварианты наглядного выбора принтера в диалоге привязки — inventory 1.7.1.
// Проблема: старый <select> принтера не показывал состояние (свободен/занят/эта катушка здесь),
// легко было заменить материал не на том принтере. Стало: карточки принтеров с состоянием,
// свободные сверху, подтверждение при замене, один клик для свободного, no-op для той же катушки.
// Данные — из УЖЕ загруженного ams-обзора (ams.value), без новых API и повторных запросов.
// Стиль проекта: статические проверки исходника + компиляция Vue-шаблона вендорным Vue.
// Запуск: node tools/test_inventory_bind_ui.mjs   (0 = все инварианты выполнены)
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
const idx = (s) => panel.indexOf(s);

// Тело функции по имени (для локальных проверок «нет fetch внутри»)
const bodyOf = (re) => { const m = panel.match(re); return m ? m[0] : ''; };

// 1. Свободные принтеры — сверху (секция «Свободные» раньше «Занятые» в шаблоне)
check('1. свободные принтеры отображаются выше занятых (порядок секций в шаблоне)',
  idx("bindGroups.free.length") > 0 && idx("bindGroups.occupied.length") > 0
  && idx("bindGroups.free.length") < idx("bindGroups.occupied.length")
  && idx("L('Свободные','Free')") < idx("L('Занятые','Occupied')"));

// 2. Занятые — ниже (группировка current/free/occupied в computed)
check('2. bindGroups раскладывает принтеры по состоянию current/free/occupied',
  /const bindGroups = computed\(\(\) => \{[\s\S]*?state === 'current'[\s\S]*?state === 'free'[\s\S]*?occupied/.test(panel)
  && /return \{ current: cur, free: free, occupied: occ \}/.test(panel));

// 3. Текущая катушка — яркая зелёная индикация (класс cur + «уже привязана»)
check('3. текущий принтер: класс .fm-inv-bpr.cur (зелёная рамка) + «✓ уже привязана»',
  /\.fm-inv-bpr\.cur\{[^}]*var\(--fm-success/.test(panel)
  && has('class="fm-inv-bpr cur"') && has("L('уже привязана','already bound')"));

// 4. Занятый принтер показывает материал/vendor/остаток
check('4. занятый принтер показывает материал · vendor · остаток (боунд-катушки)',
  has('class="fm-inv-bpr-spools"') && has('[sl.spool.material, sl.spool.vendor_name].filter(Boolean).join')
  && has('Math.round(sl.spool.weight_remaining_g||0)'));

// 5. Замена требует подтверждения (занятый слот -> bindConfirm, НЕ мгновенно)
check('5. tryBindTarget: занятый слот -> подтверждение (bindConfirm.open), без мгновенной привязки',
  /const tryBindTarget[\s\S]*?if \(cur\) \{[\s\S]*?bindConfirm\.open = true; return;/.test(panel)
  && has('const confirmBindReplace = () =>') && has('@click="confirmBindReplace()"'));

// 6. Свободный привязывается сразу (без подтверждения)
check('6. tryBindTarget: свободный слот -> applyBindGuarded() сразу (одним кликом)',
  /const tryBindTarget[\s\S]*?applyBindGuarded\(\);   \/\/ свободный/.test(panel)
  && /chooseBindPrinter[\s\S]*?slots\.length === 1[\s\S]*?tryBindTarget\(p, slots\[0\]\.index\)/.test(panel));

// 7. Повторная привязка ЭТОЙ же катушки ничего не делает (нет записи в БД)
check('7. та же катушка -> no-op без записи: cur.id===bind.sid -> return; current-карточка -> return',
  /if \(cur && bind\.sid && cur\.id === bind\.sid\) \{ flash\([\s\S]*?\); return; \}/.test(panel)
  && /info\.state === 'current' && slots\.length === 1\) \{ flash\([\s\S]*?\); return; \}/.test(panel));

// 8. Backend не вызывается повторно: busy-guard + переиспользование существующего applyBind
check('8. busy-guard bindBusy (двойной клик = один запрос), коммит через существующий applyBind',
  /const applyBindGuarded = async \(\) => \{\s*if \(bindBusy\.value\) return;/.test(panel)
  && /try \{ await applyBind\(\); \} finally \{ bindBusy\.value = false; \}/.test(panel));

// 9. Никаких новых API: выбор/состояние не делают fetch; коммит — прежний /spool/{id}/bind; backend не трогали
const noFetch = (re, label) => { const b = bodyOf(re); return b && !b.includes('fetch('); };
check('9. выбор принтера НЕ делает запросов (bindGroups/bindPrinterInfo/chooseBindPrinter/tryBindTarget без fetch)',
  noFetch(/const bindGroups = computed[\s\S]*?\n    \};/, 'bindGroups')
  && noFetch(/const bindPrinterInfo = \(p\) => \{[\s\S]*?\n    \};/, 'bindPrinterInfo')
  && noFetch(/const chooseBindPrinter[\s\S]*?\n    \};/, 'chooseBindPrinter')
  && noFetch(/const tryBindTarget[\s\S]*?\n    \};/, 'tryBindTarget')
  && has("fetch('/api/mod/inventory/spool/' + bind.sid + '/bind'")   // прежний эндпоинт привязки
  && !/add_route\(\s*["'][^"']*bind-printer/.test(backend));         // никаких новых bind-роутов в backend

// 10. Данные — из уже загруженного ams-обзора (ams.value), не новый источник
check('10. состояние принтеров берётся из ams.value (ams-обзор), не из отдельного запроса',
  /const bindGroups = computed\(\(\) => \{[\s\S]*?ams\.value\.printers/.test(panel)
  && /const bindPrinterInfo = \(p\) => \{[\s\S]*?p\.slots/.test(panel));

// 11. Работает при большом числе принтеров: список карточек прокручивается
check('11. список принтеров прокручивается (.fm-inv-bprs: max-height + overflow-y:auto)',
  /\.fm-inv-bprs\{[^}]*max-height:[^}]*overflow-y:auto/.test(panel));

// 12. Режим «привязать материал к принтеру» (bind.pick) и одиночное/массовое удаление не тронуты
check('12. bind.pick (выбор катушки со склада) и Escape-стек не сломаны',
  has("bind.pick ? L('Привязать материал к принтеру'") && has("stockOptions")
  && has("_bindEsc('bindConfirm'"));

// ── Фикс регрессии 1.7.3: выбор AMS-слота. КОРЕНЬ: имя с «_» (_bindPrinterObj) НЕ проксируется Vue в
//    шаблон (см. настоящий runtime-тест test_inventory_bind_runtime.mjs), поэтому переименовано в
//    bindPrinterObj. Ниже — структурные проверки; ДОКАЗАТЕЛЬСТВО поведения — в runtime-тесте. ──
// A0. РЕГРЕССИЯ-GUARD: во ВСЁМ файле нет идентификатора _bindPrinterObj (ни в шаблоне, ни в коде)
check('A0. нет зарезервированного имени _bindPrinterObj нигде в файле (шаблон видит только bindPrinterObj)',
  !panel.includes('_bindPrinterObj'));

// A1. bindPrinterObj (без «_») + selectBindSlot/bindSlotIndex/canApplyBind экспортированы; слот зовёт их
check('A1. bindPrinterObj/bindSlotIndex/canApplyBind экспортированы; AMS-слот -> selectBindSlot(bindPrinterObj, bindSlotIndex(sl))',
  has('bindGroups, bindPrinterObj, bindSlotIndex, canApplyBind, chooseBindPrinter')
  && has('selectBindSlot, bindTargetIsSelf')
  && has('@click.stop="selectBindSlot(bindPrinterObj, bindSlotIndex(sl))"'));

// A2. Клик по слоту: slot 0 валиден, внешняя позиция -1 валидна, «не выбран» = null (idx==null||idx<-2, не !idx).
//     16.10.2026 (склад, R-137): -2 — левая внешняя катушка H2D, тоже допустимая позиция.
check('A2. selectBindSlot: явная проверка индекса (idx == null || idx < -2), slot 0, внешняя -1 и левая -2 валидны',
  /const selectBindSlot = \(p, idx\) => \{\s*if \(!p \|\| idx == null \|\| idx < -2\) return;/.test(panel)
  && !/const selectBindSlot[\s\S]{0,200}!idx\b/.test(panel));

// A3. Кнопка «Привязать»: единое условие canApplyBind (без длинного дублирования, slot 0 валиден целочисленно)
check('A3. кнопка «Привязать»: :disabled="!canApplyBind"; canApplyBind проверяет slot!=null и slot>=-2 (внешняя -1 и левая -2 валидны)',
  has(':disabled="!canApplyBind"')
  && /const canApplyBind = computed\([\s\S]*?bind\.slot != null[\s\S]*?Number\.isInteger\(Number\(bind\.slot\)\)[\s\S]*?Number\(bind\.slot\) >= -2[\s\S]*?!bindBusy\.value[\s\S]*?!bindTargetIsSelf\.value/.test(panel));

// A4. Slot 1/2/3 тоже выбираются; выбор реактивен (bind.slot=idx); active по нормализованному индексу
check('A4. selectBindSlot ставит bind.slot=idx реактивно; активный слот по bindSlotIndex(sl)',
  /bind\.printer_id = p\.printer_id; bind\.slot = idx;/.test(panel)
  && has(':class="{active: bind.slot===bindSlotIndex(sl)}"'));

// A5. bindSlotIndex нормализует индекс в целое (0 валиден; недопустимое -> -1, не undefined/NaN)
check('A5. bindSlotIndex(sl): Number(sl.index), целое или -1 (0 валиден)',
  /const bindSlotIndex = \(sl\) => \{ const n = Number\(sl && sl\.index\); return Number\.isInteger\(n\) \? n : -1; \}/.test(panel));

// A6. В payload уходит ТОЧНЫЙ числовой ams_slot (существующий applyBind, эндпоинт не менялся)
check('A6. payload привязки: ams_slot = bind.slot (числовой) + external:true у внешних позиций (-1, левая -2), эндпоинт /spool/{id}/bind',
  has("body: JSON.stringify({ printer_id: bind.printer_id, ams_slot: bind.slot, external: Number(bind.slot) < 0 })")
  && has("fetch('/api/mod/inventory/spool/' + bind.sid + '/bind'"));

// A7. Занятый слот -> кнопка «Привязать» ведёт к подтверждению замены (tryBindTarget -> bindConfirm)
check('A7. занятый слот: «Привязать» -> tryBindTarget(bindPrinterObj,…) -> подтверждение замены',
  has('@click="tryBindTarget(bindPrinterObj, bind.slot)"')
  && /const tryBindTarget[\s\S]*?if \(cur\) \{[\s\S]*?bindConfirm\.open = true; return;/.test(panel));

// A8. Confirmation использует ИМЕННО выбранный слот (target.slot = idx), не соседний
check('A8. подтверждение берёт выбранный слот: bindConfirm.target={printer_id,slot:idx}; confirm шлёт его',
  /bindConfirm\.target = \{ printer_id: p\.printer_id, slot: idx \}/.test(panel)
  && /confirmBindReplace = \(\) => \{[\s\S]*?bind\.slot = bindConfirm\.target\.slot;/.test(panel));

// A9. Текущая катушка в этом слоте -> «Уже привязана», без выбора и без запроса
check('A9. selectBindSlot: слот с этой же катушкой -> flash «уже» + return (no-op, без запроса)',
  /const selectBindSlot[\s\S]*?if \(cur && bind\.sid && cur\.id === bind\.sid\) \{ flash\([\s\S]*?\); return; \}/.test(panel));

// A10. bindTargetIsSelf — без truthy-проверки числа (null = не выбран, -1 внешняя валидна)
check('A10. bindTargetIsSelf: явная проверка bind.slot == null || bind.slot < -2',
  /const bindTargetIsSelf = computed\(\(\) => \{[\s\S]*?bind\.slot == null \|\| bind\.slot < -2/.test(panel));

// A11. Закрытие/повторное открытие диалога не сохраняет старый выбор (openBind сбрасывает bind.slot)
check('A11. openBind сбрасывает bind.slot (нет случайно сохранённого выбора)',
  /const openBind = \(s\) => \{[\s\S]*?bind\.slot = \(s\.ams_slot != null && \(s\.ams_slot >= 0 \|\| Number\(s\.ams_slot\) === -2\)\) \? s\.ams_slot : -1/.test(panel));

// A12. Несколько AMS unit не смешиваются: ключ по уникальному sl.index, active по bindSlotIndex(sl)
check('A12. слоты идентифицируются по sl.index; active по bindSlotIndex(sl) (несколько AMS unit не смешивают)',
  has(':key="sl.index"') && has('bind.slot===bindSlotIndex(sl)'));

// 13. Версия модуля: Alpha 2.795 — semver-порог вместо хрупкого точного пина (точный пин краснел
//     после каждого патча inventory, что и было причиной ложного падения до 2.795).
const verGE = (a, b) => { const pa = String(a).split('.').map(Number), pb = b.split('.').map(Number); for (let i = 0; i < 3; i++) { if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0); } return true; };
check('13. версия inventory валидна (semver) и не ниже 1.7.24', /^\d+\.\d+\.\d+$/.test(mj.version) && verGE(mj.version, '1.7.24'));

// 14. Vue-шаблон компилируется реальным компилятором (вендорный Vue, identity-декодер сущностей)
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
check('14. Vue-шаблон компилируется без ошибок' + (compileOk ? '' : ' [' + compileErr + ']'), compileOk);

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: наглядный выбор принтера — все инварианты выполнены'));
process.exit(fail ? 1 : 0);
