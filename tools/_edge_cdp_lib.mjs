// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Alpha 2.835 — ЕДИНЫЙ мост «тест ↔ настоящий браузер» через Chrome DevTools Protocol (Node).
//
// ЗАЧЕМ. До 2.835 браузерные .mjs-харнессы читали отрендеренный документ из stdout запуска
// `msedge --headless=new --dump-dom <url>`. Edge 150.0.4078.83 этот режим сломал: процесс выходит
// с кодом 0, stdout ПУСТОЙ. Харнессы трактовали пустой stdout как «браузера нет» и писали SKIP —
// то есть ~48 браузерных проверок геометрии молча не выполнялись. Именно эта слепая зона скрыла
// реальный дефект раскладки. Здесь ОДНА реализация CDP на все харнессы: движок поднимается с
// временным профилем и своим свободным портом, документ и измерения снимаются по протоколу.
//
// ПРИНЦИПЫ (важны для честности набора):
//   * `--dump-dom` не используется НИКОГДА, даже как резерв;
//   * любая проблема (движка нет, порт не появился, target не найден, таймаут CDP, ошибка
//     страницы) — это ИСКЛЮЧЕНИЕ с точной причиной. Решение «SKIP или FAIL» больше не делается
//     здесь: харнессы обязаны краснеть;
//   * `--in-process-gpu` обязателен: отдельный GPU-процесс Chromium на этой машине падает
//     («GPU process isn't usable») и уносит DevTools;
//   * браузер закрывается через `Browser.close` (иначе процессы живут сотнями и держат профиль),
//     профиль удаляется, живые процессы добиваются на выходе из Node.
//
// Сеть: только 127.0.0.1 к собственному браузеру. Ни БД, ни DATA_DIR, ни принтеров.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ENGINES = [
  process.env.CHROME_PATH,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];

/** Путь к установленному движку рендера или null. */
export function findEngine(explicit) {
  for (const p of [explicit, ...ENGINES]) {
    if (!p) continue;
    try { if (existsSync(p)) return p; } catch { /* недоступен — пробуем следующий */ }
  }
  return null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Харнессы подменяют globalThis.fetch (стаб ответов фермы) и иногда другие глобалы, доказывая, что
// продуктовый код не ходит в сеть. Мост — часть оснастки: ему нужно ровно одно соединение с
// СОБСТВЕННЫМ браузером на 127.0.0.1. Модуль импортируется ДО установки стабов, поэтому забираем
// настоящие реализации здесь и пользуемся только ими (тот же приём, что `_ORIG_SOCKET` в _edge_dom.py).
const ORIG_FETCH = globalThis.fetch.bind(globalThis);
const ORIG_WS = globalThis.WebSocket;

// Все запущенные движки — чтобы ни один процесс не пережил тест даже при аварийном выходе.
// Родительский msedge.exe выходит сразу (Edge перезапускает себя другим процессом), поэтому
// одного child.kill() мало: на выходе из Node подчищаем ВСЕ процессы, которые держат наши
// временные профили. Фильтр — только созданные нами пути, чужой браузер задеть нельзя.
const LIVE = new Set();
const PROFILES = new Set();
let hookInstalled = false;
function trackChild(child, profile) {
  LIVE.add(child);
  if (profile) PROFILES.add(profile);
  if (!hookInstalled) {
    hookInstalled = true;
    const killAll = () => {
      for (const c of LIVE) { try { c.kill(); } catch { /* уже мёртв */ } }
      if (PROFILES.size) sweepProfiles([...PROFILES]);
    };
    process.on('exit', killAll);
    process.on('uncaughtException', (e) => { killAll(); throw e; });
  }
}

/** Одним вызовом снять процессы движка, держащие любой из наших временных профилей. */
function sweepProfiles(profiles) {
  const cond = profiles.map((p) => '$_.CommandLine.Contains(' + JSON.stringify(p) + ')').join(' -or ');
  const ps = 'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\' OR Name=\'chrome.exe\'" | ' +
    'Where-Object { $_.CommandLine -and (' + cond + ') } | ' +
    'ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }';
  try {
    spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps],
      { stdio: 'ignore', timeout: 30000, windowsHide: true });
  } catch { /* нет powershell — остаётся штатное закрытие */ }
}

