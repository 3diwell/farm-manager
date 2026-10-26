// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Frontend-инварианты менеджера модулей (Настройки → Система → Модули), Alpha 2.719.
// Регрессия бага: клик по кнопке действия карточки открывал модуль (карточка была <button>,
// а кнопки действий — вложенными в неё). Тест фиксирует исправление на уровне разметки/логики.
// Запуск: node tools/test_module_manager_ui.mjs   (0 = все инварианты выполнены)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const html = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
const app = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');

// фрагмент двух карточек модулей (launcher + disabled)
const a = html.indexOf('<div v-for="l in moduleLaunchers"');
const oldBtn = html.indexOf('<button v-for="l in moduleLaunchers"');
const b = html.indexOf('<button v-if="moduleRestartNeeded"', a >= 0 ? a : 0);
const card = a >= 0 && b > a ? html.slice(a, b) : '';

let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// 1. Карточка — НЕ <button> (иначе вложенные кнопки действий ненадёжны); открытие через guard-хелпер
//    3.000 (встроенные настройки модуля): роль и tabindex стали ПРИВЯЗКАМИ. Карточка модуля,
//    у которого есть только настройки, окна не открывает — значит и кнопкой притворяться не должна:
//    role/tabindex у неё пустые. Смысл проверки прежний: карточка-<div>, у настоящего пускателя
//    роль кнопки и фокус с клавиатуры, открытие — через guard-хелпер.
check('1. карточка модуля — кликабельный <div role="button">, а не <button>; открытие через openModuleFromCard',
  oldBtn < 0
  && /<div v-for="l in moduleLaunchers"[^>]*:role="[^"]*'button'[^"]*"[^>]*:tabindex="[^"]*0[^"]*"[^>]*@click="openModuleFromCard\(\$event, l\)"/.test(card));

// 2. Клавиатурная доступность карточки сохранена (Enter/Пробел открывают)
check('2. карточка открывается с клавиатуры (@keydown.enter/@keydown.space → runInstalledModule)',
  /@keydown\.enter\.prevent="runInstalledModule\(l\)"/.test(card) && /@keydown\.space\.prevent="runInstalledModule\(l\)"/.test(card));

// 3. ВСЕ кнопки действий карточки изолированы: data-module-action + @click.stop (не только удаление)
const actions = [['disableModule', 'fm-set-mod-sw'], ['deleteModule', 'fm-set-mod-del'], ['enableModule', 'fm-set-mod-sw']];
check('3. все действия (отключить/удалить/включить) имеют data-module-action + @click.stop',
  actions.every(([fn]) => new RegExp('data-module-action[^>]*@click\\.stop="' + fn + '\\(').test(card)
                       || new RegExp('@click\\.stop="' + fn + '\\([^"]*"[^>]*data-module-action').test(card)
                       || (card.includes('data-module-action') && card.includes('@click.stop="' + fn + '('))));

// 4. Действия достижимы с клавиатуры и НЕ всплывают на карточку (stop на keydown)
check('4. действия по клавиатуре с изоляцией (@keydown.enter.stop.prevent / @keydown.space.stop.prevent)',
  actions.every(([fn]) => card.includes('@keydown.enter.stop.prevent="' + fn + '(') && card.includes('@keydown.space.stop.prevent="' + fn + '(')));

// 5. Второй уровень защиты: openModuleFromCard игнорирует события из action-зоны (closest data-module-action)
check('5. openModuleFromCard: guard через closest([data-module-action]) — событие из action-зоны не открывает модуль',
  /const openModuleFromCard = \(ev, l\) =>/.test(app) && /closest\('\[data-module-action\]'\)/.test(app));

// 6. Подтверждение удаления сохранено. 2.959: вопрос задаёт САМА программа (askConfirm),
//    а не окно браузера confirm() — смысл проверки прежний: спросили до запроса.
check('6. удаление сохраняет подтверждение (confirm) перед запросом',
  /const deleteModule = async \(l\) => \{[\s\S]*?if \(!await askConfirm\(/.test(app) && app.includes("fetch('/api/modules/' + l.moduleId, { method: 'DELETE' })"));

// 7. Busy-защита: один клик = один запрос (guard moduleBusy) во всех трёх действиях, с корректным сбросом
const busyGuarded = (fn) => new RegExp('const ' + fn + ' = async \\([^)]*\\) => \\{\\s*if \\(moduleBusy\\.value\\) return;').test(app);
check('7. busy-lock во всех действиях (if (moduleBusy.value) return) — двойной клик не делает второй запрос',
  ['deleteModule', 'disableModule', 'enableModule'].every(busyGuarded)
  && /moduleBusy\.value = true/.test(app) && (app.match(/moduleBusy\.value = false/g) || []).length >= 3);

// 8. Ошибка API: карточка остаётся, показывается сообщение, busy сбрасывается (moduleInstallMsg ok:false)
check('8. при ошибке — сообщение пользователю и сброс busy (moduleInstallMsg ok:false + moduleBusy=false после)',
  app.includes("moduleInstallMsg.value = { ok: false") && /await loadInstalledModules\(\);\s*moduleBusy\.value = false;/.test(app));

// 9. На карточке НЕТ mouse/pointer/drag-обработчиков, которые могли бы открыть модуль в обход клика
check('9. карточка без @mousedown/@pointerdown/@mouseup/@dblclick/draggable (никакой drag-логики)',
  !/@mousedown|@pointerdown|@mouseup|@dblclick|draggable/.test(card));

// 10. Регресс-охрана: старая структура <button v-for="l in moduleLaunchers"> удалена
check('10. регресс: карточка-<button> с вложенными действиями больше не существует', oldBtn < 0 && card.length > 0);

// ── 17.09.2026, по слову владельца: вместо крестика у установленного модуля — ползунок ВКЛ/ВЫКЛ.
const css = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
check('11. у включённого модуля — переключатель в положении ВКЛ (а не крестик)',
  /class="fm-set-mod-sw on"[^>]*role="switch"[^>]*aria-checked="true"/.test(card)
  && /@click\.stop="disableModule\(l\)"/.test(card)
  && card.includes("'ВКЛ':'ON'") && !/name="close"/.test(card.split('fm-set-mod-sw')[0].slice(-400)));
check('12. у выключенного модуля — тот же переключатель в положении ВЫКЛ',
  /class="fm-set-mod-sw"[^>]*role="switch"[^>]*aria-checked="false"/.test(card)
  && /@click\.stop="enableModule\(m\)"/.test(card) && card.includes("'ВЫКЛ':'OFF'"));
check('13. переключатель виден как переключатель: дорожка, кружок и цвет включённого',
  /\.fm-set-mod-sw\{/.test(css) && /\.fm-set-mod-sw-r\{/.test(css) && /\.fm-set-mod-sw-k\{/.test(css)
  && /\.fm-set-mod-sw\.on \.fm-set-mod-sw-k\{left:16px/.test(css));
check('14. переключатель доступен с клавиатуры и не открывает модуль по клику',
  /class="fm-set-mod-sw[^"]*"[^>]*data-module-action/.test(card)
  && /@keydown\.enter\.stop\.prevent="disableModule\(l\)"/.test(card)
  && /@keydown\.enter\.stop\.prevent="enableModule\(m\)"/.test(card));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: менеджер модулей — все инварианты выполнены'));
process.exit(fail ? 1 : 0);
