// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// UI-фаза 5A3b «Источник материала» — core Alpha 2.745 (dry-run: выбор и подтверждение подачи).
// Проверяет РЕАЛЬНУЮ разметку из web/index.html, РЕАЛЬНЫЕ функции из web/app.js и РЕАЛЬНЫЙ CSS —
// статические инварианты, которые обязаны держаться без браузера.
// ЖИВОЙ РЕНДЕР настоящим вендорным Vue (U1-U32 + вёрстка dark/light × 1366×768 и 1550×900) идёт в
// браузере через харнесс tools/e2e_feed_plan_harness.html — инструкция запуска печатается ниже.
// Запуск: node tools/test_project_feed_plan_ui.mjs   (0 = пройдено)
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

// Границы блока 5B2a «контрольный запуск»: он лежит ВНУТРИ того же участка app.js, но к выбору
// источника материала не относится и проверяется своим тестом (test_project_controlled_start_ui.mjs).
// Вырезаем его, иначе его единственный законный /start ломал бы инвариант «feed не печатает».
const CS_A = "const armStatus = ref(null);", CS_B = 'const confirmFeedClear = async () => {';
const cutCS = (s) => {
  const a = s.indexOf(CS_A), b = s.indexOf(CS_B);
  if (a < 0 || b < 0 || b <= a) throw new Error('блок 5B2a не найден: якоря разошлись с web/app.js');
  return s.slice(0, a) + s.slice(b);
};
// Код блока feed без комментариев: упоминания в тексте не должны давать ложных срабатываний.
const FEED_ALL = (() => {
  // Якорь БЕЗ перечня причин: состав FEED_APPROVABLE меняется по замыслу (2.751 добавила
  // manual_external), и жёсткий якорь с полным списком молча превращал indexOf в -1.
  const s = APPJS.indexOf('const FEED_APPROVABLE = [');
  const e = APPJS.indexOf('const closeActiveModule =');
  if (s < 0 || e < 0 || e <= s) throw new Error('блок feed не найден: якорь FEED_APPROVABLE разошёлся');
  return APPJS.slice(s, e).replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
})();
const FEED = cutCS(FEED_ALL);

// ── S1-S6: UI не умеет печатать ───────────────────────────────────────────────────────────────
check('S1. КРИТИЧНО: в коде feed нет ни одного печатного/запускающего endpoint',
  !/\/start\b|\/print\b|print_path|upload_print|\/api\/part\/print|send-jobs|print-queue|\/cmd\b/.test(FEED));
check('S1b. КРИТИЧНО: единственный /start на этом участке — в блоке контрольного запуска 5B2a',
  (FEED_ALL.match(/\/start\b/g) || []).length === 1);
check('S2. feed НЕ трогает подтверждение очистки стола (plate-clear) — это разные вещи',
  !/plate-clear/.test(FEED));
check('S3. feed ходит РОВНО в четыре эндпоинта 5A3a',
  /\/feed-candidates/.test(FEED) && /\/feed-plan\/' \+ path/.test(FEED)
  && ["'select'", "'approve'", "'clear'"].every((k) => FEED.includes(k)));
check('S4. GET кандидатов не входит в периодический опрос (только явное открытие/refresh)',
  !/setInterval[\s\S]{0,120}feed/i.test(APPJS) && !/PROJECT_RUNS_POLL_MS[\s\S]{0,200}feed-candidates/.test(APPJS));
check('S5. второй polling-таймер не создаётся: после действия — ОДИН существующий GET деталей run',
  /_prFetchDetail\(runId\)/.test(FEED) && !/setInterval/.test(FEED));
check('S6. approved_by в теле запроса не формируется (подпись ставит сервер по своей сессии)',
  !/approved_by/.test(FEED));

// ── S7-S10: согласие ──────────────────────────────────────────────────────────────────────────
check('S7. UI знает ровно три approvable-причины — те же, что backend (2.751: + manual_external)',
  /const FEED_APPROVABLE = \['close_color', 'inventory_declared', 'manual_external'\]/.test(APPJS));
