// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Рендер-часть UI-фазы 5A3b «Источник материала». Монтирует НАСТОЯЩУЮ разметку из web/index.html и
// НАСТОЯЩИЕ функции из web/app.js (извлекаются по сбалансированным скобкам, код не переписан).
// Все fetch перехвачены фикстурами; /start, печать, отправка, планировщик и MQTT/FTP — bomb.
import { createApp, ref, reactive, computed, nextTick } from 'vue';

const log = [], checks = [];
const say = (m) => { log.push(m); document.getElementById('out').textContent = log.join('\n'); };
const check = (n, c) => { checks.push({ name: n, ok: !!c }); say((c ? 'PASS' : 'FAIL') + ' — ' + n); };
window.__CALLS = [];      // [method, url] всех перехваченных запросов
window.__BOOM = [];       // любой запрещённый запрос

const realFetch = window.fetch.bind(window);
const APPJS = await realFetch('/web/app.js?v=' + Date.now()).then(r => r.text());
const INDEX = await realFetch('/web/index.html?v=' + Date.now()).then(r => r.text());

// ── фикстуры: ровно та форма, что отдаёт backend 5A3a ──
const cand = (o) => Object.assign({
  printer_id: 'pr1', printer_name: 'X1C', transport: 'bambu', ams_slot: 0, mode: 'ams',
  spool_id: 'sp_0', inventory_bound: true, required_material: 'PETG', inventory_material: 'PETG',
  reported_material: 'PETG', required_color: '#161616', inventory_color: '#161616',
  reported_color: '#161616', color_distance: 0, color_relation: 'exact',
  verification: 'telemetry_confirmed', status: 'ready', effective_status: 'ready', reason: '',
  required_approval_reasons: [], fingerprint: 'fp_exact_1',
}, o);
const candResp = (list, extra) => Object.assign({
  status: 'ok', run_id: 'prun_1', item_id: 'it_1', file_id: 'F1', file_hash: 'h1', filament_count: 1,
  candidates: list, selected: list.find((c) => ['ready', 'approval_required'].includes(c.status)) || null,
  summary: {
    ready: list.filter((c) => c.status === 'ready').length,
    approval_required: list.filter((c) => c.status === 'approval_required').length,
    attention_required: list.filter((c) => c.status === 'attention_required').length,
    blocked: list.filter((c) => c.status === 'blocked').length,
  },
}, extra || {});
const feedPlan = (o) => Object.assign({
  version: 1, status: 'ready', effective_status: 'ready', reason: '', printer_id: 'pr1',
  transport: 'bambu', filament_count: 1, ams_slot: 0, mode: 'ams', spool_id: 'sp_0',
  inventory_bound: true, required_material: 'PETG', inventory_material: 'PETG', reported_material: 'PETG',
  required_color: '#161616', inventory_color: '#161616', reported_color: '#161616',
  color_distance: 0, color_relation: 'exact', verification: 'telemetry_confirmed',
  required_approval_reasons: [], approved_reasons: [], requires_approval: false, approval: null,
  approval_valid: false, fingerprint: 'fp_exact_1', file_hash: 'h1',
}, o);
// РОВНО форма реального item_public: поля и только они. updated_at (Alpha 2.749) — canonical
// версия строки item'а; раньше её тут не было, а readyItem() дорисовывал её «от себя», и харнесс
// переставал воспроизводить production. Форму держит tools/test_project_start_contract.py (N1/N1b).
const item = (o) => Object.assign({
  item_id: 'it_1', seq: 1, file_id: 'F1', state: 'pending', updated_at: 5, block_reason: '',
  planned_parts: {}, planned_overproduction: {}, assigned_printer_id: '', project_print_job_id: '',
  command_sent: false, attempt: 0, last_error: '', feed_plan: null,
}, o);
const run = (items) => ({
  run_id: 'prun_1', project_id: 'prj', project_name: 'Проект', state: 'running',
  allow_overproduction: false, plan_quality: 'exact', blocked: [], created_at: 1, updated_at: 1,
  boot_id: 'b', note: '', dispatch_enabled: false, items, counts: { pending: items.length },
  printers: [{ printer_id: 'pr1', name: 'X1C', status: 'IDLE', telemetry_fresh: true,
               has_send_reservation: false, available: true, unavailable_reasons: [], clearance: null,
               last_clearance: null }],
});

// Сценарий задаёт: что вернёт GET кандидатов и что вернут POST'ы.
const S = { cands: null, candStatus: 200, post: {}, run: null };
const J = (o, st) => new Response(JSON.stringify(o), { status: st || 200, headers: { 'Content-Type': 'application/json' } });

window.fetch = async (url, opt) => {
  const u = String(url), m = ((opt && opt.method) || 'GET').toUpperCase();
  window.__CALLS.push([m, u.split('?')[0], opt && opt.body ? JSON.parse(opt.body) : null]);
  // Ни один из этих запросов UI делать не должен НИКОГДА.
  // Alpha 2.748: /start ИСКЛЮЧЁН из запретов — это легитимный контрольный запуск 5B2a (фикстура
  // ниже). Всё остальное печатное/отправляющее по-прежнему валит сценарий.
  if (/\/print\b|print_path|upload_print|\/api\/part\/print|send-jobs|print-queue|\/cmd\b|scheduler|plate-clear/.test(u)) {
    window.__BOOM.push(m + ' ' + u);
    throw new Error('ЗАПРЕЩЁННЫЙ ВЫЗОВ: ' + u);
  }
  if (/\/start$/.test(u)) {
    const r = S.post.start;
    if (r === '__THROW__') throw new TypeError('Failed to fetch');   // потеря ответа/таймаут
    const v = r || { status: 'ok', accepted: true, result: 'accepted_awaiting_start_confirmation' };
    return J(v, v.http || 200);
  }
  if (/\/feed-candidates$/.test(u)) {
    if (S.candStatus !== 200) return J({ status: 'error', reason: S.candErr || 'boom' }, S.candStatus);
    if (S.candDelay) await new Promise((r) => setTimeout(r, S.candDelay));
    return J(S.cands);
  }
  const mp = u.match(/\/feed-plan\/(select|approve|clear)$/);
  if (mp) {
    const r = S.post[mp[1]] || { status: 'ok', feed_plan: feedPlan({}) };
    return J(r, r.http || 200);
  }
  if (/transport-status$/.test(u)) return J(S.arm || { status: 'ok', dispatch_enabled: false,
    transport_enabled: false, armed: false, consumed: false, expires_in_s: 0, scope: null, error: '' });
  if (/\/api\/project-runs\/prun_1$/.test(u)) return J(S.run || run([item({})]));
  if (/\/api\/project-runs\?active=1/.test(u)) return J({ status: 'ok', runs: [S.run || run([item({})])] });
  return J({});
};

// ── реальные функции из app.js ──
const extractBlock = (src, from, to) => src.slice(src.indexOf(from), src.indexOf(to));
const SRC = extractBlock(APPJS, 'const showProjectWholePreflight = ref(false);', 'const closeActiveModule =');
const SAFEHEX = (() => {   // safeHex объявлен ВЫШЕ блока — берём его дословно отдельно
  const s = APPJS.indexOf('const safeHex = (v) => {');
  let d = 0, i = APPJS.indexOf('{', s + 20);
  for (; i < APPJS.length; i++) { const ch = APPJS[i]; if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) break; } }
  return APPJS.slice(s, i + 1) + ';';
})();

