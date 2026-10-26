// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Рендер-часть UI-теста фазы A. Монтирует НАСТОЯЩУЮ разметку окна из web/index.html и НАСТОЯЩИЕ
// функции из web/app.js (извлекаются по сбалансированным скобкам, код не переписан).
// Все fetch перехвачены фикстурами; /start и печатные endpoint — bomb.
import { createApp, ref, reactive, computed, nextTick } from 'vue';

const log = [], checks = [];
const say = (m) => { log.push(m); document.getElementById('out').textContent = log.join('\n'); };
const check = (n, c) => { checks.push({ name: n, ok: !!c }); say((c ? 'PASS' : 'FAIL') + ' — ' + n); };
window.__CALLS = [];
window.__BOOM = [];

const realFetch = window.fetch.bind(window);
const APPJS = await realFetch('/web/app.js?v=' + Date.now()).then(r => r.text());
const INDEX = await realFetch('/web/index.html?v=' + Date.now()).then(r => r.text());

// ── фикстуры: ровно та форма, что отдаёт реальный backend (см. app/project_orchestrator.preflight) ──
const part = (id, name, req, pr, rem, rw = 0, rwd = 0) =>
  ({ part_id: id, part_name: name, required_qty: req, printed_qty: pr, rework_qty: rw, rework_done: rwd, remaining: rem, order_idx: 0 });
const prn = (id, name, status, fresh, avail, reasons = []) =>
  ({ printer_id: id, name, status, telemetry_fresh: fresh, has_send_reservation: false, available: avail,
     unavailable_reasons: reasons, clearance: null });
const base = (plan, parts, printers) => ({
  project_id: 'prj', plan, remaining: Object.fromEntries(parts.filter(p => p.remaining > 0).map(p => [p.part_id, p.remaining])),
  parts, printers, existing_run: null, requires_initial_clearance: true, dispatch_enabled: false,
  idle_is_not_proof: 'IDLE/FINISH не доказывают, что стол пуст: подтверждение снятия деталей даёт только оператор кнопкой «Стол очищен».',
});
const plan = (o) => Object.assign({
  project_id: 'prj', snapshot_version: 'v_exact_1', deficits: {}, chosen_files: {}, items: [],
  overproduction_total: {}, overproduction_count: 0, uncovered: {}, blocked: [],
  plan_quality: 'exact', requires_overproduction_approval: false, allow_overproduction: false }, o);

const FIX = {
  exact: base(plan({ deficits: { pa: 4 }, chosen_files: { F1: 1 },
    items: [{ seq: 1, file_id: 'F1', filename: 'plate_a.3mf', file_content_hash: 'h1',
              planned_parts: { pa: 4 }, planned_overproduction: {}, compatible_pids: ['pr1'] }] }),
    [part('pa', 'Кронштейн', 4, 0, 4)], [prn('pr1', 'X1C-01', 'IDLE', true, true)]),
  approx: base(plan({ snapshot_version: 'v_approx', plan_quality: 'approximate', deficits: { pa: 7 },
    chosen_files: { F1: 7 }, items: [{ seq: 1, file_id: 'F1', filename: 'p.3mf', file_content_hash: 'h',
      planned_parts: { pa: 1 }, planned_overproduction: {}, compatible_pids: ['pr1'] }] }),
    [part('pa', 'Деталь', 7, 0, 7)], [prn('pr1', 'X1C-01', 'IDLE', true, true)]),
  completed: base(plan({ snapshot_version: 'v_done' }), [part('pa', 'Готовая', 2, 2, 0)],
    [prn('pr1', 'X1C-01', 'IDLE', true, true)]),
  blocked: base(plan({ snapshot_version: 'v_block', deficits: { pa: 1, pb: 1 }, chosen_files: { F1: 1 },
    items: [{ seq: 1, file_id: 'F1', filename: 'ok.3mf', file_content_hash: 'h',
              planned_parts: { pa: 1 }, planned_overproduction: {}, compatible_pids: ['pr1'] }],
    uncovered: { pb: 1 }, blocked: [{ part_id: 'pb', part_name: 'Без принтера', qty: 1, reason: 'no_compatible_printer' }] }),
    [part('pa', 'Обычная', 1, 0, 1), part('pb', 'Без принтера', 1, 0, 1)],
    [prn('pr1', 'X1C-01', 'IDLE', true, true), prn('pr2', 'P1S-02', 'RUNNING', true, false, ['busy_running']),
     prn('pr3', 'AD5M', 'OFFLINE', false, false, ['offline_or_stale'])]),
  // перепроизводство: allow=0 -> ничего не планируем; allow=1 -> план с точными лишними
  overNo: base(plan({ snapshot_version: 'v_over', deficits: { pa: 1 }, uncovered: { pa: 1 },
    requires_overproduction_approval: true,
    blocked: [{ part_id: 'pa', part_name: 'Уголок', qty: 1, reason: 'overproduction_not_allowed' }] }),
    [part('pa', 'Уголок', 1, 0, 1)], [prn('pr1', 'X1C-01', 'IDLE', true, true)]),
  overYes: base(plan({ snapshot_version: 'v_over', deficits: { pa: 1 }, chosen_files: { F1: 1 },
    items: [{ seq: 1, file_id: 'F1', filename: 'quad.3mf', file_content_hash: 'h',
              planned_parts: { pa: 1 }, planned_overproduction: { pa: 3 }, compatible_pids: ['pr1'] }],
    overproduction_total: { pa: 3 }, overproduction_count: 3, allow_overproduction: true,
    requires_overproduction_approval: false }),
    [part('pa', 'Уголок', 1, 0, 1)], [prn('pr1', 'X1C-01', 'IDLE', true, true)]),
};

// ── управление сценарием ──
window.__MODE = 'exact';
// ── фикстура GET /api/project-runs?active=1 (форма реального list_active_runs: run_public + project_name)
// Фикстура ответа СПИСКА GET /api/project-runs?active=1 — РОВНО форма реального list_active_runs()
// (run_public + project_name). items/counts/printers здесь НЕТ и быть не должно: настоящий список
// их не отдаёт, за ними UI обязан идти в detail. Раньше фикстура их объявляла, и харнесс переставал
// воспроизводить production — тест tools/test_project_start_contract.py (N1) держит эту форму.
const mkRun = (id, pname, state, q) => ({ run_id: id, project_id: 'p_' + id, project_name: pname,
  state, allow_overproduction: false, plan_quality: q || 'exact', blocked: [], created_at: 1000,
  updated_at: 1001, boot_id: 'b1', note: '', dispatch_enabled: false });
window.__ACTIVE = { status: 'ok', runs: [] };
window.__LIST_FAIL = false;
// ── detail-фикстуры GET /api/project-runs/{id}: РОВНО форма реального get_run (run_public + items
// + counts + printers), включая аддитивное printers[].last_clearance ──
const clr = (status, reason, cid) => (!status ? null : ({
  clearance_id: cid || 'clr_1', printer_id: 'pr1', finished_job_id: 'pjob_1', confirmed_by: 'op',
  confirmed_at: 1000, boot_id: 'b1', is_initial: false, status, invalid_reason: reason || '',
  consumed_at: status === 'consumed' ? 1001 : null,
  invalidated_at: (status === 'revoked' || status === 'invalidated') ? 1002 : null }));
// safe_idle/unsafe_reason — реальные поля production printer_availability (правило то же, что в
// safety-снимке: safe_idle = свежая телеметрия + IDLE). Alpha 2.752: первичное «Стол очищен»
// зависит от них, поэтому фикстура обязана их отдавать, как настоящий backend.
const prn2 = (id, name, status, fresh, active, last) => ({
  printer_id: id, name, status, telemetry_fresh: fresh, has_send_reservation: false,
  available: fresh && status === 'IDLE', unavailable_reasons: (fresh && status === 'IDLE') ? [] : ['busy_or_stale'],
  safe_idle: !!fresh && status === 'IDLE',
  unsafe_reason: (!!fresh && status === 'IDLE') ? '' : ('not_idle_raw:' + (status || 'OFFLINE')),
  hold: null, clearance: active || null, last_clearance: last || active || null });
// updated_at и feed_plan — реальные поля item_public (2.749/2.742); fp нужен первичной цели.
const itm = (id, state, pid, job, fp) => ({ item_id: id, seq: 1, file_id: 'F1', state, updated_at: 5,
  block_reason: '', planned_parts: {}, planned_overproduction: {}, assigned_printer_id: pid || '',
  project_print_job_id: job || '', command_sent: false, attempt: 0, last_error: '',
  filename: '', feed_plan: fp || null });   // filename — production-поле 2.754 (get_run)
const mkDetail = (id, state, items, printers, partNames) => ({ run_id: id, project_id: 'p_' + id, state,
  allow_overproduction: false, plan_quality: 'exact', blocked: [], created_at: 1000, updated_at: 1001,
  boot_id: 'b1', note: '', dispatch_enabled: false, items: items || [], counts: {},
  printers: printers || [], part_names: partNames || {} });   // part_names — production-поле 2.754
window.__DETAIL = {};          // run_id -> detail; отсутствует -> дефолтный пустой draft
window.__DETAIL_FAIL = {};     // run_id -> true: detail этого run падает (снимок не стирается)
window.__DETAIL_CALLS = 0;
window.__LIST_CALLS = 0;
window.__POST = { status: 200, body: { status: 'ok', run_id: 'prun_new' } };
window.__DELAY = 0;

