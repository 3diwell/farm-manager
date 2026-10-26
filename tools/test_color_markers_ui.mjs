// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест цветовых маркеров материала — Alpha 2.736 / inventory 1.7.16.
// Часть S: ДОСЛОВНО извлечённый safeHex (из web/app.js И modules/inventory/web/InventoryPanel.js) —
//          безопасная HEX-нормализация: #RGB/RGB/#RRGGBB/RRGGBB/#RRGGBBAA/RRGGBBAA → '#RRGGBB' upper;
//          пусто/служебное/CSS/URL/';'/не-hex → null. Обе копии идентичны по поведению.
// Часть I: прямоугольный маркер варианта склада (.fm-inv-vsw) на вендорном Vue — заливка реальным цветом,
//          fallback при невалидном, сосуществование с checkbox (.fm-inv-cb) в режиме выбора.
// Часть P: круглый маркер карточки принтера (.pc-fil-dot) поверх ДОСЛОВНО извлечённого filamentRows ядра —
//          цвет КАЖДОЙ строки независим (external/AMS/multi-AMS/AMS HT), null→нейтраль, нет provider→[] fail-open.
// Запуск: node tools/test_color_markers_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (со стилем-объектом для чтения заливки) ───────────
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
const { createApp, ref, reactive, nextTick } = Vue;

// ─────────── извлечение ДОСЛОВНОГО `const NAME = <expr>;` ───────────
const extractConst = (src, name) => {
  const anchor = 'const ' + name + ' = '; const i = src.indexOf(anchor);
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) { const ch = src[k];
    if (esc) { esc = false; continue; } if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if ('([{'.includes(ch)) d++; else if (')]}'.includes(ch)) d--; else if (ch === ';' && d === 0) return src.slice(i, k + 1); }
  throw new Error('unbalanced: ' + name);
};

// ═══════════════ ЧАСТЬ S: safeHex (обе копии — ядро + модуль) ═══════════════
const SRC_SAFE_APP = extractConst(APPJS, 'safeHex');
const SRC_SAFE_INV = extractConst(PANEL, 'safeHex');
const safeHexApp = new Function(SRC_SAFE_APP + '; return safeHex;')();
const safeHexInv = new Function(SRC_SAFE_INV + '; return safeHex;')();
check('S0. safeHex извлечён из ядра и модуля; НЕ путём построения style из сырого текста',
  SRC_SAFE_APP.includes('safeHex') && SRC_SAFE_INV.includes('safeHex') && /\[0-9a-fA-F\]\{6\}/.test(SRC_SAFE_APP));
const cases = [
  ['#FF0000', '#FF0000'], ['FF0000', '#FF0000'], ['#00AEEF', '#00AEEF'], ['00aeef', '#00AEEF'],
  ['#f00', '#FF0000'], ['f00', '#FF0000'], ['#FF0000AA', '#FF0000'], ['ff0000aa', '#FF0000'],
  ['#FFFFFF', '#FFFFFF'], ['000000', '#000000'],
  ['', null], ['   ', null], [null, null], [undefined, null], ['red', null], ['transparent', null],
  ['red; background:url(x)', null], ['12px', null], ['#12', null], ['#1234567', null], [' #FF0000', '#FF0000'],
];
let sok = true, imismatch = false;
for (const [inp, exp] of cases) { if (safeHexApp(inp) !== exp) sok = false; if (safeHexApp(inp) !== safeHexInv(inp)) imismatch = true; }
check('S1. safeHex: #RGB/RGB/#RRGGBB/RRGGBB/#RRGGBBAA/RRGGBBAA → #RRGGBB upper; пусто/служебное/CSS/URL/не-hex → null (все кейсы)', sok);
check('S2. обе копии safeHex (ядро/модуль) дают ИДЕНТИЧНЫЙ результат', !imismatch);

