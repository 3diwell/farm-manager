// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест системы активных предупреждений принтеров — Alpha 2.731 (+2.818).
// Часть E: ДОСЛОВНО извлечённый из web/app.js движок alert'ов исполняется на вендорном Vue (ref/computed);
//          проверяем проверенную state machine runout (A→E), дедуп, offline-заморозку, Klipper/FlashForge,
//          антидребезг, счётчик принтеров, 20 принтеров, отсутствие toast/Suggestions.
// Часть CANCEL: Alpha 2.818 — классификация «отмена ≠ ошибка устройства» переехала в БЭКЕНД
//          (app/printer_health_policy.py); фронтенд ТОЛЬКО показывает готовое s.device_error и своего
//          whitelist кодов отмены не держит. Полную классификацию проверяет
//          tools/test_user_cancelled_print_classification.py.
// Часть M: МОНТИРУЕМ ДОСЛОВНУЮ разметку (web/index.html) — полоса карточки, значок+badge шапки, панель —
//          и проверяем DOM (русские сообщения, неизвестный код, +N, «Нет свежих данных», строки панели).
// Запуск: node tools/test_printer_alerts_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (как в других runtime-тестах) ───────────
class DNode { constructor(t){ this.nodeType=t; this.childNodes=[]; this.parentNode=null; }
  get nextSibling(){ const p=this.parentNode; if(!p) return null; const i=p.childNodes.indexOf(this); return i>=0?(p.childNodes[i+1]||null):null; }
  _link(c,a){ if(c.parentNode)c.parentNode.removeChild(c); c.parentNode=this; if(a&&a.parentNode===this)this.childNodes.splice(this.childNodes.indexOf(a),0,c); else this.childNodes.push(c); return c; }
  insertBefore(c,a){ return this._link(c,a); } appendChild(c){ return this._link(c,null); }
  removeChild(c){ const i=this.childNodes.indexOf(c); if(i>=0)this.childNodes.splice(i,1); c.parentNode=null; return c; }
  getRootNode(){ return globalThis.document; } get ownerDocument(){ return globalThis.document; } }
class DText extends DNode { constructor(t){ super(3); this.nodeValue=t==null?'':String(t); } get data(){ return this.nodeValue; } set data(v){ this.nodeValue=v; } }
class DComment extends DNode { constructor(t){ super(8); this.nodeValue=t==null?'':String(t); } }
class DElement extends DNode {
  constructor(tag){ super(1); this._tag=tag; this.tagName=String(tag).toUpperCase(); this.namespaceURI='http://www.w3.org/1999/xhtml'; this.attributes={}; this._listeners={}; this.style={}; this._cls=''; }
  setAttribute(k,v){ this.attributes[k]=String(v); if(k==='class')this._cls=String(v); }
  removeAttribute(k){ delete this.attributes[k]; if(k==='class')this._cls=''; }
  getAttribute(k){ return k in this.attributes?this.attributes[k]:null; }
  hasAttribute(k){ return k in this.attributes; }
  get className(){ return this._cls; } set className(v){ this._cls=v==null?'':String(v); this.attributes['class']=this._cls; }
  get classList(){ const s=this; const set=()=>new Set(s._cls.split(/\s+/).filter(Boolean)); const put=x=>{ s.className=[...x].join(' '); }; return { add:(...c)=>{ const x=set(); c.forEach(y=>x.add(y)); put(x); }, remove:(...c)=>{ const x=set(); c.forEach(y=>x.delete(y)); put(x); }, contains:c=>set().has(c) }; }
  addEventListener(t,fn){ (this._listeners[t]=this._listeners[t]||[]).push(fn); }
  removeEventListener(t,fn){ const a=this._listeners[t]; if(a){ const i=a.indexOf(fn); if(i>=0)a.splice(i,1); } }
  get textContent(){ return this.childNodes.map(c=>c.nodeType===3?c.nodeValue:(c.nodeType===1?c.textContent:'')).join(''); }
  set textContent(v){ this.childNodes.forEach(c=>(c.parentNode=null)); this.childNodes=[]; if(v!==''&&v!=null)this.appendChild(new DText(String(v))); }
  hasChildNodes(){ return this.childNodes.length>0; } get firstChild(){ return this.childNodes[0]||null; }
  get innerHTML(){ return ''; } set innerHTML(v){ if(v===''||v==null){ this.childNodes.forEach(c=>(c.parentNode=null)); this.childNodes=[]; } }
  querySelector(){ return null; } scrollIntoView(){}
  _fire(type,ev){ (this._listeners[type]||[]).slice().forEach(fn=>fn(ev)); }
  _findAll(pred,out=[]){ if(this.nodeType===1&&pred(this))out.push(this); this.childNodes.forEach(c=>{ if(c.nodeType===1)c._findAll(pred,out); }); return out; } }