window.fetch = async (url, opt) => {
  const u = String(url), m = (opt && opt.method) || 'GET';
  window.__CALLS.push({ u, m, body: opt && opt.body ? JSON.parse(opt.body) : null });
  if (/\/start\b/.test(u) || /files\/[^/]+\/print/.test(u) || /\/api\/part\/print/.test(u)
      || /upload_print|print_path/.test(u)) {
    window.__BOOM.push(u);
    throw new Error('ЗАПРЕЩЁННЫЙ ВЫЗОВ ПЕЧАТИ: ' + u);
  }
  const J = (o, st = 200) => new Response(JSON.stringify(o), { status: st, headers: { 'Content-Type': 'application/json' } });
  if (u.includes('/whole-print/preflight')) {
    if (window.__DELAY) await new Promise(r => setTimeout(r, window.__DELAY));
    if (opt && opt.signal && opt.signal.aborted) { const e = new Error('aborted'); e.name = 'AbortError'; throw e; }
    const over = u.includes('allow_overproduction=1');
    const mode = window.__MODE;
    if (mode === 'over') return J(over ? FIX.overYes : FIX.overNo);
    return J(FIX[mode] || FIX.exact);
  }
  if (u.includes('/api/project-runs?active=1')) {
    window.__LIST_CALLS++;
    if (window.__LIST_FAIL) return new Response('boom', { status: 500 });
    if (window.__DELAY) await new Promise(r => setTimeout(r, window.__DELAY));
    if (opt && opt.signal && opt.signal.aborted) { const e = new Error('aborted'); e.name = 'AbortError'; throw e; }
    return J(window.__ACTIVE);
  }
  if (/\/api\/project-runs\/[^/]+\/(pause|resume|cancel)$/.test(u) && m === 'POST') return J({ status: 'ok' });
  if (u.includes('/whole-print/runs') && m === 'POST') return J(window.__POST.body, window.__POST.status);
  if (/\/api\/project-runs\/[^/]+\/printers\/[^/]+\/plate-clear$/.test(u) && m === 'POST') return J({ status: 'ok' });
  if (/\/api\/project-runs\/[^/]+\/printers\/[^/]+\/plate-clear\/revoke$/.test(u) && m === 'POST') return J({ status: 'ok' });
  if (/\/api\/project-runs\/[^/]+\/items\/[^/]+\/resolve$/.test(u) && m === 'POST') {
    const b = opt && opt.body ? JSON.parse(opt.body) : {};
    // Реальный backend НЕ верит на слово: «началась» без подтверждающего project_print_job -> 409.
    if (b.resolution === 'started' && window.__RESOLVE_409)
      return J({ status: 'error', reason: 'no_project_print_job_to_confirm' }, 409);
    return J({ status: 'ok', state: 'completed' });
  }
  if (/\/api\/project-runs\/[^/]+$/.test(u)) {
    window.__DETAIL_CALLS++;
    const id = u.split('/').pop();
    if (window.__DETAIL_FAIL[id]) return new Response('boom', { status: 500 });
    if (window.__DETAIL[id]) return J(window.__DETAIL[id]);
    // Дефолт обязан быть ЧЕСТНЫМ: реальный get_run читает ТУ ЖЕ строку project_runs, что и список,
    // поэтому state/plan_quality совпадают. Отличия только: есть items/counts/printers, нет project_name.
    const inList = ((window.__ACTIVE && window.__ACTIVE.runs) || []).find(r => r.run_id === id);
    if (!inList) return J(mkDetail(id, 'draft', [], []));
    const d = Object.assign({}, inList, { items: [], counts: {}, printers: [] });
    delete d.project_name;
    return J(d);
  }
  return J({});
};

// ── реальные функции из app.js ──
const extractArrow = (src, decl) => {
  const s = src.indexOf(decl);
  if (s < 0) throw new Error('не найдено: ' + decl);
  const open = src.indexOf('{', s + decl.length);
  let d = 0, i = open;
  for (; i < src.length; i++) { const ch = src[i]; if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) break; } }
  return src.slice(s, i + 1) + ';';
};
const blockOf = (src, from, to) => src.slice(src.indexOf(from), src.indexOf(to));
const SRC = blockOf(APPJS, 'const showProjectWholePreflight = ref(false);', 'const closeActiveModule =');
// safeHex объявлен ВЫШЕ блока, а блок «Источник материала» (5A3b) его вызывает при рендере —
// поэтому берём его дословно отдельно и инжектим как параметр.
const SAFEHEX_FN = (() => {
  const s = APPJS.indexOf('const safeHex = (v) => {');
  let d = 0, i = APPJS.indexOf('{', s + 20);
  for (; i < APPJS.length; i++) { const ch = APPJS[i]; if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) break; } }
  return new Function(APPJS.slice(s, i + 1) + '; return safeHex;')();
})();

// ── реальная разметка из index.html ──
// Alpha 2.753: модалки preflight и глобальной панели больше НЕТ. Весь сценарий — во ВСТРОЕННОМ
// блоке .wpx внутри раскрытого проекта. Монтируем его в host-цикле по проектам, как в проде.
const cut = (from, to) => {
  const a = INDEX.indexOf(from);
  const b = INDEX.indexOf(to, a) + to.length;
  return INDEX.slice(a, b).replace('<teleport to="body">', '').replace(/<\/teleport>$/, '');
};
const WPX_TPL = (() => {
  const a = INDEX.indexOf('<div v-if="wpxOpenFor(pr.id)" class="wpx"');
  const b = INDEX.indexOf('<div class="p-2">', a);
  if (a < 0 || b < 0) throw new Error('встроенный блок .wpx не найден (якорь разошёлся)');
  return INDEX.slice(a, INDEX.lastIndexOf('</div>', b) + 6);
})();
const TPL = '';                                     // модалки нет по замыслу 2.753
const PANEL_TPL = '<template v-for="pr in wpxProjects" :key="pr.id">' + WPX_TPL + '</template>';
const CONFIRM_TPL = cut('<teleport to="body"><div v-if="projectRunConfirm.open"', '</div></teleport>');
// Alpha 2.757: ПРОСТОЕ подтверждение запуска печати из приложения (многострочный teleport,
// поэтому режем окно напрямую, без обёртки teleport — как это делает и feed-харнесс).
const IACF_TPL = (() => {
  const a = INDEX.indexOf('<div v-if="inAppConfirm.open"');
  const b = INDEX.indexOf('</div>\n</teleport>', a);
  if (a < 0 || b < 0) throw new Error('окно inAppConfirm не найдено (якорь разошёлся)');
  return INDEX.slice(a, b + '</div>'.length);
})();

// Настоящая кнопка-индикатор waiting_plate_clear, дословно вырезанная из карточки принтера.
const WPC_BTN = (() => {
  const a = INDEX.indexOf('<button type="button" v-if="printerAwaitsPlateClear(p)"');
  return INDEX.slice(a, INDEX.indexOf('</button>', a) + '</button>'.length);
})();
// Мини-карточка принтера: реальный индикатор в окружении, имитирующем grid/list.
const CARDS_TPL = '<div id="tp"><div v-for="p in testPrinters" :key="p.id" class="tp-card" '
  + 'style="display:flex;align-items:center;gap:4px">'
  + '<span class="tp-name">{{ p.name }}</span>' + WPC_BTN + '</div></div>';

const App = {
  template: '<div>' + TPL + PANEL_TPL + CONFIRM_TPL + IACF_TPL + CARDS_TPL + '</div>',
  setup() {
    const lang = ref('ru');
    const registerEscapeLayer = (fn) => { window.__esc.push(fn); return 'tok' + window.__esc.length; };
    const unregisterEscapeLayer = () => { window.__esc.pop(); };
    window.__esc = [];
    const api = new Function('ref', 'reactive', 'computed', 'nextTick', 'registerEscapeLayer', 'unregisterEscapeLayer', 'lang', 'safeHex', 'project2Expanded',
      SRC + '\n return { showProjectWholePreflight, projectWholeProject, projectWholePreflight, projectWholeLoading, '
      + 'projectWholeError, projectWholeSaveError, projectWholeSaving, projectWholeAllowOverproduction, '
      + 'projectWholeSavedRun, projectWholeNotice, projectWholePlan, projectWholeParts, projectWholeCompleted, '
      + 'projectWholeNeedsApproval, projectWholeOverRows, projectWholePartName, projectWholeCanSave, '
      + 'openProjectWholePreflight, closeProjectWholePreflight, refreshProjectWholePreflight, saveProjectWholeDraft, '
      + 'projectRunsById, projectRunOrder, projectRunsList, projectRunsActiveCount, '
      + 'projectRunsInitialLoading, projectRunsListError, projectRunActions, '
      + 'projectRunErrors, projectRunConfirm, highlightedRunId, projectRunName, projectRunCounts, '
      + 'projectRunCanPause, projectRunCanResume, projectRunCanCancel, projectRunBusy, refreshProjectRuns, '
      // Alpha 2.753: встроенный блок .wpx
      + 'wpxOpenMap, wpxTechOpen, wpxRunFor, wpxOpenFor, toggleWholePrint, wpxPreflightFor, wpxStatus, '
      + 'wpxSummary, wpxProgressPct, wpxItemState, wpxItemKind, wpxMaterialLine, wpxMaterialWarn, '
      + 'wpxItemClearance, wpxPrinterName, wpxPartsLine, wpxMainCta, wpxDoMain, wpxToggleTech, '
      + 'wpxCurrentItem, wpxCurrentIndex, wpxQueueItems, wpxPartsText, wpxFileLabel, wpxSeriesPrinter, '
      + 'wpxSeriesMaterial, wpxClrState, wpxHint, wpxQueueOpen, wpxToggleQueue, wpxMatMenu, wpxToggleMatMenu, ' 
      + 'printEnabled, printEnableBusy, setPrintEnabled, canStartInApp, inAppConfirm, requestInAppStart, '
      + 'closeInAppStartConfirm, confirmInAppStart, inAppStartFacts, '
      + 'project2Expanded, pauseProjectRun, resumeProjectRun, requestCancelProjectRun, '
      + 'closeCancelProjectRunConfirm, confirmCancelProjectRun, loadActiveProjectRuns, stopProjectRunsPolling, '
      + '_pollTimer: () => projectRunsPollTimer, _inFlight: () => projectRunsPollInFlight, '
      + 'pollProjectRunsOnce, syncProjectRunsPolling, '
      + 'projectRunClearanceTargets, projectRunPlateClearIds, printerAwaitsPlateClear, focusPlateClearRun, '
      + 'clearanceCanConfirm, clearanceCanRevoke, clearanceBlockReason, clearanceStateText, '
      + 'projectRunAmbiguousItems, requestPlateClear, revokePlateClear, requestResolveItem, '
      + 'projectRunConfirmTitle, projectRunConfirmText, projectRunConfirmOk, '
      // Alpha 2.745: в разметке панели появился блок «Источник материала» (UI-фаза 5A3b). Он живёт
      // в ТОМ ЖЕ SRC-блоке, поэтому его функции обязаны быть в возврате — иначе шаблон панели
      // падает с «feedBlockState is not a function». Сам блок этот харнесс не проверяет (для него
      // есть tools/e2e_feed_plan_harness.html), но отрендериться панель обязана целиком.
      + 'feedWin, feedConfirm, feedCandidates, feedSummary, feedItemActive, feedItemBusy, '
      + 'feedItemNotice, feedItemError, feedBlockState, feedSlotLabel, feedSwatch, feedSwatchOk, '
      + 'feedHexText, feedDeltaText, feedRelText, feedVerifyText, feedReasonText, feedPlanReasons, '
      + 'openFeedWindow, closeFeedWindow, refreshFeedCandidates, feedCanSelect, feedCanApprove, '
      + 'selectFeedCandidate, requestFeedApprove, requestFeedClear, closeFeedConfirm, toggleFeedReason, '
      + 'confirmFeedApprove, confirmFeedClear, feedConfirmReasons, feedConfirmUnknown, feedApproveReady, '
      // Alpha 2.748/2.749: в ту же разметку панели добавлен блок «Реальная отправка» (контрольный
      // запуск). По той же причине его функции обязаны быть в возврате — иначе панель падает с
      // «canControlledStart is not a function» и рендерится ПУСТОЙ, а проверки этого харнесса
      // становятся ложнозелёными. Сам блок проверяет tools/e2e_feed_plan_harness.html.
      + 'armStatus, armScope, armReady, startConfirm, START_CHECKS, startCheckText, startKey, '
      + 'startItemBusy, startItemNotice, startItemUnknown, canControlledStart, startApproveReady, '
      + 'startVersions, startVersionBlocked, toggleStartCheck, requestControlledStart, '
      + 'closeStartConfirm, confirmControlledStart, loadArmStatus };'
    )(ref, reactive, computed, nextTick, registerEscapeLayer, unregisterEscapeLayer, lang, SAFEHEX_FN, ref(''));
    window.__api = api;
    const testPrinters = ref([]);
    window.__setPrinters = (list) => { testPrinters.value = list; };
    // host-проекты для v-for блока: preflight-фазы живут в 'prj', run-фазы — в 'p_prun_W'
    // (project_id run-фикстур). Так же и проверяется, что run НЕ появляется в чужом проекте.
    const wpxProjects = ref([{ id: 'prj', name: 'Тестовый проект' }, { id: 'p_prun_W', name: 'Проект W' }]);
    window.__setWpxProjects = (list) => { wpxProjects.value = list; };
    return Object.assign({ lang, testPrinters, wpxProjects }, api);
  },
};
const app = createApp(App);
app.config.errorHandler = (e, i, info) => { say('VUE ERROR: ' + (e && e.message) + ' | ' + info); window.__E2E_ERR = String((e && e.stack) || e); };
app.mount('#app');
await nextTick();

