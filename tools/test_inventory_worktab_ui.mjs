// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест верхней части Inventory → «В работе» — inventory 1.7.20.
// 1.7.20: навигация = 2 кнопки (в работе / на складе; кнопка «мало остатка» убрана — дублировала галочку
// «Мало» в «На складе»); toolbar «В работе» = только поиск, прижатый вправо (margin-left:auto).
// Монтирует ДОСЛОВНУЮ из InventoryPanel.js KPI-полосу и toolbar «В работе»; проверяет ВЫПОЛНЕНИЕМ:
//  T — навигация (кнопки) переключает wmode/фильтр + active-state; инфо-сводка (plain, без button/role/
//      tabindex/@click, cursor:default по CSS) НЕ меняет состояние по клику; toolbar «В работе» = только поиск
//      (нет «Добавить катушку»/«Скрыть пустые»/счётчика); линия под sticky-заголовками убрана (CSS без
//      border-bottom, но position:sticky/top:0/z-index сохранены); «Добавить катушку» осталась в «На складе».
// Запуск: node tools/test_inventory_worktab_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM ───────────
class DNode { constructor(t){ this.nodeType=t; this.childNodes=[]; this.parentNode=null; }
  get nextSibling(){ const p=this.parentNode; if(!p) return null; const i=p.childNodes.indexOf(this); return i>=0?(p.childNodes[i+1]||null):null; }
  _link(c,a){ if(c.parentNode)c.parentNode.removeChild(c); c.parentNode=this; if(a&&a.parentNode===this)this.childNodes.splice(this.childNodes.indexOf(a),0,c); else this.childNodes.push(c); return c; }
  insertBefore(c,a){ return this._link(c,a); } appendChild(c){ return this._link(c,null); }
  removeChild(c){ const i=this.childNodes.indexOf(c); if(i>=0)this.childNodes.splice(i,1); c.parentNode=null; return c; }
  getRootNode(){ return globalThis.document; } get ownerDocument(){ return globalThis.document; } }
class DText extends DNode { constructor(t){ super(3); this.nodeValue=t==null?'':String(t); } get data(){ return this.nodeValue; } set data(v){ this.nodeValue=v; } }
class DComment extends DNode { constructor(t){ super(8); this.nodeValue=t==null?'':String(t); } }
class DElement extends DNode {
  constructor(tag){ super(1); this._tag=tag; this.tagName=String(tag).toUpperCase(); this.namespaceURI='http://www.w3.org/1999/xhtml'; this.attributes={}; this._listeners={}; this.style={}; this._cls=''; this._value=''; }
  setAttribute(k,v){ this.attributes[k]=String(v); if(k==='class')this._cls=String(v); }
  removeAttribute(k){ delete this.attributes[k]; if(k==='class')this._cls=''; }
  getAttribute(k){ return k in this.attributes?this.attributes[k]:null; }
  hasAttribute(k){ return k in this.attributes; }
  get className(){ return this._cls; } set className(v){ this._cls=v==null?'':String(v); this.attributes['class']=this._cls; }
  get value(){ return this._value; } set value(v){ this._value=v==null?'':String(v); }
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
const { createApp, ref, nextTick } = Vue;

// ─────────── извлечение балансированного <div class="X">…</div> ───────────
const sliceDiv = (src, startStr) => {
  const s = src.indexOf(startStr); if (s < 0) throw new Error('not found: ' + startStr);
  const openEnd = src.indexOf('>', s) + 1;
  const re = /<div\b|<\/div>/g; re.lastIndex = openEnd; let m, d = 1, c = -1;
  while ((m = re.exec(src))) { d += (m[0] === '</div>') ? -1 : 1; if (d === 0) { c = m.index; break; } }
  return src.slice(s, c + 6);
};
const CARD_CSS = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); return new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))().join('\n'); })();
const KPI = sliceDiv(PANEL, '<div v-if="tab===\'warehouse\'" class="fm-inv-kpis">').replace('v-if="tab===\'warehouse\'"', 'v-if="true"');
const TOOLBAR = sliceDiv(PANEL, '<div class="fm-inv-toolbar"><input v-model="q" class="fm-inv-search" style="margin-left:auto" :placeholder="L(\'Поиск: материал, цвет, принтер');
check('T0. извлечены KPI-полоса и toolbar «В работе»; svg-icon в toolbar нет (кнопок не осталось)',
  KPI.includes('fm-inv-nav') && KPI.includes('fm-inv-sum') && TOOLBAR.includes('fm-inv-search') && !TOOLBAR.includes('<button') && !TOOLBAR.includes('svg-icon'));

const byCls = (root, c) => root._findAll(e => (' ' + (e.getAttribute('class')||'') + ' ').includes(' ' + c + ' '));
const clickEl = (el) => el._fire('click', { type:'click', target:el, currentTarget:el, stopPropagation(){}, preventDefault(){} });

// ─────────── монтаж KPI + toolbar ───────────
const wmode = ref('work'); const fLow = ref(false); const q = ref('');
const kpi = { bound: 3, stock: 12, low: 2, kg: '5.4', types: 4, total: 18 };
const comp = { setup(){ return { wmode, fLow, q, kpi, L:(ru)=>ru }; },
  template: '<div class="root">' + KPI + TOOLBAR + '</div>', compilerOptions: { decodeEntities: (x) => x } };
const app = createApp(comp); app.config.warnHandler = () => {};
const root = new DElement('div'); app.mount(root); await nextTick();