const doc={ createElement:t=>new DElement(t), createElementNS:(ns,t)=>new DElement(t), createTextNode:t=>new DText(t), createComment:t=>new DComment(t), querySelector:()=>null, addEventListener:()=>{}, removeEventListener:()=>{}, activeElement:null };
doc.body=new DElement('body'); doc.head=new DElement('head'); doc.documentElement=new DElement('html');
if(!globalThis.document) globalThis.document=doc;
if(!globalThis.window){ try{ globalThis.window=globalThis; }catch(e){} }
for(const g of ['SVGElement','HTMLElement','Element','Node','ShadowRoot','Document','DocumentFragment']){ if(globalThis[g]===undefined) globalThis[g]=class{}; }

const Vue = await import(pathToFileURL(join(REPO,'web','vendor','vue.esm-browser.js')).href);
const { ref, computed, createApp } = Vue;

// ═══════════════ ЧАСТЬ E: движок alert'ов ═══════════════
const bStart = APPJS.indexOf('const KNOWN_BAMBU_CODES = {');
const bEnd = APPJS.indexOf('const installedModules = ref([]);', bStart);
const BLOCK = APPJS.slice(bStart, bEnd);
check('E0. движок alert извлечён из web/app.js; НЕ содержит pushToast / Suggestions / typeHl (не toast, не Подсказки)',
  BLOCK.length > 1500 && !/pushToast/.test(BLOCK) && !/showSuggestions|farm_show_suggest|typeHl/.test(BLOCK));

const env = {
  watch: () => {},   // стаб: реконсиляцию гоняем вручную (детерминированно)
  wsData: ref({}),
  printers: ref([{ id: 'H1', type: 'bambu' }, { id: 'K1', type: 'klipper' }, { id: 'F1', type: 'flashforge' }]),
  lang: ref('ru'), tourActive: ref(false),
  _printerNameOf: (pid) => ({ H1: 'X1 #1', K1: 'K1-макс', F1: 'AD5M' })[pid] || pid,
  isMobile: ref(false), mobileTab: ref('printers'),
  nextTick: (cb) => { if (cb) cb(); return Promise.resolve(); },
  document: { querySelector: () => null },
};
const E = new Function('Vue', 'env', [
  'const { ref, computed } = Vue;',
  'const { watch, wsData, printers, lang, tourActive, _printerNameOf, isMobile, mobileTab, nextTick, document } = env;',
  BLOCK,
  'return { printerAlerts, cardTopAlert, alertsForPrinter, alertBadgeCount, alertTopSeverity, alertPanelRows, alertsPanelOpen, toggleAlertsPanel, closeAlertsPanel, focusPrinterCard, alertTimeLabel, KNOWN_BAMBU_CODES, _reconcileAlerts };',
].join('\n'))(Vue, env);

const setWs = (o) => { env.wsData.value = o; };
const rec = () => E._reconcileAlerts();
const two = (o) => { setWs(o); rec(); rec(); };   // 2 подряд свежих кадра — антидребезг
const alertsOf = (pid) => E.alertsForPrinter(pid);
const one = (pid) => alertsOf(pid)[0];
// Alpha 2.818: health-канал Bambu приходит от бэкенда полем device_error. В тесте задаём его ЯВНО
// (эмуляция вывода app/printer_health_policy.py): реальный код → показать; отмена → device_error=null.

// ─── A. PAUSE + подтверждённый runout → одно предупреждение «Закончился филамент в AMS» ───
two({ H1: { status: 'PAUSE', error_code: '07FF-8011', mc_err: '32785', hms_codes: ['12FF-8011'], device_error: '07FF-8011', seen_ago: 1 } });
check('A. Runout (device_error от бэкенда) → РОВНО ОДНО предупреждение «Закончился филамент в AMS» (warning), код 07FF-8011',
  E.alertBadgeCount.value === 1 && alertsOf('H1').length === 1 && one('H1').title === 'Закончился филамент в AMS' && one('H1').severity === 'warning' && one('H1').code === '07FF-8011' && one('H1').source === 'bambu');