// Скрипт ставится ДО загрузки документа: иначе ранние отказы промисов и window.onerror теряются.
const DIAG_SOURCE = `
(function(){
  if (window.__fmDiag) return;
  window.__fmDiag = { unhandled: [], errors: [] };
  window.addEventListener('unhandledrejection', function(e){
    try { var r = e && e.reason; window.__fmDiag.unhandled.push(String((r && (r.message || r)) || 'unhandledrejection')); } catch(_){}
  });
  window.addEventListener('error', function(e){
    try { window.__fmDiag.errors.push(String((e && (e.message || e.type)) || 'error')); } catch(_){}
  });
})();`;

function argText(a) {
  if (!a) return '';
  if (a.value !== undefined) return typeof a.value === 'string' ? a.value : JSON.stringify(a.value);
  if (a.description) return String(a.description);
  if (a.unserializableValue) return String(a.unserializableValue);
  return String(a.type || '');
}

/**
 * Добить процессы движка, которые держат НАШ временный профиль.
 * Фильтр — точный путь профиля во внутреннем `--user-data-dir`, поэтому обычный браузер владельца
 * задеть невозможно. Нужен как страховка: `Browser.close` иногда не успевает, а оставшийся
 * headless-движок держит профиль и копится сотнями.
 */
function killByProfile(profile) {
  const ps = 'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\' OR Name=\'chrome.exe\'" | ' +
    'Where-Object { $_.CommandLine -and $_.CommandLine.Contains(' + JSON.stringify(profile) + ') } | ' +
    'ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }';
  try {
    spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps],
      { stdio: 'ignore', timeout: 20000, windowsHide: true });
  } catch { /* нет powershell — остаётся штатное закрытие */ }
}

export class CdpStage {
  constructor(child, ws, profile, engine, port) {
    this.child = child; this.ws = ws; this.profile = profile; this.engine = engine; this.port = port;
    this._id = 0; this._pend = new Map(); this._closed = false;
    this.consoleErrors = [];     // console.error / Log.entryAdded level=error
    this.consoleWarnings = [];   // console.warn (сюда попадают предупреждения Vue) / level=warning
    this.pageErrors = [];        // Runtime.exceptionThrown: необработанные исключения и отказы промисов
    this.loadFired = false;
    ws.onmessage = (e) => this._onMessage(e);
  }

  _onMessage(e) {
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    if (m.id && this._pend.has(m.id)) {
      const { resolve, timer } = this._pend.get(m.id);
      clearTimeout(timer); this._pend.delete(m.id); resolve(m);
      return;
    }
    const p = m.params || {};
    if (m.method === 'Runtime.consoleAPICalled') {
      const text = (p.args || []).map(argText).join(' ');
      if (p.type === 'error' || p.type === 'assert') this.consoleErrors.push(text);
      else if (p.type === 'warning' || p.type === 'warn') this.consoleWarnings.push(text);
    } else if (m.method === 'Runtime.exceptionThrown') {
      const d = (p.exceptionDetails || {});
      const ex = d.exception || {};
      this.pageErrors.push(String(ex.description || ex.value || d.text || 'exception'));
    } else if (m.method === 'Log.entryAdded') {
      const en = p.entry || {};
      const t = String(en.text || '') + (en.url ? ' <' + en.url + '>' : '');
      if (en.level === 'error') this.consoleErrors.push(t);
      else if (en.level === 'warning') this.consoleWarnings.push(t);
    } else if (m.method === 'Page.loadEventFired') {
      this.loadFired = true;
    }
  }

  /** Одна команда CDP. Таймаут — ИСКЛЮЧЕНИЕ, а не молчаливый пустой ответ. */
  send(method, params = {}, timeoutMs = 20000) {
    if (this._closed) return Promise.reject(new Error('CDP: сцена уже закрыта (' + method + ')'));
    return new Promise((resolve, reject) => {
      const id = ++this._id;
      const timer = setTimeout(() => {
        this._pend.delete(id);
        reject(new Error('CDP timeout ' + timeoutMs + 'ms: ' + method));
      }, timeoutMs);
      this._pend.set(id, { resolve, timer });
      try { this.ws.send(JSON.stringify({ id, method, params })); } catch (e) {
        clearTimeout(timer); this._pend.delete(id); reject(new Error('CDP send: ' + e.message));
      }
    });
  }