// ── реальная разметка из index.html ──
const cut = (from, to) => {
  const a = INDEX.indexOf(from);
  const b = INDEX.indexOf(to, a) + to.length;
  return INDEX.slice(a, b).replace('<teleport to="body">', '').replace(/<\/teleport>$/, '');
};
// Alpha 2.753: глобальной панели больше нет — вырезаем ВСТРОЕННЫЙ блок .wpx из раскрытого проекта
// и монтируем его в host-цикле по проектам, ровно как в настоящем index.html (v-for pr in ...).
const WPX_TPL = (() => {
  const a = INDEX.indexOf('<div v-if="wpxOpenFor(pr.id)" class="wpx"');
  const b = INDEX.indexOf('<div class="p-2">', a);
  if (a < 0 || b < 0) throw new Error('встроенный блок .wpx не найден (якорь разошёлся)');
  return INDEX.slice(a, INDEX.lastIndexOf('</div>', b) + 6);
})();
const PANEL_TPL = '<template v-for="pr in wpxProjects" :key="pr.id">' + WPX_TPL + '</template>';
const FEED_TPL = cut('<div v-if="feedWin.open"', '</div>\n</teleport>');
const FEEDCF_TPL = cut('<div v-if="feedConfirm.open"', '</div>\n</teleport>');
const CSCF_TPL = cut('<div v-if="startConfirm.open"', '</div>\n</teleport>');   // 5B2a
const IACF_TPL = cut('<div v-if="inAppConfirm.open"', '</div>\n</teleport>');   // 2.757 in-app запуск
for (const [n, t] of [['WPX', WPX_TPL], ['FEED', FEED_TPL], ['FEEDCF', FEEDCF_TPL], ['CSCF', CSCF_TPL], ['IACF', IACF_TPL]])
  if (!t || t.length < 200) throw new Error('разметка ' + n + ' не вырезана (якорь не совпал): ' + t.length);

const App = {
  template: '<div>' + PANEL_TPL + FEED_TPL + FEEDCF_TPL + CSCF_TPL + IACF_TPL + '</div>',
  setup() {
    const lang = ref('ru');
    window.__esc = [];
    const registerEscapeLayer = (fn) => { window.__esc.push(fn); return 'tok' + window.__esc.length; };
    const unregisterEscapeLayer = () => { window.__esc.pop(); };
    const api = new Function('ref', 'reactive', 'computed', 'nextTick', 'registerEscapeLayer',
      'unregisterEscapeLayer', 'lang', 'safeHex', 'project2Expanded',
      SRC + '\n return { projectRunsById, projectRunOrder, projectRunsList, projectRunsActiveCount, '
      + 'projectRunsInitialLoading, projectRunsListError, '
      + 'projectRunActions, projectRunErrors, projectRunConfirm, highlightedRunId, projectRunName, '
      + 'projectRunCounts, projectRunCanPause, projectRunCanResume, projectRunCanCancel, projectRunBusy, '
      + 'refreshProjectRuns, pauseProjectRun, resumeProjectRun, '
      + 'requestCancelProjectRun, closeCancelProjectRunConfirm, confirmCancelProjectRun, '
      // Alpha 2.753: встроенный блок .wpx + preflight внутри него
      + 'wpxOpenMap, wpxTechOpen, wpxRunFor, wpxOpenFor, toggleWholePrint, wpxPreflightFor, wpxStatus, '
      + 'wpxSummary, wpxProgressPct, wpxItemState, wpxItemKind, wpxMaterialLine, wpxMaterialWarn, '
      + 'wpxItemClearance, wpxPrinterName, wpxPartsLine, wpxMainCta, wpxDoMain, wpxToggleTech, '
      + 'wpxCurrentItem, wpxCurrentIndex, wpxQueueItems, wpxPartsText, wpxFileLabel, wpxSeriesPrinter, '
      + 'wpxSeriesMaterial, wpxClrState, wpxHint, wpxQueueOpen, wpxToggleQueue, wpxMatMenu, wpxToggleMatMenu, ' 
      + 'printEnabled, printEnableBusy, setPrintEnabled, canStartInApp, inAppConfirm, requestInAppStart, '
      + 'closeInAppStartConfirm, confirmInAppStart, inAppStartFacts, '
      + 'showProjectWholePreflight, projectWholeProject, projectWholePreflight, projectWholeLoading, '
      + 'projectWholeError, projectWholeSaveError, projectWholeSaving, projectWholeAllowOverproduction, '
      + 'projectWholeNotice, projectWholePlan, projectWholeParts, projectWholeCompleted, '
      + 'projectWholeNeedsApproval, projectWholeOverRows, projectWholePartName, projectWholeCanSave, '
      + 'openProjectWholePreflight, closeProjectWholePreflight, refreshProjectWholePreflight, saveProjectWholeDraft, '
      + 'loadActiveProjectRuns, stopProjectRunsPolling, pollProjectRunsOnce, syncProjectRunsPolling, '
      + 'projectRunClearanceTargets, projectRunPlateClearIds, printerAwaitsPlateClear, focusPlateClearRun, '
      + 'clearanceCanConfirm, clearanceCanRevoke, clearanceBlockReason, clearanceStateText, '
      + 'projectRunAmbiguousItems, requestPlateClear, revokePlateClear, requestResolveItem, '
      + 'projectRunConfirmTitle, projectRunConfirmText, projectRunConfirmOk, '
      + 'feedWin, feedConfirm, feedCandidates, feedSummary, feedKey, feedItemActive, feedItemBusy, '
      + 'feedItemNotice, feedItemError, feedBlockState, feedSlotLabel, feedSwatch, feedSwatchOk, '
      + 'feedHexText, feedDeltaText, feedRelText, feedVerifyText, feedReasonText, feedPlanReasons, '
      + 'openFeedWindow, closeFeedWindow, refreshFeedCandidates, feedCanSelect, feedCanApprove, '
      + 'selectFeedCandidate, requestFeedApprove, requestFeedClear, closeFeedConfirm, toggleFeedReason, '
      + 'confirmFeedApprove, confirmFeedClear, feedConfirmReasons, feedConfirmUnknown, feedApproveReady, '
      + 'feedNotice, feedErrors, feedBusy, '
      // 5B2a: без этих имён шаблон панели падает (canControlledStart не определён).
      + 'armStatus, armScope, armReady, startConfirm, START_CHECKS, startCheckText, startKey, '
      + 'startItemBusy, startItemNotice, startItemUnknown, canControlledStart, startApproveReady, '
      + 'toggleStartCheck, requestControlledStart, closeStartConfirm, confirmControlledStart, loadArmStatus, '
      // 5B2a/2.749: без startVersionBlocked шаблон панели падает на рендере и панель пустеет
      + 'startVersions, startVersionBlocked, '
      // сырые ref'ы — только чтобы reset() гасил состояние прошлого сценария; шаблону они не нужны
      + 'startBusy, startNotice, startUnknown, '
      + '_pollTimer: () => projectRunsPollTimer };'
    )(ref, reactive, computed, nextTick, registerEscapeLayer, unregisterEscapeLayer, lang,
      new Function(SAFEHEX + ' return safeHex;')(), ref(''));
    window.__api = api;
    // host-проекты для v-for блока: ровно один проект, как в реальном разделе «Проекты»
    const wpxProjects = ref([{ id: 'prj', name: 'Проект' }]);
    window.__setWpxProjects = (list) => { wpxProjects.value = list; };
    return Object.assign({ lang, wpxProjects }, api);
  },
};
const app = createApp(App);
app.config.errorHandler = (e, i, info) => { say('VUE ERROR: ' + (e && e.message) + ' | ' + info); window.__E2E_ERR = String((e && e.stack) || e); };
app.mount('#app');

