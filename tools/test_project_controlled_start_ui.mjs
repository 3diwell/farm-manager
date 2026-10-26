// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// UI-фаза 5B2a «Контрольный запуск одной печати» — core Alpha 2.748.
// Проверяет РЕАЛЬНУЮ разметку из web/index.html, РЕАЛЬНЫЕ функции из web/app.js и РЕАЛЬНЫЙ CSS —
// статические инварианты, которые обязаны держаться без браузера.
// Главный инвариант этапа: UI НЕ УМЕЕТ ВООРУЖАТЬ. Вооружение делается ровно один раз ключами
// командной строки на сервере; страница может лишь спросить статус и один раз нажать «отправить».
// ЖИВОЙ РЕНДЕР (B1-B7 + вёрстка dark/light × 1366×768 и 1550×900) — в браузере через харнесс
// tools/e2e_feed_plan_harness.html (инструкция запуска печатается ниже).
// Запуск: node tools/test_project_controlled_start_ui.mjs   (0 = пройдено)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const INDEX = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
const APPCSS = readFileSync(join(REPO, 'web', 'app.css'), 'latin1');   // битый UTF-8 хвост -> байты
const HARNESS = readFileSync(join(REPO, 'tools', 'e2e_feed_plan_harness.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// Блок 5B2a БЕЗ комментариев: свои же пояснения не должны давать ложных срабатываний
// (напр. слово «автозапуск» в комментарии «это НЕ автозапуск»).
const nocomm = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
const CS = (() => {
  const s = APPJS.indexOf('const armStatus = ref(null);');
  const e = APPJS.indexOf('const confirmFeedClear = async () => {');
  if (s < 0 || e < 0 || e <= s) throw new Error('блок 5B2a не найден в web/app.js (якоря разошлись)');
  return nocomm(APPJS.slice(s, e));
})();
// Тело ОТПРАВКИ отдельно: в блоке есть и второй fetch (статус), и по нему нельзя судить о порядке.
// С 2.757 фактическую отправку делает общий помощник _sendControlledStart (его зовут оба пути:
// «четыре галочки» confirmControlledStart и одно-кнопочный запуск из приложения confirmInAppStart).
// Инварианты отправки (одно тело, action-lock, запрет автоповтора) проверяем именно на нём.
const SEND = (() => {
  const s = CS.indexOf('const _sendControlledStart = async (r, it) => {');
  const e = CS.indexOf('const confirmControlledStart = async () => {', s);
  if (s < 0 || e < 0 || e <= s) throw new Error('_sendControlledStart не найден в web/app.js (якоря разошлись)');
  return CS.slice(s, e);
})();
// Только КОД отправки: тексты для оператора («Не повторяйте», «Do not retry») — не автоповтор.
const SEND_CODE = SEND.replace(/'(?:[^'\\]|\\.)*'/g, "''");
// Разметка 5B2a: блок в карточке item + окно подтверждения.
const cut = (from, to) => {
  const a = INDEX.indexOf(from), b = INDEX.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('разметка 5B2a не найдена: ' + from);
  return INDEX.slice(a, b + to.length);
};
// 2.753: зона контрольного запуска живёт в карточке запуска встроенного блока (.wpx-it-go + нотисы)
const BLK = nocomm(cut('<div v-else-if="canControlledStart(wpxRunFor(pr.id), it)" class="wpx-it-go">',
                       '<!-- ambiguity'));
const CF = nocomm(cut('<div v-if="startConfirm.open"', '</div>\n</teleport>'));
const UI = BLK + '\n' + CF;

// ── A: вооружение НЕДОСТУПНО из браузера ─────────────────────────────────────────────────────
check('A1. КРИТИЧНО: фраза вооружения не встречается нигде в web/',
  !/I_UNDERSTAND_THIS_SENDS_A_REAL_PRINT/.test(APPJS + INDEX + APPCSS));
check('A2. КРИТИЧНО: UI не знает ключей вооружения (--project-one-shot-*)',
  !/project-one-shot|project_one_shot/.test(APPJS + INDEX));
check('A3. КРИТИЧНО: transport-status запрашивается из одного места и только GET (без method -> GET)',
  (APPJS.match(/fetch\('\/api\/project-orchestrator\/transport-status'/g) || []).length === 1
  && /fetch\('\/api\/project-orchestrator\/transport-status', \{ signal \}\)/.test(CS));
// A4: с 2.757 включение печати из приложения — ОТДЕЛЬНОЕ явное действие владельца (тумблер
// setPrintEnabled -> POST /api/project-orchestrator/print-enabled), покрытое отдельным тестом
// tools/test_project_print_enable.py. Поэтому «UI вообще ничего не включает» уже неверно и было бы
// ложнозелёным. Реальный остаточный инвариант: САМА команда запуска (_sendControlledStart) не имеет
// права протащить включение предохранителей — её тело только confirmed + optimistic-lock.
check('A4. КРИТИЧНО: путь ОТПРАВКИ /start не несёт флагов предохранителей (arm/enable/allowlist/транспорт)',
  !/\b(arm|disarm|enable|allowlist|allowed_printer_ids|dispatch_enabled|transport_enabled)\s*:/i.test(SEND));
check('A5. неизвестный статус = невооружён (ошибка/отказ обнуляют armStatus, не «включают»)',
  /armStatus\.value = null;/.test(CS) && /if \(!r\.ok\) throw new Error/.test(CS)
  && /armReady = computed\(\(\) => !!\(armStatus\.value && armStatus\.value\.armed && !armStatus\.value\.consumed\)\)/.test(CS));

// ── B: кнопки нет, пока сервер не подтвердил ТОЧНУЮ тройку ───────────────────────────────────
check('B1. КРИТИЧНО: кнопка контрольного запуска существует только под v-else-if="canControlledStart(...)" (в приоритете — запуск из приложения)',
  /<div v-else-if="canControlledStart\(wpxRunFor\(pr\.id\), it\)" class="wpx-it-go">/.test(BLK)
  && /@click="requestControlledStart\(wpxRunFor\(pr\.id\), it, \$event\)"/.test(BLK)
  && (BLK.match(/<button/g) || []).length === 1);
for (const [n, re] of [
  ['вооружение активно и не израсходовано', /if \(!armReady\.value \|\| !armScope\.value\) return false;/],
  ['run совпал', /armScope\.value\.run_id !== r\.run_id/],
  ['item совпал', /armScope\.value\.item_id !== it\.item_id/],
  ['принтер ПЛАНА совпал', /armScope\.value\.printer_id !== p\.printer_id\) return false;/],
  ['план готов', /p\.effective_status !== 'ready'\) return false;/],
  ['item не активен', /feedItemActive\(it\)\) return false;/],
  ['состояние pending/eligible', /return \['pending', 'eligible'\]\.includes\(it\.state\);/],
]) check('B2. canControlledStart требует: ' + n, re.test(CS));
check('B3. КРИТИЧНО: requestControlledStart перепроверяет право сам, не доверяя разметке',
  /const requestControlledStart = \(r, it, ev\) => \{\s*if \(!canControlledStart\(r, it\) \|\| startItemBusy\(r\.run_id, it\.item_id\)\) return;/.test(CS));

// ── C: четыре галочки, native confirm() запрещён ─────────────────────────────────────────────
check('C1. КРИТИЧНО: ровно ЧЕТЫРЕ отдельные проверки',
  /const START_CHECKS = \['plate_empty', 'printer_ok', 'spool_ok', 'nearby'\];/.test(CS));
check('C2. КРИТИЧНО: отправка разблокируется только когда отмечены ВСЕ четыре',
  /startApproveReady = computed\(\(\) => START_CHECKS\.every\(\(k\) => startConfirm\.checks\[k\] === true\)\)/.test(CS)
  && /class="pw-btn danger cs-go" :disabled="!startApproveReady"/.test(CF));
check('C3. галочки при каждом открытии сбрасываются в выкл',
  /for \(const k of START_CHECKS\) ch\[k\] = false;/.test(CS) && /startConfirm\.checks = ch; startConfirm\.open = true;/.test(CS));
check('C4. КРИТИЧНО: native confirm\\(\\)/alert\\(\\) не используются', !/(^|[^.\w])(confirm|alert)\s*\(/.test(CS));
// Alpha 2.815: граница СМЕЩЕНА намеренно. Слои больше не телепортируются в голый <body>:
// у #app есть z-index:1, он создаёт stacking context, поэтому все полноэкранные слои уходят
// в один общий overlay root — соседний с #app узел. Требование к самому окну не изменилось.
check('C5. окно — модальный слой в общем overlay root с role=dialog и закрытием по фону',
  /<teleport to="#fm-overlay-root">\s*<div v-if="startConfirm\.open" class="pf-cf-back cs-cf-back" @click\.self="closeStartConfirm\(\)">/.test(INDEX)
  && /role="dialog" aria-modal="true" aria-labelledby="cs-t"/.test(CF)
  && /<div id="fm-overlay-root"><\/div>/.test(INDEX));
check('C6. слой зарегистрирован в Escape-stack и снимается при закрытии',
  /registerEscapeLayer\(/.test(CS) && /unregisterEscapeLayer\(/.test(CS));

// ── D: тело POST — только canonical optimistic-lock ──────────────────────────────────────────
// Счёт по project-runs/.../start: посторонний /api/diagnostics/bambu-sniff/start к этапу не относится.
check('D1. КРИТИЧНО: запуск плана вызывается РОВНО из одного места во всём app.js',
  (APPJS.match(/'\/api\/project-runs\/' \+ encodeURIComponent\([^)]*\) \+ '\/start'/g) || []).length === 1
  && /fetch\('\/api\/project-runs\/' \+ encodeURIComponent\(r\.run_id\) \+ '\/start', \{/.test(SEND));
const BODY = (SEND.match(/const body = \{[\s\S]*?\};/) || [''])[0];
// Alpha 2.749: тело собирается ИЗ ПРОВЕРЕННОГО снимка (ver), а не напрямую из r/it. Это и есть
// fail-closed: пройти мимо startVersions() и подсунуть undefined больше нельзя.
check('D2. КРИТИЧНО: в теле только confirmed + item_id + три expected_* — ни принтера, ни слота, ни катушки, ни флагов',
  /confirmed: true/.test(BODY) && /item_id: it\.item_id/.test(BODY)
  && /expected_run_updated_at: ver\.run/.test(BODY) && /expected_item_updated_at: ver\.item/.test(BODY)
  && /expected_feed_fingerprint: ver\.fp/.test(BODY)
  && !/printer|ams_slot|spool|enabled|allow|approved_by|force/i.test(BODY));
check('D2b. КРИТИЧНО: три значения берутся ТОЛЬКО из startVersions(), без запасных значений',
  /const ver = startVersions\(r, it\);/.test(SEND)
  && SEND.indexOf('const ver = startVersions(r, it);') < SEND.indexOf('const body = {')
  && /if \(!ver\) \{/.test(SEND)
  && !/Date\.now\(\)|created_at|built_at|\|\| 0\b/.test(BODY));
check('D2c. КРИТИЧНО: startVersions требует НАСТОЯЩИЕ числа и непустой отпечаток (undefined/строка/NaN не проходят)',
  /const num = \(v\) => typeof v === 'number' && isFinite\(v\);/.test(CS)
  && /if \(!num\(r\.updated_at\) \|\| !num\(it\.updated_at\)\) return null;/.test(CS)
  && /if \(typeof p\.fingerprint !== 'string' \|\| !p\.fingerprint\) return null;/.test(CS));
check('D2d. КРИТИЧНО: без версии снимка кнопки нет, а вместо неё — постоянная понятная ошибка',
  /if \(!startVersions\(r, it\)\) return false;/.test(CS)
  && /startVersionBlocked\(wpxRunFor\(pr\.id\), it\)/.test(BLK)
  && /Не удалось получить версию плана\. Обновите данные; запуск заблокирован\./.test(BLK));
check('D3. КРИТИЧНО: второй POST не уходит (action-lock ставится ДО fetch отправки)',
  SEND.indexOf('if (startBusy.value[k]) return;') >= 0
  && SEND.indexOf('if (startBusy.value[k]) return;') < SEND.indexOf('await fetch(')
  && /startBusy\.value = Object\.assign\(\{\}, startBusy\.value, \{ \[k\]: true \}\);/.test(SEND));
check('D4. КРИТИЧНО: отправка невозможна без всех галочек и без пары run/item',
  /if \(!r \|\| !it \|\| !startApproveReady\.value\) return;/.test(CS));

// ── E: честность исхода ──────────────────────────────────────────────────────────────────────
check('E1. КРИТИЧНО: accepted НЕ выдаётся за «печать началась»',
  /'Команда отправлена\. Ожидается подтверждение старта от принтера\.'/.test(CS)
  && !/Печать (запущена|началась|идёт)|Printing started/i.test(CS + UI));
check('E2. КРИТИЧНО: потерянный ответ -> НИКАКОГО автоповтора (в КОДЕ отправки нет таймеров и циклов)',
  !/setTimeout|setInterval|requestAnimationFrame|while\s*\(|for\s*\(/.test(SEND_CODE)
  && (SEND_CODE.match(/await fetch\(/g) || []).length === 1);
check('E3. КРИТИЧНО: при потерянном ответе блокировка НЕ снимается (повтор невозможен)',
  /lost = true;/.test(CS) && /if \(!lost\) \{\s*const b = Object\.assign\(\{\}, startBusy\.value\); delete b\[k\]; startBusy\.value = b;\s*\}/.test(CS));
check('E4. блокировка снимается только после авторитетного снимка сервера',
  CS.indexOf('await refreshFeedRun(r.run_id)') < CS.indexOf('if (!lost) {')
  && /await loadArmStatus\(\);/.test(CS));
check('E5. отказ сервера показывается человеческим текстом причины, а не голым кодом',
  /feedReasonText\(\(j && j\.reason\) \|\| \('http ' \+ resp\.status\)\)/.test(CS));
check('E6. КРИТИЧНО: в окне сказано, что команда НАСТОЯЩАЯ и следующая деталь НЕ запустится сама',
  /НАСТОЯЩАЯ команда печати/.test(CF) && /автоматически НЕ запустится/.test(CF));
check('E7. КРИТИЧНО: слово «Автозапуск» в разметке 5B2a не употребляется', !/Автозапуск|автозапуск/.test(UI));

// ── F: факты в окне берутся из сохранённого плана, цвет — только через safeHex ────────────────
check('F1. окно показывает принтер/подачу/катушку/материал ИЗ ПЛАНА (startConfirm.cand)',
  /startConfirm\.cand\.printer_id/.test(CF) && /feedSlotLabel\(startConfirm\.cand\.ams_slot[,)]/.test(CF)
  && /startConfirm\.cand\.spool_id/.test(CF) && /startConfirm\.cand\.inventory_material/.test(CF)
  && /startConfirm\.cand = it\.feed_plan;/.test(CS));
check('F2. КРИТИЧНО: цвет в style идёт только через feedSwatch (safeHex), без конкатенации',
  (CF.match(/:style="/g) || []).length === (CF.match(/:style="feedSwatch\(/g) || []).length
  && !/:style="'/.test(CF));

// ── G: экспорт в шаблон (ведущий «_» шаблону не виден) ───────────────────────────────────────
const NAMES = ['armStatus', 'armScope', 'armReady', 'startConfirm', 'START_CHECKS', 'startCheckText',
  'startKey', 'startItemBusy', 'startItemNotice', 'startItemUnknown', 'canControlledStart',
  'startApproveReady', 'toggleStartCheck', 'requestControlledStart', 'closeStartConfirm',
  'confirmControlledStart', 'loadArmStatus'];
const RET = APPJS.slice(APPJS.lastIndexOf('return {'), APPJS.lastIndexOf('};'));
check('G1. КРИТИЧНО: все имена 5B2a экспортированы из setup', NAMES.every((n) => new RegExp('\\b' + n + '\\b').test(RET)));
check('G2. КРИТИЧНО: ни одно имя для шаблона не начинается с «_»', NAMES.every((n) => !n.startsWith('_')));
const USED = new Set((UI.match(/\b(?:arm|start|can|toggle|request|confirm|close)[A-Za-z_]*\b/g) || [])
  .filter((n) => new RegExp('const ' + n + '\\b').test(CS)));
check('G3. КРИТИЧНО: каждая функция, вызываемая из разметки 5B2a, экспортирована',
  [...USED].every((n) => new RegExp('\\b' + n + '\\b').test(RET)));

// ── H: CSS — слой и прокрутка ────────────────────────────────────────────────────────────────
check('H1. окно подтверждения лежит на слое .pf-cf-back (выше панелей планов и отправок, ниже алертов)',
  /class="pf-cf-back cs-cf-back"/.test(CF) && /\.pf-cf-back\s*\{[^}]*z-index:\s*100000/.test(APPCSS));
check('H2. КРИТИЧНО: длинное окно прокручивается внутри себя, а не растягивает страницу',
  /\.cs-cf \{[^}]*max-height: calc\(100vh - 32px\)[^}]*overflow-y: auto/.test(APPCSS)
  && /overflow-x: hidden/.test((APPCSS.match(/\.cs-cf \{[^}]*\}/) || [''])[0] + APPCSS.slice(APPCSS.indexOf('.cs-cf {'), APPCSS.indexOf('.cs-facts'))));
// Якорь ТОЛЬКО ASCII: app.css читается как latin1, кириллица в комментарии тут не найдётся никогда
// (indexOf -> -1, slice(-1) -> один символ, и проверка молча становится вакуумной).
const CSS5B2A = (() => {
  const a = APPCSS.indexOf('.cs-blk.armed');
  if (a < 0) throw new Error('CSS 5B2a не найден в web/app.css');
  return APPCSS.slice(a);
})();
check('H3. КРИТИЧНО: backdrop-filter в блоке 5B2a не объявлен', !/backdrop-filter/.test(CSS5B2A));
check('H4. вооружённый блок помечен цветом опасности из палитры, а не хардкодом',
  /\.cs-blk\.armed \{ border-color: var\(--fm-danger\); \}/.test(APPCSS));

// ── I: харнесс живого рендера смонтирует именно эту разметку ─────────────────────────────────
check('I1. харнесс вырезает окно 5B2a по тому же якорю, что стоит в index.html',
  /cut\('<div v-if="startConfirm\.open"'/.test(HARNESS) && INDEX.includes('<div v-if="startConfirm.open"'));
check('I2. КРИТИЧНО: харнесс по-прежнему бомбит печатные endpoint\'ы (кроме легитимного /start)',
  /window\.__BOOM\.push/.test(HARNESS) && /\\\/print\\b\|print_path\|upload_print/.test(HARNESS)
  && !/\\\/start\\b\|/.test(HARNESS));

console.log(fail ? '\nПРОВАЛЕНО: ' + fail : ('\nВСЁ ЗЕЛЁНОЕ: UI контрольного запуска не умеет вооружать (фразы и '
  + 'ключей нет, transport-status только GET), кнопка появляется лишь при точном совпадении '
  + 'run/item/printer с готовым планом, требует все четыре галочки, шлёт РОВНО один POST с одним '
  + 'canonical-телом, accepted не выдаётся за начало печати, потерянный ответ запрещает повтор.\n'
  + 'ЖИВОЙ РЕНДЕР (B1-B7 + вёрстка): поднять статический сервер в корне репозитория и открыть\n'
  + '  tools/e2e_feed_plan_harness.html  — итог печатается в <pre id="out">.'));
process.exit(fail ? 1 : 0);
