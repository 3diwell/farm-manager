// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Alpha 2.841 / этап 3A — драйвер декларативного UI-сценария поверх ОБЩЕЙ реализации CDP.
//
// ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. В проекте уже есть единственная реализация протокола —
// tools/_edge_cdp_lib.mjs, и копировать её нельзя. Но существующий CLI tools/_edge_cdp.mjs умеет
// ровно один снимок за запуск и не ведёт журнал сетевых обращений, а верификатору нужны снимки
// «до» и «после» в ОДНОЙ сессии и доказательство, что страница никуда наружу не ходила.
// Поэтому здесь тонкая надстройка над той же библиотекой, без своей работы с протоколом.
//
// ЧТО ИСПОЛНЯЕТ. Только декларативные действия из сценария. Произвольный JavaScript из сценария
// не принимается: тип действия обязан быть из списка ниже, селектор уходит в страницу
// исключительно через JSON.stringify, кода из конфигурации не исполняется.
//
// Использование: node _ui_driver.mjs <config.json>
// Результат кладётся в <config.result_path>. stdout содержит короткую строку статуса.
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { openStage } from '../../_edge_cdp_lib.mjs';

const CFG_PATH = process.argv[2];
if (!CFG_PATH || !existsSync(CFG_PATH)) {
  process.stdout.write('CONFIG_MISSING\n');
  process.exit(2);
}
const CFG = JSON.parse(readFileSync(CFG_PATH, 'utf8'));

const ALLOWED = new Set(['wait_for_selector', 'click', 'fill', 'press', 'set_viewport',
  'screenshot', 'read_text', 'assert_visible', 'assert_hidden', 'assert_text',
  'assert_attribute']);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (v) => JSON.stringify(String(v == null ? '' : v));

const OUT = {
  ok: false, application_mode: CFG.application_mode || 'unknown',
  actions: [], assertions: [], screenshots: [], reads: {},
  console: { errors: [], warnings: [], pageErrors: [], unhandled: [] },
  network: [], documentTitle: '', bridgeError: null, timedOut: false,
};

function record(kind, index, type, status, detail) {
  const row = { index, type, status, detail: String(detail || '').slice(0, 400) };
  (kind === 'assert' ? OUT.assertions : OUT.actions).push(row);
  return status === 'pass';
}

// ── Выражения, уходящие в страницу. Селектор всегда экранируется, кода из сценария нет. ──
const JS_VISIBLE = (sel) => `(function(){var e=document.querySelector(${q(sel)});
  if(!e) return 'absent';
  var s=getComputedStyle(e), r=e.getBoundingClientRect();
  if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity||'1')===0) return 'styled-hidden';
  if(r.width<=0||r.height<=0) return 'zero-size';
  return 'visible';})()`;

const JS_TEXT = (sel) => `(function(){var e=document.querySelector(${q(sel)});
  return e?(e.textContent||'').trim().slice(0,500):null;})()`;

const JS_ATTR = (sel, name) => `(function(){var e=document.querySelector(${q(sel)});
  return e?String(e.getAttribute(${q(name)})):null;})()`;

// Клик как у пользователя: настоящее событие с bubbles, чтобы сработал обработчик Vue.
const JS_CLICK = (sel, variants) => `(function(){
  var list=[].slice.call(document.querySelectorAll(${q(sel)}));
  var want=${JSON.stringify(variants || [])};
  var el=null;
  if(want.length){ for(var i=0;i<list.length;i++){ var t=(list[i].textContent||'');
      for(var j=0;j<want.length;j++){ if(t.indexOf(want[j])>=0){ el=list[i]; break; } }
      if(el) break; } }
  else el=list[0];
  if(!el) return 'absent';
  el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));
  return 'clicked';})()`;

const JS_FILL = (sel, value) => `(function(){var e=document.querySelector(${q(sel)});
  if(!e) return 'absent';
  e.focus(); e.value=${q(value)};
  e.dispatchEvent(new Event('input',{bubbles:true}));
  e.dispatchEvent(new Event('change',{bubbles:true}));
  return 'filled';})()`;