const A = window.__api;
const tick = async (n) => { for (let i = 0; i < (n || 3); i++) { await nextTick(); await new Promise((r) => setTimeout(r, 0)); } };
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
// Текст ТОЛЬКО смонтированного UI. document.body сюда не годится: в body лежит и <pre id="out"> с
// протоколом прогона, а имена проверок содержат те самые фразы, которые проверки же и запрещают.
// Все teleport'ы вырезаны в cut(), поэтому вся разметка — внутри #app.
const txt = () => (document.getElementById('app') || {}).innerText || '';
const btnByText = (re) => $$('button').find((b) => re.test(b.textContent || ''));
const posts = (kind) => window.__CALLS.filter((c) => c[0] === 'POST' && c[1].endsWith('/feed-plan/' + kind));
const gets = () => window.__CALLS.filter((c) => c[0] === 'GET' && c[1].endsWith('/feed-candidates'));
const reset = async (r, cands) => {
  window.__CALLS = [];
  A.stopProjectRunsPolling();
  S.run = r; S.cands = cands || candResp([cand({})]); S.candStatus = 200; S.candDelay = 0; S.post = {};
  A.projectRunsById.value = { prun_1: r }; A.projectRunOrder.value = ['prun_1'];
  // Встроенный блок открыт автоматически: у проекта 'prj' есть run (wpxOpenFor default).
  A.wpxOpenMap.value = {};
  if (A.feedWin.open) A.closeFeedWindow();
  if (A.feedConfirm.open) A.closeFeedConfirm();
  A.feedWin.data = null; A.feedWin.error = '';
  // Сообщения/ошибки прошлого сценария обязаны исчезнуть, иначе следующая проверка «успех НЕ
  // показан» пройдёт по чужому тексту и ничего не докажет.
  A.feedNotice.value = {}; A.feedErrors.value = {}; A.feedBusy.value = {};
  // То же и для 5B2a. Отдельно важно startBusy: сценарий «ответ потерян» НАМЕРЕННО не снимает
  // блокировку никогда (повтор запрещён), и без сброса она утекала бы в следующий сценарий —
  // кнопка там осталась бы disabled, а проверка «клик ничего не отправил» прошла бы впустую.
  A.startBusy.value = {}; A.startNotice.value = {}; A.startUnknown.value = {};
  if (A.startConfirm.open) A.closeStartConfirm();
  window.__CALLS = [];
  await tick();
};

// ══ U1-U4: открытие окна ══════════════════════════════════════════════════════════════════════
await reset(run([item({})]));
check('U1. item без плана -> строка «Материал: не выбран» + кнопка «Выбрать материал» (2.754)',
  /Материал: не выбран/.test(txt()) && !!btnByText(/^\s*Выбрать материал\s*$/));
btnByText(/^\s*Выбрать материал\s*$/).click();
await tick(6);
check('U2. один клик -> ровно один GET кандидатов и одно окно',
  gets().length === 1 && $$('.pf-win').length === 1);
check('U2b. окно показывает предупреждение, что печать не запускается',
  /НЕ запускает печать/.test(txt()));
A.closeFeedWindow(); await tick();
window.__CALLS = [];
S.candDelay = 40;
const p1 = A.openFeedWindow(S.run, S.run.items[0], { currentTarget: null });
const p2 = A.openFeedWindow(S.run, S.run.items[0], { currentTarget: null });
await Promise.all([p1, p2]); await tick(6);
check('U3. двойной клик во время загрузки -> предыдущий GET отменён, окно одно, ошибки нет',
  $$('.pf-win').length === 1 && !A.feedWin.error && !!A.feedWin.data);
S.candDelay = 0;
window.__CALLS = [];
A.openFeedWindow(S.run, S.run.items[0], { currentTarget: null });
A.closeFeedWindow();
await tick(6);
check('U4. закрытие во время загрузки -> окно закрыто, AbortError пользователю не показан',
  !A.feedWin.open && !A.feedWin.error && !window.__E2E_ERR);

// ══ U5-U9: слоты и порядок ════════════════════════════════════════════════════════════════════
const SLOTS = [[-1, 'Внешняя катушка', 'external'], [0, 'AMS 1·1', 'ams'], [5, 'AMS 2·2', 'ams'],
               [512, 'AMS HT·1', 'ams']];