// ═══════════════ ЧАСТЬ I: прямоугольный маркер варианта склада (.fm-inv-vsw) ═══════════════
const invSwatch = (colorHex, selMode) => {
  const state = { v: reactive({ color_hex: colorHex }), selMode: ref(!!selMode), sel: reactive({ all: false, some: false }) };
  const comp = { setup(){ const safeHex = safeHexInv; return { safeHex, v: state.v, selMode: state.selMode, sel: state.sel }; },
    // ДОСЛОВНАЯ пара из InventoryPanel.js: checkbox (только selMode) + декоративный swatch
    template: '<div class="vhead">'
      + '<span v-if="selMode" class="fm-inv-cb" :class="{on: sel.all, ind: sel.some}" role="checkbox"></span>'
      + '<span class="fm-inv-vsw" :style="{background: safeHex(v.color_hex) || \'var(--fm-border-strong)\'}"></span>'
      + '</div>', compilerOptions: { decodeEntities: (x) => x } };
  const app = createApp(comp); app.config.warnHandler = () => {};
  const root = new DElement('div'); app.mount(root);
  return { root, state };
};
const swOf = (root) => root._findAll(e => (e.getAttribute('class')||'').split(/\s+/).includes('fm-inv-vsw'))[0];
const cbOf = (root) => root._findAll(e => (e.getAttribute('class')||'').split(/\s+/).includes('fm-inv-cb'));

{ const { root } = invSwatch('FF0000', false); await nextTick();
  check('I1a. вариант #FF0000 → .fm-inv-vsw background = #FF0000', swOf(root) && swOf(root).style.background === '#FF0000'); }
{ const { root } = invSwatch('00AEEF', false); await nextTick();
  check('I1b. вариант #00AEEF → background = #00AEEF (два разных цвета — разные заливки)', swOf(root) && swOf(root).style.background === '#00AEEF'); }
{ const rW = invSwatch('FFFFFF', false).root, rB = invSwatch('000000', false).root; await nextTick();
  check('I2. белый #FFFFFF и чёрный #000000 корректно заливаются (различимость даёт CSS-обводка .fm-inv-vsw border+inset ring)',
    swOf(rW).style.background === '#FFFFFF' && swOf(rB).style.background === '#000000'); }
{ const rEmpty = invSwatch('', false).root, rBad = invSwatch('red; background:url(x)', false).root, rNull = invSwatch(null, false).root; await nextTick();
  check('I3. невалидный/пустой/CSS-инъекция → нейтральный fallback var(--fm-border-strong) (сырой текст в style НЕ попадает)',
    swOf(rEmpty).style.background === 'var(--fm-border-strong)' && swOf(rBad).style.background === 'var(--fm-border-strong)' && swOf(rNull).style.background === 'var(--fm-border-strong)'); }
{ const { root } = invSwatch('FF0000', true); await nextTick();
  check('I4. режим выбора: checkbox .fm-inv-cb СОХРАНЁН РЯДОМ со swatch (маркер не заменяет и не ломает выбор; второго цветового маркера нет)',
    cbOf(root).length === 1 && swOf(root) && swOf(root).style.background === '#FF0000' && root._findAll(e=>(e.getAttribute('class')||'').includes('fm-inv-vsw')).length === 1); }
{ const { root } = invSwatch('FF0000', false); await nextTick();
  check('I5. без режима выбора: checkbox отсутствует, swatch залит', cbOf(root).length === 0 && swOf(root).style.background === '#FF0000'); }

