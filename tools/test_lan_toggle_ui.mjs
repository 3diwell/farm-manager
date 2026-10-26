// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Инварианты переключателя «Локальное обнаружение» (Настройки → Система → Сеть и доступ) — Alpha 2.720.
// Статические проверки web/app.js + web/index.html + КОМПИЛЯЦИЯ шаблона #app вендорным Vue.
// Запуск: node tools/test_lan_toggle_ui.mjs   (0 = все инварианты выполнены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const appjs = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const html = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');

let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// Alpha 2.795: границы функций для точечных (а не сквозных по всему файлу) проверок тела.
const fnSlice = (name) => {
  const i = appjs.indexOf('const ' + name + ' =');
  if (i < 0) return '';
  const n = appjs.indexOf('\n    const ', i + 1);
  return appjs.slice(i, n < 0 ? i + 2000 : n);
};

// 1. Toggle отображает СОХРАНЁННОЕ состояние: loadNetworkInfo(GET /api/network) -> _applyNet.
//    Alpha 2.787: default OFF — lanAccess включается ТОЛЬКО при явном requested/enabled, иначе false
//    (прежнее `!== false` трактовало отсутствие/мусор как включено; тест обновлён под усиленный контракт).
check('1. loadNetworkInfo читает /api/network через _applyNet; lanAccess по СОХРАНЁННОМУ состоянию с default OFF; вызван при открытии настроек',
  /const loadNetworkInfo = async \(\) => \{[\s\S]*?fetch\('\/api\/network'\)[\s\S]*?_applyNet/.test(appjs)
  && appjs.includes('lanAccess.value = (j.requested_enabled === true) || (j.lan_access_enabled === true)')
  && /loadStorageInfo\(\);\s*loadNetworkInfo\(\);/.test(appjs));

// 2. OFF показывает «Только этот компьютер»
check('2. OFF -> «Только этот компьютер» / «This computer only»',
  html.includes("'Только этот компьютер':'This computer only'"));

// 3. ON показывает «Доступен в локальной сети»
check('3. ON -> «Доступен в локальной сети» / «Available on the network»',
  html.includes("'Доступен в локальной сети':'Available on the network'"));

// 4. Изменение вызывает РОВНО один save-запрос POST /api/network со строгим boolean
check('4. setLanAccess шлёт один POST /api/network c { lan_access_enabled: !!v }',
  /const setLanAccess = async \(v\) => \{[\s\S]*?fetch\('\/api\/network', \{ method: 'POST'[\s\S]*?lan_access_enabled: !!v/.test(appjs)
  && (appjs.match(/fetch\('\/api\/network', \{ method: 'POST'/g) || []).length === 1);

// 4b. Alpha 2.787: включение при НЕвыполненных предпосылках (нет AUTH+admin) НЕ шлёт POST —
//     ранний выход в loadNetworkInfo. Это ключевой сетевой инвариант: LAN нельзя открыть без прав.
check('4b. предпосылки 2.787: при !lanCanEnable включение не шлёт save-запрос (ранний return -> loadNetworkInfo)',
  /const setLanAccess = async \(v\) => \{[\s\S]{0,160}if \(v && !lanCanEnable\.value\) \{ await loadNetworkInfo\(\); return; \}/.test(appjs));

// 5. Двойной клик не создаёт два запроса (busy-guard) + тумблер disabled во время сохранения.
//    Alpha 2.787: :disabled стал составным — гасит тумблер и при невыполненных предпосылках.
// Alpha 2.837: в составной :disabled добавлена МАШИННАЯ граница (!lanChangeAllowed) — сетевой
// режим, как и порт, меняется только на компьютере-сервере. Смысл прежних условий сохранён.
check('5. busy-guard: setLanAccess ранним return при lanBusy; тумблер disabled во время сохранения, при !lanCanEnable и в удалённом клиенте',
  /const setLanAccess = async \(v\) => \{\s*if \(lanBusy\.value\) return;/.test(appjs)
  && html.includes(':disabled="lanBusy || !lanChangeAllowed || (!lanAccess && !lanCanEnable)"'));

// 6. После изменения появляется «Требуется перезапуск» (по restart_required)
check('6. lanRestartRequired из restart_required; в UI пометка «Требуется перезапуск»',
  /lanRestartRequired\.value = !!j\.restart_required/.test(appjs)
  && /v-if="lanRestartRequired"[\s\S]{0,120}Требуется перезапуск/.test(html));

// 7. При ошибке сохранения toggle возвращается в прежнее состояние И перечитывает свежее (Alpha 2.787:
//    откат больше не «немой» — за ним следует loadNetworkInfo, чтобы UI не расходился с сервером).
check('7. ошибка сохранения -> откат тумблера + свежее состояние: catch { lanAccess.value = prev; await loadNetworkInfo(); }',
  /const prev = lanAccess\.value;[\s\S]*?catch \(e\) \{ lanAccess\.value = prev; await loadNetworkInfo\(\); \}/.test(appjs));

// 8. Alpha 2.834: настройка стала нативным CHECKBOX (галочка = включено): Tab/Space работают без
//    доработок, состояние читается формой, а не подписью кнопки. Составной :disabled сохранён, и
//    backend остаётся авторитетом — DOM-состояние сразу возвращается к модели, менять её вправе
//    только успешный setLanAccess.
check('8. переключатель — нативный <input type="checkbox" class="fm-chk-in" …составной :disabled… @change возвращает DOM к модели и вызывает setLanAccess> (клавиатурно доступен)',
  html.includes('<input type="checkbox" class="fm-chk-in" :checked="lanAccess" :disabled="lanBusy || !lanChangeAllowed || (!lanAccess && !lanCanEnable)" @change="$event.target.checked = lanAccess; setLanAccess(!lanAccess)">'));

// 9. Не ломается Escape stack настроек: toggle не трогает escLayers/registerEscapeLayer.
//    Alpha 2.795: проверяем ТОЛЬКО тела двух функций (прежний сквозной regex по всему файлу
//    ложно срабатывал, т.к. escLayers встречается где-то дальше — это был баг теста, не продукта).
check('9. LAN-логика не вмешивается в Escape-стек (в телах setLanAccess/loadNetworkInfo нет escLayers/registerEscapeLayer)',
  !/escLayers|registerEscapeLayer/.test(fnSlice('setLanAccess'))
  && !/escLayers|registerEscapeLayer/.test(fnSlice('loadNetworkInfo'))
  && fnSlice('setLanAccess').length > 50);

// 10. Остальные настройки системы не изменены (группа «Хранение данных» на месте)
check('10. группа «Хранение данных» сохранена (остальные системные настройки не тронуты)',
  html.includes("'Хранение данных':'Data storage'"));

// 11. Новые имена экспортированы из setup() (иначе шаблон их не увидит)
check('11. lanAccess/lanRestartRequired/lanBusy/setLanAccess/loadNetworkInfo экспортированы',
  /lanAccess, lanApplied, lanRestartRequired, lanBusy, setLanAccess, loadNetworkInfo/.test(appjs));

// 12. Перезапуск переиспользует существующий механизм doRestart (не изобретаем свой)
check('12. кнопка «Перезапустить сейчас» -> существующий doRestart()',
  /v-if="lanRestartRequired"[\s\S]{0,400}@click="doRestart\(\)"/.test(html));

// 13. Описание настройки присутствует
// Alpha 2.834: пояснение сокращено по требованию владельца (экран настроек не должен быть
// полотном текста): в строке остаётся одна короткая подсказка, а уточнение про принтеры и
// камеры вынесено в info-панель, которая показывается только при включённом доступе.
check('13. описание: короткая подсказка в строке + уточнение про принтеры в info-панели (без длинного полотна)',
  html.includes('Другие компьютеры смогут открыть Farm Manager в этой сети.')
  && html.includes('Связь с принтерами, камеры и печать от этой настройки не зависят.')
  && !html.includes('Разрешить другим компьютерам в локальной сети находить и открывать Farm Manager'));

// 14. Шаблон #app компилируется реальным Vue (вставка toggle корректна)
let compileOk = false, compileErr = '';
try {
  if (!globalThis.document) globalThis.document = { createElement: () => ({ style: {} }), querySelector: () => null, head: {} };
  if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
  let s = html.indexOf('id="app"'); s = html.lastIndexOf('<div', s);
  const openEnd = html.indexOf('>', s) + 1;
  const re = /<div\b|<\/div>/g; re.lastIndex = openEnd; let mm, depth = 1, close = -1;
  while ((mm = re.exec(html))) { depth += (mm[0] === '</div>') ? -1 : 1; if (depth === 0) { close = mm.index; break; } }
  const inner = html.slice(openEnd, close);
  const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
  const compile = Vue.compile || (Vue.default && Vue.default.compile);
  const r = compile(inner, { decodeEntities: (x) => x });
  compileOk = (typeof r === 'function');
} catch (e) { compileErr = (e && e.message) || String(e); }
check('14. шаблон #app компилируется без ошибок' + (compileOk ? '' : ' [' + compileErr + ']'), compileOk);

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: переключатель «Локальное обнаружение» — все frontend-инварианты выполнены'));
process.exit(fail ? 1 : 0);
