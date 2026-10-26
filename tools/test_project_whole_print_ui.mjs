// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// UI функции «Печатать весь проект» — core Alpha 2.740, ФАЗА A (dry-run: только расчёт и сохранение плана).
// Проверяет РЕАЛЬНУЮ разметку окна из web/index.html и РЕАЛЬНЫЕ функции из web/app.js (извлекаются
// дословно, не переписываются). Живой рендер настоящим вендорным Vue идёт в браузере через харнесс
// tools/e2e_whole_print_harness.html (U1-U21 + Edge layout) — этот файл проверяет статические
// инварианты и печатает инструкцию запуска браузерной части.
//
// ФАЗА B (панель run, pause/resume/cancel, «Стол очищен», ambiguity, polling) здесь НАМЕРЕННО
// отсутствует — соответствующие проверки U17-U32 добавятся вместе с ней.
// Запуск: node tools/test_project_whole_print_ui.mjs   (0 = пройдено)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const INDEX = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
const APPCSS = readFileSync(join(REPO, 'web', 'app.css'), 'latin1');   // битый UTF-8 хвост -> читаем как байты
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// код UI-фазы A без комментариев (чтобы упоминания в тексте не давали ложных срабатываний)
// Alpha 2.745: конец блока — НАЧАЛО фазы B1, а не closeActiveModule. Раньше срез тянулся до конца
// setup и потому захватывал всё, что дописано ниже (B1/B2, а с 5A3b — блок «Источник материала»,
// где законно встречаются поля backend inventory_material/inventory_declared). Проверка B28 —
// именно про ФАЗУ A, поэтому и область должна быть фазой A.
const PW = (() => {
  const s = APPJS.indexOf('const showProjectWholePreflight = ref(false);');
  const e = APPJS.indexOf('const PROJECT_RUNS_POLL_MS = 4000;');
  if (s < 0 || e < 0 || e <= s) throw new Error('границы блока фазы A не найдены');
  return APPJS.slice(s, e).replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
})();

