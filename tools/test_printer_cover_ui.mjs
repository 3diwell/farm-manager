// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест единого canonical cover-resolver в UI — Alpha 2.733 / inventory 1.7.15.
// Часть I: ДОСЛОВНО извлечённая миниатюра «Склад → В работе» из shipped InventoryPanel.js монтируется на
//          вендорном Vue: приоритет cover_url → klipper-силуэт → generic; klipper С обложкой показывает PNG
//          (Creality K1 / Prusa MK4S / Voron 2.4 300), Bambu/FF не регрессируют, MT500/пусто/unknown → fallback,
//          404 → fallback, смена cover_url сбрасывает coverBroken, async-появление cover заменяет силуэт.
// Часть A: ДОСЛОВНО извлечённый selectedModelCover из web/app.js — Add Printer берёт ГОТОВЫЙ cover из registry,
//          резолвит legacy (регистр/пробелы), async-registry заменяет fallback, и даёт ТОТ ЖЕ cover, что Inventory.
// Часть M: инвариант — главная карточка использует архетип printerIcon (НЕ PNG cover); PRINTER_ICONS целы.
// Запуск: node tools/test_printer_cover_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
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
const { createApp, ref, reactive, computed, nextTick } = Vue;
const KL_SVG = '<svg viewBox="0 0 10 10" class="owner-printer-icon"><path d="M1 1h8v8H1z"/></svg>';   // стаб owner-иконки Klipper

// ═══════════════ ЧАСТЬ I: миниатюра «В работе» (ДОСЛОВНО из InventoryPanel.js) ═══════════════
const ts = PANEL.indexOf('<span class="fm-inv-pimg"');
const te = PANEL.indexOf('<span class="fm-inv-pcol-t"', ts);
const THUMB = PANEL.slice(ts, te);
check('I0. миниатюра извлечена из shipped-панели; приоритет cover_url → klipper-силуэт → generic; URL из model не строит',
  THUMB.includes('<img v-if="r.cover && !coverBroken[r.cover]" :src="r.cover"') &&
  THUMB.includes('v-else-if="r.kl && klipperSvg"') && THUMB.includes('<svg-icon v-else name="printer">') &&
  !THUMB.includes('coverUrl'));

const makeThumb = (rInit) => {
  const r = reactive(Object.assign({ cover: '', kl: false, model: '' }, rInit));
  const coverBroken = reactive({});
  const comp = { setup(){ return { r, coverBroken, klipperSvg: KL_SVG }; },
    template: '<div class="row">' + THUMB + '</div>', compilerOptions: { decodeEntities: (x) => x } };
  const app = createApp(comp); app.config.warnHandler = () => {};
  app.component('svg-icon', { props: ['name'], template: '<i class="ico" :data-name="name"></i>' });
  const root = new DElement('div'); app.mount(root);
  return { root, r, coverBroken };
};
const imgs = (root) => root._findAll(e => e._tag === 'img');
const kls = (root) => root._findAll(e => (e.getAttribute('class') || '').split(/\s+/).includes('fm-inv-pimg-kl'));
const gens = (root) => root._findAll(e => e._tag === 'i' && e.getAttribute('data-name') === 'printer');
const src = (root) => (imgs(root)[0] || { getAttribute: () => null }).getAttribute('src');

// ── klipper-модели С обложкой → PNG (главный фикс: type=klipper больше НЕ блокирует cover) ──
const KLCOVER = [
  { model: 'Creality K1', cover: '/covers/Creality%20K1_cover.png' },
  { model: 'Prusa MK4S', cover: '/covers/Prusa%20MK4S_cover.png' },
  { model: 'Voron 2.4 300', cover: '/covers/Voron%202.4%20300_cover.png' },
];
for (const m of KLCOVER) {
  const { root } = makeThumb({ cover: m.cover, kl: true, model: m.model });
  await nextTick();
  check('I. ' + m.model + ' (type=klipper, cover_url задан) → <img src="' + m.cover + '">, НЕ силуэт Klipper',
    imgs(root).length === 1 && src(root) === m.cover && kls(root).length === 0 && gens(root).length === 0);
}