// ═══════════════ ЧАСТЬ P: круглый маркер карточки принтера (.pc-fil-dot) на РЕАЛЬНОМ filamentRows ═══════════════
const SRC_FILROWS = extractConst(APPJS, 'filamentRows');
const buildCore = (fil) => new Function('env', [
  'const { printerFilament, amsGroups, amsIsHt, lang } = env;',
  SRC_SAFE_APP, SRC_FILROWS, 'return { safeHex, filamentRows };'
].join('\n'))({
  printerFilament: { value: { P1: fil } },
  amsGroups: () => [{ unit: 0, label: 'AMS 1' }, { unit: 1, label: 'AMS 2' }, { unit: 128, label: 'AMS HT' }],
  amsIsHt: (u) => u != null && u >= 128,
  lang: { value: 'ru' },
});
const FIL = { slots: [
  { external: true, spool: { color_hex: 'FF0000', material: 'PLA', weight_remaining_g: 500, weight_total_g: 1000 } },          // внешняя → красный
  { unit: 0, tray: 0, index: 0, spool: { color_hex: '00aeef', material: 'PETG', weight_remaining_g: 800, weight_total_g: 1000 } }, // AMS слот 0
  { unit: 0, tray: 1, index: 1, spool: { color_hex: '#FFFFFF', material: 'ABS', weight_remaining_g: 300, weight_total_g: 1000 } }, // AMS слот 1 (белый)
  { unit: 1, tray: 1, index: 5, spool: { color_hex: '000000', material: 'PLA', weight_remaining_g: 100, weight_total_g: 1000 } },  // multi-AMS слот 5 (чёрный)
  { unit: 128, tray: 0, index: 512, spool: { color_hex: '12ab34', material: 'PA', weight_remaining_g: 900, weight_total_g: 1000 } }, // AMS HT / index 512
  { unit: 1, tray: 2, index: 6, spool: { color_hex: 'red; url(x)', material: 'TPU', weight_remaining_g: 200, weight_total_g: 1000 } }, // невалидный цвет
] };
const core = buildCore(FIL);
const rows = core.filamentRows({ id: 'P1' });
check('P0. filamentRows извлечён из ядра; вернул 6 строк (по одной на привязанный слот)', Array.isArray(rows) && rows.length === 6);
check('P1. внешняя катушка #FF0000 → row.hex=#FF0000, подпись «Внешняя катушка»', rows[0].hex === '#FF0000' && rows[0].label === 'Внешняя катушка');
check('P2. обычные AMS-слоты разного цвета → КАЖДЫЙ свой hex независимо (00AEEF слот0, FFFFFF слот1)',
  rows[1].hex === '#00AEEF' && rows[2].hex === '#FFFFFF' && rows[1].hex !== rows[2].hex);
check('P3. multi-AMS index 5 (#000000) и AMS HT index 512 (#12AB34) сохраняют СВОИ цвета и подписи',
  rows[3].hex === '#000000' && rows[4].hex === '#12AB34' && rows[4].label === 'AMS HT·1' && rows[3].label === 'AMS 2·2');
check('P4. невалидный цвет → row.hex="" (в шаблоне даст нейтральный var(--fm-neutral-29))', rows[5].hex === '');
check('P5. цвет каждой строки НЕЗАВИСИМ — не цвет активного слота на всех (6 значений, 5 разных валидных + 1 пустой)',
  new Set(rows.map(r => r.hex)).size === 6);

// РЕАЛЬНЫЙ монтаж круглого маркера (.pc-fil-dot) поверх этих строк
const comp = { setup(){ return { rows: ref(rows) }; },
  template: '<div><div v-for="r in rows" :key="r.key" class="pc-fil-row"><span class="pc-fil-dot" :style="{ backgroundColor: r.hex || \'var(--fm-neutral-29)\' }"></span></div></div>',
  compilerOptions: { decodeEntities: (x) => x } };
const app = createApp(comp); app.config.warnHandler = () => {};
const root = new DElement('div'); app.mount(root); await nextTick();
const dots = root._findAll(e => (e.getAttribute('class')||'').split(/\s+/).includes('pc-fil-dot'));
check('P6. монтаж .pc-fil-dot: 6 кругов, каждый залит цветом своей строки (external красный, HT #12AB34), невалидный → нейтраль',
  dots.length === 6 && dots[0].style.backgroundColor === '#FF0000' && dots[2].style.backgroundColor === '#FFFFFF'
  && dots[3].style.backgroundColor === '#000000' && dots[4].style.backgroundColor === '#12AB34'
  && dots[5].style.backgroundColor === 'var(--fm-neutral-29)');

// нет generic provider (принтер вне снимка) → fail-open, пустой список, без падения
const rowsNP = core.filamentRows({ id: 'PX_missing' });
check('P7. без данных provider (принтер вне printerFilament) → filamentRows=[] (fail-open, без падения)', Array.isArray(rowsNP) && rowsNP.length === 0);

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: цветовые маркеры — safeHex (ядро+модуль, все форматы/reject), маркер варианта склада (.fm-inv-vsw заливка/fallback/checkbox coexist), круглый маркер карточки (.pc-fil-dot на реальном filamentRows: external/AMS/multi/HT независимо, null→нейтраль, нет provider→fail-open)'));
process.exit(fail ? 1 : 0);