const $ = (s) => document.querySelector(s);
// 2.753: «окно» -> ВСТРОЕННЫЙ блок .wpx. В каждый момент открыт ровно один (preflight — у 'prj',
// run-фазы — у 'p_prun_W'), поэтому селектор общий.
const win = () => $('.wpx');
const T = () => (win() ? win().textContent : '');   // ТОЛЬКО блок: body включает лог теста -> ложные совпадения
const settle = async (ms = 60) => { await new Promise(r => setTimeout(r, ms)); await nextTick(); };
const calls = (re, m) => window.__CALLS.filter(c => re.test(c.u) && (!m || c.m === m));
const reset = () => { window.__CALLS = []; };
const pollOnce = () => window.__api.pollProjectRunsOnce();
const btn = document.createElement('button');   // источник focus (в проде — кнопка в шапке проекта)
btn.className = 'pw-open-btn'; btn.textContent = 'Печатать весь проект';
document.body.appendChild(btn);
const open = async (mode) => {
  // Между сценариями блок СВОРАЧИВАЕМ и сбрасываем preflight — иначе фикстура не сменится.
  window.__api.closeProjectWholePreflight();
  window.__api.wpxOpenMap.value = {};
  await settle(20);
  window.__MODE = mode; reset();
  btn.focus();
  // Ровно то, что делает кнопка шапки проекта: toggle встроенного блока (+ авторасчёт при нет-run).
  window.__api.toggleWholePrint({ id: 'prj', name: 'Тестовый проект' });
  await settle(140);
};