  /** Выполнить JS на странице и вернуть значение. Исключение страницы -> исключение теста. */
  async evaluate(expression, { awaitPromise = false, timeoutMs = 30000 } = {}) {
    const r = await this.send('Runtime.evaluate',
      { expression, awaitPromise, returnByValue: true, allowUnsafeEvalBlockedByCSP: true }, timeoutMs);
    const res = r.result || {};
    if (res.exceptionDetails) {
      const ex = res.exceptionDetails.exception || {};
      throw new Error('JS исключение на странице: ' + String(ex.description || ex.value || res.exceptionDetails.text));
    }
    return res.result ? res.result.value : undefined;
  }

  /** Ждать выполнения предиката (выражение JS -> true). Таймаут — исключение с причиной. */
  async waitFor(expression, { timeoutMs = 30000, what = 'условие', pollMs = 100 } = {}) {
    const t0 = Date.now();
    let last = '';
    while (Date.now() - t0 < timeoutMs) {
      try {
        const v = await this.evaluate('(function(){try{return (' + expression + ')?1:0;}catch(e){return String(e&&e.message||e);}})()');
        if (v === 1) return true;
        if (typeof v === 'string') last = v;
      } catch (e) { last = e.message; }
      await sleep(pollMs);
    }
    throw new Error('таймаут ожидания (' + timeoutMs + 'ms): ' + what + (last ? ' [' + last + ']' : ''));
  }

  /**
   * Единая готовность стенда. Каждый пункт даёт СВОЮ причину отказа, поэтому красный тест
   * говорит, чего именно не дождались, а не «headless не вернул результат».
   *   selector      — элемент обязан появиться в DOM;
   *   textIncludes  — его текст обязан содержать маркер (обычно '@@RES@@' сценария страницы);
   *   vueMounted    — на корне приложения появился data-v-app (Vue смонтирован);
   *   noVCloak      — атрибут v-cloak снят (шаблон отрисован, а не «сырой»);
   *   noBootFallback— аварийный экран #fm-boot-fallback НЕ показан.
   */
  async waitReady(opts = {}) {
    const { selector = '', textIncludes = '', vueMounted = false, vueRoot = '#app',
      noVCloak = false, noBootFallback = false, timeoutMs = 45000 } = opts;
    await this.waitFor("document.readyState === 'interactive' || document.readyState === 'complete'",
      { timeoutMs, what: 'DOMContentLoaded' });
    if (noBootFallback) {
      await this.waitFor("(function(){var f=document.getElementById('fm-boot-fallback');" +
        "return !f || getComputedStyle(f).display==='none';})()",
        { timeoutMs, what: 'аварийный экран #fm-boot-fallback не показан' });
    }
    if (vueMounted) {
      await this.waitFor("!!document.querySelector(" + JSON.stringify(vueRoot) + ") && " +
        "document.querySelector(" + JSON.stringify(vueRoot) + ").hasAttribute('data-v-app')",
        { timeoutMs, what: 'Vue смонтирован (data-v-app на ' + vueRoot + ')' });
    }
    if (noVCloak) {
      await this.waitFor("document.querySelectorAll('[v-cloak]').length === 0",
        { timeoutMs, what: 'снятие v-cloak' });
    }
    if (selector) {
      await this.waitFor('!!document.querySelector(' + JSON.stringify(selector) + ')',
        { timeoutMs, what: 'появление ' + selector });
    }
    if (textIncludes) {
      const sel = selector || 'body';
      await this.waitFor('((document.querySelector(' + JSON.stringify(sel) + ')||{}).textContent||"")' +
        '.indexOf(' + JSON.stringify(textIncludes) + ') >= 0',
        { timeoutMs, what: 'результат сценария (' + textIncludes + ') в ' + sel });
    }
    return true;
  }

  /** Полный отрендеренный документ — то же, что прежде приходило из --dump-dom. */
  outerHTML() { return this.evaluate('document.documentElement.outerHTML'); }

  /** Геометрия элемента (то же, что getBoundingClientRect в странице). */
  rect(selector) {
    return this.evaluate('(function(){var e=document.querySelector(' + JSON.stringify(selector) + ');' +
      'if(!e) return null; var r=e.getBoundingClientRect();' +
      'return {top:r.top,left:r.left,right:r.right,bottom:r.bottom,width:r.width,height:r.height};})()');
  }