const aidA = one('H1').alert_id;

// ─── B. Повторные partial snapshots (backend держит поля sticky) → без дублей ───
rec(); rec(); rec();
check('B. Повторные snapshots → без дублей: тот же alert_id, badge=1, telemetry_fresh=true',
  E.alertBadgeCount.value === 1 && alertsOf('H1').length === 1 && one('H1').alert_id === aidA && one('H1').telemetry_fresh === true);

// ─── C. Новый код 07FF-8007 → старое сообщение ЗАМЕНЯЕТСЯ, не второе ───
setWs({ H1: { status: 'PAUSE', error_code: '07FF-8007', mc_err: '32775', hms_codes: [], device_error: '07FF-8007', seen_ago: 1 } }); rec();
check('C. Смена кода 07FF-8011→07FF-8007: заменено на «Проверьте подачу филамента», по-прежнему ОДНО предупреждение',
  E.alertBadgeCount.value === 1 && alertsOf('H1').length === 1 && one('H1').title === 'Проверьте подачу филамента' && one('H1').code === '07FF-8007' && one('H1').alert_id !== aidA);   // новый alert_id = событие ЗАМЕНЕНО (детерминированно, без завязки на Date.now())

// ─── D. OFFLINE/stale → предупреждение остаётся, telemetry_fresh=false, нового не создаём ───
setWs({ H1: { status: 'OFFLINE' } }); rec();   // OFFLINE_STATE без error-полей
check('D. OFFLINE: предупреждение СОХРАНЯЕТСЯ (не resolved), telemetry_fresh=false, badge всё ещё 1, offline-alert не создан',
  E.alertBadgeCount.value === 1 && alertsOf('H1').length === 1 && one('H1').telemetry_fresh === false && one('H1').code === '07FF-8007');

// ─── E. RUNNING → все error-поля очищены backend'ом, alert исчезает автоматически ───
setWs({ H1: { status: 'RUNNING', seen_ago: 1 } }); rec();
check('E. RUNNING → предупреждение снято автоматически, badge=0, карточка пуста',
  E.alertBadgeCount.value === 0 && alertsOf('H1').length === 0 && E.cardTopAlert('H1') === null);

// ─── Неизвестный код → «Ошибка принтера» + код, без выдуманного диагноза ───
two({ H1: { status: 'PAUSE', error_code: '1234-5678', device_error: '1234-5678', seen_ago: 1 } });
check('U. Неизвестный код 1234-5678 → title «Ошибка принтера», message с кодом, severity error (без выдумки)',
  one('H1').title === 'Ошибка принтера' && /1234-5678/.test(one('H1').message) && one('H1').severity === 'error');
setWs({ H1: { status: 'RUNNING', seen_ago: 1 } }); rec();

// ─── Ручная PAUSE без кода → alert НЕ создаётся ───
two({ H1: { status: 'PAUSE', seen_ago: 1 } });
check('P. Ручная PAUSE без активного кода → предупреждения НЕТ (badge=0)', E.alertBadgeCount.value === 0);

// ─── Антидребезг: одиночный кадр не мигает ───
setWs({ H1: { status: 'PAUSE', error_code: '07FF-8011', device_error: '07FF-8011', seen_ago: 1 } }); rec();   // 1 кадр
const afterOne = E.alertBadgeCount.value;
setWs({ H1: { status: 'RUNNING', seen_ago: 1 } }); rec();                            // проблема ушла до 2-го кадра
check('F. Антидребезг: после 1 кадра alert ещё НЕ активен; кратковременный кадр не мигает (0 → 0)', afterOne === 0 && E.alertBadgeCount.value === 0);

