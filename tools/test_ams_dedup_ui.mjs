// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест фикса «двойного окна выбора AMS» — Alpha 2.729.
// Двойное окно было так: launchPrintSelected («Запустить на печать») для одиночного Bambu-принтера с живым
// AMS открывал СТАРЫЙ picker (amsPick), а он через amsPickSlot → printFileOn/printProject2File (без print_opts)
// открывал ВТОРОЕ окно «Параметры запуска печати» (PrintStartDialog), где источник выбирался повторно.
// Фикс: launchPrintSelected больше НЕ открывает amsPick — одиночный принтер идёт СРАЗУ в PrintStartDialog
// (ветка ids.length===1), и он — единственный источник ams_slot. Проверяем ВЫПОЛНЕНИЕМ ДОСЛОВНО извлечённой
// из web/app.js функции launchPrintSelected (с вложенным _doSend) на реальных Vue-ref, со шпионами на
// openAmsPick / openPrintStart и мок-fetch. Плюс статические инварианты по app.js/index.html/app.css.
// Запуск: node tools/test_ams_dedup_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
const CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── извлечение ДОСЛОВНОГО исходника функции: от якоря до начала следующей декларации ───────────
// (надёжнее подсчёта скобок: в комментариях launchPrintSelected есть скобки/кавычки, которые сбивают баланс).
const sliceFn = (src, startAnchor, endAnchor) => {
  const si = src.indexOf(startAnchor);
  if (si < 0) throw new Error('start anchor not found: ' + startAnchor);
  const ei = src.indexOf(endAnchor, si + startAnchor.length);
  if (ei < 0) throw new Error('end anchor not found: ' + endAnchor);
  return src.slice(si, ei).replace(/\s+$/, '');
};
const SRC_LAUNCH = sliceFn(APPJS, 'const launchPrintSelected = async (ev) => {', '\n    const onPrintBtn = ');

// ═══════════════ СТАТИЧЕСКИЕ ИНВАРИАНТЫ ═══════════════
check('S1. launchPrintSelected НЕ содержит вызова openAmsPick (старый picker убран из Задач/Проектов)',
  !/openAmsPick/.test(SRC_LAUNCH));