// ══ U1-U5 ══
check('U1. кнопка «Печатать весь проект» объявлена в разметке проекта РОВНО один раз и раскрывает '
      + 'встроенный блок (toggleWholePrint), с aria-expanded',
      (INDEX.match(/toggleWholePrint\(pr\)/g) || []).length === 1
      && /class="pw-open-btn"[^>]*@click\.stop="toggleWholePrint\(pr\)"/.test(INDEX)
      && /class="pw-open-btn"[^>]*:aria-expanded="wpxOpenFor\(pr\.id\)/.test(INDEX));
check('U2. кнопка не сворачивает проект: @click.stop и стоит в контейнере действий',
      /class="pw-open-btn"[^>]*@click\.stop=/.test(INDEX)
      && INDEX.indexOf('pw-open-btn') > INDEX.indexOf('<div class="flex items-center gap-2 shrink-0" @click.stop>'));
await open('exact');
check('U3. один клик -> один встроенный блок и РОВНО один GET preflight',
      !!win() && document.querySelectorAll('.wpx').length === 1 && calls(/whole-print\/preflight/).length === 1);
reset();
window.__DELAY = 200;
window.__api.openProjectWholePreflight({ id: 'prj', name: 'Тестовый проект' }, { currentTarget: btn });
window.__api.openProjectWholePreflight({ id: 'prj', name: 'Тестовый проект' }, { currentTarget: btn });
window.__api.refreshProjectWholePreflight();
await settle(320);
check('U4. двойной клик во время загрузки -> один GET и один блок',
      calls(/whole-print\/preflight/).length === 1 && document.querySelectorAll('.wpx').length === 1);
window.__DELAY = 0;
reset();
window.__DELAY = 250;
window.__api.refreshProjectWholePreflight();
await settle(30);
window.__api.closeProjectWholePreflight();
await settle(320);
check('U5. сброс расчёта отменяет запрос: AbortError НЕ показан как ошибка; блок остаётся в '
      + 'потоке (не модалка) и предлагает «Рассчитать план»',
      !window.__api.projectWholeError.value && !window.__api.wpxPreflightFor('prj')
      && !!win() && T().includes('Рассчитать план'));
window.__DELAY = 0;

// ══ U6-U11 ══
await open('exact');
check('U6. exact -> «Точный план»', T().includes('Точный план') && !T().includes('Приближённый план'));
await open('approx');
check('U7. approximate -> честная плашка, «Точный план» не показан',
      T().includes('Приближённый план') && T().includes('достигнут лимит полного перебора')
      && !T().includes('Точный план'));
await open('completed');
check('U8. завершённый проект: сказано прямо; главной кнопки «Сохранить план» НЕТ вовсе (CTA контекстная)',
      T().includes('Проект уже напечатан полностью') && window.__api.projectWholeCanSave.value === false
      && ![...document.querySelectorAll('.pw-btn')].find(b => b.textContent.includes('Сохранить план')));
await open('exact');
check('U9. остаток и план файлов показаны точно (4 шт, plate_a.3mf, «Кронштейн × 4»)',
      T().includes('Кронштейн') && T().includes('plate_a.3mf') && T().includes('Кронштейн × 4')
      && /запуск\s*#1/.test(T()));
await open('blocked');
check('U10. blocked/uncovered и состояния принтеров с реальными причинами видимы',
      T().includes('no_compatible_translate') === false && T().includes('no_compatible_printer')
      && T().includes('Без принтера') && T().includes('busy_running') && T().includes('offline_or_stale')
      && T().includes('нет свежих данных'));
check('U10b. постоянное предупреждение про IDLE присутствует', T().includes('IDLE/FINISH не доказывают'));
await open('over');
check('U11. перепроизводство: точные «нужно 1 / будет 4 / лишнее +3»',
      T().includes('Неизбежное перепроизводство')
      && JSON.stringify(window.__api.projectWholeOverRows.value) ===
         JSON.stringify([{ part_id: 'pa', name: 'Уголок', need: 1, extra: 3, total: 4 }])
      && T().includes('+3'));

// ══ U12-U16 ══
reset();
check('U12. без чекбокса сохранение недоступно и POST не уходит',
      window.__api.projectWholeAllowOverproduction.value === false
      && window.__api.projectWholeCanSave.value === false
      && (window.__api.saveProjectWholeDraft(), calls(/whole-print\/runs/, 'POST').length === 0));
window.__api.projectWholeAllowOverproduction.value = true;
await settle();
reset();
await window.__api.saveProjectWholeDraft();
await settle();
const p1 = calls(/whole-print\/runs/, 'POST');
check('U13. с чекбоксом -> РОВНО один POST с точным snapshot_version и allow_overproduction=true',
      p1.length === 1 && p1[0].body.allow_overproduction === true && p1[0].body.snapshot_version === 'v_over'
      && !('plan' in p1[0].body) && !('items' in p1[0].body));
await open('exact');
reset();
await window.__api.saveProjectWholeDraft();
await settle();
const p2 = calls(/whole-print\/runs/, 'POST');
check('U14. обычный план -> allow_overproduction=false', p2.length === 1 && p2[0].body.allow_overproduction === false
      && p2[0].body.snapshot_version === 'v_exact_1');
await open('exact');
reset();
window.__api.saveProjectWholeDraft(); window.__api.saveProjectWholeDraft();
await settle(120);
check('U15. двойной клик «Сохранить» -> один POST', calls(/whole-print\/runs/, 'POST').length === 1);
await open('exact');
window.__POST = { status: 200, body: { status: 'ok', run_id: 'prun_ok' } };
await window.__api.saveProjectWholeDraft(); await settle();
check('U16a. успех: «План сохранён…», ложного «Печать запущена» НЕТ; run подгружен (raw id НЕ '
      + 'на первом уровне)',
      T().includes('План сохранён') && T().includes('Автоматическая печать в этой версии отключена')
      && (window.__api.projectWholeSavedRun.value || {}).run_id === 'prun_ok'
      && !T().includes('Печать запущена') && !T().includes('prun_ok'));
await open('exact');
window.__POST = { status: 409, body: { status: 'error', reason: 'project_run_exists', existing_run_id: 'prun_old' } };
reset();
await window.__api.saveProjectWholeDraft(); await settle();
check('U16b. 409 existing_run_id: второй run не создаётся, подгружен существующий (raw id НЕ на первом уровне)',
      T().includes('уже существует сохранённый план')
      && (window.__api.projectWholeSavedRun.value || {}).run_id === 'prun_old'
      && calls(/whole-print\/runs/, 'POST').length === 1 && calls(/project-runs\/prun_old$/).length === 1);
await open('exact');
window.__POST = { status: 409, body: { status: 'error', reason: 'project_plan_stale' } };
await window.__api.saveProjectWholeDraft(); await settle();
check('U16c. 409 project_plan_stale: окно открыто, предложено обновить, run не создан',
      T().includes('Проект изменился после расчёта') && !!win()
      && !window.__api.projectWholeSavedRun.value
      && !![...document.querySelectorAll('.pw-btn')].find(b => b.textContent.includes('Обновить расчёт')));
window.__POST = { status: 200, body: { status: 'ok', run_id: 'prun_new' } };

// ══ инварианты безопасности ══
reset();
check('U17. 2.753: мёртвой кнопки «Автозапуск будет подключён» больше нет; вместо неё — одна '
      + 'спокойная плашка проверочного режима (НЕ кнопка), и запросов от неё ноль',
      document.querySelectorAll('.pw-btn.pw-dead').length === 0
      && !!$('.wpx-mode') && $('.wpx-mode').tagName !== 'BUTTON'
      && T().includes('Проверочный режим: доступен только один контролируемый запуск')
      && window.__CALLS.length === 0);
check('U18. за весь сценарий НИ ОДНОГО запроса к /start и к печатным endpoint', window.__BOOM.length === 0);
const appjsCode = APPJS.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter(l => !l.trim().startsWith('//')).join('\n');
const pwBlockAll = blockOf(appjsCode, 'const showProjectWholePreflight', 'const closeActiveModule =');
// Блок контрольного запуска (5B2a) лежит внутри тех же якорей, но к UI-фазе A не относится и
// проверяется своим тестом. Его единственный законный /start вырезаем, иначе инвариант «фаза A
// сама не печатает» стал бы ложным; а U19b следит, чтобы этот /start остался ровно один.
const pwBlock = (() => {
  const a = pwBlockAll.indexOf('const armStatus = ref(null);');
  const b = pwBlockAll.indexOf('const confirmFeedClear = async () => {');
  if (a < 0 || b < 0 || b <= a) throw new Error('блок 5B2a не найден: якоря разошлись с web/app.js');
  return pwBlockAll.slice(0, a) + pwBlockAll.slice(b);
})();
check('U19. в коде UI-фазы A нет /start и нет вызова печатных endpoint',
      !/\/start/.test(pwBlock) && !/files\/[^'"]*\/print/.test(pwBlock) && !/_send|mqtt|ftp/i.test(pwBlock));
check('U19b. КРИТИЧНО: единственный /start на участке — в блоке контрольного запуска 5B2a',
      (pwBlockAll.match(/\/start\b/g) || []).length === 1);
check('U20. существующая печать одного файла проекта не изменена (endpoint и вызов на месте)',
      /\/api\/projects2\/'\s*\+\s*[^;]*\+\s*'\/files\/'/.test(APPJS) || APPJS.includes('/files/') );
check('U21. 2.753: встроенный блок НЕ модалка — открытие/сброс расчёта НЕ трогает Escape-стек',
      (() => { window.__api.closeProjectWholePreflight();
               const n0 = window.__esc.length;
               window.__api.openProjectWholePreflight({ id: 'prj', name: 'X' });
               const n1 = window.__esc.length;
               window.__api.closeProjectWholePreflight();
               return n1 === n0 && window.__esc.length === n0; })());


// ══ U17-U23: встроенные блоки по проектам, восстановление, polling, pause/resume/cancel ══
// 2.753: общей панели нет. Каждый run рендерится ТОЛЬКО в блоке .wpx СВОЕГО проекта
// (host-цикл по wpxProjects, как v-for проектов в проде).
const blocks = () => [...document.querySelectorAll('.wpx')];
const blockOfName = (name) => blocks().find(e => (e.getAttribute('aria-label') || '').includes(name));
const resetRuns = async () => {
  window.__api.stopProjectRunsPolling();
  window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
  window.__api.wpxOpenMap.value = {};
  window.__ACTIVE = { status: 'ok', runs: [] }; window.__LIST_CALLS = 0; reset();
  await settle(30);
};

// U17: success + existing НЕ создают дубль run'а
await resetRuns();
window.__setWpxProjects([{ id: 'prj', name: 'Тестовый проект' }, { id: 'p_prun_ok', name: 'Проект OK' }]);
await open('exact');
window.__POST = { status: 200, body: { status: 'ok', run_id: 'prun_ok' } };
await window.__api.saveProjectWholeDraft(); await settle(80);
const afterSave = Object.keys(window.__api.projectRunsById.value).length;
await open('exact');
window.__POST = { status: 409, body: { status: 'error', reason: 'project_run_exists', existing_run_id: 'prun_ok' } };
await window.__api.saveProjectWholeDraft(); await settle(80);
check('U17b. success и existing_run_id дают ОДИН run без дубля; его блок открыт в СВОЁМ проекте',
      afterSave === 1 && Object.keys(window.__api.projectRunsById.value).length === 1
      && !!blockOfName('Проект OK') && window.__api.wpxOpenMap.value['p_prun_ok'] === true);
window.__POST = { status: 200, body: { status: 'ok', run_id: 'prun_new' } };
window.__api.closeProjectWholePreflight();

// U18: восстановление после reload через ?active=1 — каждый run в СВОЁМ проекте
await resetRuns();
window.__setWpxProjects([{ id: 'p_prun_A', name: 'Проект A' }, { id: 'p_prun_B', name: 'Проект B' },
                         { id: 'p_prun_C', name: 'Проект C' }, { id: 'p_prun_X', name: 'Посторонний' }]);
window.__ACTIVE = { status: 'ok', runs: [
  mkRun('prun_A', 'Проект A', 'draft', 'exact'),
  mkRun('prun_B', 'Проект B', 'paused', 'approximate'),
  mkRun('prun_C', null, 'draft', 'exact'),                 // project_name=null -> run не теряем
  mkRun('prun_A', 'Проект A', 'draft', 'exact')] };        // дубль в ответе -> должен схлопнуться
reset();
await window.__api.loadActiveProjectRuns(true);
await settle(60);
check('U18. КРИТИЧНО: после reload каждый run восстановлен во ВСТРОЕННОМ блоке своего проекта; '
      + 'дублей нет; у постороннего проекта блока НЕТ; НИ ОДНОГО POST',
      blocks().length === 3 && !!blockOfName('Проект A') && !!blockOfName('Проект B')
      && !!blockOfName('Проект C') && !blockOfName('Посторонний')
      && Object.keys(window.__api.projectRunsById.value).length === 3
      && calls(/project-runs\?active=1/).length === 1
      && window.__CALLS.filter(c => c.m === 'POST').length === 0);
check('U18b. КРИТИЧНО: run одного проекта НЕ появляется внутри другого (wpxRunFor строго по project_id)',
      (() => { window.__api.wpxTechOpen.value = { p_prun_A: true, p_prun_B: true };
               return true; })()
      && (window.__api.wpxRunFor('p_prun_A') || {}).run_id === 'prun_A'
      && (window.__api.wpxRunFor('p_prun_B') || {}).run_id === 'prun_B'
      && window.__api.wpxRunFor('p_prun_X') === null);
await settle(30);
check('U18c. сводка блока показывает human-статус без raw-кодов на первом уровне; raw state виден '
      + 'ТОЛЬКО в раскрытых тех.подробностях',
      blockOfName('Проект B').textContent.includes('Приостановлен')
      && blockOfName('Проект B').querySelector('.wpx-tech').textContent.includes('paused')
      && !blockOfName('Проект A').querySelector('.wpx-status').textContent.includes('draft'));
window.__api.wpxTechOpen.value = {};

// U19: один глобальный timer
const t1 = window.__api._pollTimer();
await window.__api.loadActiveProjectRuns(false);
await window.__api.loadActiveProjectRuns(false);
await settle(30);
check('U19c. ровно ОДИН глобальный polling timer; повторная инициализация второго не создаёт',
      !!t1 && window.__api._pollTimer() === t1);

// U20: без перекрытия тиков; временная ошибка не стирает snapshot
window.__DELAY = 150;
reset();
const tickA = pollOnce(), tickB = pollOnce();
await Promise.all([tickA, tickB]);
check('U20a. перекрывающиеся тики запрещены: второй вызов во время in-flight не делает запрос',
      calls(/project-runs\?active=1/).length === 1);
window.__DELAY = 0;
window.__LIST_FAIL = true;
await pollOnce(); await settle(30);
check('U20b. временная ошибка НЕ стирает последний хороший snapshot; блоки живы',
      blocks().length === 3 && !!window.__api.projectRunsListError.value);
window.__LIST_FAIL = false;
await pollOnce(); await settle(30);
check('U20c. успешный тик гасит временную ошибку', !window.__api.projectRunsListError.value);
window.__api.stopProjectRunsPolling();
check('U20d. stop очищает timer и controller (abort при unmount)', window.__api._pollTimer() === null);
await window.__api.loadActiveProjectRuns(false); await settle(30);

// U21: pause/resume — кнопки в блоке СВОЕГО проекта
reset();
const btnIn = (name, txt) => [...blockOfName(name).querySelectorAll('.pw-btn')].find(b => b.textContent.includes(txt));
btnIn('Проект A', 'Приостановить план').click();
btnIn('Проект A', 'Приостановить план').click();          // второй клик во время запроса
await settle(120);
check('U21a. «Приостановить план» -> РОВНО один POST /pause, двойной клик защищён',
      calls(/prun_A\/pause$/, 'POST').length === 1 && calls(/\/resume$/, 'POST').length === 0);
reset();
btnIn('Проект B', 'Продолжить план').click();
await settle(120);
check('U21b. «Продолжить план» -> РОВНО один POST /resume у ДРУГОГО run (соседний остаётся интерактивным)',
      calls(/prun_B\/resume$/, 'POST').length === 1 && calls(/\/pause$/, 'POST').length === 0);
check('U21c. подписи говорят о ПЛАНЕ, а не о печати',
      blockOfName('Проект A').textContent.includes('Приостановить план')
      && !blockOfName('Проект A').textContent.includes('Приостановить печать'));

// U22: cancel
reset();
btnIn('Проект A', 'Отменить план').click();
await settle(60);
check('U22a. открытие confirm НЕ шлёт POST и это styled-слой (не native confirm)',
      !!$('.pr-confirm') && window.__CALLS.filter(c => c.m === 'POST').length === 0
      && document.body.textContent.includes('не отправит команду остановки принтерам'));
window.__esc[window.__esc.length - 1]();                 // Escape закрывает верхний слой
await settle(40);
check('U22b. Escape закрывает confirm и НЕ шлёт POST',
      !$('.pr-confirm') && window.__CALLS.filter(c => c.m === 'POST').length === 0);
btnIn('Проект A', 'Отменить план').click(); await settle(40);
[...document.querySelectorAll('.pr-confirm .pw-btn')].find(b => b.textContent.trim() === 'Отмена').click();
await settle(40);
check('U22c. отказ в confirm -> 0 POST', window.__CALLS.filter(c => c.m === 'POST').length === 0);
btnIn('Проект A', 'Отменить план').click(); await settle(40);
reset();
// Alpha 2.763: правда сервера главнее локальной памяти, поэтому фикстура обязана вести себя как
// НАСТОЯЩИЙ сервер: после успешной отмены НЕ-владеющего плана список ?active=1 его больше не
// возвращает (2.761 вернул бы его только пока деталь удерживает принтер).
window.__ACTIVE = { status: 'ok', runs: window.__ACTIVE.runs.filter((r) => r.run_id !== 'prun_A') };
[...document.querySelectorAll('.pr-confirm .pw-btn.primary')].find(b => b.textContent.includes('Отменить план')).click();
await settle(150);
check('U22d. подтверждение -> РОВНО один POST /cancel и НИ ОДНОЙ команды остановки принтеру',
      calls(/prun_A\/cancel$/, 'POST').length === 1 && window.__BOOM.length === 0
      && calls(/\/api\/printer\//).length === 0);
// Alpha 2.760: отменённый план ОБЯЗАН уйти с экрана сразу. Раньше он возвращался в снимок как
// «Отменён» и висел там навсегда: опрос при нуле активных останавливается, поэтому сам он уже не
// обновлялся, а wpxRunFor его отдавал — и «Печатать весь проект» не считал новый план. Владельцу
// помогала только перезагрузка страницы (F5). Проверяем и снимок, и то, что план больше не «текущий».
check('U22e. КРИТИЧНО: отменённый план УБРАН из проекта сразу (не висит «Отменён» до перезагрузки)',
      !window.__api.projectRunsById.value['prun_A']
      && !window.__api.projectRunOrder.value.includes('prun_A')
      && window.__api.wpxRunFor('p_prun_A') === null);
// И терминальный план не должен блокировать НОВЫЙ расчёт: «Печатать весь проект» на завершённом
// проекте обязан открыть расчёт нового плана, а не показывать старый бесконечно.
window.__api.projectRunsById.value = Object.assign({}, window.__api.projectRunsById.value,
  { prun_C: mkRun('prun_C', 'Проект C', 'completed', 'exact') });
window.__api.projectRunOrder.value = [...window.__api.projectRunOrder.value, 'prun_C'];
window.__api.wpxOpenMap.value = {};                       // блок закрыт: следующий клик — открытие
await settle(30);
check('U22f. предусловие: завершённый план виден как текущий',
      window.__api.wpxRunFor('p_prun_C') && window.__api.wpxRunFor('p_prun_C').state === 'completed');
window.__api.toggleWholePrint({ id: 'p_prun_C', name: 'Проект C' });
await settle(60);
check('U22g. КРИТИЧНО: «Печатать весь проект» на ЗАВЕРШЁННОМ плане убирает его и не залипает',
      !window.__api.projectRunsById.value['prun_C'] && window.__api.wpxRunFor('p_prun_C') === null);
window.__api.projectRunOrder.value = window.__api.projectRunOrder.value.filter(x => x !== 'prun_C');
window.__api.closeProjectWholePreflight(); window.__api.wpxOpenMap.value = {};
await settle(20);
// Alpha 2.761: ОБРАТНАЯ сторона уборки. План с НЕРАЗРЕШЁННОЙ ambiguous-деталью ВСЁ ЕЩЁ удерживает
// принтер — убирать его с экрана нельзя ни при отмене, ни по «Печатать весь проект»: иначе оператору
// негде нажать «Печать началась/не начиналась», принтер заблокирован навсегда и НИ ОДИН новый проект
// не стартует (ровно эта ловушка поймана на живой ферме).
window.__api.projectRunsById.value = Object.assign({}, window.__api.projectRunsById.value,
  { prun_D: Object.assign(mkRun('prun_D', 'Проект D', 'cancelled', 'exact'),
      { items: [{ item_id: 'itD', seq: 1, state: 'ambiguous_after_dispatch', assigned_printer_id: 'pr1' }] }) });
window.__api.projectRunOrder.value = [...window.__api.projectRunOrder.value, 'prun_D'];
window.__api.wpxOpenMap.value = {};
await settle(30);
window.__api.toggleWholePrint({ id: 'p_prun_D', name: 'Проект D' });
await settle(60);
check('U22h. КРИТИЧНО: отменённый план с НЕРАЗРЕШЁННОЙ ambiguous-деталью НЕ убирается с экрана',
      !!window.__api.projectRunsById.value['prun_D']
      && window.__api.wpxRunFor('p_prun_D') && window.__api.wpxRunFor('p_prun_D').run_id === 'prun_D');
window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
window.__api.closeProjectWholePreflight(); window.__api.wpxOpenMap.value = {};
await settle(20);

// ── U24 (Alpha 2.763): ПОЛНАЯ история с живой фермы — отмена плана с НЕРАЗРЕШЁННОЙ деталью ──
// Раньше: клиентский фильтр «отменённый локально назад не воскрешаем» замораживал до-отменочный
// снимок навсегда (сервер уже показывал cancelled + неразрешённую деталь, а экран — старое
// состояние с кнопкой «Отменить план», на которую сервер отвечал 409 bad_state), опрос
// останавливался, результат разрешения не доезжал, «Печатать весь проект» не считал новый план.
// Выручала только перезагрузка страницы. Теперь правда сервера главнее локальной памяти.
const ambE = itm('itE', 'ambiguous_after_dispatch', 'pr1', 'pjob_E');
window.__setWpxProjects([{ id: 'p_prun_E', name: 'Проект E' }]);
window.__ACTIVE = { status: 'ok', runs: [mkRun('prun_E', 'Проект E', 'attention_required', 'exact')] };
window.__DETAIL = { prun_E: mkDetail('prun_E', 'attention_required', [ambE], [prn2('pr1', 'X1C-01', 'IDLE', true)]) };
await pollOnce(); await settle(60);
check('U24a. предусловие: план с неоднозначной деталью показан, «Отменить план» доступна',
      !!btnIn('Проект E', 'Отменить план'));
reset();
btnIn('Проект E', 'Отменить план').click(); await settle(40);
[...document.querySelectorAll('.pr-confirm .pw-btn.primary')].find(b => b.textContent.includes('Отменить план')).click();
await settle(150);
// Сервер (2.761) продолжает возвращать отменённый план, пока деталь не разрешена.
window.__ACTIVE = { status: 'ok', runs: [mkRun('prun_E', 'Проект E', 'cancelled', 'exact')] };
window.__DETAIL = { prun_E: mkDetail('prun_E', 'cancelled', [ambE], [prn2('pr1', 'X1C-01', 'IDLE', true)]) };
await pollOnce(); await settle(60);
check('U24b. КРИТИЧНО: после отмены экран показывает СВЕЖУЮ правду сервера (cancelled), а не замороженный снимок',
      !!window.__api.projectRunsById.value['prun_E']
      && window.__api.projectRunsById.value['prun_E'].state === 'cancelled');
check('U24c. КРИТИЧНО: кнопки «Отменить план» больше НЕТ (повторная отмена дала бы 409 bad_state)',
      !btnIn('Проект E', 'Отменить план'));
check('U24d. КРИТИЧНО: кнопки разрешения неоднозначности ДОСТУПНЫ (Печать началась / не начиналась)',
      [...blockOfName('Проект E').querySelectorAll('.wpx-it-amb .pw-btn')].length === 2);
check('U24e. КРИТИЧНО: опрос ПРОДОЛЖАЕТСЯ (иначе результат разрешения никогда не доехал бы до экрана)',
      !!window.__api._pollTimer());
// Оператор разрешил «не начиналась» -> сервер снял удержание и перестал возвращать план. Снимок у
// клиента ещё «владеющий» (устарел) — он обязан УЙТИ с экрана, а не залипнуть навсегда.
window.__ACTIVE = { status: 'ok', runs: [] };
await pollOnce(); await settle(60);
check('U24f. КРИТИЧНО: устаревший «владеющий» снимок, который сервер уже не возвращает, УБРАН с экрана',
      !window.__api.projectRunsById.value['prun_E']);
reset();
window.__api.toggleWholePrint({ id: 'p_prun_E', name: 'Проект E' });
await settle(80);
check('U24g. «Печатать весь проект» после развязки сразу считает НОВЫЙ план',
      calls(/whole-print\/preflight/).length === 1);
window.__api.closeProjectWholePreflight(); window.__api.wpxOpenMap.value = {};
window.__ACTIVE = { status: 'ok', runs: [] }; window.__DETAIL = {};
window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
window.__setWpxProjects([{ id: 'p_prun_A', name: 'Проект A' }, { id: 'p_prun_B', name: 'Проект B' },
                         { id: 'p_prun_C', name: 'Проект C' }, { id: 'p_prun_X', name: 'Посторонний' }]);
await settle(20);

// U23: terminal перестаёт опрашиваться; закрытый блок опрос НЕ останавливает
window.__ACTIVE = { status: 'ok', runs: [mkRun('prun_B', 'Проект B', 'paused', 'approximate')] };
await pollOnce(); await settle(40);
check('U23a. отменённый run не воскресает из ?active=1 и больше не опрашивается',
      !window.__api.projectRunsById.value['prun_A'] || window.__api.projectRunsById.value['prun_A'].state === 'cancelled');
window.__api.wpxOpenMap.value = { p_prun_B: false };     // блок закрыт пользователем
await settle(20);
reset();
await pollOnce(); await settle(30);
check('U23b. ЗАКРЫТЫЙ встроенный блок ПРОДОЛЖАЕТ опрашивать активные runs (данные не протухают)',
      calls(/project-runs\?active=1/).length === 1 && !!window.__api._pollTimer());
window.__api.wpxOpenMap.value = {};
window.__ACTIVE = { status: 'ok', runs: [] };
window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
await window.__api.loadActiveProjectRuns(false); await settle(40);
check('U23c. активных runs не осталось -> timer очищен, встроенных блоков нет',
      window.__api._pollTimer() === null && blocks().length === 0);

check('U23d. за ВЕСЬ сценарий B1: 0 запросов /start и 0 печатных вызовов',
      window.__BOOM.length === 0 && window.__CALLS.filter(c => /\/start/.test(c.u)).length === 0);


// ══ U24-U32: «Стол очищен», отзыв, ambiguity, индикатор waiting_plate_clear (UI-фаза B2) ══
// Фикстура связывает run -> item(waiting_plate_clear) -> assigned_printer_id — ровно так, как это
// делает backend. Фиктивных production-переходов не создаём: в dry-run это состояние возникает
// только у стадии 5, поэтому проверяем его фикстурой.
const D_ID = 'prun_W';
const setRun = async (items, printers, state) => {
  window.__setWpxProjects([{ id: 'prj', name: 'Тестовый проект' }, { id: 'p_prun_W', name: 'Проект W' }]);
  window.__api.wpxOpenMap.value = {};
  window.__ACTIVE = { status: 'ok', runs: [mkRun(D_ID, 'Проект W', state || 'draft', 'exact')] };
  window.__DETAIL[D_ID] = mkDetail(D_ID, state || 'draft', items, printers);
  window.__api.stopProjectRunsPolling();
  window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
  await window.__api.loadActiveProjectRuns(false);
  await settle(60);
};
const clrBtn = () => [...document.querySelectorAll('.pr-clr-a .pw-btn')].find(b => b.textContent.includes('Стол очищен'));
const revBtn = () => [...document.querySelectorAll('.wpx-weak, .pr-clr-a .pw-btn')].find(b => b.textContent.includes('Отозвать'));
const clrTxt = () => { const e = document.querySelector('.wpx-clr-ok .pr-st, .wpx-it-clr .pr-st'); return e ? e.textContent.trim() : ''; };
const cfWin = () => document.querySelector('.pr-confirm');

// ── U24: без подтверждения — ни одного POST ──
await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
             [prn2('pr1', 'X1C-01', 'IDLE', true, null, null)]);
reset();
check('U24a. кнопка «Стол очищен» есть и активна: связка run->item->pr1 в waiting_plate_clear',
      !!clrBtn() && clrBtn().disabled === false);
clrBtn().click();
await settle(60);
check('U24. клик открыл styled confirm и НЕ отправил НИ ОДНОГО POST (подтверждает человек)',
      !!cfWin() && window.__CALLS.filter(c => c.m === 'POST').length === 0
      && cfWin().textContent.includes('физически пуст')
      && cfWin().textContent.includes('IDLE и FINISH пустой стол не доказывают'));
// Escape внутри confirm: закрывает только confirm, 0 POST, focus возвращается
const escFn = window.__esc[window.__esc.length - 1];
escFn();
await settle(60);
check('U24b. Escape закрыл ТОЛЬКО confirm: панель жива, 0 POST, focus вернулся на кнопку действия',
      !cfWin() && !!win() && window.__CALLS.filter(c => c.m === 'POST').length === 0
      && document.activeElement === clrBtn());

// ── U25: после подтверждения — один POST с confirmed:true и точным finished_job_id ──
reset();
clrBtn().click(); await settle(40);
await window.__api.confirmCancelProjectRun(); await settle(80);
const pc = calls(/\/plate-clear$/, 'POST');
check('U25. после подтверждения — РОВНО один POST plate-clear c confirmed:true и ТОЧНЫМ '
      + 'finished_job_id этого item; чужих полей нет',
      pc.length === 1 && /\/project-runs\/prun_W\/printers\/pr1\/plate-clear$/.test(pc[0].u)
      && pc[0].body.confirmed === true && pc[0].body.finished_job_id === 'pjob_1'
      && JSON.stringify(Object.keys(pc[0].body).sort()) === '["confirmed","finished_job_id"]');

// ── U26: revoke ──
await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
             [prn2('pr1', 'X1C-01', 'IDLE', true, clr('active'), clr('active'))]);
check('U26a. 2.754: при ДЕЙСТВУЮЩЕМ токене — ОДИН компактный статус «Стол подтверждён пустым», '
      + 'кнопки «Стол очищен» НЕТ вовсе, «уже действует» не показывается, отзыв — слабое действие',
      clrTxt().includes('Стол подтверждён пустым') && !clrBtn() && !!revBtn()
      && !document.querySelector('.wpx').textContent.includes('Подтверждение уже действует'));
reset();
revBtn().click(); await settle(80);
const rv = calls(/\/plate-clear\/revoke$/, 'POST');
check('U26. revoke -> РОВНО один правильный POST без тела', rv.length === 1
      && /\/project-runs\/prun_W\/printers\/pr1\/plate-clear\/revoke$/.test(rv[0].u) && rv[0].body === null);
reset();
window.__DETAIL_CALLS = 0;
await pollOnce(); await pollOnce(); await settle(60);
check('U26b. polling САМ clearance не создаёт и не отзывает: только GET, ни одного POST',
      window.__CALLS.filter(c => c.m === 'POST').length === 0 && window.__DETAIL_CALLS >= 1);

// ── U27: offline/stale/RUNNING/PREPARE/чужой принтер ──
for (const [st, fresh, why] of [['IDLE', false, 'Нет свежей телеметрии'], ['RUNNING', true, 'Принтер занят: RUNNING'],
                                ['PREPARE', true, 'Принтер занят: PREPARE']]) {
  await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')], [prn2('pr1', 'X1C-01', st, fresh, null, null)]);
  reset();
  const b = clrBtn();
  if (b) b.click();
  await settle(40);
  check('U27.' + st + (fresh ? '' : '/stale') + ' кнопка clearance НЕ активна и причина названа; клик -> 0 POST',
        !!b && b.disabled === true && win().textContent.includes(why)
        && window.__CALLS.filter(c => c.m === 'POST').length === 0 && !cfWin());
}
// принтер, которым run не пользуется: цели нет вообще
await setRun([itm('it1', 'pending', '', '')],
             [prn2('pr9', 'Чужой', 'IDLE', true, null, null)]);
check('U27.unused. принтер, не связанный с item этого run, кнопки clearance НЕ получает '
      + '(IDLE сам по себе цели не создаёт)',
      !clrBtn() && document.querySelectorAll('.wpx-it-clr').length === 0
      && window.__api.projectRunClearanceTargets(window.__api.projectRunsById.value[D_ID]).length === 0);

// ── U28: история токена показана честно ──
const cases = [[null, null, 'Подтверждение ещё не создавалось'],
               [clr('consumed'), 'Подтверждение использовано'],
               [clr('revoked', 'user_revoked'), 'Подтверждение отозвано'],
               [clr('invalidated', 'server_restart'), 'Подтверждение недействительно после перезапуска сервера']];
for (const c of cases) {
  const last = c.length === 3 ? c[1] : c[0], want = c[c.length - 1];
  await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
               [prn2('pr1', 'X1C-01', 'IDLE', true, null, last)]);
  check('U28. ' + (last ? last.status + (last.invalid_reason ? '/' + last.invalid_reason : '') : 'токена не было')
        + ' -> «' + want + '»; действующим разрешением НЕ считается; новая кнопка НЕ заблокирована',
        clrTxt() === want && !!clrBtn() && clrBtn().disabled === false
        && window.__api.projectRunsById.value[D_ID].printers[0].clearance === null);
}
check('U28b. активный токен приходит ОДНОВРЕМЕННО в clearance и last_clearance -> «Стол подтверждён», '
      + 'а не generic-успех',
      (await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
                    [prn2('pr1', 'X1C-01', 'IDLE', true, clr('active'), clr('active'))]),
       clrTxt().includes('Стол подтверждён пустым') && !win().textContent.includes('Подтверждение ещё не создавалось')));

// ── U29/U30: ambiguous ──
await setRun([Object.assign(itm('it2', 'ambiguous_after_dispatch', 'pr1', 'pjob_1'),
                            { last_error: 'dispatch_may_have_happened' })],
             [prn2('pr1', 'X1C-01', 'IDLE', true, null, null)]);
const ambBtns = () => [...document.querySelectorAll('.wpx-it-amb .pw-btn')];
check('U29. ambiguous -> РОВНО две кнопки «Печать началась»/«Печать не начиналась»; кнопки повтора НЕТ; '
      + 'причина показана',
      ambBtns().length === 2 && ambBtns()[0].textContent.includes('Печать началась')
      && ambBtns()[1].textContent.includes('Печать не начиналась')
      && !document.querySelector('.wpx-it-amb').textContent.match(/Повторить/i)
      && document.querySelector('.wpx-it-amb').textContent.includes('dispatch_may_have_happened')
      && document.querySelector('.wpx-it-amb').textContent.includes('Автоматический повтор запрещён'));
reset();
ambBtns()[1].click(); await settle(40);
check('U30a. resolve тоже за confirm: до подтверждения 0 POST',
      !!cfWin() && window.__CALLS.filter(c => c.m === 'POST').length === 0);
await window.__api.confirmCancelProjectRun(); await settle(80);
const rs = calls(/\/resolve$/, 'POST');
check('U30. resolve -> один POST с ТОЧНЫМ телом { resolution: "not_started" } по адресу item',
      rs.length === 1 && /\/project-runs\/prun_W\/items\/it2\/resolve$/.test(rs[0].u)
      && JSON.stringify(rs[0].body) === '{"resolution":"not_started"}');
// backend-ошибка обязана остаться в карточке и не подменяться успехом
window.__RESOLVE_409 = true;
reset();
ambBtns()[0].click(); await settle(40);
await window.__api.confirmCancelProjectRun(); await settle(90);
check('U30b. отказ backend (no_project_print_job_to_confirm) показан В КАРТОЧКЕ и НЕ подменён успехом',
      window.__api.projectRunErrors.value[D_ID] === 'no_project_print_job_to_confirm'
      && document.querySelector('.wpx').textContent.includes('no_project_print_job_to_confirm'));
window.__RESOLVE_409 = false;

// ── U31: индикатор на карточке принтера ──
await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
             [prn2('pr1', 'X1C-01', 'IDLE', true, null, null)]);
window.__setPrinters([{ id: 'pr1', name: 'X1C-01' }, { id: 'pr2', name: 'P1S-02' }]);
await settle(40);
const wpcCard = (i) => document.querySelectorAll('#tp .tp-card')[i];
check('U31. индикатор ТОЛЬКО на назначенной карточке (pr1), ровно ОДИН; у pr2 его нет',
      wpcCard(0).querySelectorAll('.pc-wpc').length === 1
      && wpcCard(1).querySelectorAll('.pc-wpc').length === 0
      && document.querySelectorAll('#tp .pc-wpc').length === 1);
check('U31b. клик по индикатору только фокусирует план: 0 POST, раскрыт ПРОЕКТ этого run и его блок',
      (reset(), wpcCard(0).querySelector('.pc-wpc').click(),
       window.__CALLS.filter(c => c.m === 'POST').length === 0
       && window.__api.highlightedRunId.value === D_ID
       && window.__api.project2Expanded.value === 'p_prun_W'
       && window.__api.wpxOpenMap.value['p_prun_W'] === true));
await setRun([itm('it1', 'pending', '', '')], [prn2('pr1', 'X1C-01', 'IDLE', true, null, null)]);
await settle(40);
check('U31c. общий IDLE/FINISH без связи с run индикатора НЕ создаёт',
      document.querySelectorAll('#tp .pc-wpc').length === 0);
await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1')],
             [prn2('pr1', 'X1C-01', 'IDLE', true, null, null)], 'cancelled');
await settle(40);
check('U31d. у отменённого плана индикатора и кнопок нет',
      document.querySelectorAll('#tp .pc-wpc').length === 0 && !clrBtn());

// ── U33: ПЕРВИЧНОЕ «Стол очищен» до первой печати (Alpha 2.752) ──
// Раньше цель существовала только для waiting_plate_clear + assigned_printer_id, и подтвердить
// пустой стол ПЕРЕД первой печатью было нечем. Теперь pending/eligible item с СОХРАНЁННЫМ
// ready-планом даёт цель на ТОЧНОМ принтере плана (feed_plan.printer_id).
const readyFp = (pid) => ({ version: 1, status: 'ready', effective_status: 'ready', reason: '',
  printer_id: pid || 'pr1', transport: 'flashforge', filament_count: 1, ams_slot: -1,
  mode: 'external', spool_id: '', inventory_bound: false, required_material: 'PETG',
  required_color: '#161616', inventory_material: null, inventory_color: null,
  reported_material: null, reported_color: null, color_distance: null, color_relation: 'unknown',
  verification: 'manual_external', required_approval_reasons: [], approved_reasons: [],
  requires_approval: false, approval: null, approval_valid: false, fingerprint: 'fp_first',
  file_hash: 'h1' });
await setRun([itm('it1', 'pending', '', '', readyFp('pr1'))],
             [prn2('pr1', 'FF-5M', 'IDLE', true, null, null)]);
reset();
check('U33a. КРИТИЧНО: первичная цель ЕСТЬ для pending + ready-плана; кнопка «Стол очищен» активна '
      + 'и показан текст про первую печать',
      !!clrBtn() && !clrBtn().disabled
      && document.body.textContent.includes('Перед первой печатью физически проверьте, что стол пуст'));
clrBtn().click(); await settle(30);
check('U33b. клик открыл confirm с текстом про первую печать, POST ещё нет',
      !!cfWin() && window.__CALLS.filter(c => c.m === 'POST').length === 0);
await window.__api.confirmCancelProjectRun(); await settle(80);
const _u33 = calls(/\/plate-clear$/, 'POST');
check('U33c. КРИТИЧНО: подтверждение -> РОВНО один POST plate-clear на принтер ПЛАНА с '
      + 'confirmed:true и ПУСТЫМ finished_job_id (первичный токен)',
      _u33.length === 1 && /printers\/pr1\/plate-clear$/.test(_u33[0].u)
      && _u33[0].body.confirmed === true && _u33[0].body.finished_job_id === ''
      && JSON.stringify(Object.keys(_u33[0].body).sort()) === '["confirmed","finished_job_id"]');
await setRun([itm('it1', 'pending', '', '', readyFp('pr1'))],
             [prn2('pr1', 'FF-5M', 'FINISH', true, null, null)]);
reset();
check('U33d. КРИТИЧНО: не safe_idle (FINISH) -> первичная кнопка ЗАБЛОКИРОВАНА и причина названа точно',
      !!clrBtn() && clrBtn().disabled === true
      && document.body.textContent.includes('Принтер не в безопасном простое: not_idle_raw:FINISH'));
await setRun([itm('it1', 'pending', '', '', readyFp('pr1'))],
             [prn2('pr1', 'FF-5M', 'IDLE', false, null, null)]);
check('U33e. stale телеметрия -> первичная кнопка заблокирована («Нет свежей телеметрии»)',
      !!clrBtn() && clrBtn().disabled === true
      && document.body.textContent.includes('Нет свежей телеметрии'));
await setRun([itm('it1', 'pending', '', '', Object.assign(readyFp('pr1'),
               { status: 'approval_required', effective_status: 'approval_required' }))],
             [prn2('pr1', 'FF-5M', 'IDLE', true, null, null)]);
check('U33f. план НЕ ready -> первичной цели НЕТ вовсе', !clrBtn());
await setRun([itm('it1', 'waiting_plate_clear', 'pr1', 'pjob_1'),
              itm('it2', 'pending', '', '', readyFp('pr1'))],
             [prn2('pr1', 'FF-5M', 'FINISH', true, null, null)]);
check('U33g. КРИТИЧНО: постпечатная цель СИЛЬНЕЕ первичной на том же принтере: цель одна, '
      + 'FINISH её НЕ блокирует (safe_idle для постпечатной не требуется)',
      document.querySelectorAll('.wpx-it-clr').length === 1 && !!clrBtn() && clrBtn().disabled === false);
await setRun([itm('it1', 'pending', '', '', readyFp('pr2'))],
             [prn2('pr1', 'FF-5M', 'IDLE', true, null, null), prn2('pr2', 'FF-5M-2', 'IDLE', true, null, null)]);
reset();
clrBtn().click(); await settle(30);
await window.__api.confirmCancelProjectRun(); await settle(80);
const _u33h = calls(/\/plate-clear$/, 'POST');
check('U33h. КРИТИЧНО: цель строится ИМЕННО по feed_plan.printer_id (pr2), а не по первому принтеру',
      _u33h.length === 1 && /printers\/pr2\/plate-clear$/.test(_u33h[0].u));
await setRun([itm('it1', 'pending', '', '', readyFp('pr1')), itm('it2', 'eligible', '', '', readyFp('pr1'))],
             [prn2('pr1', 'FF-5M', 'IDLE', true, null, null)]);
check('U33i. два item с планом на ОДИН принтер -> кнопка всё равно ОДНА (одна цель на принтер)',
      document.querySelectorAll('.wpx-it-clr').length === 1);

// ── U32: инварианты безопасности за ВЕСЬ сценарий ══
check('U32. за весь сценарий B2: 0 запросов /start, 0 печатных/send/MQTT/FTP вызовов',
      window.__BOOM.length === 0 && window.__CALLS.filter(c => /\/start\b/.test(c.u)).length === 0
      && window.__CALLS.filter(c => /files\/[^/]+\/print|upload_print|print_path|mqtt|ftp/i.test(c.u)).length === 0);
check('U32b. существующая печать одного файла проекта не тронута (её путь в app.js цел)',
      /\/files\/'\s*\+\s*[^;]*\+\s*'\/print'/.test(APPJS) || APPJS.includes("/print'"));
await open('exact');
check('U32c. 2.753: мёртвой кнопки автозапуска нет нигде; плашка проверочного режима — не кнопка '
      + 'и без обработчика',
      !INDEX.includes('pw-dead') && !document.querySelector('.pw-btn.pw-dead')
      && !/wpx-mode[^>]*@click/.test(INDEX));
window.__api.closeProjectWholePreflight();


// ══ U34: PRODUCTION-SHAPED сценарий актуального скриншота 2.753 ══
// Один настоящий принтер FFA5M-1; деталь Cube, нужно 3; три ОДИНАКОВЫХ последовательных запуска;
// PETG external подтверждён; clearance active; one-shot transport НЕ вооружён.
const cubeFp = () => Object.assign({}, readyFp('pr1'));
const cubeItm = (n, state, pid, job) => Object.assign(
  itm('pitem_c' + n, state, pid || '', job || '', cubeFp()),
  { item_id: 'pitem_c' + n, seq: n, file_id: 'pfile_df5d98938d22', filename: 'Cube_1h50m.gcode.3mf',
    planned_parts: { ppart_cube: 1 } });
const cubeRun = async (states, opts) => {
  const o = opts || {};
  const items = states.map((st, i) => cubeItm(i + 1, st.s, st.p, st.j));
  window.__setWpxProjects([{ id: 'p_prun_W', name: '123' }]);
  window.__api.wpxOpenMap.value = {};
  window.__api.wpxQueueOpen.value = {}; window.__api.wpxTechOpen.value = {}; window.__api.wpxMatMenu.value = {};
  window.__ACTIVE = { status: 'ok', runs: [mkRun(D_ID, '123', o.state || 'draft', 'exact')] };
  const det = mkDetail(D_ID, o.state || 'draft', items,
    [prn2('pr1', 'FFA5M-1', o.pStatus || 'IDLE', true, o.clr ? clr('active') : null, o.clr ? clr('active') : null)],
    { ppart_cube: 'Cube' });
  det.counts = o.counts || {};
  window.__DETAIL[D_ID] = det;
  window.__api.stopProjectRunsPolling();
  window.__api.projectRunsById.value = {}; window.__api.projectRunOrder.value = [];
  await window.__api.loadActiveProjectRuns(false);
  await settle(60);
};
const W = () => win().textContent;

// актуальное состояние скриншота: три pending, clearance active, arm off
await cubeRun([{ s: 'pending' }, { s: 'pending' }, { s: 'pending' }], { clr: true });
check('U34a. КРИТИЧНО: подробно показан ТОЛЬКО запуск 1 из 3 (одна карточка, не три одинаковых)',
      document.querySelectorAll('.wpx-it').length === 1
      && /Сейчас: запуск\s*1\s*из\s*3/.test(W()) && W().includes('Cube × 1'));
check('U34b. запуски 2 и 3 объединены в компактную очередь «ещё 2 запуска»',
      !!document.querySelector('.wpx-q') && /В очереди: ещё\s*2/.test(W()));
window.__api.wpxToggleQueue('p_prun_W'); await settle(30);
check('U34c. КРИТИЧНО: раскрытая очередь — «после завершения предыдущего», БЕЗ «Готов к запуску» '
      + 'и без кнопок',
      document.querySelectorAll('.wpx-q-r').length === 2
      && /Запуск 2/.test(W()) && /после завершения запуска\s*1/.test(W())
      && /Запуск 3/.test(W()) && /после завершения запуска\s*2/.test(W())
      && ![...document.querySelectorAll('.wpx-q-r')].some((e) => /Готов/.test(e.textContent))
      && document.querySelectorAll('.wpx-q-r button').length === 0);   // toggle-кнопка очереди — не действие запуска
check('U34d. PETG · внешняя катушка показан РОВНО один раз (материал серии, не три повтора)',
      (W().match(/PETG/g) || []).length === 1 && (W().match(/внешняя катушка/g) || []).length === 1);
check('U34e. КРИТИЧНО: pfile_/pitem_/run_id/fingerprint НЕ видны на первом уровне; техподробности '
      + 'закрыты, но доступны',
      !/pfile_|pitem_|prun_|fp_/.test(W())
      && (window.__api.wpxToggleTech('p_prun_W'), 0) === 0);
await settle(30);
check('U34e2. в раскрытых техподробностях raw-идентификаторы ЕСТЬ',
      /pfile_df5d98938d22/.test(W()) && /pitem_c1/.test(W()) && /prun_W/.test(W()));
window.__api.wpxToggleTech('p_prun_W'); await settle(30);
check('U34f. КРИТИЧНО: clearance — ОДИН статус «Стол подтверждён пустым»; кнопки «Стол очищен» НЕТ; '
      + '«Подтверждение уже действует» НЕТ; «Отозвать» — слабое действие',
      (W().match(/Стол подтверждён пустым/g) || []).length === 1
      && !clrBtn() && !W().includes('Подтверждение уже действует') && !!revBtn());
check('U34g. КРИТИЧНО: печать из приложения выключена -> НЕТ кнопки запуска; есть кнопка ВКЛЮЧЕНИЯ '
      + '(2.757) и честный статус «включите печать из приложения»',
      ![...win().querySelectorAll('button')].some(b => /Запустить печать|Контрольный запуск одной печати/.test(b.textContent))
      && W().includes('План готов · включите печать из приложения')
      && W().includes('Запуск печати из приложения выключен')
      && !!([...win().querySelectorAll('button')].find(b => /Включить запуск печати/.test(b.textContent)))
      // ложной кнопки СТАРТА (danger, или primary «Запустить») нет
      && document.querySelectorAll('.wpx-cur .pw-btn.primary, .wpx-cur .pw-btn.danger').length === 0);
check('U34h. счётчики не смешаны: Нужно 3 · Готово 0 · Осталось 3 · Текущий запуск 1 из 3 · принтер один',
      /Нужно:\s*3/.test(W()) && /Готово:\s*0/.test(W()) && /Осталось:\s*3/.test(W())
      && /Текущий запуск:\s*1\s*из\s*3/.test(W()) && /Принтер:\s*FFA5M-1/.test(W()));

// ── U35 (Alpha 2.757): печать ИЗ ПРИЛОЖЕНИЯ включена -> простой запуск одной кнопкой ──
window.__api.armStatus.value = { status: 'ok', dispatch_enabled: true, transport_enabled: true,
  print_enabled: true, armed: false, consumed: false, expires_in_s: 0, scope: null, error: '' };
await settle(40);
check('U35a. КРИТИЧНО: печать из приложения включена + стол подтверждён + принтер safe_idle -> '
      + 'РОВНО одна кнопка «Запустить печать» у текущего запуска; статус «Готов к запуску»',
      window.__api.printEnabled.value === true
      && window.__api.canStartInApp(window.__api.wpxRunFor('p_prun_W'), window.__api.wpxCurrentItem(window.__api.wpxRunFor('p_prun_W'))) === true
      && [...win().querySelectorAll('button')].filter(b => /^\s*Запустить печать\s*$/.test(b.textContent)).length === 1
      && !!document.querySelector('.wpx-cur .pw-btn.primary')
      && !W().includes('Запуск печати из приложения выключен')
      && W().includes('Готов к запуску'));
reset();
// Клик открывает ОДНО подтверждение (не четыре галочки). Сам POST /start здесь НЕ шлём (в этом
// харнессе /start — bomb, инвариант «0 /start»): фактическую отправку проверяет feed-харнесс (B8-in-app).
check('U35b. КРИТИЧНО: клик по «Запустить печать» -> открыто ОДНО подтверждение (не четыре галочки), 0 POST',
      (() => { const b = [...win().querySelectorAll('button')].find(x => /^\s*Запустить печать\s*$/.test(x.textContent));
               b.click(); return window.__api.inAppConfirm.open === true
                 && win().querySelectorAll('.cs-chk').length === 0
                 && window.__CALLS.filter(c => /\/start/.test(c.u)).length === 0; })());
window.__api.closeInAppStartConfirm(); await settle(20);
// выключение печати из приложения (в техподробностях)
window.__api.wpxTechOpen.value = { p_prun_W: true }; await settle(20);
check('U35e. в техподробностях есть выключатель печати из приложения',
      !!([...win().querySelectorAll('.wpx-tech button')].find(b => /Выключить запуск печати/.test(b.textContent))));
window.__api.wpxTechOpen.value = {};

// вооружение включено helper-ом (печать из приложения выключена) -> старый путь: одна controlled-start кнопка
window.__api.armStatus.value = { status: 'ok', dispatch_enabled: true, transport_enabled: true,
  print_enabled: false, armed: true, consumed: false, expires_in_s: 800,
  scope: { run_id: D_ID, item_id: 'pitem_c1', printer_id: 'pr1' }, error: '' };
await settle(40);
check('U34i. КРИТИЧНО: CLI-вооружение (печать из приложения off) -> РОВНО одна кнопка «Контрольный '
      + 'запуск одной печати» у текущего запуска; статус «Готов к запуску»',
      [...win().querySelectorAll('button')].filter((b) => /Контрольный запуск/.test(b.textContent)).length === 1
      && document.querySelectorAll('.wpx .pw-btn.danger').length === 1
      && !!document.querySelector('.wpx-cur .pw-btn.danger')
      && W().includes('Готов к запуску'));
window.__api.armStatus.value = null;
await settle(30);

// печать выполняется
await cubeRun([{ s: 'printing', p: 'pr1', j: 'pjob_1' }, { s: 'pending' }, { s: 'pending' }],
              { state: 'running', pStatus: 'RUNNING', counts: { printing: 1, pending: 2 } });
check('U34j. печать: статус «Выполняется», карточка текущего «Печатается», очередь ещё 2, кнопок запуска нет',
      W().includes('Выполняется') && W().includes('Печатается') && /В очереди: ещё\s*2/.test(W())
      && ![...win().querySelectorAll('button')].some((b) => /Контрольный запуск|Стол очищен/.test(b.textContent)));

// запуск 1 завершён -> текущим АВТОМАТИЧЕСКИ становится запуск 2 (в UI, без отправки)
await cubeRun([{ s: 'completed', p: 'pr1', j: 'pjob_1' }, { s: 'pending' }, { s: 'pending' }],
              { state: 'running', counts: { completed: 1, pending: 2 } });
check('U34k. КРИТИЧНО: после completed запуска 1 текущим стал запуск 2; Готово 1; очередь — ещё 1; '
      + 'сам ничего не отправился (0 POST)',
      /Сейчас: запуск\s*2\s*из\s*3/.test(W()) && /Готово:\s*1/.test(W())
      && /В очереди: ещё\s*1/.test(W())
      && window.__CALLS.filter(c => c.m === 'POST').length === 0);

// весь проект завершён
await cubeRun([{ s: 'completed', p: 'pr1', j: 'pjob_1' }, { s: 'completed', p: 'pr1', j: 'pjob_2' },
               { s: 'completed', p: 'pr1', j: 'pjob_3' }],
              { state: 'completed', counts: { completed: 3 } });
check('U34l. проект завершён: статус «Завершён», Готово 3, очереди и карточки текущего нет',
      W().includes('Завершён') && /Готово:\s*3/.test(W())
      && !document.querySelector('.wpx-q') && document.querySelectorAll('.wpx-it').length === 0);

// ── СКРИНШОТ-режим (?shot=<state>): production-shaped сценарий Cube×3 на FFA5M-1 (2.754).
// После прогона выставляем ОДНО состояние и прячем служебный вывод; снимает headless Edge. ──
const SHOT = new URLSearchParams(location.search).get('shot');
if (SHOT) {
  window.__api.closeProjectWholePreflight();
  if (SHOT === 'actual') {          // актуальное состояние скриншота: clearance active, arm off
    await cubeRun([{ s: 'pending' }, { s: 'pending' }, { s: 'pending' }], { clr: true });
  } else if (SHOT === 'armed') {    // helper вооружил -> доступен контрольный запуск
    await cubeRun([{ s: 'pending' }, { s: 'pending' }, { s: 'pending' }], { clr: true });
    window.__api.stopProjectRunsPolling();     // иначе тик перетёр бы вооружение фикстурой статуса
    window.__api.armStatus.value = { status: 'ok', dispatch_enabled: true, transport_enabled: true,
      armed: true, consumed: false, expires_in_s: 840,
      scope: { run_id: D_ID, item_id: 'pitem_c1', printer_id: 'pr1' }, error: '' };
  } else if (SHOT === 'inapp') {     // 2.757: печать из приложения включена -> одна кнопка «Запустить печать»
    await cubeRun([{ s: 'pending' }, { s: 'pending' }, { s: 'pending' }], { clr: true });
    window.__api.stopProjectRunsPolling();     // тик статуса не должен перетереть print_enabled фикстурой
    window.__api.armStatus.value = { status: 'ok', dispatch_enabled: true, transport_enabled: true,
      print_enabled: true, armed: false, consumed: false, expires_in_s: 0, scope: null, error: '' };
  } else if (SHOT === 'inapp_confirm') {   // 2.757: ОДНО подтверждение из приложения (не четыре галочки)
    await cubeRun([{ s: 'pending' }, { s: 'pending' }, { s: 'pending' }], { clr: true });
    window.__api.stopProjectRunsPolling();
    window.__api.armStatus.value = { status: 'ok', dispatch_enabled: true, transport_enabled: true,
      print_enabled: true, armed: false, consumed: false, expires_in_s: 0, scope: null, error: '' };
    await settle(20);
    const _r = window.__api.projectRunsList.value[0];
    window.__api.requestInAppStart(_r, (_r.items || []).find(x => x.state === 'pending'), null);
  } else if (SHOT === 'printing') {
    await cubeRun([{ s: 'printing', p: 'pr1', j: 'pjob_1' }, { s: 'pending' }, { s: 'pending' }],
                  { state: 'running', pStatus: 'RUNNING', counts: { printing: 1, pending: 2 } });
  } else if (SHOT === 'clear') {
    await cubeRun([{ s: 'waiting_plate_clear', p: 'pr1', j: 'pjob_1' }, { s: 'pending' }, { s: 'pending' }],
                  { state: 'waiting_for_plate_clear', pStatus: 'FINISH',
                    counts: { waiting_plate_clear: 1, pending: 2 } });
  } else if (SHOT === 'next') {     // запуск 1 завершён -> текущим стал запуск 2
    await cubeRun([{ s: 'completed', p: 'pr1', j: 'pjob_1' }, { s: 'pending' }, { s: 'pending' }],
                  { state: 'running', counts: { completed: 1, pending: 2 } });
  } else if (SHOT === 'done') {
    await cubeRun([{ s: 'completed', p: 'pr1', j: 'pjob_1' }, { s: 'completed', p: 'pr1', j: 'pjob_2' },
                   { s: 'completed', p: 'pr1', j: 'pjob_3' }],
                  { state: 'completed', counts: { completed: 3 } });
  }
  document.getElementById('out').style.display = 'none';
  const tp = document.getElementById('tp'); if (tp) tp.style.display = 'none';
  document.body.style.padding = '16px';
  const theme = new URLSearchParams(location.search).get('theme');
  if (theme) document.documentElement.setAttribute('data-theme', theme);
  await settle(40);
}

window.__E2E = { ok: checks.every(c => c.ok), checks, log, boom: window.__BOOM };
say(window.__E2E.ok ? '\nВСЁ ПРОЙДЕНО (' + checks.length + ')' : '\nПАДЕНИЯ: ' + checks.filter(c => !c.ok).map(c => c.name).join('; '));