// ─── Klipper: err_msg → alert; resolve; ручная PAUSED без err_msg → нет ───
// Alpha 2.826: health-канал Klipper/FlashForge унифицирован — бэкенд отдаёт device_error (как Bambu);
// отмена → device_error=null → нет alert; реальный сбой → device_error задан (Klipper: err_msg, FF: 'FAILED').
two({ K1: { status: 'FAILED', err_msg: 'MCU "mcu" shutdown: ADC out of range', device_error: 'MCU "mcu" shutdown: ADC out of range', seen_ago: 1 } });
check('K1. Klipper err_msg → alert «Ошибка Klipper» с сообщением принтера', one('K1') && one('K1').source === 'klipper' && one('K1').title === 'Ошибка Klipper' && /shutdown/.test(one('K1').message));
setWs({ K1: { status: 'RUNNING', err_msg: '', seen_ago: 1 } }); rec();
check('K2. Klipper printing + пустой err_msg → resolve', alertsOf('K1').length === 0);
two({ K1: { status: 'PAUSED', seen_ago: 1 } });
check('K3. Klipper ручная PAUSED без err_msg → alert НЕ создаётся', alertsOf('K1').length === 0);

// ─── FlashForge: FAILED → generic; выход из FAILED → resolve ───
two({ F1: { status: 'FAILED', device_error: 'FAILED', seen_ago: 1 } });
check('FF1. FlashForge FAILED → generic «Ошибка печати» (без выдуманной причины)', one('F1') && one('F1').source === 'flashforge' && one('F1').title === 'Ошибка печати');
setWs({ F1: { status: 'IDLE', seen_ago: 1 } }); rec();
check('FF2. FlashForge вышел из FAILED → resolve', alertsOf('F1').length === 0);

// ─── Badge считает ПРИНТЕРЫ, а не коды ───
two({ H1: { status: 'PAUSE', error_code: '07FF-8011', mc_err: '32785', hms_codes: ['12FF-8011'], device_error: '07FF-8011', seen_ago: 1 }, F1: { status: 'FAILED', device_error: 'FAILED', seen_ago: 1 } });
check('G. Badge = число ПРИНТЕРОВ с проблемами (H1 = 1 alert; +F1) → badge=2, всего alert=2',
  E.alertBadgeCount.value === 2 && E.alertPanelRows.value.length === 2 && alertsOf('H1').length === 1);
setWs({}); rec();   // очистка перед нагрузочным

// ─── 20 принтеров, часть с ошибками — без зависаний ───
const many = []; const wd = {};
for (let i = 0; i < 20; i++) { const id = 'P' + i; many.push({ id, type: 'bambu' }); wd[id] = (i % 2 === 0) ? { status: 'PAUSE', error_code: '07FF-8011', mc_err: '32785', device_error: '07FF-8011', seen_ago: 1 } : { status: 'RUNNING', seen_ago: 1 }; }
env.printers.value = many;
setWs(wd); rec(); rec();
check('L. 20 принтеров (10 с runout) → badge=10, панель 10 строк, без падений', E.alertBadgeCount.value === 10 && E.alertPanelRows.value.length === 10);
env.printers.value = [{ id: 'H1', type: 'bambu' }, { id: 'K1', type: 'klipper' }, { id: 'F1', type: 'flashforge' }];
setWs({}); rec();

// ─── Escape/click-outside/панель: логика (state) + статическая проводка в app.js ───
E.alertsPanelOpen.value = false; E.toggleAlertsPanel();
check('PN1. toggleAlertsPanel открывает панель', E.alertsPanelOpen.value === true);
E.closeAlertsPanel();
check('PN2. closeAlertsPanel закрывает панель (закрытие панели ≠ решение alert)', E.alertsPanelOpen.value === false);
check('PN3. app.js: Escape и клик-вне закрывают ТОЛЬКО панель (alertsPanelOpen) — проводка присутствует',
  /if \(alertsPanelOpen\.value\) \{ closeAlertsPanel\(\); return; \}/.test(APPJS) && /alertsPanelOpen\.value && !e\.target\.closest\('\.fm-alert-panel'\)/.test(APPJS));