  /** Горизонтальное/вертикальное превышение содержимого над видимой областью элемента. */
  overflow(selector) {
    return this.evaluate('(function(){var e=' + (selector
      ? 'document.querySelector(' + JSON.stringify(selector) + ')'
      : 'document.documentElement') + ';' +
      'if(!e) return null; return {x:e.scrollWidth-e.clientWidth, y:e.scrollHeight-e.clientHeight,' +
      ' scrollWidth:e.scrollWidth, clientWidth:e.clientWidth, scrollHeight:e.scrollHeight, clientHeight:e.clientHeight};})()');
  }

  /** Отказы промисов и window.onerror, собранные внутри страницы. */
  async unhandled() {
    const v = await this.evaluate('JSON.stringify((window.__fmDiag||{unhandled:[],errors:[]}))');
    try { return JSON.parse(v || '{}'); } catch { return { unhandled: [], errors: [] }; }
  }

  /** Снимок видимой области (нужен, когда проверка упала и надо посмотреть глазами). */
  async screenshot(path) {
    if (!path) return false;
    try {
      const s = await this.send('Page.captureScreenshot', { format: 'png' }, 30000);
      const b64 = s && s.result && s.result.data;
      if (!b64) return false;
      mkdirSync(join(path, '..'), { recursive: true });
      writeFileSync(path, Buffer.from(b64, 'base64'));
      return true;
    } catch { return false; }
  }

  /** Жив ли ещё DevTools-эндпоинт этого движка (единственный честный признак живого процесса). */
  async _alive() {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 800);
      const r = await ORIG_FETCH('http://127.0.0.1:' + this.port + '/json/version', { signal: c.signal });
      clearTimeout(t);
      return !!r;
    } catch { return false; }
  }

  /**
   * Закрыть страницу и движок, снять профиль. Ошибки закрытия не маскируют ошибки теста.
   * Закрытие ПРОВЕРЯЕТСЯ: пока DevTools отвечает, движок жив — тогда процессы этого профиля
   * добиваются принудительно. Иначе headless-движки копятся и держат временные папки.
   */
  async close() {
    if (this._closed) return;
    this._closed = true;
    try { this.ws.send(JSON.stringify({ id: 999999, method: 'Browser.close', params: {} })); }
    catch { /* сокет уже мёртв */ }
    for (let i = 0; i < 20; i++) {          // до ~4 c ждём фактического исчезновения эндпоинта
      await sleep(200);
      if (!(await this._alive())) break;
    }
    try { this.ws.close(); } catch { /* уже закрыт */ }
    try { this.child.kill(); } catch { /* уже вышел */ }
    LIVE.delete(this.child);
    if (await this._alive()) killByProfile(this.profile);
    await sleep(250);
    for (let i = 0; i < 12; i++) {
      try { rmSync(this.profile, { recursive: true, force: true }); break; } catch { await sleep(300); }
    }
    if (existsSync(this.profile)) {          // профиль ещё занят -> процесс не умер, добиваем
      killByProfile(this.profile);
      await sleep(400);
      for (let i = 0; i < 8; i++) {
        try { rmSync(this.profile, { recursive: true, force: true }); break; } catch { await sleep(300); }
      }
    }
  }
}

// Код выхода запущенного msedge.exe НЕ признак отказа: Edge перезапускает себя другим процессом,
// а родитель тут же выходит с кодом 0. Единственный надёжный признак живого CDP — файл
// DevToolsActivePort в профиле.
async function readPort(profile, child, timeoutMs) {
  const f = join(profile, 'DevToolsActivePort');
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (existsSync(f)) {
      const first = readFileSync(f, 'utf8').split('\n')[0].trim();
      if (/^\d+$/.test(first)) return parseInt(first, 10);
    }
    await sleep(120);
  }
  throw new Error('DevToolsActivePort не появился за ' + timeoutMs + 'ms (движок не поднял CDP)');
}

async function findTarget(port, timeoutMs) {
  const t0 = Date.now();
  let last = '';
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await ORIG_FETCH('http://127.0.0.1:' + port + '/json/list');
      const list = await r.json();
      if (!Array.isArray(list)) {
        last = 'ответ /json/list не список: ' + JSON.stringify(list).slice(0, 200);
      } else {
        const t = list.find((x) => x.type === 'page' && x.webSocketDebuggerUrl);
        if (t) return t;
        last = 'page-target отсутствует (' + list.length + ' целей)';
      }
    } catch (e) { last = String(e && e.message || e); }
    await sleep(150);
  }
  throw new Error('рабочий page-target не найден за ' + timeoutMs + 'ms [' + last + ']');
}