// ── Bambu / FlashForge не регрессировали (type≠klipper, cover есть) → PNG ──
for (const m of [{ model: 'Bambu Lab P2S', cover: '/covers/Bambu%20Lab%20P2S_cover.png' },
                 { model: 'Flashforge Adventurer 5M', cover: '/covers/Flashforge%20Adventurer%205M_cover.png' }]) {
  const { root } = makeThumb({ cover: m.cover, kl: false, model: m.model });
  await nextTick();
  check('I. ' + m.model + ' → обложка <img> без регрессии', imgs(root).length === 1 && src(root) === m.cover && kls(root).length === 0);
}

// ── MT500 (klipper, cover_url='') → силуэт Klipper (намеренно) ──
{
  const { root } = makeThumb({ cover: '', kl: true, model: 'MT500' });
  await nextTick();
  check('I. MT500 (type=klipper, cover_url="") → силуэт Klipper, обложки нет (намеренно)',
    imgs(root).length === 0 && kls(root).length === 1);
}
// ── custom klipper с пустой моделью → силуэт Klipper ──
{
  const { root } = makeThumb({ cover: '', kl: true, model: '' });
  await nextTick();
  check('I. custom Klipper (model="", cover_url="") → силуэт Klipper', imgs(root).length === 0 && kls(root).length === 1);
}
// ── unknown/не-klipper без обложки → generic svg-icon printer ──
{
  const { root } = makeThumb({ cover: '', kl: false, model: 'Unknown 9000' });
  await nextTick();
  check('I. unknown non-klipper (cover_url="") → generic <svg-icon name="printer">', imgs(root).length === 0 && kls(root).length === 0 && gens(root).length === 1);
}
// ── image 404 → @error → coverBroken → fallback (силуэт для klipper) ──
{
  const { root } = makeThumb({ cover: '/covers/Creality%20K1_cover.png', kl: true, model: 'Creality K1' });
  await nextTick();
  const wasImg = imgs(root).length === 1;
  imgs(root)[0]._fire('error', { type: 'error' });   // симулируем 404/битый PNG
  await nextTick();
  check('I. image 404 → @error помечает coverBroken → <img> убран, показан силуэт Klipper (fail-open)',
    wasImg && imgs(root).length === 0 && kls(root).length === 1);
}
// ── смена cover_url сбрасывает coverBroken: новый URL грузится, не «залипает» на битом ──
{
  const { root, r } = makeThumb({ cover: '/covers/A%20broken_cover.png', kl: false, model: 'A broken' });
  await nextTick();
  imgs(root)[0]._fire('error', { type: 'error' });   // старый cover битый
  await nextTick();
  const brokenNoImg = imgs(root).length === 0;
  r.cover = '/covers/Creality%20K1_cover.png';        // модель сменилась → новый cover_url
  await nextTick();
  check('I. смена cover_url → прежний coverBroken НЕ блокирует новое изображение (нет «залипания» битой картинки)',
    brokenNoImg && imgs(root).length === 1 && src(root) === '/covers/Creality%20K1_cover.png');
}
// ── async: сначала cover_url пуст (fallback-силуэт), затем пришёл из ядра → заменяет на PNG ──
{
  const { root, r } = makeThumb({ cover: '', kl: true, model: 'Creality K1' });
  await nextTick();
  const first = imgs(root).length === 0 && kls(root).length === 1;
  r.cover = '/covers/Creality%20K1_cover.png';        // /api/printers ответил позже
  await nextTick();
  check('I. async: cover_url пришёл после монтажа → силуэт заменяется на обложку <img> без перезагрузки',
    first && imgs(root).length === 1 && src(root) === '/covers/Creality%20K1_cover.png');
}

// ═══════════════ ЧАСТЬ A: Add Printer selectedModelCover (ДОСЛОВНО из app.js) ═══════════════
const as = APPJS.indexOf('const _normModelKey =');
const ae = APPJS.indexOf('});', APPJS.indexOf('const selectedModelCover = computed(')) + 3;
const ADDPICK = APPJS.slice(as, ae);
check('A0. selectedModelCover извлечён из app.js; НЕ строит /covers/ из сырого model (только готовый cover из registry)',
  ADDPICK.includes('const selectedModelCover = computed(') && !/'\/covers\/'\s*\+/.test(ADDPICK) && !ADDPICK.includes("_cover.png'"));