check('S2. launchPrintSelected сохраняет единый одиночный путь: ids.length === 1 → openPrintStart(...onConfirm) → _doSend',
  /if \(ids\.length === 1\)/.test(SRC_LAUNCH) && /openPrintStart\(\{/.test(SRC_LAUNCH) && /_doSend\(/.test(SRC_LAUNCH));
check('S3. launchPrintSelected: пакетный инвариант не тронут (stagger ≥2 и финальный _doSend(null))',
  /staggerOn\.value && ids\.length >= 2/.test(SRC_LAUNCH) && /await _doSend\(null\)/.test(SRC_LAUNCH));

// Проводник: exConfirmFnFor(print) и кнопка «Печать» идут СРАЗУ в exPrint(null), без exAms-дропдауна.
check('S4. app.js exConfirmFnFor(print) → exPrint(null) без установки exAmsOpen',
  /case 'print':\s*return[\s\S]{0,120}\?\s*\(\(\)\s*=>\s*exPrint\(null\)\)/.test(APPJS));
check('S5. index.html: кнопка «Печать» проводника → exPrint(null) (без exAmsOpen=!exAmsOpen)',
  /@click\.stop="exPrint\(null\)">\{\{ tr\('Print'\) \}\}<\/button>/.test(HTML));

// Ни один живой путь больше НЕ устанавливает exAmsOpen=true (дропдаун проводника не открывается).
check('S6. нигде не выставляется exAmsOpen в true (ни app.js, ни index.html)',
  !/exAmsOpen(\.value)?\s*=\s*true/.test(APPJS) && !/exAmsOpen\s*=\s*!\s*exAmsOpen/.test(HTML) && !/exAmsOpen(\.value)?\s*=\s*true/.test(HTML));

// openAmsPick остаётся только как вызов из НЕподключённого printPickPrinter (мёртвого): в шаблоне его нет.
check('S7. openAmsPick вызывается РОВНО из одного места (printPickPrinter), а он не подключён в index.html (мёртвый)',
  !/printPickPrinter/.test(HTML) && (APPJS.match(/openAmsPick\(/g) || []).length === 1 && !/openAmsPick/.test(SRC_LAUNCH));

// C1 «файл уже на принтере» НЕ тронут: sendCmd(start_print) по-прежнему берёт printAmsSlot; кнопка «Внешняя катушка» жива; общий CSS .ams-popup на месте.
check('C1a. sendCmd(start_print): ams_slot по-прежнему из printAmsSlot (null = настоящая внешняя катушка)',
  /cmd === 'start_print'\) body\.ams_slot = \(printAmsSlot\.value === null \|\| printAmsSlot\.value === undefined\) \? null : Number\(printAmsSlot\.value\)/.test(APPJS));
check('C1b. index.html: кнопка C1 «Внешняя катушка» → printAmsSlot=null; sendCmd(start_print) — не изменена',
  /printAmsSlot=null; cellAmsOpen=false; sendCmd\('start_print', printFileName\)/.test(HTML)
  && HTML.includes("{{ lang==='ru'?'Внешняя катушка':'External spool' }}"));
check('C1c. общий CSS .ams-popup сохранён (используется C1-дропдауном cellAmsOpen)',
  /\.ams-popup\{/.test(CSS) && /cellAmsOpen && activeModalPrinterId===p\.id" class="ams-popup"/.test(HTML));

// ═══════════════ RUNTIME: исполнение launchPrintSelected на реальных Vue-ref ═══════════════
const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { ref, computed } = Vue;

let jid = 0;
//  08.10.2026 (R-008): ответ сервера задаётся набором — reply(url, body, n) → объект; по умолчанию «принято».
const mk = (reply) => {
  const spy = { openAmsPick: 0, openPrintStart: 0, decision: [], toasts: [] };
  let lastCtx = null, jobs = 0;
  const posts = [];
  const env = {
    printSpotlightCtx: ref(null),
    printSel: ref([]),
    wsData: ref({}),
    openAmsPick: () => { spy.openAmsPick++; },
    openPrintStart: (ctx) => { spy.openPrintStart++; lastCtx = ctx; },
    staggerOn: ref(false), staggerInterval: ref(30),
    printers: ref([{ id: 'p2', name: 'X1-AMS' }, { id: 'p1', name: 'X1-noAMS' }, { id: 'p3', name: 'X1-AMS-2' }]),
    fetch: async (url, opts) => {
      const body = opts && opts.body ? JSON.parse(opts.body) : null;
      posts.push({ url: String(url), body });
      const r = reply ? reply(String(url), body, posts.length) : null;
      return { json: async () => (r || { accepted: true, job_id: 'j' + (++jid) }) };
    },
    pushToast: (msg) => { spy.toasts.push(String(msg)); }, lang: ref('ru'), tr: (s) => s,
    openFilamentDecision: (blocked, items, interval, direct) => { spy.decision.push({ blocked, items, interval, direct }); },
    filNoteText: (n) => 'NOTE:' + (n.kind || '') + ':' + (n.printer_name || ''),
    //  16.10.2026: уведомление склада показывается через pushFilNote (R-151) — как в app.js, тостом текста
    //  filNoteText. Без него извлечённый _doSend падал на принятом запуске с notes (R10 краснел с R-151).
    pushFilNote: (n) => { env.pushToast(env.filNoteText(n)); },
    readinessReasonText: (c) => 'REASON:' + c,
    exitSpotlight: () => { env.printSel.value = []; env.printSpotlightCtx.value = null; },
    fetchPrintQueue: () => {},
    _printerNameOf: (pid) => pid,
    //  15.09.2026 («Отправка» до подтверждения принтером): строка отправки проекта берёт имя
    //  файла по id из дерева проекта. Без этого помощника извлечённый _doSend падает.
    _p2FileNameOf: (pid, fileId) => (pid && fileId ? String(fileId) + '.3mf' : ''),
    handleSendResp: (resp) => { if (resp && resp.accepted) { jobs++; return 'accepted'; } if (resp && resp.error === 'printer_send_busy') return 'busy'; return 'other'; },
    loadProject2Tree: async () => {},
  };
  const fn = new Function('Vue', 'env', [
    'const { ref, computed } = Vue;',
    'const { printSpotlightCtx, printSel, wsData, openAmsPick, staggerOn, staggerInterval, printers, fetch, pushToast, lang, tr, exitSpotlight, fetchPrintQueue, _printerNameOf, _p2FileNameOf, handleSendResp, openPrintStart, loadProject2Tree, openFilamentDecision, filNoteText, pushFilNote, readinessReasonText } = env;',
    SRC_LAUNCH,
    'return launchPrintSelected;',
  ].join('\n'))(Vue, env);
  return { env, spy, fn, posts, getJobs: () => jobs, getCtx: () => lastCtx };
};
const settle = async () => { for (let i = 0; i < 4; i++) { await new Promise((r) => setTimeout(r, 0)); } };

// ─── R1: одиночный Bambu с живым AMS (Задачи) → НИ ОДНОГО amsPick, РОВНО одно окно PrintStartDialog ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: 'Деталь', rowKey: 'st:part.gcode.3mf' };
  t.env.printSel.value = ['p2'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }, { index: 1, unit: 0, tray: 1, type: 'PETG' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  check('R1a. Задачи+Bambu AMS: legacy picker (amsPick) НЕ открыт, PrintStartDialog открыт РОВНО один раз',
    t.spy.openAmsPick === 0 && t.spy.openPrintStart === 1);
  check('R1b. до подтверждения: ни одного POST печати, ни одного job/reservation (окно ещё не подтверждено)',
    t.posts.length === 0 && t.getJobs() === 0);
  check('R1c. ctx окна корректен (printerId=p2, source проброшен, есть onConfirm)',
    t.getCtx() && t.getCtx().printerId === 'p2' && t.getCtx().source === 'quick' && typeof t.getCtx().onConfirm === 'function');
}

// ─── R2: подтверждение с разными источниками → РОВНО один POST /api/part/print с точным ams_slot ───
const confirmSlotCase = async (srcSlot, expect) => {
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: 'Деталь', rowKey: 'st:x' };
  t.env.printSel.value = ['p2'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  t.getCtx().onConfirm({ timelapse: false, bed_leveling: true, flow_cal: false }, srcSlot);
  await settle();
  const p = t.posts.filter((x) => x.url === '/api/part/print');
  const okOne = p.length === 1 && t.getJobs() === 1;
  const okSlot = expect === 'absent' ? !('ams_slot' in p[0].body) : p[0].body.ams_slot === expect;
  const okOpts = JSON.stringify(p[0] && p[0].body.print_opts) === JSON.stringify({ timelapse: false, bed_leveling: true, flow_cal: false });
  return okOne && okSlot && okOpts;
};
check('R2a. Подтвердить «Авто (как в файле)» (srcSlot=null) → один POST БЕЗ ams_slot, один job',
  await confirmSlotCase(null, 'absent'));
check('R2b. Подтвердить AMS слот 1 (srcSlot=0, backend index 0) → ams_slot=0', await confirmSlotCase(0, 0));
check('R2c. Подтвердить AMS слот 2 (srcSlot=1, backend index 1) → ams_slot=1', await confirmSlotCase(1, 1));
check('R2d. Подтвердить multi-AMS global index 5 (srcSlot=5) → ams_slot=5', await confirmSlotCase(5, 5));
check('R2e. Подтвердить AMS HT index 512 (srcSlot=512) → ams_slot=512', await confirmSlotCase(512, 512));
check('R2f. Подтвердить «Внешняя катушка» (srcSlot=-1) → ams_slot=-1', await confirmSlotCase(-1, -1));

// ─── R3: ОТМЕНА окна → ноль POST, ноль job, ноль reservation (onConfirm не вызван) ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' };
  t.env.printSel.value = ['p2'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  // отмена = окно закрылось без onConfirm
  await settle();
  check('R3. Отмена: PrintStartDialog открыт один раз, но POST печати=0, jobs=0, reservations=0 (нет HTTP-запуска)',
    t.spy.openPrintStart === 1 && t.posts.length === 0 && t.getJobs() === 0);
}

// ─── R4: одно подтверждение = РОВНО один job (нет двойного submit при одном onConfirm) ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' };
  t.env.printSel.value = ['p2'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  t.getCtx().onConfirm({ timelapse: false, bed_leveling: true, flow_cal: false }, 0);
  await settle();
  check('R4. Один клик подтверждения → РОВНО один POST и один job (без двойного submit)',
    t.posts.filter((x) => x.url === '/api/part/print').length === 1 && t.getJobs() === 1);
}

// ─── R5: Проекты + Bambu AMS → одно окно; подтверждение → один POST /api/projects2/.../print с ams_slot ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'project', pid: 'PR1', fileId: 'F1', rowKey: 'p2:F1' };
  t.env.printSel.value = ['p2'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 5, unit: 1, tray: 1, type: 'ABS' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  check('R5a. Проекты+Bambu AMS: legacy picker НЕ открыт, PrintStartDialog открыт один раз', t.spy.openAmsPick === 0 && t.spy.openPrintStart === 1);
  t.getCtx().onConfirm({ timelapse: false, bed_leveling: true, flow_cal: false }, 5);
  await settle();
  const p = t.posts.filter((x) => x.url === '/api/projects2/PR1/files/F1/print');
  //  08.10.2026 (обход фермы, R-008): запуск из проекта больше НЕ пропускает склад — skip_filament
  //  появляется только после решения владельца в окне «Материал закончился».
  check('R5b. Подтверждение → один POST в проектный роут с ams_slot=5 и БЕЗ skip_filament (склад спрашивается)',
    p.length === 1 && p[0].body.ams_slot === 5 && !('skip_filament' in p[0].body) && t.getJobs() === 1);
}

// ─── R6: одиночный принтер БЕЗ живого AMS → тоже сразу PrintStartDialog (не picker); подтверждение → ams_slot=-1 ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' };
  t.env.printSel.value = ['p1'];
  t.env.wsData.value = { p1: {} };   // нет ams_trays
  await t.fn({ currentTarget: {} });
  await settle();
  check('R6a. Принтер без AMS: legacy picker НЕ открыт, PrintStartDialog открыт один раз', t.spy.openAmsPick === 0 && t.spy.openPrintStart === 1);
  t.getCtx().onConfirm({ timelapse: false, bed_leveling: true, flow_cal: false }, -1);
  await settle();
  const p = t.posts.filter((x) => x.url === '/api/part/print');
  check('R6b. Подтверждение «Внешняя катушка» → один POST с ams_slot=-1', p.length === 1 && p[0].body.ams_slot === -1 && t.getJobs() === 1);
}

// ─── R7: ПАКЕТ (≥2 принтера) → окно НЕ открывается, прежний путь _doSend, POST без ams_slot ───
{
  const t = mk();
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' };
  t.env.printSel.value = ['p2', 'p3'];
  t.env.wsData.value = { p2: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }] }, p3: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }] } };
  await t.fn({ currentTarget: {} });
  await settle();
  const p = t.posts.filter((x) => x.url === '/api/part/print');
  check('R7. Пакет ≥2: PrintStartDialog и amsPick НЕ открыты; 2 POST без ams_slot (пакетный контракт как раньше)',
    t.spy.openPrintStart === 0 && t.spy.openAmsPick === 0 && p.length === 2 && p.every((x) => !('ams_slot' in x.body)) && t.getJobs() === 2);
}

