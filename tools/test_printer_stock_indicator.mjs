// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Тест индикатора-КНОПКИ «Сверить катушки со складом» на карточке принтера — core Alpha 2.739.
// Извлекает РЕАЛЬНЫЕ printerStockBound/filamentForPrinter/filamentRows/safeHex из web/app.js и ВЫПОЛНЯЕТ их
// на снапшоте ТОЧНО той формы, что отдаёт настоящий /api/printer-filament (её проверяет и фиксирует
// tools/test_printer_stock_indicator_backend_e2e.py — реальный провайдер Inventory + реальный агрегатор ядра).
//
// ВАЖНО (урок Alpha 2.737): раньше здесь проверялось только НАЛИЧИЕ grid-разметки в index.html. Это давало
// ложное «зелено»: индикатор жил ТОЛЬКО внутри <div v-if="viewMode==='grid'"> (grid-summary), а режим по
// умолчанию — 'list' (app.js: const viewMode = ref('list')), поэтому в реальном UI его не было вовсе.
// Теперь разметка проверяется В ОБОИХ режимах. Живой рендер проверялся стендом
// tools/e2e_badge_harness.html; стенд удалён 26.08.2026 как неработоспособный: он читал
// tools/_e2e_payload.json, а этот файл запрещено держать в дереве с Alpha 2.797.
// Запуск: node tools/test_printer_stock_indicator.mjs   (0 = пройдено)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const INDEX = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
const COMPOSABLE = readFileSync(join(REPO, 'web', 'composables', 'usePrinterFilament.js'), 'utf8');
const APPCSS = readFileSync(join(REPO, 'web', 'app.css'), 'latin1');   // app.css: битый UTF-8 хвост -> читаем как байты
const SERVER = readFileSync(join(REPO, 'server.py'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// извлечение arrow-функции `const NAME = (args) => { ... };` со сбалансированными скобками
const extractArrow = (src, decl) => {
  const s = src.indexOf(decl); if (s < 0) throw new Error('не найдено: ' + decl);
  const bodyOpen = src.indexOf('{', s + decl.length);
  let d = 0, i = bodyOpen;
  for (; i < src.length; i++) { const c = src[i]; if (c === '{') d++; else if (c === '}') { d--; if (d === 0) break; } }
  return src.slice(s, i + 1) + ';';
};
const SRC = [extractArrow(APPJS, 'const safeHex = (v) =>'),
             extractArrow(APPJS, 'const filamentForPrinter = (p) =>'),
             extractArrow(APPJS, 'const printerStockBound = (p) =>'),
             extractArrow(APPJS, 'const filamentRows = (p) =>')].join('\n');
const build = new Function('printerFilament', 'lang', 'amsGroups', 'amsIsHt',
  SRC + '\n return { filamentForPrinter, filamentRows, printerStockBound };');

// строка провайдера склада = spool + ЯВНЫЙ признак inventory_bound/source (как отдаёт _inv_filament_provider)
const spool = (id, o) => Object.assign({ id, material: 'PLA', color_hex: 'ff0000', weight_remaining_g: 500, weight_total_g: 1000 }, o || {});
const inv = (o) => Object.assign({ inventory_bound: true, source: 'inventory' }, o);
const SNAP = {
  P_EXT: { has_ams: false, slots: [inv({ index: -1, external: true, spool: spool('e1') })] },
  P_AMS: { has_ams: true, slots: [
    inv({ index: 0, unit: 0, tray: 0, spool: spool('a0', { material: 'PETG' }) }),
    inv({ index: 5, unit: 1, tray: 1, spool: spool('a5', { material: 'ASA' }) }),
    inv({ index: 512, unit: 128, tray: 0, spool: spool('a512', { material: 'PA-CF' }) })] },
  P_TELEM: { has_ams: true, slots: [] },                       // telemetry-only: складской катушки нет
  P_OTHER: { has_ams: true, slots: [                            // сырая строка НЕ от модуля: spool есть, ни флага, ни module_id
    { index: 0, unit: 0, tray: 0, spool: spool('z0') }] },
  // Alpha 2.755: СТАРЫЙ модуль склада (1.7.20) — привязанная катушка БЕЗ полей inventory_bound/source,
  // но с module_id (его ставит generic-агрегатор ЯДРА на любую версию модуля). Значок ОБЯЗАН гореть.
  P_OLD: { has_ams: false, module_id: 'inventory',
           slots: [{ index: -1, external: true, spool: spool('o1') }] },
  // P_NONE отсутствует в snapshot (модуль не установлен / нет привязок)
};
const api = build({ value: SNAP }, { value: 'ru' }, () => [], () => false);

// ── условие показа: ТОЛЬКО по явному признаку, один значок на принтер ──
check('I1. external(-1) bound -> индикатор есть', api.printerStockBound('P_EXT') === true);
check('I2. AMS0 + мульти-AMS5 + AMS HT512 bound -> индикатор есть, и он ОДИН (булево, не количество)',
  api.printerStockBound('P_AMS') === true && api.filamentRows('P_AMS').length === 3);
check('I3. telemetry-only (AMS-материал без складской катушки) -> индикатора нет',
  api.filamentForPrinter('P_TELEM') !== null && api.printerStockBound('P_TELEM') === false);
check('I4. принтера нет в snapshot (Inventory не установлен) -> индикатора нет, без ошибок (fail-open)',
  api.printerStockBound('P_NONE') === false && api.filamentForPrinter('P_NONE') === null);
check('I5. пустой snapshot целиком (Inventory отсутствует) -> индикатора нет для любого принтера',
  build({ value: {} }, { value: 'ru' }, () => [], () => false).printerStockBound('P_EXT') === false);
check('I6. сырая строка НЕ от модуля (spool есть, но ни inventory_bound/source, ни module_id) -> индикатора НЕТ',
  api.printerStockBound('P_OTHER') === false);
check('I6b. КРИТИЧНО: СТАРЫЙ модуль склада (spool + module_id, без явных полей) -> индикатор ЕСТЬ '
  + '(значок не зависит от версии модуля — корень бага «периодически пропадает»)',
  api.printerStockBound('P_OLD') === true);
check('I7. признак берётся из ЯВНЫХ полей ИЛИ из module_id агрегатора, а не из материала/цвета/телеметрии',
  /inventory_bound === true \|\| s\.source === 'inventory' \|\| !!fil\.module_id/.test(APPJS)
  && !/\.material|\.color_hex|reported_/.test(APPJS.slice(APPJS.indexOf('const printerStockBound'), APPJS.indexOf('const filamentRows'))));

// ── разметка: индикатор есть в ОБОИХ режимах карточки и является КНОПКОЙ (Alpha 2.739) ──
const BTN = /<button type="button" v-if="printerStockBound\(p\)" class="pc-stock[^>]*><svg-icon name="layers" class="w-3 h-3"><\/svg-icon><\/button>/g;
const hits = INDEX.match(BTN) || [];
check('M1. индикатор объявлен РОВНО дважды: компактная сетка + список (одинаковые кнопка и иконка layers)',
  hits.length === 2);
check('M2. индикатор ЕСТЬ в compact grid (grid-summary)',
  /v-if="printerStockBound\(p\)"/.test(INDEX.slice(INDEX.indexOf('class="grid-summary'), INDEX.indexOf('class="grid-backdrop'))));
const listPart = INDEX.slice(INDEX.indexOf('class="printer-card-primary'), INDEX.indexOf('class="card-flyout'));
check('M3. индикатор ЕСТЬ в list-режиме, в ВИДИМОЙ шапке карточки (рядом с именем, не в срезаемом .pc-fil)',
  /v-if="printerStockBound\(p\)"/.test(listPart)
  && listPart.indexOf('v-if="printerStockBound(p)"') < listPart.indexOf('class="pc-fil"'));
check('M4. старое условие v-if="filamentRows(p).length" для значка больше не используется',
  !/v-if="filamentRows\(p\)\.length" class="(shrink-0|pc-stock)/.test(INDEX));
check('M5. расширенный блок .pc-fil цел (по filamentForPrinter(p)), строки несут tooltip привязки',
  INDEX.includes('v-if="filamentForPrinter(p)" class="pc-fil"')
  && /class="pc-fil-row"[^>]*Катушка привязана со склада/.test(INDEX));
check('B1. это <button type="button"> с aria-label и title «Сверить катушки со складом» (оба режима)',
  hits.length === 2 && hits.every((h) => /type="button"/.test(h)
    && /:aria-label="lang==='ru' \? 'Сверить катушки со складом'/.test(h)
    && /:title="lang==='ru' \? 'Сверить катушки со складом'/.test(h)));
// Ровно ОДНО открытие на действие: элемент — нативная <button>, поэтому Enter/Space сами порождают click.
// Своих @keydown на кнопке быть НЕ должно, иначе keydown + native click = два вызова. Гасим только всплытие
// клика (иначе раскроется карточка) и ПКМ (у карточки своё контекстное меню).
// Для сравнения: у span role="button" в менеджере модулей @keydown.enter/space нужны — там нативной
// активации нет; здесь она есть, и дублировать её нельзя.
check('B2. клик не всплывает в карточку (@click.stop), ПКМ не мешает, и НЕТ своих keydown-обработчиков '
  + '(нативная активация -> ровно один вызов на Enter/Space, без двойного)',
  hits.every((h) => /@click\.stop="openFilamentSource\(p\)"/.test(h)
    && /@contextmenu\.stop/.test(h)
    && !/@keydown/.test(h)));
check('B3. кнопка выглядит кликабельной: hover и focus-visible объявлены (клавиатура видит фокус)',
  /\.pc-stock:hover\s*\{/.test(APPCSS) && /\.pc-stock:focus-visible\s*\{/.test(APPCSS)
  && /\.pc-stock\s*\{[^}]*cursor:\s*pointer/.test(APPCSS));
check('B4. открытие идёт ЧЕРЕЗ СУЩЕСТВУЮЩИЙ generic-механизм лаунчера (runInstalledModule), '
  + 'без своего канала/слушателя (значит и повторной регистрации подписок нет)',
  /const openFilamentSource = \(p\) =>/.test(APPJS)
  && /runInstalledModule\(\{ moduleId: mid/.test(APPJS)
  && !/fm:filament-source-open/.test(APPJS));
check('B5. клик передаёт printer_id, action="reconcile" и source (module_id из generic-агрегатора)',
  /action: 'reconcile', printerId: pid/.test(APPJS) && /const mid = fil && fil\.module_id/.test(APPJS));
check('B6. ядро НЕ знает про склад: module_id берётся из ответа агрегатора, «inventory» в ядре не зашит',
  /info\["module_id"\] = mid/.test(SERVER) && !/['"]inventory['"]/.test(
    APPJS.slice(APPJS.indexOf('const openFilamentSource'), APPJS.indexOf('const closeActiveModule'))));
check('B7. модуль отключён/удалён/без лаунчера -> клик безопасно ничего не делает (ранний выход)',
  /if \(!mid\) return;/.test(APPJS) && /if \(!l\) return;/.test(APPJS));
check('B8. повторный клик при уже открытом окне перенаводит инструмент (nonce), второго окна не создаёт',
  /_filSourceNonce \+= 1;/.test(APPJS) && /nonce: _filSourceNonce/.test(APPJS));

// ── обновление после bind/unbind: generic-сигнал, без агрессивного polling и без связи ядро->склад ──
check('S1. ядро слушает generic-событие обновления привязки (переиспользует свой же poll)',
  /addEventListener\('fm:printer-filament-changed', poll\)/.test(COMPOSABLE));
check('S2. частота штатного опроса не увеличена (10с), новый канал данных не добавлен',
  /setInterval\(poll, 10000\)/.test(COMPOSABLE) && (COMPOSABLE.match(/fetch\(/g) || []).length === 1);
check('S3. ядро НЕ импортирует inventory backend и НЕ ходит в /api/mod/inventory/*',
  !/import[^\n]*inventory\/backend/.test(APPJS) && !/\/api\/mod\/inventory/.test(APPJS)
  && !/\/api\/mod\//.test(COMPOSABLE));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: индикатор склада показывается по ЯВНОМУ признаку провайдера (external -1 / AMS0 / мульти-AMS / AMS HT), ' +
  'один на принтер, в ОБОИХ режимах карточки; telemetry-only, чужие provider-строки и отсутствие Inventory ' +
  'значок не включают (fail-open); обновление — generic-сигналом через существующий poll'));
process.exit(fail ? 1 : 0);