for (const [slot, label, mode] of SLOTS) {
  await reset(run([item({})]), candResp([cand({ ams_slot: slot, mode, spool_id: 'sp' + slot })]));
  await A.openFeedWindow(S.run, S.run.items[0], {});
  await tick(4);
  check('U5-U8. слот ' + slot + ' подписан как «' + label + '»', txt().includes(label));
}
check('U8b. 512 НЕ превращается в «Слот 513»', !/Слот 513|слот 513/i.test(txt()));
await reset(run([item({})]), candResp([
  cand({ printer_id: 'pr1', printer_name: 'A', ams_slot: 0, spool_id: 'sp_a', fingerprint: 'f1' }),
  cand({ printer_id: 'pr2', printer_name: 'B', ams_slot: 5, spool_id: 'sp_b', fingerprint: 'f2',
         status: 'approval_required', effective_status: 'approval_required', color_relation: 'close',
         color_distance: 3.1, reason: 'close_color', required_approval_reasons: ['close_color'] }),
  cand({ printer_id: 'pr3', printer_name: 'C', ams_slot: 3, spool_id: 'sp_c', fingerprint: 'f3',
         status: 'blocked', effective_status: 'blocked', reason: 'material_mismatch', inventory_material: 'PLA' }),
]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
check('U9. порядок кандидатов — КАК ПРИШЁЛ от backend (фронт не сортирует)',
  $$('.pf-card .pw-name').map((e) => e.textContent.trim()).join(',') === 'A,B,C');

// ══ U10-U12: exact select ═════════════════════════════════════════════════════════════════════
await reset(run([item({})]), candResp([cand({ fingerprint: 'fp_sel_1' })]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
const selBtn = btnByText(/Выбрать этот источник/);
check('U10a. у ready-кандидата есть кнопка «Выбрать этот источник»', !!selBtn);
selBtn.click(); selBtn.click();                     // двойной клик
await tick(8);
check('U11. двойной клик -> РОВНО один POST select', posts('select').length === 1);
check('U10b. тело POST — только printer/slot/spool/fingerprint (ничего лишнего)',
  JSON.stringify(Object.keys(posts('select')[0][2]).sort())
  === JSON.stringify(['ams_slot', 'expected_fingerprint', 'printer_id', 'spool_id']));
check('U10c. значения тела точные',
  posts('select')[0][2].printer_id === 'pr1' && posts('select')[0][2].ams_slot === 0
  && posts('select')[0][2].spool_id === 'sp_0' && posts('select')[0][2].expected_fingerprint === 'fp_sel_1');
check('U10d. материал/цвет/статус в теле НЕ отправляются',
  !('required_material' in posts('select')[0][2]) && !('inventory_color' in posts('select')[0][2])
  && !('status' in posts('select')[0][2]));
check('U12a. окно закрылось после успеха', !A.feedWin.open);
check('U12b. сообщение НЕ утверждает, что печать запущена',
  /Печать ещё не запускается/.test(A.feedItemNotice('prun_1', 'it_1'))
  && !/Печать запущена|запущена печать/i.test(txt()));

// ══ U13-U19: подтверждение ════════════════════════════════════════════════════════════════════
const CLOSE_C = cand({ status: 'approval_required', effective_status: 'approval_required',
  color_relation: 'close', color_distance: 3.14, inventory_color: '#191919', reported_color: '#191919',
  reason: 'close_color', required_approval_reasons: ['close_color'], fingerprint: 'fp_close' });
const DECL_C = cand({ transport: 'klipper', ams_slot: -1, mode: 'external', spool_id: 'sp_k',
  status: 'approval_required', effective_status: 'approval_required', verification: 'inventory_declared',
  reported_material: null, reported_color: null, reason: 'inventory_declared',
  required_approval_reasons: ['inventory_declared'], fingerprint: 'fp_decl' });
const BOTH_C = cand({ transport: 'klipper', status: 'approval_required', effective_status: 'approval_required',
  color_relation: 'close', color_distance: 4.2, inventory_color: '#191919', reported_color: null,
  reported_material: null, verification: 'inventory_declared', reason: 'close_color',
  required_approval_reasons: ['close_color', 'inventory_declared'], fingerprint: 'fp_both' });

await reset(run([item({})]), candResp([CLOSE_C]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click();
await tick(4);
check('U13a. close_color -> confirm открыт, РОВНО один checkbox', $$('.pf-rz-c').length === 1);
check('U13b. checkbox по умолчанию выключен и кнопка подтверждения disabled',
  $('.pf-rz-c').checked === false && btnByText(/Подтверждаю/).disabled === true);
check('U13c. показан текст причины и ΔE', /Цвет близкий, но не совпадает точно/.test(txt()) && /ΔE 3\.14/.test(txt()));
check('U13d. показано постоянное предупреждение о границах подтверждения',
  /относится только к этому источнику, принтеру, слоту и версии файла/.test(txt()));
// Комментарии снимаем ОБЯЗАТЕЛЬНО: иначе проверка ловит собственную фразу «native confirm() не
// используется» и падает на пустом месте. Свои confirmFeed* — не native, их тоже исключаем.
const SRC_CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
check('U13e. native confirm() не используется — только свой styled confirm',
  !/window\.confirm|[^.\w]confirm\(/.test(SRC_CODE.replace(/confirmFeed\w+/g, 'X')));
A.toggleFeedReason('close_color'); await tick();
check('U13f. после включения галочки кнопка активна', btnByText(/Подтверждаю/).disabled === false);
A.closeFeedConfirm(); await tick();

await reset(run([item({})]), candResp([DECL_C]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click();
await tick(4);
check('U14. inventory_declared -> один checkbox со своим текстом',
  $$('.pf-rz-c').length === 1 && /не подтверждены датчиком принтера/.test(txt()));

await reset(run([item({})]), candResp([BOTH_C]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click();
await tick(4);
check('U15. КРИТИЧНО: close+declared -> ДВА независимых checkbox',
  $$('.pf-rz-c').length === 2 && /Цвет близкий/.test(txt()) && /не подтверждены датчиком/.test(txt()));
A.toggleFeedReason('close_color'); await tick();
check('U16a. отмечена одна из двух -> кнопка всё ещё disabled', btnByText(/Подтверждаю/).disabled === true);
btnByText(/Подтверждаю/).click(); await tick(4);
check('U16b. КРИТИЧНО: без второй галочки НИ ОДНОГО POST approve', posts('approve').length === 0);
A.toggleFeedReason('inventory_declared'); await tick();
check('U17a. обе отмечены -> кнопка активна', btnByText(/Подтверждаю/).disabled === false);
btnByText(/Подтверждаю/).click(); await tick(8);
check('U17b. один POST approve с ОБЕИМИ причинами', posts('approve').length === 1
  && JSON.stringify(posts('approve')[0][2].approved_reasons) === JSON.stringify(['close_color', 'inventory_declared']));
check('U17c. confirmed:true и точный fingerprint',
  posts('approve')[0][2].confirmed === true && posts('approve')[0][2].expected_fingerprint === 'fp_both');
check('U18. КРИТИЧНО: approved_by в теле НЕ отправляется', !('approved_by' in posts('approve')[0][2]));
check('U18b. сообщение об успехе не говорит про запуск печати',
  /Печать ещё не запускается/.test(A.feedItemNotice('prun_1', 'it_1')));

await reset(run([item({})]), candResp([BOTH_C]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click();
await tick(4);
A.toggleFeedReason('close_color'); A.toggleFeedReason('inventory_declared'); await tick();
window.__esc[window.__esc.length - 1]();            // Escape закрывает ВЕРХНИЙ слой (confirm)
await tick(4);
check('U19a. Escape закрыл confirm -> НИ ОДНОГО POST', posts('approve').length === 0 && !A.feedConfirm.open);
check('U19b. окно кандидатов при этом осталось открытым', A.feedWin.open === true);

// ══ U20-U23: ошибки ═══════════════════════════════════════════════════════════════════════════
await reset(run([item({})]), candResp([cand({ fingerprint: 'fp_old' })]));
S.post.select = { status: 'error', reason: 'feed_plan_stale', http: 409, fingerprint: 'fp_new' };
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Выбрать этот источник/).click();
await tick(8);
check('U20a. stale -> окно НЕ закрыто, показано понятное сообщение',
  A.feedWin.open === true && /Обновите кандидатов/.test(A.feedWin.error));
check('U20b. есть кнопка обновления', !!$('.pf-win .pr-ico'));
S.cands = candResp([cand({ fingerprint: 'fp_new' })]);
S.post.select = { status: 'ok', feed_plan: feedPlan({}) };
window.__CALLS = [];
await A.refreshFeedCandidates(); await tick(4);
btnByText(/Выбрать этот источник/).click(); await tick(8);
check('U20c. КРИТИЧНО: после refresh используется НОВЫЙ fingerprint, старый не переиспользован',
  posts('select')[0][2].expected_fingerprint === 'fp_new');

await reset(run([item({})]), candResp([BOTH_C]));
S.post.approve = { status: 'error', reason: 'approval_incomplete', http: 409,
                   required_approval_reasons: ['close_color', 'inventory_declared'] };
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click(); await tick(4);
A.toggleFeedReason('close_color'); A.toggleFeedReason('inventory_declared'); await tick();
btnByText(/Подтверждаю/).click(); await tick(8);
check('U21. approval_incomplete -> окно остаётся, успех НЕ показан',
  A.feedWin.open === true && /Подтверждены не все причины/.test(A.feedWin.error)
  && !A.feedItemNotice('prun_1', 'it_1'));

await reset(run([item({})]), candResp([cand({ status: 'blocked', effective_status: 'blocked',
  reason: 'material_mismatch', inventory_material: 'PLA', required_approval_reasons: [] })]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
check('U22. blocked: ни «Выбрать», ни «Подтвердить» — только объяснение',
  !btnByText(/Выбрать этот источник/) && !btnByText(/Подтвердить этот источник/)
  && /Материал катушки не совпадает/.test(txt()) && /Этот вариант выбрать нельзя/.test(txt()));

await reset(run([item({})]), candResp([cand({ status: 'approval_required', effective_status: 'approval_required',
  reason: 'потому_что_так', required_approval_reasons: ['потому_что_так'], fingerprint: 'fp_unk' })]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
btnByText(/Подтвердить этот источник/).click(); await tick(4);
check('U23a. неизвестная причина: checkbox заблокирован, подтвердить нельзя',
  $('.pf-rz-c').disabled === true && btnByText(/Подтверждаю/).disabled === true
  && /неизвестная этой версии интерфейса/.test(txt()));
btnByText(/Подтверждаю/).click(); await tick(4);
check('U23b. и POST не уходит', posts('approve').length === 0);
A.closeFeedConfirm(); await tick();

// ══ U24-U25: повреждённый план и активный item ════════════════════════════════════════════════
await reset(run([item({ feed_plan: { version: 1, status: 'attention_required', reason: 'feed_plan_corrupt',
                                     effective_status: 'attention_required', item_id: 'it_1' } })]));
check('U24. повреждённый план: честный текст + кнопка повторного подбора, UI жив',
  /запись повреждена — выберите заново/.test(txt()) && !!btnByText(/^\s*Выбрать материал\s*$/) && !window.__E2E_ERR);

for (const st of ['sending', 'printing', 'waiting_plate_clear', 'leased', 'waiting_start_confirmation']) {
  await reset(run([item({ state: st, feed_plan: feedPlan({}), assigned_printer_id: 'pr1' })]));
  const ro = !btnByText(/Выбрать этот источник/) && !btnByText(/Сбросить выбор/)
    && !btnByText(/^\s*(Выбрать материал|Изменить|Подтвердить материал|Настроить)\s*$/);
  check('U25.' + st + ' активный item -> только просмотр, действий с материалом нет',
    ro && !!txt());
}

// ══ U26-U28: сброс выбора (2.754: «Изменить»/«Сбросить выбор» — во вторичном меню настроек) ═══
await reset(run([item({ feed_plan: feedPlan({}) })]));
check('U26pre. «Сбросить выбор» НЕ на первом уровне: спрятан за «Настройки материала»',
  !btnByText(/Сбросить выбор/) && !!btnByText(/Настройки материала/));
btnByText(/Настройки материала/).click(); await tick(2);
check('U26a. в раскрытом меню настроек есть «Сбросить выбор»', !!btnByText(/Сбросить выбор/));
btnByText(/Сбросить выбор/).click(); await tick(4);
check('U26b. сначала styled confirm (не native), с честным текстом',
  A.feedConfirm.open === true && /не отменяет план проекта и не запускает печать/.test(txt()));
A.closeFeedConfirm(); await tick(4);
check('U26c. отказ -> НИ ОДНОГО POST clear', posts('clear').length === 0);
btnByText(/Сбросить выбор/).click(); await tick(4);
btnByText(/^\s*Сбросить\s*$/).click(); await tick(8);
check('U27. подтверждение -> РОВНО один POST clear с confirmed:true',
  posts('clear').length === 1 && posts('clear')[0][2].confirmed === true);
check('U28. КРИТИЧНО: сброс выбора НЕ трогает подтверждение очистки стола (нет plate-clear/revoke)',
  !window.__CALLS.some((c) => /plate-clear/.test(c[1])) && window.__BOOM.length === 0);
check('U28b. текст сброса и текст отзыва «Стол очищен» не смешаны',
  !/Отозвать подтверждение очистки стола/.test(txt()));

// ══ U29: безопасность цвета ═══════════════════════════════════════════════════════════════════
await reset(run([item({})]), candResp([cand({
  required_color: 'red;background:url(javascript:alert(1))', inventory_color: '#00A0E3',
  reported_color: 'нет', fingerprint: 'fp_x' })]));
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
const sw = $$('.pf-win .pf-sw');
check('U29a. КРИТИЧНО: невалидный цвет в style не попадает (CSS-инъекция отбита)',
  sw.length >= 3 && !/javascript|url\(/i.test($('.pf-win').innerHTML)
  && sw[0].getAttribute('style') === null || !/javascript/i.test(sw[0].getAttribute('style') || ''));
check('U29b. валидный цвет применён как background', /rgb\(0, 160, 227\)|#00A0E3/i.test(sw[1].style.background));
check('U29c. невалидные помечены классом none и подписаны честно',
  sw[0].classList.contains('none') && sw[2].classList.contains('none') && /не задан/.test(txt()));

// ══ U30-U32: polling и запреты ════════════════════════════════════════════════════════════════
await reset(run([item({})]), candResp([cand({ fingerprint: 'fp_p' })]));
A.stopProjectRunsPolling();
const t0 = A._pollTimer();
await A.openFeedWindow(S.run, S.run.items[0], {});
await tick(4);
window.__CALLS = [];
btnByText(/Выбрать этот источник/).click(); await tick(8);
check('U30a. после действия snapshot обновлён ОДНИМ GET деталей run',
  window.__CALLS.filter((c) => c[0] === 'GET' && c[1] === '/api/project-runs/prun_1').length === 1);
check('U30b. второй polling-таймер НЕ создан', A._pollTimer() === t0 || A._pollTimer() === null);

window.__CALLS = [];
await A.pollProjectRunsOnce();
await tick(4);
check('U31. периодический опрос НЕ делает feed-POST и не открывает confirm',
  posts('select').length === 0 && posts('approve').length === 0 && posts('clear').length === 0
  && gets().length === 0 && A.feedConfirm.open === false);
A.stopProjectRunsPolling();

check('U32. КРИТИЧНО: за весь сценарий 0 запрещённых вызовов (start/print/send/queue/scheduler/plate-clear)',
  window.__BOOM.length === 0);
check('U32b. и ни одной ошибки Vue за весь прогон', !window.__E2E_ERR);


// ══ 5B2a: КОНТРОЛЬНЫЙ ЗАПУСК одной печати ═════════════════════════════════════════════════════
const armed = (o) => Object.assign({ status: 'ok', dispatch_enabled: true, transport_enabled: true,
  armed: true, consumed: false, expires_in_s: 600,
  scope: { run_id: 'prun_1', item_id: 'it_1', printer_id: 'pr1' }, error: '' }, o || {});
const startPosts = () => window.__CALLS.filter((c) => c[0] === 'POST' && /\/start$/.test(c[1]));
const readyItem = () => item({ feed_plan: feedPlan({ fingerprint: 'fp_go' }), updated_at: 7 });

// B1: обычный режим — кнопки нет, POST невозможен
await reset(run([readyItem()]));
S.arm = null; await A.loadArmStatus(); await tick(4);
check('B1a. unarmed: кнопки запуска НЕТ, видна спокойная плашка проверочного режима (2.753: одна на блок)',
  !btnByText(/Контрольный запуск/) && /Проверочный режим: доступен только один контролируемый запуск/.test(txt()));
check('B1b. КРИТИЧНО: слова «Автозапуск» в блоке нет (это один ручной запуск)', !/Автозапуск/.test(txt()));
A.requestControlledStart(A.projectRunsList.value[0], S.run.items[0], {});
await tick(4);
check('B1c. КРИТИЧНО: программный вызов запуска в unarmed НЕ открывает confirm и не шлёт POST',
  A.startConfirm.open === false && startPosts().length === 0);

// B2: вооружён — кнопка ровно у своей цели
await reset(run([readyItem(), item({ item_id: 'it_2', seq: 2, feed_plan: feedPlan({}), updated_at: 7 })]));
S.arm = armed(); await A.loadArmStatus(); await tick(4);
const r0 = A.projectRunsList.value[0];
check('B2a. armed + точное совпадение -> кнопка в КАРТОЧКЕ ровно у одного item (+ главная CTA сверху)',
  A.canControlledStart(r0, S.run.items[0]) === true && A.canControlledStart(r0, S.run.items[1]) === false
  && $$('.wpx-it .pw-btn.danger').length === 1
  && $$('button').filter((b) => /Контрольный запуск/.test(b.textContent)).length <= 2);
for (const [lbl, sc] of [['другой run', { run_id: 'prun_9' }], ['другой item', { item_id: 'it_9' }],
                         ['другой printer', { printer_id: 'pr9' }]]) {
  S.arm = armed({ scope: Object.assign({ run_id: 'prun_1', item_id: 'it_1', printer_id: 'pr1' }, sc) });
  await A.loadArmStatus(); await tick(3);
  check('B2b.' + lbl + ' -> кнопки НЕТ', A.canControlledStart(r0, S.run.items[0]) === false);
}
S.arm = armed({ consumed: true, armed: false }); await A.loadArmStatus(); await tick(3);
check('B2c. КРИТИЧНО: израсходованное вооружение убирает кнопку', A.canControlledStart(r0, S.run.items[0]) === false);
S.arm = armed({ armed: false, expires_in_s: 0 }); await A.loadArmStatus(); await tick(3);
check('B2d. истёкшее вооружение убирает кнопку', A.canControlledStart(r0, S.run.items[0]) === false);

// B3: четыре галочки обязательны
await reset(run([readyItem()]));
S.arm = armed(); await A.loadArmStatus(); await tick(4);
btnByText(/Контрольный запуск/).click(); await tick(4);
check('B3a. confirm открыт, РОВНО четыре галочки, все выключены',
  A.startConfirm.open === true && $$('.cs-chk').length === 4
  && $$('.cs-chk').every((e) => e.checked === false));
check('B3b. показаны факты: принтер, подача, катушка, материал и предупреждение о реальной команде',
  /pr1/.test(txt()) && /AMS 1·1/.test(txt()) && /sp_0/.test(txt()) && /PETG/.test(txt())
  && /НАСТОЯЩАЯ команда печати/.test(txt()) && /автоматически НЕ запустится/.test(txt()));
check('B3c. кнопка отправки disabled, пока отмечены не все', $('.cs-go').disabled === true);
for (let i = 0; i < 3; i++) { A.toggleStartCheck(A.START_CHECKS[i]); await tick(1); }
check('B3d. КРИТИЧНО: три из четырёх — всё ещё disabled', $('.cs-go').disabled === true);
$('.cs-go').click(); await tick(3);
check('B3e. КРИТИЧНО: без четвёртой галочки НИ ОДНОГО POST', startPosts().length === 0);
A.toggleStartCheck(A.START_CHECKS[3]); await tick(1);
check('B3f. все четыре -> кнопка активна', $('.cs-go').disabled === false);

// B4: Escape
window.__esc[window.__esc.length - 1]();
await tick(3);
check('B4. Escape закрыл confirm -> 0 POST', A.startConfirm.open === false && startPosts().length === 0);

// B5: двойной клик -> один POST, тело точное
await reset(run([readyItem()]));
S.arm = armed(); S.post.start = { status: 'ok', accepted: true, result: 'accepted_awaiting_start_confirmation' };
await A.loadArmStatus(); await tick(4);
btnByText(/Контрольный запуск/).click(); await tick(3);
for (const k of A.START_CHECKS) A.toggleStartCheck(k);
await tick(1);
$('.cs-go').click(); $('.cs-go') && $('.cs-go').click();
await tick(10);
check('B5a. КРИТИЧНО: двойной клик -> РОВНО один POST /start', startPosts().length === 1);
check('B5b. КРИТИЧНО: тело только canonical optimistic-lock — без printer/slot/spool/флагов',
  JSON.stringify(Object.keys(startPosts()[0][2]).sort())
  === JSON.stringify(['confirmed', 'expected_feed_fingerprint', 'expected_item_updated_at',
                      'expected_run_updated_at', 'item_id']));
check('B5c. значения точные', startPosts()[0][2].confirmed === true && startPosts()[0][2].item_id === 'it_1'
  && startPosts()[0][2].expected_feed_fingerprint === 'fp_go' && startPosts()[0][2].expected_run_updated_at === 1);
check('B5d. КРИТИЧНО: accepted НЕ показывается как «печать началась»',
  /Ожидается подтверждение старта/.test(A.startItemNotice('prun_1', 'it_1'))
  && !/Печать запущена|печать началась/i.test(txt()));

// B6: потеря ответа -> запрет повтора
await reset(run([readyItem()]));
S.arm = armed(); await A.loadArmStatus(); await tick(4);
S.post.start = '__THROW__';
btnByText(/Контрольный запуск/).click(); await tick(3);
for (const k of A.START_CHECKS) A.toggleStartCheck(k);
await tick(1);
$('.cs-go').click(); await tick(10);
check('B6a. КРИТИЧНО: ответ потерян -> честный текст и НИКАКОГО автоповтора',
  startPosts().length === 1 && A.startItemUnknown('prun_1', 'it_1') === true
  && /Не повторяйте запуск/.test(A.startItemNotice('prun_1', 'it_1')));
check('B6b. КРИТИЧНО: блокировка НЕ снята — повторный запуск невозможен',
  A.startItemBusy('prun_1', 'it_1') === true);
S.post.start = { status: 'ok', accepted: true };
await A.confirmControlledStart();
await tick(4);
check('B6c. и повторная попытка POST не делает', startPosts().length === 1);
S.post = {};

// B7: опрос не печатает
await reset(run([readyItem()]));
S.arm = armed(); await A.loadArmStatus(); await tick(4);
window.__CALLS = [];
await A.pollProjectRunsOnce(); await tick(4);
check('B7. КРИТИЧНО: периодический опрос делает только GET, /start не зовёт',
  startPosts().length === 0 && window.__CALLS.every((c) => c[0] === 'GET'));
check('B7b. статус вооружения опрашивается тем же тиком (отдельного таймера нет)',
  window.__CALLS.some((c) => /transport-status$/.test(c[1])));
S.arm = null; await A.loadArmStatus(); await tick(2);

// B8: FAIL-CLOSED по версии снимка (Alpha 2.749). Ровно та дыра, из-за которой запрещали железо:
// item.updated_at не приходил, UI слал undefined, ключ выпадал из JSON, сервер молча пропускал
// проверку устаревшего экрана. Теперь пропажа ЛЮБОГО из трёх значений обязана убивать кнопку.
const NO_VER = [
  ['нет item.updated_at', (r) => { delete r.items[0].updated_at; }],
  ['item.updated_at = null', (r) => { r.items[0].updated_at = null; }],
  ['item.updated_at — строка', (r) => { r.items[0].updated_at = '7'; }],
  ['item.updated_at = NaN', (r) => { r.items[0].updated_at = NaN; }],
  ['нет run.updated_at', (r) => { delete r.updated_at; }],
  ['нет feed_plan.fingerprint', (r) => { delete r.items[0].feed_plan.fingerprint; }],
  ['пустой feed_plan.fingerprint', (r) => { r.items[0].feed_plan.fingerprint = ''; }],
];
for (const [lbl, brk] of NO_VER) {
  const rr = run([readyItem()]);
  brk(rr);
  await reset(rr);
  S.arm = armed(); await A.loadArmStatus(); await tick(4);
  const r0 = A.projectRunsList.value[0];
  check('B8. КРИТИЧНО: ' + lbl + ' -> кнопки НЕТ и запуск невозможен',
    A.canControlledStart(r0, r0.items[0]) === false && A.startVersions(r0, r0.items[0]) === null
    && !btnByText(/Контрольный запуск/));
  check('B8. ' + lbl + ' -> показана постоянная понятная ошибка вместо кнопки',
    A.startVersionBlocked(r0, r0.items[0]) === true
    && /Не удалось получить версию плана\. Обновите данные; запуск заблокирован\./.test(txt()));
  // Даже принудительный вызов отправки не должен слать POST: гейт не только в разметке.
  A.startConfirm.run = r0; A.startConfirm.item = r0.items[0];
  for (const k of A.START_CHECKS) A.toggleStartCheck(k);
  await A.confirmControlledStart(); await tick(4);
  check('B8. КРИТИЧНО: ' + lbl + ' -> НИ ОДНОГО POST даже при прямом вызове отправки',
    startPosts().length === 0);
  A.startConfirm.run = null; A.startConfirm.item = null;
}
// Контроль не-вакуумности: тот же путь с полным снимком обязан ДАВАТЬ кнопку и ровно один POST.
await reset(run([readyItem()]));
S.arm = armed(); S.post.start = { status: 'ok', accepted: true };
await A.loadArmStatus(); await tick(4);
{
  const r0 = A.projectRunsList.value[0];
  check('B8z. КРИТИЧНО: полный снимок -> кнопка есть, версии читаются (проверки B8 не вакуумны)',
    A.canControlledStart(r0, r0.items[0]) === true
    && A.startVersionBlocked(r0, r0.items[0]) === false
    && JSON.stringify(A.startVersions(r0, r0.items[0])) === JSON.stringify({ run: 1, item: 7, fp: 'fp_go' }));
  btnByText(/Контрольный запуск/).click(); await tick(3);
  for (const k of A.START_CHECKS) A.toggleStartCheck(k);
  await tick(1);
  $('.cs-go').click(); await tick(10);
  check('B8z. тело POST — ровно значения текущего detail-снимка',
    startPosts().length === 1 && startPosts()[0][2].expected_run_updated_at === 1
    && startPosts()[0][2].expected_item_updated_at === 7
    && startPosts()[0][2].expected_feed_fingerprint === 'fp_go');
}
S.arm = null; await A.loadArmStatus(); await tick(2);

// ── B9 (Alpha 2.757): печать проектов ИЗ ПРИЛОЖЕНИЯ — простой запуск ОДНОЙ кнопкой, одно подтверждение ──
const iaPrinter = { printer_id: 'pr1', name: 'FF', status: 'IDLE', telemetry_fresh: true,
  has_send_reservation: false, available: true, unavailable_reasons: [], safe_idle: true,
  unsafe_reason: '', hold: null, clearance: { clearance_id: 'c1', printer_id: 'pr1', status: 'active' },
  last_clearance: { clearance_id: 'c1', printer_id: 'pr1', status: 'active' } };
await reset(Object.assign(run([readyItem()]), { printers: [iaPrinter] }));
S.arm = { status: 'ok', dispatch_enabled: true, transport_enabled: true, print_enabled: true,
  armed: false, consumed: false, expires_in_s: 0, scope: null, error: '' };
await A.loadArmStatus(); await tick(4);
S.post.start = { status: 'ok', accepted: true };
{
  const r0 = A.projectRunsList.value[0];
  check('B9a. КРИТИЧНО: печать из приложения включена + стол подтверждён + safe_idle -> кнопка '
    + '«Запустить печать», а НЕ четырёхгалочный контрольный запуск',
    A.printEnabled.value === true && A.canStartInApp(r0, r0.items[0]) === true
    && A.canControlledStart(r0, r0.items[0]) === false
    && !!btnByText(/^\s*Запустить печать\s*$/) && !btnByText(/Контрольный запуск/)
    && !/Запуск печати из приложения выключен/.test(txt()));
  btnByText(/^\s*Запустить печать\s*$/).click(); await tick(3);
  check('B9b. КРИТИЧНО: клик -> ОДНО подтверждение (НИ ОДНОЙ из четырёх галочек), POST ещё нет',
    A.inAppConfirm.open === true && $$('.cs-chk').length === 0 && startPosts().length === 0);
  $('.ia-go').click(); await tick(10);
  check('B9c. КРИТИЧНО: подтверждение -> РОВНО один POST /start; тело canonical (confirmed + optimistic-lock, без флагов)',
    startPosts().length === 1 && startPosts()[0][2].confirmed === true
    && startPosts()[0][2].item_id === 'it_1'
    && JSON.stringify(Object.keys(startPosts()[0][2]).sort())
       === JSON.stringify(['confirmed', 'expected_feed_fingerprint', 'expected_item_updated_at',
                           'expected_run_updated_at', 'item_id'])
    && !/enabled|transport|printer_id|ams_slot|spool/i.test(JSON.stringify(startPosts()[0][2])));
}
// двойной клик защищён и Escape закрывает без POST
await reset(Object.assign(run([readyItem()]), { printers: [iaPrinter] }));
await A.loadArmStatus(); await tick(4);
{
  const r0 = A.projectRunsList.value[0];
  A.requestInAppStart(r0, r0.items[0], {}); await tick(2);
  window.__esc[window.__esc.length - 1](); await tick(3);
  check('B9d. Escape закрыл подтверждение -> НИ ОДНОГО POST',
    A.inAppConfirm.open === false && startPosts().length === 0);
}
S.arm = null; await A.loadArmStatus(); await tick(2);

window.__E2E_DONE = true;
window.__E2E_RESULT = { total: checks.length, failed: checks.filter((c) => !c.ok).length,
                        names: checks.filter((c) => !c.ok).map((c) => c.name) };
say('\nИТОГ: ' + (checks.length - window.__E2E_RESULT.failed) + '/' + checks.length
  + (window.__E2E_RESULT.failed ? ('  ПРОВАЛЕНО: ' + window.__E2E_RESULT.names.join(' | ')) : '  ВСЁ ЗЕЛЁНОЕ'));

// ══ Edge-вёрстка: dark/light × 1366×768 и 1550×900 ════════════════════════════════════════════
// Замер СИНХРОННЫЙ: на статике rAF не срабатывает (нет композитора) — ждать его бессмысленно.
window.__LAYOUT = async () => {
  const L = [];
  const lay = (n, c) => L.push({ name: n, ok: !!c });
  await reset(run([item({ feed_plan: feedPlan({ status: 'approval_required', effective_status: 'approval_required',
    color_relation: 'close', color_distance: 4.2, required_approval_reasons: ['close_color', 'inventory_declared'] }) })]),
    candResp([cand({ printer_name: 'Очень длинное имя принтера для проверки переноса строк 12345678',
                     spool_id: 'sp_ОЧЕНЬ_ДЛИННЫЙ_ИДЕНТИФИКАТОР_КАТУШКИ_1234567890',
                     inventory_material: 'PETG-CF Матовый Особо Длинное Название', required_color: '#FFFFFF',
                     inventory_color: '#000000', reported_color: '#FFFFFF' }), BOTH_C,
              cand({ status: 'blocked', effective_status: 'blocked', reason: 'material_mismatch', spool_id: 'sp_b' })]));
  await A.openFeedWindow(S.run, S.run.items[0], {});
  await tick(4);
  lay('L1. страница НЕ листается вбок (overflowX = 0)',
    document.documentElement.scrollWidth <= window.innerWidth + 1);
  const w = $('.pf-win').getBoundingClientRect();
  lay('L2. окно целиком внутри viewport', w.left >= -1 && w.top >= -1
    && w.right <= window.innerWidth + 1 && w.bottom <= window.innerHeight + 1);
  const b = $('.pf-body');
  lay('L3. длинный список прокручивается ВНУТРИ окна', b.scrollHeight > b.clientHeight ? b.clientHeight > 0 : true);
  lay('L4. у окна есть внутренняя прокрутка, а не рост страницы',
    getComputedStyle(b).overflowY === 'auto' && getComputedStyle(b).overscrollBehavior.includes('contain'));
  lay('L5. длинные имена не растягивают карточку',
    $$('.pf-card').every((c) => c.getBoundingClientRect().right <= w.right + 1));
  lay('L6. backdrop-filter не используется', getComputedStyle($('.pf-back')).backdropFilter === 'none');
  const sws = $$('.pf-win .pf-sw');
  lay('L7. образцы цвета видимы и имеют рамку (белый/чёрный не сливаются с фоном)',
    sws.length >= 3 && sws.every((s) => { const r = s.getBoundingClientRect();
      return r.width >= 10 && r.height >= 10 && parseFloat(getComputedStyle(s).borderTopWidth) > 0; }));
  // Пересечения с соседними фиксированными панелями — по РЕАЛЬНЫМ прямоугольникам.
  const zi = (s) => { const e = $(s); if (!e) throw new Error('нет элемента ' + s); return parseInt(getComputedStyle(e).zIndex, 10); };
  // feedCandidates — computed-REF: снаружи шаблона нужен .value (внутри Vue разворачивает сам).
  const appr = (A.feedCandidates.value || []).find((c) => A.feedCanApprove(c));
  if (!appr) throw new Error('в фикстуре нет approval-кандидата');
  A.requestFeedApprove(appr, {});
  await tick(4);
  lay('L8. confirm ВЫШЕ окна кандидатов', zi('.pf-cf-back') > zi('.pf-back'));
  lay('L9. окно кандидатов ВЫШЕ немодальной панели планов и панели отправок',
    zi('.pf-back') > 9996 && zi('.pf-back') > 9997);
  lay('L10. алерты остаются самым верхним слоем', zi('.pf-cf-back') < 100050);
  const cf = $('.pf-cf').getBoundingClientRect();
  lay('L11. confirm целиком внутри viewport', cf.left >= -1 && cf.top >= -1
    && cf.right <= window.innerWidth + 1 && cf.bottom <= window.innerHeight + 1);
  lay('L12. цель нажатия галочки >= 24x24 вместе с подписью',
    $$('.pf-rz-l').every((e) => { const r = e.getBoundingClientRect(); return r.height >= 24 && r.width >= 24; }));
  lay('L13. сама галочка не меньше 16px', $$('.pf-rz-c').every((e) => {
    const r = e.getBoundingClientRect(); return r.width >= 16 && r.height >= 16; }));
  A.closeFeedConfirm(); await tick(2);
  lay('L14. строка материала в карточке запуска не выходит за пределы встроенного блока', (() => {
    const p = $('.wpx'), blk = $('.wpx .wpx-it-mat');
    if (!p || !blk) return false;
    const pr = p.getBoundingClientRect(), br = blk.getBoundingClientRect();
    return br.right <= pr.right + 1 && br.left >= pr.left - 1; })());

  // ── вёрстка окна КОНТРОЛЬНОГО ЗАПУСКА (5B2a) ──
  // Нарочно длинные значения: окно с реальной командой печати не должно ни разъезжаться, ни
  // прятать галочки за краем экрана — оператор обязан видеть все четыре и кнопку.
  await reset(run([readyItem()]));
  S.run.items[0].feed_plan = feedPlan({ fingerprint: 'fp_go', ams_slot: 3,
    spool_id: 'sp_ОЧЕНЬ_ДЛИННЫЙ_ИДЕНТИФИКАТОР_КАТУШКИ_1234567890',
    inventory_material: 'PETG-CF Матовый Особо Длинное Название Материала 1234567890',
    required_color: '#FFFFFF', inventory_color: '#000000', reported_color: '#FFFFFF' });
  S.run.project_name = 'Проект с очень длинным именем для проверки переноса строк 1234567890';
  S.arm = armed(); await A.loadArmStatus(); await tick(4);
  btnByText(/Контрольный запуск/).click(); await tick(4);
  lay('L15. окно контрольного запуска открыто', A.startConfirm.open === true && !!$('.cs-cf'));
  lay('L16. страница НЕ листается вбок при открытом окне запуска',
    document.documentElement.scrollWidth <= window.innerWidth + 1);
  const cs = $('.cs-cf').getBoundingClientRect();
  lay('L17. окно запуска целиком внутри viewport', cs.left >= -1 && cs.top >= -1
    && cs.right <= window.innerWidth + 1 && cs.bottom <= window.innerHeight + 1);
  lay('L18. окно запуска прокручивается ВНУТРИ себя, а не растит страницу',
    getComputedStyle($('.cs-cf')).overflowY === 'auto'
    && getComputedStyle($('.cs-cf')).overscrollBehavior.includes('contain'));
  lay('L19. длинные имя проекта/катушки/материала не растягивают окно',
    $$('.cs-facts .pf-c-r, .cs-facts .pf-cols').every((e) => e.getBoundingClientRect().right <= cs.right + 1));
  lay('L20. backdrop-filter на слое запуска не используется',
    getComputedStyle($('.cs-cf-back')).backdropFilter === 'none');
  lay('L21. слой запуска выше панели планов (9996) и панели отправок (9997), ниже алертов (100050)',
    zi('.cs-cf-back') > 9997 && zi('.cs-cf-back') < 100050);
  lay('L22. КРИТИЧНО: все ЧЕТЫРЕ галочки и кнопка отправки видимы внутри viewport', (() => {
    const cks = $$('.cs-cf .cs-chk'), go = $('.cs-go');
    if (cks.length !== 4 || !go) return false;
    const vis = (e) => { const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.top >= -1 && r.bottom <= window.innerHeight + 1; };
    // Окно может прокручиваться: докручиваем до кнопки и убеждаемся, что цели остаются нажимаемыми.
    go.scrollIntoView({ block: 'nearest' });
    return cks.every((c) => c.getBoundingClientRect().width >= 16) && vis(go); })());
  lay('L23. цель нажатия галочки в окне запуска >= 24x24 вместе с подписью',
    $$('.cs-cf .pf-rz-l').every((e) => { const r = e.getBoundingClientRect(); return r.height >= 24 && r.width >= 24; }));
  A.closeStartConfirm(); await tick(2);
  lay('L24. карточка запуска с контрольной кнопкой не выходит за пределы встроенного блока', (() => {
    const p = $('.wpx'), blk = $('.wpx .wpx-it');
    if (!p || !blk) return false;
    const pr = p.getBoundingClientRect(), br = blk.getBoundingClientRect();
    return br.right <= pr.right + 1 && br.left >= pr.left - 1; })());
  return L;
};

// Драйвер для headless --dump-dom: из дампа функцию не позвать, поэтому режим задаёт строка запроса.
//   ?layout=1        — прогнать замеры вёрстки и напечатать их в тот же <pre id="out">
//   &theme=light     — тема через :root[data-theme] (реальный переключатель приложения)
// Размер окна задаётся снаружи (--window-size): здесь его только протоколируем.
if (/[?&]layout=1/.test(location.search)) {
  const theme = /[?&]theme=light/.test(location.search) ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  await tick(2);
  const L = await window.__LAYOUT();
  const bad = L.filter((x) => !x.ok);
  say('\n── ВЁРСТКА ' + window.innerWidth + 'x' + window.innerHeight + ' ' + theme + ' ──');
  for (const x of L) say((x.ok ? 'PASS' : 'FAIL') + ' — ' + x.name);
  window.__LAYOUT_RESULT = { total: L.length, failed: bad.length, names: bad.map((x) => x.name) };
  say('ВЁРСТКА-ИТОГ: ' + (L.length - bad.length) + '/' + L.length
    + (bad.length ? ('  ПРОВАЛЕНО: ' + bad.map((x) => x.name).join(' | ')) : '  ВСЁ ЗЕЛЁНОЕ'));
}