const JS_PRESS = (sel, key) => `(function(){var e=${sel ? `document.querySelector(${q(sel)})` : 'document.activeElement||document.body'};
  if(!e) return 'absent';
  var o={key:${q(key)},bubbles:true,cancelable:true};
  e.dispatchEvent(new KeyboardEvent('keydown',o));
  e.dispatchEvent(new KeyboardEvent('keyup',o));
  return 'pressed';})()`;

// Журнал сети. Resource Timing покрывает ВСЁ, что страница уже загрузила к моменту опроса,
// включая загрузку до установки перехватчиков; обёртки покрывают фазу действий.
const JS_NET_HOOK = `(function(){
  if(window.__fmNetLog) return 'already';
  window.__fmNetLog=[];
  var push=function(kind,u){ try{ window.__fmNetLog.push({kind:kind,url:String(u)}); }catch(e){} };
  var of=window.fetch;
  if(of) window.fetch=function(){ push('fetch',(arguments[0]&&arguments[0].url)||arguments[0]);
    return of.apply(this,arguments); };
  var ox=window.XMLHttpRequest&&window.XMLHttpRequest.prototype.open;
  if(ox) window.XMLHttpRequest.prototype.open=function(m,u){ push('xhr',u);
    return ox.apply(this,arguments); };
  var ow=window.WebSocket;
  if(ow){ window.WebSocket=function(u,p){ push('websocket',u); return new ow(u,p); };
    window.WebSocket.prototype=ow.prototype; }
  var oe=window.EventSource;
  if(oe){ window.EventSource=function(u,c){ push('eventsource',u); return new oe(u,c); };
    window.EventSource.prototype=oe.prototype; }
  return 'installed';})()`;

const JS_NET_DUMP = `JSON.stringify((function(){
  var out=[];
  try{ var nav=performance.getEntriesByType('navigation')||[];
       for(var i=0;i<nav.length;i++) out.push({kind:'navigation',url:String(nav[i].name)}); }catch(e){}
  try{ var res=performance.getEntriesByType('resource')||[];
       for(var j=0;j<res.length;j++) out.push({kind:String(res[j].initiatorType||'resource'),
                                               url:String(res[j].name)}); }catch(e){}
  try{ var lg=window.__fmNetLog||[]; for(var k=0;k<lg.length;k++) out.push(lg[k]); }catch(e){}
  return out;})())`;

async function waitFor(stage, expression, timeoutMs, wanted) {
  const deadline = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < deadline) {
    last = await stage.evaluate(expression);
    if (String(last) === wanted) return { ok: true, last };
    await sleep(120);
  }
  return { ok: false, last };
}