/**
 * Поднять движок, открыть страницу и вернуть готовую сцену.
 * Бросает исключение с точной причиной — вызывающий харнесс обязан покраснеть, а не пропустить.
 */
export async function openStage(opts = {}) {
  const { url, width = 1440, height = 900, extraArgs = [], engine: forced,
    startupTimeoutMs = 30000, ready, profileHint } = opts;
  if (!url) throw new Error('openStage: не задан url');
  const engine = findEngine(forced);
  if (!engine) throw new Error('движок рендера не найден (Edge/Chrome не установлен) — браузерные проверки не могут быть выполнены');
  // profileHint — путь, который вызывающая сторона (Python-обёртка) уже завела под удаление;
  // без него профиль создаётся во временной папке и снимается здесь же.
  let profile;
  if (profileHint) { mkdirSync(profileHint, { recursive: true }); profile = profileHint; }
  else { profile = mkdtempSync(join(tmpdir(), 'fm-cdp-')); }
  const args = ['--headless=new', '--disable-gpu', '--in-process-gpu', '--disable-software-rasterizer',
    '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,MediaRouter',
    '--remote-debugging-port=0', '--remote-allow-origins=*', '--user-data-dir=' + profile,
    '--allow-file-access-from-files', '--hide-scrollbars', '--window-size=' + width + ',' + height,
    ...extraArgs, 'about:blank'];
  const child = spawn(engine, args, { stdio: 'ignore' });
  trackChild(child, profile);
  let stage = null;
  try {
    const port = await readPort(profile, child, startupTimeoutMs);
    const tgt = await findTarget(port, startupTimeoutMs);
    const ws = new ORIG_WS(tgt.webSocketDebuggerUrl);
    await new Promise((res, rej) => {
      ws.onopen = res;
      ws.onerror = () => rej(new Error('WebSocket CDP не открылся'));
      setTimeout(() => rej(new Error('WebSocket CDP: таймаут рукопожатия 20000ms')), 20000);
    });
    stage = new CdpStage(child, ws, profile, engine, port);
    await stage.send('Runtime.enable');
    await stage.send('Log.enable');
    await stage.send('Page.enable');
    // Диагностика ставится ДО навигации — иначе ранние ошибки страницы теряются.
    await stage.send('Page.addScriptToEvaluateOnNewDocument', { source: DIAG_SOURCE });
    const nav = await stage.send('Page.navigate', { url }, 60000);
    const err = nav && nav.result && nav.result.errorText;
    if (err) throw new Error('страница не открылась: ' + err + ' (' + url + ')');
    await stage.waitReady(Object.assign({ timeoutMs: 45000 }, ready || {}));
    return stage;
  } catch (e) {
    if (stage) { try { await stage.close(); } catch { /* закрытие не важнее причины */ } }
    else {
      try { child.kill(); } catch { /* уже мёртв */ }
      LIVE.delete(child);
      killByProfile(profile);               // родитель msedge выходит сам — добиваем по профилю
      await sleep(300);
      for (let i = 0; i < 10; i++) {
        try { rmSync(profile, { recursive: true, force: true }); break; } catch { await sleep(250); }
      }
    }
    throw e;
  }
}

/**
 * Открыть сцену, выполнить fn(stage) и ГАРАНТИРОВАННО закрыть браузер.
 * shotOnError — необязательный PNG видимой области, снимается ДО закрытия при ошибке.
 */
export async function withStage(opts, fn) {
  const stage = await openStage(opts);
  try {
    return await fn(stage);
  } catch (e) {
    if (opts && opts.shotOnError) { try { await stage.screenshot(opts.shotOnError); } catch { /* снимок не обязателен */ } }
    throw e;
  } finally {
    await stage.close();
  }
}

/**
 * Проблемы страницы, которые ОБЯЗАНЫ краснить браузерную проверку: ошибки консоли, предупреждения
 * (в т.ч. «[Vue warn]»), необработанные исключения и отказы промисов. Раньше их никто не смотрел.
 * ignore — список подстрок для заведомо посторонних сообщений самого движка (по умолчанию пуст).
 */