// T1: toolbar «В работе» = ТОЛЬКО поиск
{
  const tb = byCls(root, 'fm-inv-toolbar')[0];
  const inputs = tb._findAll(e => e._tag === 'input');
  const buttons = tb._findAll(e => e._tag === 'button');
  check('T1. toolbar «В работе»: ровно 1 поиск (input.fm-inv-search), 0 кнопок, нет счётчика (.fm-inv-stat) и spacer',
    inputs.length === 1 && (inputs[0].getAttribute('class')||'').includes('fm-inv-search') && buttons.length === 0
    && byCls(root, 'fm-inv-stat').length === 0 && byCls(root, 'fm-inv-spacer').length === 0);
}

// T2: навигация = 3 кнопки; сводка = 3 plain div (не button, без role/tabindex/@click)
{
  const nav = byCls(root, 'fm-inv-nav')[0];
  const navBtns = nav._findAll(e => e._tag === 'button');
  const sum = byCls(root, 'fm-inv-sum')[0];
  const sumItems = byCls(root, 'fm-inv-sum-i');
  check('T2. навигация .fm-inv-nav = 2 <button> (в работе/на складе; «мало остатка» убрана); сводка .fm-inv-sum = 3 <div>.fm-inv-sum-i (НЕ button, без role/tabindex/click-listener)',
    navBtns.length === 2 && !!sum && sumItems.length === 3
    && sumItems.every(e => e._tag === 'div' && !e.getAttribute('role') && e.getAttribute('tabindex') == null && !(e._listeners && e._listeners.click))
    && sum._findAll(e => e._tag === 'button').length === 0);
}

// T3: навигация интерактивна — клик переключает wmode + active-state
{
  const nav = byCls(root, 'fm-inv-nav')[0];
  const navBtns = nav._findAll(e => e._tag === 'button');
  clickEl(navBtns[1]); await nextTick();   // «на складе»
  const stockActive = wmode.value === 'stock' && (navBtns[1].getAttribute('class')||'').includes('on') && !(navBtns[0].getAttribute('class')||'').includes('on');
  clickEl(navBtns[0]); await nextTick();   // «в работе»
  const workActive = wmode.value === 'work' && (navBtns[0].getAttribute('class')||'').includes('on') && !(navBtns[1].getAttribute('class')||'').includes('on');
  check('T3. навигация интерактивна: клик по «на складе»/«в работе» переключает wmode + active-state (.on) корректно (кнопка «мало» убрана; fLow — галочкой в «На складе»)',
    stockActive && workActive);
}

// T4: клик по инфо-сводке НЕ меняет состояние (не кнопка)
{
  wmode.value = 'work'; fLow.value = false; await nextTick();
  const sumItems = byCls(root, 'fm-inv-sum-i');
  clickEl(sumItems[0]); clickEl(sumItems[1]); clickEl(sumItems[2]); await nextTick();
  check('T4. клик по любому элементу инфо-сводки НЕ меняет wmode/fLow (сводка некликабельна)',
    wmode.value === 'work' && fLow.value === false);
}

// T5: CSS — сводка cursor:default без hover/active-рамки; линия под sticky-заголовками убрана, sticky сохранён
{
  const sumCss = /\.fm-inv-sum\{[^}]*cursor:default[^}]*\}/.test(CARD_CSS);
  const noActiveOnSum = !/\.fm-inv-sum(\.on|-i\.on)/.test(CARD_CSS) && !/\.fm-inv-sum-i:hover/.test(CARD_CSS);
  const prowH = (CARD_CSS.match(/\.fm-inv-prow-h\{[^}]*\}/) || [''])[0];
  // 1.7.19: шапка несёт и .fm-inv-prow (даёт border-bottom), поэтому линия гасится ЯВНО через border-bottom:none
  // ИМЕННО на .fm-inv-prow-h; не должно быть рисующей границы (1px/solid) и псевдоэлемента-линии.
  check('T5. CSS: .fm-inv-sum cursor:default без hover/active; .fm-inv-prow-h гасит нижнюю линию (border-bottom:none, без 1px/solid и без ::after/::before), position:sticky/top:0/z-index/непрозрачный фон сохранены',
    sumCss && noActiveOnSum
    && /border-bottom:none/.test(prowH) && !/border-bottom:\s*(?:\d|thin|medium|thick|solid)/.test(prowH)
    && !/\.fm-inv-prow-h::(after|before)/.test(CARD_CSS)
    && /position:sticky/.test(prowH) && /top:0/.test(prowH) && /z-index:\d/.test(prowH) && /background:var\(--fm-surface-raised\)/.test(prowH));
}

// T6: «Добавить катушку» РОВНО одна во всём шаблоне (осталась в «На складе», убрана из «В работе»)
check('T6. «Добавить катушку» (openAdd) осталась РОВНО в одном месте — вкладка «На складе» (из «В работе» удалена)',
  (PANEL.match(/@click="openAdd\(\)"[^>]*><svg-icon name="add"/g) || []).length === 1
  && PANEL.includes("L('Добавить катушку','Add spool')"));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: верх «В работе» — навигация (кнопки, wmode+active) и инфо-сводка (plain, cursor:default, некликабельна) разделены; toolbar только поиск; линия под sticky-заголовками убрана (sticky/top:0/z-index сохранены); «Добавить катушку» лишь в «На складе» (реальный Vue mount)'));
process.exit(fail ? 1 : 0);