// ── кнопка ──
check('B1. кнопка «Печатать весь проект» объявлена РОВНО один раз, в контейнере действий проекта, '
  + 'и раскрывает ВСТРОЕННЫЙ блок (toggleWholePrint) с aria-expanded',
  (INDEX.match(/toggleWholePrint\(pr\)/g) || []).length === 1
  && INDEX.indexOf('pw-open-btn') > INDEX.indexOf('<div class="flex items-center gap-2 shrink-0" @click.stop>')
  && /class="pw-open-btn"[^>]*:aria-expanded="wpxOpenFor\(pr\.id\)/.test(INDEX));
check('B2. это <button type="button"> с @click.stop (не сворачивает проект) и с title',
  /<button type="button" class="pw-open-btn"[^>]*@click\.stop="toggleWholePrint\(pr\)" :title=/.test(INDEX));
check('B3. кнопки нет в строках файлов: она одна на раскрытый проект',
  (INDEX.match(/pw-open-btn/g) || []).length === 1);

// ── встроенный блок (2.753: модалки НЕТ) ──
check('B4. КРИТИЧНО: модальное окно расчёта УДАЛЕНО, вместо него ОДИН встроенный блок-region',
  !INDEX.includes('class="pw-back"') && !INDEX.includes('class="pw-win"')
  && !INDEX.includes('showProjectWholePreflight" class')
  && (INDEX.match(/class="wpx"/g) || []).length === 1
  && /<div v-if="wpxOpenFor\(pr\.id\)" class="wpx" role="region" :aria-label=/.test(INDEX));
check('B5. КРИТИЧНО: блок в обычном потоке ВНУТРИ раскрытого проекта: не teleport, не fixed, без backdrop',
  (() => { const a = INDEX.indexOf('class="wpx"');
           const proj = INDEX.lastIndexOf("project2Expanded === pr.id", a);
           const tele = INDEX.lastIndexOf('<teleport', a);
           const teleEnd = INDEX.lastIndexOf('</teleport>', a);
           return proj > 0 && (tele < teleEnd || tele === -1); })()
  && !/\.wpx \{[^}]*position:\s*fixed/.test(APPCSS) && !/\.wpx \{[^}]*backdrop-filter/.test(APPCSS));
check('B6. сворачивание — той же кнопкой шапки; блок не имеет крестика-закрытия',
  !/class="pw-x"/.test(INDEX) && /toggleWholePrint = \(pr\)/.test(APPJS));

// ── запрет печати ──
check('B7. в коде UI-фазы A НЕТ /start, печатных endpoint, send-manager, MQTT и FTP',
  !/\/start/.test(PW) && !/files\/[^'"]*\/print/.test(PW) && !/upload_print|print_path/.test(PW)
  && !/_send_mgr|mqtt|ftp/i.test(PW));
check('B8. в разметке окна нет ни одного вызова /start',
  !/project-runs\/[^"']*\/start/.test(INDEX));
check('B9. 2.753: мёртвой кнопки автозапуска НЕТ; одна спокойная плашка режима (не кнопка, без клика)',
  !/pw-dead/.test(INDEX)
  && (INDEX.match(/Проверочный режим: доступен только один контролируемый запуск/g) || []).length === 1
  && /<div class="wpx-mode">/.test(INDEX) && !/wpx-mode[^>]*@click/.test(INDEX));

// ── контракт запросов ──
check('B10. preflight запрашивается GET по фактическому endpoint',
  /\/whole-print\/preflight/.test(PW) && /signal: ac\.signal/.test(PW));
check('B11. AbortError не показывается как ошибка', /e\.name === 'AbortError'\) return;/.test(PW));
check('B12. один активный GET: повторный вызов во время загрузки выходит сразу',
  /if \(!pid \|\| projectWholeLoading\.value\) return;/.test(PW));
check('B13. POST шлёт ТОЛЬКО snapshot_version и allow_overproduction (клиентский план не отправляется)',
  /body: JSON\.stringify\(\{ snapshot_version: ver,\s*\n?\s*allow_overproduction: !!projectWholeAllowOverproduction\.value \}\)/.test(PW)
  && !/plan:/.test(PW.slice(PW.indexOf('whole-print/runs'), PW.indexOf('whole-print/runs') + 400)));
check('B14. 409 existing_run_id -> подгружается существующий run, второй не создаётся',
  /reason === 'project_run_exists'/.test(PW) && /\/api\/project-runs\/'\s*\+\s*encodeURIComponent\(j\.existing_run_id\)/.test(PW));
check('B15. 409 project_plan_stale -> окно не закрывается, run не создаётся',
  /reason === 'project_plan_stale'\) \{ projectWholeNotice\.value = 'stale'; return; \}/.test(PW));

// ── перепроизводство ──
check('B16. согласие сбрасывается при КАЖДОМ новом расчёте',
  /projectWholeAllowOverproduction\.value = false;\s*\/\/ новый расчёт/.test(APPJS.slice(APPJS.indexOf('const loadProjectWholePreflight'))));
check('B17. без согласия сохранение недоступно (guard в canSave)',
  /\(!projectWholeNeedsApproval\.value \|\| projectWholeAllowOverproduction\.value\)/.test(PW));
check('B18. allow_overproduction нигде не выставляется в true автоматически',
  !/projectWholeAllowOverproduction\.value = true/.test(PW));
check('B19. числа перепроизводства берутся из ответа СЕРВЕРА, а не считаются на фронте',
  /const pre = projectWholeOverPreview\.value;/.test(PW) && /pre\.plan\.overproduction_total/.test(PW));

// ── Escape / focus ──
check('B20. 2.753: встроенный блок НЕ модалка — preflight НЕ регистрирует Escape-слой',
  !/registerEscapeLayer\(closeProjectWholePreflight\)/.test(PW) && !/_pwEsc/.test(PW));
check('B21. локальные диалоги из блока по-прежнему возвращают focus (feed/confirm-слои живы)',
  /nextTick\(\(\) => \{ try \{ if \(b && b\.focus\) b\.focus\(\)/.test(APPJS));
check('B22. закрытие отменяет активный запрос', /const closeProjectWholePreflight = \(\) => \{\s*\n\s*_pwCancel\(\);/.test(PW));

// ── CSS ──
check('B23. у окна НЕТ backdrop-filter (правило проекта для постоянных слоёв)',
  !/backdrop-filter\s*:/.test(APPCSS.slice(APPCSS.indexOf('.pw-back')).replace(/\/\*[\s\S]*?\*\//g, '')));
check('B24. окно ограничено по высоте с внутренней вертикальной прокруткой и без гориз. overflow',
  /\.pw-win \{[^}]*max-height:\s*min\(/.test(APPCSS) && /\.pw-body \{[^}]*overflow-y:\s*auto/.test(APPCSS)
  && /\.pw-body \{[^}]*overflow-x:\s*hidden/.test(APPCSS));
check('B25. disabled-кнопка визуально отличается и есть focus-visible',
  /\.pw-btn:disabled \{[^}]*opacity/.test(APPCSS) && /\.pw-btn\.pw-dead \{/.test(APPCSS)
  && /\.pw-btn:focus-visible/.test(APPCSS));
check('B26. длинные имена не расширяют окно (ellipsis у имён/проекта)',
  /\.pw-name \{[^}]*text-overflow:\s*ellipsis/.test(APPCSS) && /\.pw-proj \{[^}]*text-overflow:\s*ellipsis/.test(APPCSS));

// ── существующая печать одного файла не тронута ──
check('B27. существующий одиночный запуск файла проекта остался прежним (endpoint /files/{id}/print цел)',
  /\/files\/'\s*\+\s*[^;]*\+\s*'\/print'/.test(APPJS) || APPJS.includes("/print'"));
check('B28. UI-фаза A не трогает Inventory/Quality/Cost', !/inventory|quality|cost/i.test(PW));

// Блок 5B2a «контрольный запуск» лежит ВНУТРИ этих же участков app.js, но к фазам B1/B2 не
// относится и проверяется своим тестом (test_project_controlled_start_ui.mjs). Вырезаем его:
// иначе его единственный законный /start ломал бы инвариант «фаза сама не печатает».
const CS_A = 'const armStatus = ref(null);', CS_B = 'const confirmFeedClear = async () => {';
const cutCS = (s) => {
  const a = s.indexOf(CS_A), b = s.indexOf(CS_B);
  if (a < 0 || b < 0 || b <= a) throw new Error('блок 5B2a не найден: якоря разошлись с web/app.js');
  return s.slice(0, a) + s.slice(b);
};
const nocomm = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
// код UI-фазы B2 без комментариев (упоминания в тексте не должны давать ложных срабатываний)
const B2_ALL = nocomm(APPJS.slice(APPJS.indexOf('const projectRunClearanceTargets ='), APPJS.indexOf('const closeActiveModule =')));
const B2 = cutCS(B2_ALL);

// ── UI-фаза B1: единая панель «Планы проектов» ──
const PR_ALL = nocomm(APPJS.slice(APPJS.indexOf('const PROJECT_RUNS_POLL_MS'), APPJS.indexOf('const closeActiveModule =')));
const PR = cutCS(PR_ALL);
const CSS_PR = APPCSS.slice(APPCSS.indexOf('.pr-panel {')).replace(/\/\*[\s\S]*?\*\//g, '');
const CSS_1 = CSS_PR.replace(/\s+/g, ' ');

check('P1. КРИТИЧНО: глобальная fixed-панель УДАЛЕНА; run рендерится через wpxRunFor(pr.id) строго '
  + 'по project_id — run одного проекта не может появиться в другом',
  !INDEX.includes('class="pr-panel"') && !/v-for="r in projectRunsList"/.test(INDEX)
  && !/projectRunsPanelOpen|projectRunsPanelCollapsed|toggleProjectRunsPanel/.test(APPJS)
  && !/\.pr-panel \{/.test(APPCSS)
  && /const wpxRunFor = \(pid\) => \{/.test(APPJS)
  && /r\.project_id === pid/.test(APPJS));
check('P2. источник активных runs — ТОЛЬКО GET /api/project-runs?active=1 (diagnostics не используется)',
  /\/api\/project-runs\?active=1/.test(PR) && !/diagnostics/.test(PR));
// Проверяем ТЕЛО самой loadActiveProjectRuns: соседние pause/cancel-URL вида '/api/project-runs/'+id
// легитимны, поэтому широкий поиск по блоку давал ложное падение.
const TICK_BODY = PR.slice(PR.indexOf('const _prTick = async'), PR.indexOf('const startProjectRunsPolling'));
// B1 показывал items из list-ответа, которого там НЕТ (counts/items всегда пустые). Фаза B2 берёт
// состав и порядок у списка, а items/printers/clearance — у detail, в ТОМ ЖЕ общем тике.
check('P3. list — источник состава/порядка; detail — источник items/printers/clearance, грузится в '
  + 'ТОМ ЖЕ тике одним Promise.allSettled, отдельного таймера на run нет',
  /\/api\/project-runs\?active=1/.test(TICK_BODY) && /_prFetchDetail\(id, signal\)/.test(TICK_BODY)
  && /Promise\.allSettled\(order\.map/.test(TICK_BODY)
  && /const loadActiveProjectRuns = \(initial\) => _prRunTick/.test(PR)
  && /const pollProjectRunsOnce = \(\) => _prRunTick\(false\)/.test(PR));
check('P3b. упавший detail НЕ стирает snapshot остальных runs и не роняет тик',
  /d\.status === 'fulfilled'/.test(TICK_BODY) && /const prev = projectRunsById\.value\[id\];/.test(TICK_BODY)
  && /items: prev\.items, counts: prev\.counts, printers: prev\.printers/.test(TICK_BODY));
check('P3c. project_name есть ТОЛЬКО у списка -> detail его не перетирает',
  /\{ project_name: by\[id\]\.project_name \}/.test(TICK_BODY));
check('P4. project_name=null -> «Проект недоступен»: persisted run не теряется',
  /projectRunName/.test(PR) && /Проект недоступен/.test(PR));
check('P5. дедупликация по run_id при восстановлении', /by\[run\.run_id\]/.test(PR));
check('P6. ОДИН глобальный polling timer: повторный start второго не создаёт',
  /if \(projectRunsPollTimer\) return;/.test(PR) && (PR.match(/setInterval\(/g) || []).length === 1);
check('P7. интервал polling = 4 секунды', /PROJECT_RUNS_POLL_MS = 4000/.test(PR));
check('P8. перекрытие тиков запрещено (in-flight guard) — ОДИН guard на оба входа в тик',
  /if \(projectRunsPollInFlight\) return\b/.test(PR)
  && (PR.match(/const _prRunTick = async/g) || []).length === 1);
check('P9. один AbortController на тик; stop делает abort + clearInterval',
  /projectRunsPollController = ac;/.test(PR) && /clearInterval\(projectRunsPollTimer\)/.test(PR)
  && /projectRunsPollController\.abort\(\)/.test(PR));
check('P10. polling живёт только при активных runs; без них timer очищается',
  /projectRunsActiveCount\.value > 0/.test(PR) && /else stopProjectRunsPolling\(\)/.test(PR));
check('P11. очистка при unmount подключена', /stopProjectRunsPolling\(\);\s*\/\/ «Планы проектов»/.test(APPJS));
check('P12. временная ошибка НЕ стирает последний хороший snapshot',
  !/catch[\s\S]{0,240}projectRunsById\.value = \{\}/.test(PR));
check('P13. подписи говорят о ПЛАНЕ, а не о печати',
  /Приостановить план/.test(INDEX) && /Продолжить план/.test(INDEX)
  && !/Приостановить печать/.test(INDEX) && !/Возобновить печать/.test(INDEX));
check('P14. action-lock отдельно по run id', /projectRunActions\.value\[run\.run_id\]\) return;/.test(PR));
check('P15. cancel только через styled confirm; native confirm() не используется; текст «не '
  + 'отправит команду остановки принтерам» жив (переехал из разметки в computed)',
  /requestCancelProjectRun/.test(PR) && !/[^.\w]confirm\(/.test(PR)
  && /не отправит команду остановки принтерам/.test(APPJS));
check('P16. confirm встроен в Escape-stack и возвращает focus',
  /registerEscapeLayer\(closeCancelProjectRunConfirm\)/.test(PR)
  && /unregisterEscapeLayer\(_prConfirmEsc\)/.test(PR) && /b\.focus\(\)/.test(PR));
check('P17. фаза B1 НЕ вызывает /start, печать, send, MQTT, FTP',
  !/\/start/.test(PR) && !/files\/[^'"]*\/print/.test(PR) && !/_send_mgr|mqtt|ftp/i.test(PR));
check('P17b. КРИТИЧНО: единственный /start на участке — в блоке контрольного запуска 5B2a',
  (PR_ALL.match(/\/start\b/g) || []).length === 1);
check('P18. cancel не шлёт команд принтеру', !/\/api\/printer\//.test(PR));
check('P19. human-статусы запусков живут в wpxItemState; raw-коды переведены в русский текст',
  /waiting_plate_clear: \[ 'Снимите готовую деталь'/.test(APPJS)
  && /ambiguous_after_dispatch: \[ 'Требуется решение'/.test(APPJS)
  && /waiting_start_confirmation: \[ 'Ожидается подтверждение старта'/.test(APPJS));
check('P20. постоянная плашка режима — ОДНА на блок, внутри блока',
  (INDEX.match(/wpx-mode/g) || []).length === 1
  && INDEX.indexOf('wpx-mode') > INDEX.indexOf('class="wpx"'));
check('P21. блок без backdrop-filter и без «сплошного» перекрытия соседей: обычный поток, '
  + 'техподробности со своей прокруткой',
  !/\.wpx[^{]*\{[^}]*backdrop-filter/.test(APPCSS)
  && /\.wpx-tech \{[^}]*overflow-x:\s*auto/.test(APPCSS));
check('P22. локальные слои над содержимым: pr-confirm-back 9998 < pf-back 9999 < pf-cf-back 100000, '
  + 'а .wpx без z-index вовсе',
  /\.pr-confirm-back \{ position: fixed; inset: 0; z-index: 9998/.test(APPCSS.replace(/\s+/g, ' '))
  && !/\.wpx \{[^}]*z-index/.test(APPCSS));
check('P23. кнопка шапки — единственный переключатель блока (aria-expanded на ней)',
  /pw-open-btn[^>]*:aria-expanded/.test(INDEX) && !/toggleProjectRunsPanel/.test(INDEX));
check('P24. восстановление активных планов запускается при инициализации SPA',
  /loadActiveProjectRuns\(true\);\s*\/\/ «Планы проектов»/.test(APPJS));



// ── UI-фаза B2: «Стол очищен», отзыв, решение по ambiguous, индикатор на карточке принтера ──
const CSS_B2 = APPCSS.slice(APPCSS.indexOf('.pr-st.ok')).replace(/\/\*[\s\S]*?\*\//g, '');

check('Q1. ЕДИНСТВЕННАЯ модель eligibility: карточка запуска (wpxItemClearance) и индикатор на '
  + 'карточке принтера питаются от projectRunClearanceTargets — второй модели нет',
  (B2.match(/const projectRunClearanceTargets = /g) || []).length === 1
  && /projectRunPlateClearIds = computed\([\s\S]{0,220}projectRunClearanceTargets\(r\)/.test(B2)
  && /printerAwaitsPlateClear = \(p\) =>[\s\S]{0,140}projectRunPlateClearIds/.test(B2)
  && /wpxItemClearance = \(r, it\) =>\s*\n?\s*projectRunClearanceTargets\(r\)\.find/.test(APPJS)
  && /wpxClrState\(wpxRunFor\(pr\.id\), it\)/.test(INDEX)
  && /const wpxClrState = \(r, it\) => \{[\s\S]{0,40}const t = wpxItemClearance\(r, it\);/.test(APPJS));
check('Q2. цель clearance выводится ТОЛЬКО из фактической связки run -> item -> assigned_printer_id '
  + '-> waiting_plate_clear; по IDLE/FINISH/имени/модели принтера НЕ угадывается',
  /it\.state !== 'waiting_plate_clear' \|\| !it\.assigned_printer_id/.test(B2)
  && !/'IDLE'|'FINISH'|\.model|target_model/.test(B2));
check('Q3. терминальный run целей не даёт (индикатора у отменённого/завершённого плана нет)',
  /if \(!r \|\| \['completed', 'cancelled'\]\.includes\(r\.state\)\) return \[\];/.test(B2));
check('Q4. право нажать = свежая телеметрия + не RUNNING/PREPARE + нет ДЕЙСТВУЮЩЕГО токена',
  /clearanceCanConfirm = \(t\) => !!t && !!t\.printer\.telemetry_fresh/.test(B2)
  && /!\['RUNNING', 'PREPARE'\]\.includes\(t\.printer\.status\) && !t\.printer\.clearance/.test(B2));
check('Q5. отзывают ТОЛЬКО действующее разрешение: revoke смотрит на clearance (active), а не на историю',
  /clearanceCanRevoke = \(t\) => !!\(t && t\.printer\.clearance\)/.test(B2)
  && !/clearanceCanRevoke[\s\S]{0,80}last_clearance/.test(B2));
check('Q6. U28: active берётся из clearance; история и ПРИЧИНА — из last_clearance; '
  + 'перезапуск сервера назван явно, generic-успехом не подменяется',
  /if \(t\.printer\.clearance\) return ru \? 'Стол подтверждён'/.test(B2)
  && /lc\.status === 'consumed'[\s\S]{0,60}'Подтверждение использовано'/.test(B2)
  && /lc\.status === 'revoked'[\s\S]{0,60}'Подтверждение отозвано'/.test(B2)
  && /lc\.invalid_reason === 'server_restart'[\s\S]{0,120}'Подтверждение недействительно после перезапуска сервера'/.test(B2)
  && /if \(!lc\) return ru \? 'Подтверждение ещё не создавалось'/.test(B2));
check('Q7. consumed/revoked/invalidated НЕ блокируют новую кнопку: право зависит только от '
  + 'active-токена и eligibility, историю в расчёт права не берём',
  !/clearanceCanConfirm[\s\S]{0,160}last_clearance/.test(B2));
check('Q8. «Стол очищен» шлёт confirmed:true и ТОЧНЫЙ finished_job_id этого item (\'\' = initial)',
  /\{ confirmed: true, finished_job_id: t\.finished_job_id \}/.test(APPJS)
  && /finished_job_id: it\.project_print_job_id \|\| ''/.test(B2));
check('Q9. resolve шлёт ровно { resolution } и только started/not_started; кнопки retry нет',
  /\/items\/' \+ encodeURIComponent\(t\.item\.item_id\) \+ '\/resolve', \{ resolution: res \}/.test(APPJS)
  && /requestResolveItem\(wpxRunFor\(pr\.id\), it, 'started', \$event\)/.test(INDEX)
  && /requestResolveItem\(wpxRunFor\(pr\.id\), it, 'not_started', \$event\)/.test(INDEX)
  && (() => {          // в блоке ambiguous РОВНО две кнопки и ни одного обработчика повтора
       const b = INDEX.slice(INDEX.indexOf('class="wpx-it-amb"'), INDEX.indexOf('</div>\n', INDEX.indexOf('pr-clr-a', INDEX.indexOf('class="wpx-it-amb"'))));
       return (b.match(/<button/g) || []).length === 2 && !/@click="[^"]*(retry|repeat|Повтор)/i.test(b);
     })());
check('Q10. фаза B2 не вызывает /start, печать, send, MQTT, FTP и команды принтеру',
  !/\/start/.test(B2) && !/files\/[^'"]*\/print/.test(B2) && !/_send_mgr|mqtt|ftp/i.test(B2)
  && !/\/api\/printer\//.test(B2));
check('Q10b. КРИТИЧНО: единственный /start на участке — в блоке контрольного запуска 5B2a',
  (B2_ALL.match(/\/start\b/g) || []).length === 1);
//  2.985 (R-107): видов карточки стало три — «ячейки», «сетка» и дашборд фермы. Значок
//  «ожидается очистка стола» нужен во всех трёх: на обзоре фермы он и нужнее всего.
//  Складской бейдж остаётся в двух: карточка дашборда показывает ход печати, не катушку.
check('Q11. индикатор waiting_plate_clear объявлен для ВСЕХ режимов (grid-summary, card-grid, дашборд) '
  + 'и не ломает складской бейдж рядом',
  (INDEX.match(/class="pc-wpc/g) || []).length === 3
  && (INDEX.match(/printerStockBound\(p\)/g) || []).length === 2);
check('Q12. хит-зона индикатора и компенсация отступов — те же, что у соседнего .pc-stock: '
  + 'ширина карточки в grid/list не меняется',
  /\.pc-wpc \{[\s\S]{0,320}padding: 5px; margin: -3px -3px -3px -1px;/.test(CSS_B2)
  && /\.pc-wpc:focus-visible \{/.test(CSS_B2) && !/backdrop-filter\s*:/.test(CSS_B2));

console.log('\nЖИВОЙ РЕНДЕР (обязателен, реальный Vue + Edge): подними статический сервер из корня и открой');
console.log('  http://localhost:8777/tools/e2e_whole_print_harness.html');
console.log('  -> window.__E2E.ok === true (U1-U21, 0 запрещённых вызовов) + Edge layout dark/light × 1366/1550.');
console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: кнопка одна и в шапке проекта; окно фазы A только считает и сохраняет план; /start, печатные ' +
  'endpoint, send-manager, MQTT и FTP не вызываются; согласие на перепроизводство обязательно и ' +
  'сбрасывается при каждом расчёте; клиентский план серверу не отправляется; Escape/focus и вёрстка ' +
  'соответствуют правилам проекта'));
process.exit(fail ? 1 : 0);