const newPrinter = ref({ model: '' });
const printerModels = ref([]);
const AP = new Function('Vue', 'env', [
  'const { computed } = Vue;',
  'const { newPrinter, printerModels } = env;',
  ADDPICK,
  'return { _normModelKey, selectedModelCover };',
].join('\n'))(Vue, { newPrinter, printerModels });

// canonical registry (как отдаёт /api/printer-models: name / model_key / cover)
const REG = [
  { name: 'Klipper', cover: '', generic: true },
  { name: 'Creality K1', model_key: 'creality k1', cover: '/covers/Creality%20K1_cover.png' },
  { name: 'Bambu Lab P2S', model_key: 'bambu lab p2s', cover: '/covers/Bambu%20Lab%20P2S_cover.png' },
];
// async: до загрузки registry (пусто) выбранная модель даёт '' → fallback-силуэт в форме
newPrinter.value.model = 'Creality K1';
check('A1. async: registry ещё не загружен → selectedModelCover = "" (форма покажет fallback-силуэт)', AP.selectedModelCover.value === '');
printerModels.value = REG;   // registry пришёл
check('A2. registry загружен → Add Printer показывает ГОТОВЫЙ cover модели из registry (не построенный из model)',
  AP.selectedModelCover.value === '/covers/Creality%20K1_cover.png');
// тот же cover_url, что получит Inventory для этой модели (оба из одного resolver)
check('A3. Add Printer и Inventory для одной модели дают ОДИН cover_url (Creality K1)',
  AP.selectedModelCover.value === KLCOVER[0].cover);
// legacy: регистр/лишние пробелы резолвятся по model_key
newPrinter.value.model = '  creality   k1  ';
check('A4. legacy-ввод (регистр/лишние пробелы) резолвится к тому же cover по model_key', AP.selectedModelCover.value === '/covers/Creality%20K1_cover.png');
// неизвестная/custom модель → '' → fallback (без построения произвольного URL)
newPrinter.value.model = 'Nonexistent 9000';
check('A5. неизвестная модель → selectedModelCover = "" (fallback SVG; произвольный /covers/ не строится)', AP.selectedModelCover.value === '');
newPrinter.value.model = '';
check('A6. пустая модель → "" (чистая форма добавления)', AP.selectedModelCover.value === '');

// ═══════════════ ЧАСТЬ M: главная карточка НЕ переведена на PNG (инвариант) ═══════════════
// index.html: миниатюра главной карточки использует архетип printerIcon(p) (v-html), НЕ /covers/.
check('M1. главная карточка использует архетип v-html="printerIcon(p)"', HTML.includes('v-html="printerIcon(p)"'));
// printerIcon в app.js рисует monoline-архетипы/owner-SVG и НИКОГДА не строит /covers/ (не PNG).
const ps = APPJS.indexOf('const printerIcon = p =>');
const pe = APPJS.indexOf('};', ps) + 2;
const PRICON = APPJS.slice(ps, pe);
check('M2. printerIcon возвращает архетипы (PRINTER_ICONS)/owner-svg и НЕ ссылается на /covers/ (карточка визуально не менялась)',
  PRICON.includes('PRINTER_ICONS.') && PRICON.includes('svgAssets.printer') && !PRICON.includes('/covers/') && !PRICON.includes('cover'));
check('M3. архетипы PRINTER_ICONS (enclosed/dual/open) на месте — карточка не тронута',
  /const PRINTER_ICONS = \{[\s\S]*?enclosed:[\s\S]*?dual:[\s\S]*?open:/.test(APPJS));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: единый cover-resolver в UI — klipper С обложкой показывает PNG (Creality K1/Prusa MK4S/Voron), MT500/custom/unknown → fallback, 404/async/смена cover_url корректны, Add Printer==Inventory один cover_url, главная карточка на архетипах (реальный Vue mount + извлечённые из файлов фрагменты)'));
process.exit(fail ? 1 : 0);