// ═══════════════ 08.10.2026, обход фермы (R-008): отказ склада при запуске из «Задач» и «Проектов» ═══════════════
const LOW = (pid) => ({ status: 'low_filament', printer_id: pid, shortfall: [{ material: 'PETG', needed: 120, available: 0, slot: 0 }],
                        resolve_steps: [], override_steps: [] });
const runOne = async (t, ctx, pid, slot) => {
  t.env.printSpotlightCtx.value = ctx;
  t.env.printSel.value = [pid];
  t.env.wsData.value = {};
  await t.fn({ currentTarget: {} });
  await settle();
  t.getCtx().onConfirm({ timelapse: false, bed_leveling: true, flow_cal: false }, slot);
  await settle();
};
// ─── R8: «Задачи», один принтер, склад против → окно решения (direct), без «Отправлено 0/1» ───
{
  const t = mk((url, body) => (url === '/api/part/print' && !body.skip_filament) ? LOW('p2') : null);
  await runOne(t, { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: 'Деталь', rowKey: 'st:x' }, 'p2', 0);
  const d = t.spy.decision[0];
  check('R8a. Задачи: отказ склада открывает окно «Материал закончился» (прямой режим), один ряд по принтеру p2',
    t.spy.decision.length === 1 && d.direct === true && d.blocked.length === 1 && d.blocked[0].printer_id === 'p2'
    && d.items.length === 1 && typeof d.items[0].launch === 'function');
  check('R8b. Задачи: тоста «Отправлено на принтеры: 0/1» нет — остановленный складом принтер не неудача',
    !t.spy.toasts.some((s) => /Sent to printers/.test(s)));
  const ok1 = await d.items[0].launch(true);
  await settle();
  const p = t.posts.filter((x) => x.url === '/api/part/print');
  check('R8c. «Печатать всё равно» → повтор тем же запросом с skip_filament:true (ams_slot и опции сохранены), принято',
    ok1 === true && p.length === 2 && p[1].body.skip_filament === true && p[1].body.ams_slot === 0
    && p[1].body.gcode_file === 'part.gcode.3mf' && JSON.stringify(p[1].body.print_opts) === JSON.stringify({ timelapse: false, bed_leveling: true, flow_cal: false }));
  const ok2 = await d.items[0].launch(false);
  await settle();
  const p2 = t.posts.filter((x) => x.url === '/api/part/print');
  //  16.10.2026 (R-019): склад снова против — запуск возвращает окну НОВУЮ нехватку, а не «не удалось».
  check('R8d. «Поставил новую катушку» → повтор БЕЗ skip_filament (склад спрашивается снова), повторная нехватка уходит окну',
    p2.length === 3 && !('skip_filament' in p2[2].body) && !!ok2 && !!ok2.low_filament
    && ok2.low_filament.printer_id === 'p2' && ok2.low_filament.status === 'low_filament');
}
// ─── R9: «Проекты», один принтер, склад против → то же окно; повтор идёт в проектный роут ───
{
  const t = mk((url, body) => (url.indexOf('/api/projects2/') === 0 && !body.skip_filament) ? LOW('p2') : null);
  await runOne(t, { flow: 'project', pid: 'PR1', fileId: 'F1', rowKey: 'p2:F1' }, 'p2', 5);
  const d = t.spy.decision[0];
  check('R9a. Проекты: склад спрошен (первый POST без skip_filament), отказ открывает окно в прямом режиме',
    t.posts.length === 1 && !('skip_filament' in t.posts[0].body) && t.spy.decision.length === 1 && d.direct === true);
  const ok = await d.items[0].launch(true);
  check('R9b. Проекты: «Печатать всё равно» → POST в /api/projects2/PR1/files/F1/print с skip_filament и ams_slot=5',
    ok === true && t.posts.length === 2 && t.posts[1].url === '/api/projects2/PR1/files/F1/print'
    && t.posts[1].body.skip_filament === true && t.posts[1].body.ams_slot === 5);
}
// ─── R10: уведомления склада при принятом запуске показываются, а не теряются ───
{
  const t = mk(() => ({ accepted: true, job_id: 'jn', notes: [{ status: 'advice', kind: 'tight', printer_name: 'p2' }] }));
  await runOne(t, { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' }, 'p2', 0);
  check('R10. Принятый запуск с notes → тост уведомления склада и «Отправлено на принтеры: 1», окна нет',
    t.spy.toasts.indexOf('NOTE:tight:p2') >= 0 && t.spy.toasts.some((s) => /Sent to printers: 1$/.test(s)) && t.spy.decision.length === 0);
}
// ─── R11: пакет из двух без поэтапного запуска — один принят, другой остановлен складом ───
{
  const t = mk((url, body) => (body && body.printer_id === 'p3') ? LOW('p3') : null);
  t.env.printSpotlightCtx.value = { flow: 'quick', filename: 'part.gcode.3mf', source: 'quick', partName: '', rowKey: 'st:x' };
  t.env.printSel.value = ['p2', 'p3'];
  await t.fn({ currentTarget: {} });
  await settle();
  const d = t.spy.decision[0];
  check('R11. Пакет: «Отправлено на принтеры: 1» (без 1/2) и окно решения только по p3',
    t.spy.toasts.some((s) => /Sent to printers: 1$/.test(s)) && !t.spy.toasts.some((s) => /1\/2/.test(s))
    && t.spy.decision.length === 1 && d.blocked.length === 1 && d.blocked[0].printer_id === 'p3' && t.getJobs() === 1);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: двойное окно выбора AMS устранено — единый PrintStartDialog как единственный источник ams_slot (реальное исполнение launchPrintSelected + инварианты C1/пакета/проводника)'));
process.exit(fail ? 1 : 0);