// ═══════════════ ЧАСТЬ CANCEL: отмена печати классифицируется БЭКЕНДОМ (Alpha 2.818) ═══════════════
// Whitelist кодов отмены Bambu (_BAMBU_CANCEL_CODES: 0300-400C/0002-0070) убран из фронтенда — теперь
// решение принимает app/printer_health_policy.py КОНТЕКСТНО и отдаёт готовое s.device_error (код или null).
// Каждый новый код отмены прошивки (0300-000A) больше НЕ ломает карточку. Полную классификацию
// (0300-400C/0002-0070/0300-000A, контекст, точечность, coexist) проверяет
// tools/test_user_cancelled_print_classification.py; здесь — что ФРОНТЕНД лишь ПОКАЗЫВАЕТ device_error.
setWs({}); rec();
check('C0. фронтенд НЕ содержит whitelist кодов отмены и берёт готовый s.device_error из бэкенда',
  !/const _BAMBU_CANCEL_CODES\s*=/.test(BLOCK) && !/const _bambuCanonCode\s*=/.test(BLOCK)
  && !/const _isBambuCancelFull\s*=/.test(BLOCK) && !/new Set\(\['0300-400C'/.test(BLOCK)
  && /const code = s\.device_error/.test(BLOCK));

// Отмена: бэкенд отдал device_error=null (сырой error_code/mc остаётся в снимке для диагностики) → alert НЕ создаётся
two({ H1: { status: 'RUNNING', seen_ago: 1 } });
two({ H1: { status: 'IDLE', error_code: '0300-000A', mc_err: '16396', device_error: null, seen_ago: 1 } });
check('C1. отмена (device_error=null) при сыром 0300-000A/mc16396 (Стоп в FM → IDLE): alert НЕ создаётся, карточка чиста',
  E.alertBadgeCount.value === 0 && alertsOf('H1').length === 0 && E.cardTopAlert('H1') === null);
two({ H1: { status: 'RUNNING', seen_ago: 1 } });
two({ H1: { status: 'FAILED', error_code: '0300-400C', mc_err: '16396', device_error: null, seen_ago: 1 } });
check('C2. отмена с экрана (сырой FAILED, device_error=null): alert НЕ создаётся, badge=0',
  E.alertBadgeCount.value === 0 && alertsOf('H1').length === 0);
setWs({ H1: { status: 'FAILED', error_code: '0300-000A', device_error: null, seen_ago: 1 } }); rec(); rec(); rec();
check('C3. повторные sticky-снимки отмены (device_error=null) → alert так и не появляется',
  E.alertBadgeCount.value === 0 && alertsOf('H1').length === 0);
setWs({}); rec();

// Реальный сбой ОДНОВРЕМЕННО с отменой: бэкенд отдал device_error=<реальный код> → настоящая ошибка ВИДНА
two({ H1: { status: 'FAILED', error_code: '0300-400C', mc_err: '16396', hms_codes: ['07FF-8007'], device_error: '07FF-8007', seen_ago: 1 } });
check('C4. отмена + реальный HMS: бэкенд отдал device_error=07FF-8007 → показан ТОЛЬКО настоящий сбой «Проверьте подачу филамента»',
  E.alertBadgeCount.value === 1 && alertsOf('H1').length === 1 && one('H1').code === '07FF-8007' && one('H1').title === 'Проверьте подачу филамента');
setWs({}); rec();

// Соседний код, который бэкенд НЕ счёл отменой → device_error=<код> → показывается как настоящая ошибка
two({ H1: { status: 'FAILED', error_code: '0300-400D', device_error: '0300-400D', seen_ago: 1 } });
check('C5. НЕ-отмена (0300-400D, device_error задан бэкендом) → «Ошибка принтера» + код, severity error',
  alertsOf('H1').length === 1 && one('H1').title === 'Ошибка принтера' && /0300-400D/.test(one('H1').message) && one('H1').severity === 'error');
setWs({}); rec();

// ═══════════════ ЧАСТЬ M: монтаж ДОСЛОВНОЙ разметки (index.html) ═══════════════
const sliceTag = (html, startStr, openTok, closeTok) => {
  const s = html.indexOf(startStr); if (s < 0) throw new Error('not found: ' + startStr);
  const openEnd = html.indexOf('>', s) + 1;
  const re = new RegExp(openTok.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '|' + closeTok.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
  re.lastIndex = openEnd; let m, d = 1, c = -1;
  while ((m = re.exec(html))) { d += (m[0] === closeTok) ? -1 : 1; if (d === 0) { c = m.index; break; } }
  return html.slice(s, c + closeTok.length);
};
const CARD_STRIP = sliceTag(HTML, '<div v-if="cardTopAlert(p.id)" class="pc-alert"', '<div', '</div>');
const HEADER_IND = sliceTag(HTML, '<button v-if="alertBadgeCount"', '<button', '</button>');
const PANEL = sliceTag(HTML, '<div v-if="alertsPanelOpen" class="fm-alert-panel"', '<div', '</div>');
check('M0. извлечены разметки: полоса карточки / индикатор шапки / панель', CARD_STRIP.includes('pc-alert-title') && HEADER_IND.includes('fm-alert-badge') && PANEL.includes('fm-alert-row'));

// драйвим движок: H1 runout + синтетический второй alert для +N; F1 unknown; панель открыта
setWs({ H1: { status: 'PAUSE', error_code: '07FF-8011', mc_err: '32785', hms_codes: ['12FF-8011'], device_error: '07FF-8011', seen_ago: 1 }, F1: { status: 'FAILED', device_error: 'FAILED', seen_ago: 1 } }); rec(); rec();
// синтетический второй независимый alert того же принтера — проверка «+N» (движок дедупит по source, поэтому добавляем вручную)
E.printerAlerts.value = Object.assign({}, E.printerAlerts.value, { 'H1|synthetic': { printer_id: 'H1', alert_id: 'alSyn', source: 'synthetic', code: 'X', severity: 'error', category: 'printer_error', title: 'Второй сбой', message: 'msg2', active_since: Date.now(), last_seen: Date.now(), telemetry_fresh: true } });
E.alertsPanelOpen.value = true;

const comp = { setup() { return Object.assign({ p: { id: 'H1' }, lang: env.lang }, E); },
  template: '<div class="mroot">' + HEADER_IND + '<div class="cardwrap">' + CARD_STRIP + '</div>' + PANEL + '</div>' };
const app = createApp(comp);
app.component('svg-icon', { props: ['name'], template: '<span class="svg-ico"></span>' });
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.warnHandler = () => {};
const root = new DElement('div');
app.mount(root);
await new Promise(r => setTimeout(r, 0));

const txt = () => root.textContent;
const find = (pred) => root._findAll(pred);
const byClass = (cls) => find(e => (e.getAttribute('class') || '').split(/\s+/).includes(cls));

check('M1. полоса карточки: показан известный русский title «Закончился филамент в AMS» и его message',
  byClass('pc-alert-title').length === 1 && txt().includes('Закончился филамент в AMS') && txt().includes('Установите новую катушку'));
check('M2. полоса карточки: «+N» для второго независимого alert того же принтера (+1)',
  byClass('pc-alert-more').length === 1 && byClass('pc-alert-more')[0].textContent.trim() === '+1');
check('M3. индикатор шапки: badge = число ПРИНТЕРОВ (H1+F1 = 2)',
  byClass('fm-alert-badge').length === 1 && byClass('fm-alert-badge')[0].textContent.trim() === '2');
check('M4. панель открыта: строки с именами принтеров и заголовками (X1 #1 · …, AD5M · Ошибка печати)',
  byClass('fm-alert-row').length >= 2 && txt().includes('X1 #1') && txt().includes('AD5M') && txt().includes('Ошибка печати'));

// stale-подпись: переводим H1 в OFFLINE (заморозка) и перемонтируем
E.printerAlerts.value = { 'H1|bambu': Object.assign({}, E.printerAlerts.value['H1|bambu'], { telemetry_fresh: false }) };
const app2 = createApp({ setup() { return Object.assign({ p: { id: 'H1' }, lang: env.lang }, E); }, template: '<div>' + CARD_STRIP + '</div>' });
app2.component('svg-icon', { props: ['name'], template: '<span></span>' });
app2.config.compilerOptions.decodeEntities = (x) => x; app2.config.warnHandler = () => {};
const root2 = new DElement('div'); app2.mount(root2); await new Promise(r => setTimeout(r, 0));
check('M5. stale active alert показывает вторичную подпись «Нет свежих данных»',
  root2._findAll(e => (e.getAttribute('class') || '').split(/\s+/).includes('pc-alert-stale')).length === 1 && root2.textContent.includes('Нет свежих данных'));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: активные предупреждения — runout A→E, дедуп, offline-заморозка, Klipper/FF, антидребезг, badge по принтерам, +N, «Нет свежих данных»; Alpha 2.818: классификация отмены переехала в бэкенд, фронтенд показывает готовое s.device_error без своего whitelist (C0–C5) (реальный движок app.js + монтаж разметки index.html)'));
process.exit(fail ? 1 : 0);