export function browserProblems(r, ignore = []) {
  const keep = (s) => !ignore.some((x) => String(s).includes(x));
  return []
    .concat((r.pageErrors || []).filter(keep).map((s) => 'исключение: ' + s))
    .concat((r.consoleErrors || []).filter(keep).map((s) => 'console.error: ' + s))
    .concat((r.consoleWarnings || []).filter(keep).map((s) => 'console.warn: ' + s))
    .concat((r.unhandled || []).filter(keep).map((s) => 'unhandledrejection: ' + s));
}

function resultRe(marker, endMarker) {
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(esc(marker) + '(\\{[\\s\\S]*?\\})' + esc(endMarker));
}

/**
 * ЕДИНЫЙ способ выполнить страницу-стенд и забрать её измерения.
 *
 * Стенды харнессов сами считают геометрию и кладут результат в DOM как
 * `<marker>{...}<endMarker>` — раньше это вынимали регулярным выражением из stdout `--dump-dom`.
 * Здесь то же выражение применяется к outerHTML, полученному по CDP: смысл проверок не меняется,
 * меняется только транспорт. Отсутствие результата — ИСКЛЮЧЕНИЕ (таймаут с причиной), не SKIP.
 *
 * Возвращает { res, dom, consoleErrors, consoleWarnings, pageErrors, unhandled }.
 */
export async function measure(opts = {}) {
  // ДВЕ попытки. Подъём headless-движка работает с внешними ресурсами (временный профиль, порт,
  // файлы) и под посторонней нагрузкой изредка срывается — за полный прогон набора это давало
  // один сорванный сценарий из шести десятков. Настоящий дефект проваливает ОБЕ попытки, поэтому
  // ни один порог не ослаблен: это повтор операции над средой, а не смягчение проверки.
  try {
    return await measureOnce(opts);
  } catch (e) {
    await sleep(1500);
    return await measureOnce(opts);
  }
}

async function measureOnce(opts = {}) {
  const marker = opts.marker || '@@RES@@';
  const endMarker = opts.endMarker || '@@END@@';
  const re = resultRe(marker, endMarker);
  const inPage = 'new RegExp(' + JSON.stringify(re.source) + ').test(document.documentElement.outerHTML)';
  const ready = Object.assign({}, opts.ready || {});
  return withStage(Object.assign({}, opts, { ready }), async (st) => {
    await st.waitFor(inPage, {
      timeoutMs: opts.resultTimeoutMs || 45000,
      what: 'страница-стенд не вернула результат ' + marker + '{...}' + endMarker,
    });
    if (opts.script) await st.evaluate(opts.script, { awaitPromise: true });
    const dom = await st.outerHTML();
    if (opts.shot) await st.screenshot(opts.shot);
    const diag = await st.unhandled();
    const m = re.exec(dom || '');
    if (!m) throw new Error('результат ' + marker + ' исчез из документа между ожиданием и чтением');
    let res;
    try { res = JSON.parse(m[1]); } catch (e) { throw new Error('результат стенда не разбирается как JSON: ' + e.message); }
    return {
      res,
      dom: dom || '',
      consoleErrors: st.consoleErrors.slice(),
      consoleWarnings: st.consoleWarnings.slice(),
      pageErrors: st.pageErrors.slice(),
      unhandled: (diag.unhandled || []).concat(diag.errors || []),
      engine: st.engine,
    };
  });
}

/**
 * Совместимая замена прежнего `msedge --dump-dom <url> > stdout`.
 * Возвращает { dom, consoleErrors, consoleWarnings, pageErrors, unhandled } — регулярные выражения
 * харнессов работают по dom без единой правки, а диагностика позволяет краснеть на ошибках страницы.
 */
export async function renderPage(opts = {}) {
  return withStage(opts, async (st) => {
    if (opts.script) await st.evaluate(opts.script, { awaitPromise: true });
    const dom = await st.outerHTML();
    if (opts.shot) await st.screenshot(opts.shot);
    const diag = await st.unhandled();
    return {
      dom: dom || '',
      consoleErrors: st.consoleErrors.slice(),
      consoleWarnings: st.consoleWarnings.slice(),
      pageErrors: st.pageErrors.slice(),
      unhandled: (diag.unhandled || []).concat(diag.errors || []),
      engine: st.engine,
    };
  });
}