check('S8. approved_reasons формируются ТОЛЬКО из перечня backend (не из галочек и не из констант)',
  /const reasons = \(c\.required_approval_reasons \|\| \[\]\)\.slice\(\)/.test(FEED));
check('S9. КРИТИЧНО: подтвердить можно только когда отмечены ВСЕ требуемые причины',
  /req\.every\(\(r\) => feedConfirm\.checks\[r\] === true\)/.test(FEED));
check('S10. неизвестную причину UI подтвердить не может',
  /feedConfirmUnknown[\s\S]{0,200}filter\(\(r\) => !FEED_APPROVABLE\.includes\(r\)\)/.test(FEED)
  && /if \(feedConfirmUnknown\.value\.length\) return false/.test(FEED));

// ── S11-S14: безопасность и состояния ─────────────────────────────────────────────────────────
// Проверка ПОЗИТИВНАЯ и ТОЧЕЧНАЯ: каждый образец цвета (.pf-sw) обязан получать style только из
// feedSwatch (а тот — из safeHex). Негативная («в :style нет слова color») была бы неверной: аргумент
// так и называется — c.required_color. Область — только сами образцы, а не «всё до конца файла».
const SWATCHES = INDEX.match(/<i class="pf-sw"[^>]*>/g) || [];
check('S11. цвет попадает в style ТОЛЬКО через feedSwatch -> safeHex (сырой текст не вставляется)',
  /const feedSwatch = \(hex\) => \{\s*const h = safeHex\(hex\);/.test(FEED)
  && SWATCHES.length >= 9
  && SWATCHES.every((s) => /:style="feedSwatch\([\w.]+\)"/.test(s) && !/:style="(?!feedSwatch)/.test(s)));
check('S12. активный item -> только просмотр: действия недоступны',
  /FEED_ACTIVE_STATES = \['leased', 'sending', 'waiting_start_confirmation', 'printing', 'waiting_plate_clear'\]/.test(APPJS)
  && /\['pending','eligible'\]\.includes\(it\.state\) && !feedItemActive\(it\)/.test(INDEX));
check('S13. 512 не превращается в «Слот 513»: подпись строится из unit*4+tray',
  /const unit = Math\.floor\(n \/ 4\), tray = \(n % 4\) \+ 1/.test(FEED)
  && /unit === 128 \? 'AMS HT'/.test(FEED) && !/513/.test(FEED));
//  16.10.2026 (R-137): подпись проверяется ИСПОЛНЕНИЕМ настоящей функции, а не её текстом: у двухсопельного
//  Bambu (H2D) -1 — правая внешняя катушка, -2 — левая; у односопельного и без принтера -1 — «Внешняя катушка».
const _fsl = (() => {
  const m = APPJS.match(/const feedSlotLabel = \([^)]*\) => \{[\s\S]*?\n    \};/);
  if (!m) return null;
  try {
    return new Function('lang', 'wsData', m[0] + '\nreturn feedSlotLabel;')(
      { value: 'ru' }, { value: { h2d: { nozzle_count: 2 }, p1s: { nozzle_count: 1 } } });
  } catch (e) { return null; }
})();
check('S14. внешняя катушка -1 — отдельная подпись, а не AMS 0 (у H2D -1 — правая, -2 — левая внешняя)',
  !!_fsl && _fsl(-1) === 'Внешняя катушка' && _fsl(-1, 'p1s') === 'Внешняя катушка' && _fsl(0) === 'AMS 1·1'
  && _fsl(-1, 'h2d') === 'Правая внешняя катушка' && _fsl(-2) === 'Левая внешняя катушка');
//  Подпись не роняет отрисовку там, где состояния принтеров нет вовсе (харнессы e2e_*): нейтральная подпись.
const _fsl0 = (() => {
  const m = APPJS.match(/const feedSlotLabel = \([^)]*\) => \{[\s\S]*?\n    \};/);
  try { return m ? new Function('lang', m[0] + '\nreturn feedSlotLabel;')({ value: 'ru' }) : null; } catch (e) { return null; }
})();
check('S14b. без состояния принтеров подпись -1 с номером принтера — «Внешняя катушка», без исключения',
  !!_fsl0 && (() => { try { return _fsl0(-1, 'pr1') === 'Внешняя катушка'; } catch (e) { return false; } })());

// ── S15-S19: разметка ─────────────────────────────────────────────────────────────────────────
check('S15. окно объявлено один раз, связано с заголовком, backdrop закрывает через @click.self',
  (INDEX.match(/class="pw-win pf-win"/g) || []).length === 1
  && /role="dialog" aria-modal="true" aria-labelledby="pf-t"/.test(INDEX)
  && /class="pf-back"[^>]*@click\.self="closeFeedWindow\(\)"/.test(INDEX));
check('S16. confirm источника — отдельный слой со своим aria и @click.self',
  /class="pf-cf-back"[^>]*@click\.self="closeFeedConfirm\(\)"/.test(INDEX)
  && /aria-labelledby="pf-cf-t"/.test(INDEX));
check('S17. на каждую причину — отдельный checkbox, по умолчанию выключенный',
  /v-for="rc in feedConfirmReasons"/.test(INDEX)
  && /<input type="checkbox" class="pf-rz-c"[^>]*:checked="feedConfirm\.checks\[rc\]===true"/.test(INDEX)
  && /for \(const r of \(c\.required_approval_reasons \|\| \[\]\)\) ch\[r\] = false;/.test(FEED));
check('S18. кнопка подтверждения выключена, пока отмечены не все',
  /:disabled="!feedApproveReady"/.test(INDEX));
check('S19. постоянное предупреждение о границах подтверждения присутствует',
  /относится только к этому источнику, принтеру, слоту и версии файла/.test(INDEX));
check('S19b. успех НЕ обещает запуск печати',
  /Печать ещё не запускается/.test(APPJS) && !/Печать запущена/.test(FEED));

// ── S20-S24: CSS ──────────────────────────────────────────────────────────────────────────────
// Якорь ASCII: app.css читается как latin1 (битый UTF-8 хвост), по кириллице indexOf не найдёт.
// Комментарии снимаем: в них --fm-warn упоминается намеренно («такой переменной НЕТ»), и без этого
// проверка падала бы на собственном объяснении.
// Alpha 2.834: срез «блока фида» раньше шёл ДО КОНЦА app.css, поэтому любой новый блок, дописанный
// в конец файла, попадал в него и ломал проверки фида. Ограничиваем срез началом дизайн-системы
// настроек 2.834 (её первая строка объявляет --fm-warn) — сам блок фида проверяется как прежде.
const _feedFrom = APPCSS.indexOf('.pf-back {');
const _feedTo = APPCSS.indexOf(':root{ --fm-warn');
const CSS_FEED = APPCSS.slice(_feedFrom, _feedTo > _feedFrom ? _feedTo : APPCSS.length)
  .replace(/\/\*[\s\S]*?\*\//g, '');
check('S20. z-порядок 2.753: встроенный блок БЕЗ z-index; окно 9999 < confirm 100000 < алерты 100050',
  /\.pf-back \{[^}]*z-index: 9999/.test(APPCSS) && /\.pf-cf-back \{[^}]*z-index: 100000/.test(APPCSS)
  && !/\.pr-panel \{/.test(APPCSS) && !/\.wpx \{[^}]*z-index/.test(APPCSS)
  && /\.fm-alert-panel\{[^}]*z-index: ?100050/.test(APPCSS));
check('S21. окно не выходит за экран и прокручивается ВНУТРИ себя',
  /\.pf-win \{[^}]*max-height: calc\(100vh - 32px\)/.test(APPCSS)
  && /\.pf-body \{[^}]*overflow-y: auto[^}]*overscroll-behavior: contain/.test(APPCSS));
check('S22. горизонтальной прокрутки страницы нет: overflow-x hidden + min-width:0 у карточек',
  /\.pf-body \{[^}]*overflow-x: hidden/.test(APPCSS) && /\.pf-card \{[^}]*min-width: 0/.test(APPCSS));
check('S23. у образцов цвета есть рамка (белый/чёрный не сливаются с фоном) и невалидный помечен',
  /\.pf-sw \{[^}]*border: 1px solid/.test(APPCSS) && /\.pf-sw\.none \{/.test(APPCSS));
// Инвариант проекта (и проверки B23/P21/Q12) — самого СВОЙСТВА backdrop-filter у постоянных слоёв
// быть не должно. Значение по умолчанию и так none, поэтому объявлять его незачем; отсутствие
// эффекта доказывается замером в браузере (харнесс, L6: getComputedStyle().backdropFilter==='none').
check('S24. backdrop-filter не используется вовсе, есть focus-visible, цель нажатия >= 24px',
  !/backdrop-filter\s*:/.test(CSS_FEED)
  && /\.pf-win :focus-visible/.test(APPCSS) && /\.pf-rz-l \{[^}]*min-height: 24px/.test(APPCSS));
check('S24b. блок фида не зависит от --fm-warn (переменная появилась в 2.834 для настроек) — янтарный задан явно',
  CSS_FEED.length > 500 && !/var\(--fm-warn/.test(CSS_FEED) && !/--fm-warn\s*:/.test(CSS_FEED)
  && /#f5a524/.test(CSS_FEED));

// ── S25-S27: экспорт в шаблон и харнесс ───────────────────────────────────────────────────────
const NAMES = ['feedWin', 'feedConfirm', 'feedCandidates', 'feedSummary', 'feedItemActive', 'feedItemBusy',
  'feedItemNotice', 'feedItemError', 'feedBlockState', 'feedSlotLabel', 'feedSwatch', 'feedSwatchOk',
  'feedHexText', 'feedDeltaText', 'feedRelText', 'feedVerifyText', 'feedReasonText', 'feedPlanReasons',
  'openFeedWindow', 'closeFeedWindow', 'refreshFeedCandidates', 'feedCanSelect', 'feedCanApprove',
  'selectFeedCandidate', 'requestFeedApprove', 'requestFeedClear', 'closeFeedConfirm', 'toggleFeedReason',
  'confirmFeedApprove', 'confirmFeedClear', 'feedConfirmReasons', 'feedConfirmUnknown', 'feedApproveReady'];
const RET = APPJS.slice(APPJS.indexOf('projectRunConfirmTitle, projectRunConfirmText, projectRunConfirmOk,'));
check('S25. все template-facing функции экспортированы из setup',
  NAMES.every((n) => new RegExp('\\b' + n + '\\b').test(RET.slice(0, 2000))));
check('S26. КРИТИЧНО: ни одно template-facing имя не начинается с «_» (иначе шаблон его не увидит)',
  NAMES.every((n) => n[0] !== '_'));
check('S27. харнесс монтирует НАСТОЯЩУЮ разметку и НАСТОЯЩИЕ функции, а не копии',
  /realFetch\('\/web\/app\.js/.test(HARNESS) && /realFetch\('\/web\/index\.html/.test(HARNESS)
  && /cut\('<div v-if="feedWin\.open"'/.test(HARNESS)
  && /if \(!t \|\| t\.length < 200\) throw new Error/.test(HARNESS));
check('S28. харнесс валит сценарий на любом запрещённом запросе',
  /__BOOM\.push/.test(HARNESS) && /ЗАПРЕЩЁННЫЙ ВЫЗОВ/.test(HARNESS));

console.log('\n' + (fail
  ? 'FAIL: ' + fail + ' проверок провалено'
  : 'PASS: UI источника материала не умеет печатать (нет ни одного печатного endpoint, plate-clear не '
    + 'трогает), согласие требует ВСЕ причины и формируется только из перечня backend, approved_by не '
    + 'шлётся, цвет идёт в style только через safeHex, активный item — только просмотр, слоты '
    + '-1/0/5/512 подписаны честно; z-порядок и прокрутка внутри окна закреплены в CSS.\n'
    + 'ЖИВОЙ РЕНДЕР (U1-U32 + вёрстка): поднять статический сервер в корне репозитория и открыть\n'
    + '  tools/e2e_feed_plan_harness.html  — итог печатается в <pre id="out">.'));
process.exit(fail ? 1 : 0);