let stage = null;
let hardTimer = null;
try {
  mkdirSync(dirname(CFG.result_path), { recursive: true });
  mkdirSync(CFG.artifacts_dir, { recursive: true });

  hardTimer = setTimeout(() => {
    OUT.timedOut = true;
    try { writeFileSync(CFG.result_path, JSON.stringify(OUT), 'utf8'); } catch { /* нечего */ }
    process.stdout.write('TIMEOUT\n');
    process.exit(4);
  }, Math.max(20000, (CFG.timeout_seconds || 180) * 1000));

  stage = await openStage({
    url: CFG.url,
    width: (CFG.viewport && CFG.viewport.width) || 1440,
    height: (CFG.viewport && CFG.viewport.height) || 900,
    extraArgs: CFG.extra_args || [],
    engine: CFG.engine,
    profileHint: CFG.profile_dir,
  });
  await sleep(CFG.settle_ms || 1500);
  await stage.evaluate(JS_NET_HOOK);
  OUT.documentTitle = String(await stage.evaluate('document.title') || '');

  for (let i = 0; i < (CFG.actions || []).length; i++) {
    const a = CFG.actions[i] || {};
    const t = String(a.type || '');
    const to = Math.max(500, Math.min(60000, a.timeout_ms || 8000));
    if (!ALLOWED.has(t)) { record('action', i, t, 'fail', 'действие не разрешено'); break; }

    if (t === 'wait_for_selector') {
      const r = await waitFor(stage, JS_VISIBLE(a.selector), to, 'visible');
      if (!record('action', i, t, r.ok ? 'pass' : 'fail', `${a.selector} -> ${r.last}`)) break;
    } else if (t === 'click') {
      const r = await stage.evaluate(JS_CLICK(a.selector, a.text_any_of));
      // optional — для предусловий, которых может не быть (окно тура показывается не всегда).
      // На проверки это не распространяется: assert_* обязательны всегда.
      const st = String(r) === 'clicked' ? 'pass' : (a.optional ? 'skipped' : 'fail');
      record('action', i, t, st, `${a.selector} -> ${r}`);
      if (st === 'fail') break;
      await sleep(a.settle_ms || 700);
    } else if (t === 'fill') {
      const r = await stage.evaluate(JS_FILL(a.selector, a.value));
      if (!record('action', i, t, String(r) === 'filled' ? 'pass' : 'fail', String(r))) break;
    } else if (t === 'press') {
      const r = await stage.evaluate(JS_PRESS(a.selector, a.key));
      if (!record('action', i, t, String(r) === 'pressed' ? 'pass' : 'fail', String(r))) break;
      await sleep(a.settle_ms || 400);
    } else if (t === 'set_viewport') {
      await stage.send('Emulation.setDeviceMetricsOverride', {
        width: Math.round(a.width), height: Math.round(a.height),
        deviceScaleFactor: Number(a.zoom) || 1, mobile: false });
      record('action', i, t, 'pass', `${a.width}x${a.height}`);
      await sleep(400);
    } else if (t === 'screenshot') {
      const name = String(a.name || `shot_${i}.png`);
      const p = join(CFG.artifacts_dir, name);
      await stage.screenshot(p);
      OUT.screenshots.push(name);
      record('action', i, t, existsSync(p) ? 'pass' : 'fail', name);
    } else if (t === 'read_text') {
      const v = await stage.evaluate(JS_TEXT(a.selector));
      OUT.reads[a.name || a.selector] = v === null ? null : String(v);
      record('action', i, t, v === null ? 'fail' : 'pass', String(v).slice(0, 120));
    } else if (t === 'assert_visible') {
      const r = await waitFor(stage, JS_VISIBLE(a.selector), to, 'visible');
      if (!record('assert', i, t, r.ok ? 'pass' : 'fail', `${a.selector} -> ${r.last}`)) break;
    } else if (t === 'assert_hidden') {
      const deadline = Date.now() + to;
      let last = '';
      let ok = false;
      while (Date.now() < deadline) {
        last = String(await stage.evaluate(JS_VISIBLE(a.selector)));
        if (last !== 'visible') { ok = true; break; }
        await sleep(120);
      }
      if (!record('assert', i, t, ok ? 'pass' : 'fail', `${a.selector} -> ${last}`)) break;
    } else if (t === 'assert_text') {
      const v = String(await stage.evaluate(JS_TEXT(a.selector)) || '');
      const want = a.text_any_of || (a.text ? [a.text] : []);
      const ok = want.some((w) => v.indexOf(w) >= 0);
      if (!record('assert', i, t, ok ? 'pass' : 'fail',
                  `${a.selector} -> "${v.slice(0, 90)}"`)) break;
    } else if (t === 'assert_attribute') {
      const v = String(await stage.evaluate(JS_ATTR(a.selector, a.attribute)));
      const ok = a.expect == null ? v !== 'null' : v === String(a.expect);
      if (!record('assert', i, t, ok ? 'pass' : 'fail',
                  `${a.selector}[${a.attribute}] -> ${v.slice(0, 90)}`)) break;
    }
  }

  try { OUT.network = JSON.parse(String(await stage.evaluate(JS_NET_DUMP) || '[]')); }
  catch { OUT.network = []; }
  const diag = await stage.unhandled();
  OUT.console = {
    errors: stage.consoleErrors || [], warnings: stage.consoleWarnings || [],
    pageErrors: stage.pageErrors || [], unhandled: (diag.unhandled || []).concat(diag.errors || []),
  };
  OUT.ok = true;
} catch (e) {
  OUT.bridgeError = String((e && e.message) || e).slice(0, 400);
} finally {
  if (hardTimer) clearTimeout(hardTimer);
  if (stage) { try { await stage.close(); } catch { /* уже закрыт */ } }
}

try { writeFileSync(CFG.result_path, JSON.stringify(OUT), 'utf8'); } catch { /* нечего */ }
process.stdout.write((OUT.ok ? 'OK' : 'ERROR') + '\n');
process.exit(OUT.ok ? 0 : 1);
