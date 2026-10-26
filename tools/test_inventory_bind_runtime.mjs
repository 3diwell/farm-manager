// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест привязки AMS-слотов — inventory 1.7.3.
// Монтирует Vue-компоненты НАСТОЯЩИМ вендорным Vue (web/vendor/vue.esm-browser.js) на минимальном
// самодельном DOM (jsdom/happy-dom НЕ ставим — их нет; harness описан ниже) и доказывает во время
// ВЫПОЛНЕНИЯ (не строками):
//   T1  правило Vue: доступ к setup-ключу с префиксом «_» из шаблона бросает ReferenceError (не проксируется);
//   T2  точная репродукция 1.7.2: @click через имя с «_» роняет обработчик -> состояние не меняется;
//   T3  исправленная разметка (bindPrinterObj): клик по реальному DOM-слоту 0 -> active + кнопка доступна;
//   T4  то же для слотов 1/2/3, активен ровно один;
//   T5  «Привязать» шлёт payload с ТОЧНЫМ числовым ams_slot выбранного слота;
//   T6  выбор слота НЕ вызывает fetch; запрос идёт только по «Привязать»;
//   T7  несколько AMS unit: выбирается именно кликнутый слот (index 5 -> ams_slot 5);
//   T8  занятый слот -> «Привязать» открывает подтверждение замены (без немедленной привязки);
//   T9  разметка теста ДОСЛОВНО совпадает с shipped InventoryPanel.js (мост runtime<->файл).
// Harness: класс DElement/DText/DComment реализует ровно тот DOM API, который дёргает Vue 3 runtime-dom
// (createElement/insertBefore/removeChild/nextSibling/textContent/className/style/disabled/add-removeEventListener
// + hasChildNodes/innerHTML/firstChild) и globalThis-заглушки (SVGElement и т.п.) для `instanceof` в mount().
// Клик диспатчится el._fire('click', ev) -> слушатели, зарегистрированные Vue.
// Запуск: node tools/test_inventory_bind_runtime.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM ───────────
class DNode {
  constructor(nodeType) { this.nodeType = nodeType; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(child, anchor) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; if (anchor && anchor.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(anchor), 0, child); } else this.childNodes.push(child); return child; }
  insertBefore(child, anchor) { return this._link(child, anchor); }
  appendChild(child) { return this._link(child, null); }
  removeChild(child) { const i = this.childNodes.indexOf(child); if (i >= 0) this.childNodes.splice(i, 1); child.parentNode = null; return child; }
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; }
  get firstChild() { return this.childNodes[0] || null; }
  get innerHTML() { return ''; }
  set innerHTML(v) { if (v === '' || v == null) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; } }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; }
}
const documentShim = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {} };
documentShim.body = new DElement('body'); documentShim.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = documentShim;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// fetch-счётчик: доказывает, что выбор слота НЕ шлёт запрос (только «Привязать»)
const netCalls = [];
globalThis.fetch = async (url, opts) => { netCalls.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null }); return { ok: true, status: 200, json: async () => ({ ok: true }) }; };

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

const clickEl = (el) => { const ev = { type: 'click', target: el, currentTarget: el, timeStamp: Date.now(), stopPropagation() {}, stopImmediatePropagation() {}, preventDefault() {} }; el._fire('click', ev); };
const mount = (component) => { const app = createApp(component); const root = new DElement('div'); app.mount(root); return root; };
const clsOf = (el) => el.className || '';
const slotButtons = (root) => root._findAll((e) => e._tag === 'button' && clsOf(e).includes('fm-inv-slot'));
const applyButton = (root) => root._findAll((e) => e._tag === 'button' && clsOf(e).includes('applybtn'))[0];
const silence = async (fn) => { const e = console.error; console.error = () => {}; try { return await fn(); } finally { console.error = e; } };

// ═══ T1: доступ к setup-ключу с «_» из шаблона -> render-ошибка ReferenceError; обычное имя работает ═══
// Vue не пробрасывает throw наружу mount: renderComponentRoot ловит ошибку рендера, логирует её через
// console.error и рендерит пустой Comment. Перехватываем console.error и проверяем, что там ReferenceError
// про «_secret», а сам вывод пуст (HIDDEN не отрисовался). Обычный ключ отрисовывается нормально.
{
  let captured = '', underscoreText = 'x';
  const origErr = console.error;
  console.error = (...a) => { captured += a.map((x) => (x && x.stack) || String(x)).join(' '); };
  try { const ru = mount({ setup() { return { _secret: ref('HIDDEN') }; }, template: `<div>{{ _secret }}</div>` }); underscoreText = ru.textContent; }
  finally { console.error = origErr; }
  const rn = mount({ setup() { return { shown: ref('VISIBLE') }; }, template: `<div class="n">{{ shown }}</div>` });
  const normalText = rn._findAll((e) => clsOf(e).includes('n'))[0].textContent;
  check('T1. доступ к setup-ключу с «_» из шаблона -> ReferenceError (не проксируется, вывод пуст); обычное имя работает',
    /_secret/.test(captured) && /not defined|ReferenceError/.test(captured) && underscoreText === '' && normalText === 'VISIBLE');
}

// ═══ T2: точная репродукция 1.7.2 — @click через имя с «_» роняет обработчик, состояние не меняется ═══
{
  const Comp = {
    setup() { const bind = reactive({ slot: -1 }); const _obj = computed(() => ({ id: 'p1' })); const pick = (p, idx) => { if (!p || idx == null || idx < 0) return; bind.slot = idx; }; return { bind, _obj, pick }; },
    template: `<div><button class="s" @click="pick(_obj, 0)">s0</button><span class="v">{{ bind.slot }}</span></div>`,
  };
  const root = mount(Comp);
  await silence(async () => { clickEl(root._findAll((e) => e._tag === 'button')[0]); await nextTick(); });
  check('T2. репродукция 1.7.2: @click через имя с «_» -> обработчик падает, bind.slot остаётся -1',
    root._findAll((e) => clsOf(e).includes('v'))[0].textContent === '-1');
}

// ─────────── ВЕРНАЯ разметка привязки (те же выражения, что в shipped InventoryPanel.js) + верная логика ───────────
const SLOT_MARKUP = '<div v-if="bindSlots.length > 1" class="fm-inv-field"><div class="fm-inv-slots"><button v-for="sl in bindSlots" :key="sl.index" class="fm-inv-slot" :class="{active: bind.slot===bindSlotIndex(sl)}" @click.stop="selectBindSlot(bindPrinterObj, bindSlotIndex(sl))"><span class="fm-inv-slot-n">{{ L(\'Слот\',\'Slot\') + \' \' + (sl.index + 1) }}</span></button></div></div>';
const APPLY_MARKUP = '<button class="applybtn fm-inv-btn primary" :disabled="!canApplyBind" @click="tryBindTarget(bindPrinterObj, bind.slot)">{{ bindBusy ? L(\'Привязка…\',\'Binding…\') : L(\'Привязать\',\'Bind\') }}</button>';
const makeBind = (printer, spoolId, slotMarkup) => ({
  setup() {
    const L = (ru) => ru;
    const flash = () => {};
    const bind = reactive({ sid: spoolId, printer_id: printer.printer_id, slot: -1, bound: false, pick: false, open: true });
    const bindBusy = ref(false);
    const bindConfirm = reactive({ open: false, printerName: '', slotLabel: '', occupant: null, target: null });
    const ams = ref({ printers: [printer] });
    const bindSlots = computed(() => { const p = (ams.value.printers || []).find((x) => x.printer_id === bind.printer_id); return (p && p.slots && p.slots.length) ? p.slots : [{ index: 0, external: true }]; });
    const _slotSpool = (p, idx) => { const sl = ((p && p.slots) || []).find((x) => x.index === idx); return (sl && sl.spool) ? sl.spool : null; };
    // === идентичные shipped-версии (1.7.3) ===
    const bindPrinterObj = computed(() => (ams.value.printers || []).find((x) => x.printer_id === bind.printer_id) || null);
    const bindSlotIndex = (sl) => { const n = Number(sl && sl.index); return Number.isInteger(n) ? n : -1; };
    const selectBindSlot = (p, idx) => { if (!p || idx == null || idx < 0) return; const cur = _slotSpool(p, idx); if (cur && bind.sid && cur.id === bind.sid) { flash(); return; } bind.printer_id = p.printer_id; bind.slot = idx; };
    const bindTargetIsSelf = computed(() => { const p = bindPrinterObj.value; if (!p || bind.slot < 0) return false; const sp = _slotSpool(p, bind.slot); return !!(sp && bind.sid && sp.id === bind.sid); });
    const canApplyBind = computed(() => !!bind.sid && !!bind.printer_id && Number.isInteger(Number(bind.slot)) && Number(bind.slot) >= 0 && !bindBusy.value && !bindTargetIsSelf.value);
    const applyBind = async () => { await fetch('/api/mod/inventory/spool/' + bind.sid + '/bind', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ printer_id: bind.printer_id, ams_slot: bind.slot }) }); bind.open = false; };
    const applyBindGuarded = async () => { if (bindBusy.value) return; if (bind.slot < 0 || !bind.printer_id || !bind.sid) return; bindBusy.value = true; try { await applyBind(); } finally { bindBusy.value = false; } };
    const tryBindTarget = (p, idx) => { if (!p || idx == null || idx < 0) return; const cur = _slotSpool(p, idx); if (cur && bind.sid && cur.id === bind.sid) { flash(); return; } bind.printer_id = p.printer_id; bind.slot = idx; if (cur) { bindConfirm.occupant = cur; bindConfirm.target = { printer_id: p.printer_id, slot: idx }; bindConfirm.open = true; return; } applyBindGuarded(); };
    //  1.7.26: подпись варианта — та же функция, что в поставляемом модуле: внешняя катушка,
    //  метка принтера («Слот T1B») либо порядковый номер.
    const bindSlotName = (sl) => {
      if (!sl) return '';
      if (sl.external) return L('Внешняя катушка', 'External spool');
      if (sl.label) return L('Слот ', 'Slot ') + sl.label;
      return L('Слот', 'Slot') + ' ' + (Number(sl.index) + 1);
    };
    return { L, bind, bindBusy, bindConfirm, bindSlots, bindPrinterObj, bindSlotIndex, selectBindSlot, bindTargetIsSelf, canApplyBind, tryBindTarget, bindSlotName };
  },
  template: '<div class="root">' + (slotMarkup || SLOT_MARKUP) + APPLY_MARKUP + '</div>',
});
const ams4 = { printer_id: 'PRN_A', printer_name: 'X2', has_ams: true, slots: [{ index: 0 }, { index: 1 }, { index: 2 }, { index: 3 }] };

// ═══ T3: клик по реальному DOM-слоту 0 -> active + кнопка доступна ═══
{
  netCalls.length = 0;
  const root = mount(makeBind(ams4, 'spoolX'));
  const btns = slotButtons(root), apply = applyButton(root);
  const before = apply.disabled;
  clickEl(btns[0]); await nextTick();
  check('T3. slot 0: до клика кнопка disabled=true; после клика слот active И кнопка disabled=false',
    before === true && clsOf(btns[0]).includes('active') && apply.disabled === false);
}

// ═══ T4: слоты 1/2/3 выбираются, активен ровно один ═══
{
  const root = mount(makeBind(ams4, 'spoolX'));
  const btns = slotButtons(root), apply = applyButton(root);
  let ok = true;
  for (const i of [1, 2, 3, 0]) {
    clickEl(btns[i]); await nextTick();
    const actives = btns.filter((b) => clsOf(b).includes('active'));
    if (!(actives.length === 1 && clsOf(btns[i]).includes('active') && apply.disabled === false)) ok = false;
  }
  check('T4. слоты 1/2/3/0 по очереди выбираются; активен ровно один; кнопка доступна', ok);
}

// ═══ T5 + T6: «Привязать» шлёт точный числовой ams_slot; выбор НЕ шлёт fetch ═══
{
  netCalls.length = 0;
  const root = mount(makeBind(ams4, 'spoolX'));
  const btns = slotButtons(root), apply = applyButton(root);
  clickEl(btns[2]); await nextTick();
  const afterSelect = netCalls.length;                       // 0 — выбор не шлёт запрос
  clickEl(apply); await nextTick(); await nextTick();
  const req = netCalls[netCalls.length - 1];
  check('T5. payload «Привязать»: ams_slot === 2 (число), верный эндпоинт',
    req && /\/spool\/spoolX\/bind$/.test(req.url) && req.body && req.body.ams_slot === 2 && typeof req.body.ams_slot === 'number' && req.body.printer_id === 'PRN_A');
  check('T6. выбор слота НЕ вызывает fetch (запрос только по «Привязать»)',
    afterSelect === 0 && netCalls.length === 1);
}

// ═══ T7: несколько AMS unit — выбирается именно кликнутый слот (index 5 -> ams_slot 5) ═══
{
  netCalls.length = 0;
  const ams2u = { printer_id: 'PRN_B', printer_name: 'X1C', has_ams: true, slots: [{ index: 0, unit: 0 }, { index: 1, unit: 0 }, { index: 2, unit: 0 }, { index: 3, unit: 0 }, { index: 4, unit: 1 }, { index: 5, unit: 1 }, { index: 6, unit: 1 }, { index: 7, unit: 1 }] };
  const root = mount(makeBind(ams2u, 'spoolY'));
  const btns = slotButtons(root), apply = applyButton(root);
  const b5 = btns.find((b) => b.textContent.trim() === 'Слот 6');   // index 5 -> подпись «Слот 6»
  clickEl(b5); await nextTick();
  clickEl(apply); await nextTick(); await nextTick();
  const req = netCalls[netCalls.length - 1];
  check('T7. мульти-AMS: клик по слоту index 5 -> ams_slot 5 (не смешивает unit), active ровно на нём',
    clsOf(b5).includes('active') && slotButtons(root).filter((b) => clsOf(b).includes('active')).length === 1 && req && req.body.ams_slot === 5);
}

// ═══ T8: занятый слот -> «Привязать» открывает подтверждение замены, без немедленного запроса ═══
{
  netCalls.length = 0;
  const amsOcc = { printer_id: 'PRN_C', printer_name: 'X3', has_ams: true, slots: [{ index: 0 }, { index: 1, spool: { id: 'other', material: 'PETG' } }, { index: 2 }, { index: 3 }] };
  const app = createApp(makeBind(amsOcc, 'spoolZ')); const root = new DElement('div'); const vm = app.mount(root);
  const btns = slotButtons(root), apply = applyButton(root);
  clickEl(btns[1]); await nextTick();                        // выбрать занятый слот 1
  const beforeReq = netCalls.length;
  clickEl(apply); await nextTick();
  // confirm открылся через reactive — проверяем состояние компонента
  const proxy = vm.$ ? vm.$.setupState : null;               // доступ к setupState экземпляра
  const confirmOpen = proxy && proxy.bindConfirm && proxy.bindConfirm.open;
  check('T8. занятый слот: «Привязать» -> подтверждение замены (bindConfirm.open), без немедленного fetch',
    beforeReq === 0 && confirmOpen === true && netCalls.length === 0 && proxy.bindConfirm.target.slot === 1);
}

// ═══ T9: разметка теста ДОСЛОВНО совпадает с shipped InventoryPanel.js (мост runtime<->файл) ═══
{
  check('T9. shipped InventoryPanel.js содержит те же выражения, что смонтированы выше (нет «_bindPrinterObj»)',
    PANEL.includes('@click.stop="selectBindSlot(bindPrinterObj, bindSlotIndex(sl))"')
    && PANEL.includes('@click="tryBindTarget(bindPrinterObj, bind.slot)"')
    && PANEL.includes(':disabled="!canApplyBind"')
    && PANEL.includes(':class="{active: bind.slot===bindSlotIndex(sl)}"')
    && !/@click[^"]*_bindPrinterObj|selectBindSlot\(_bindPrinterObj/.test(PANEL));
}

// ═══ T10: АУДИТ «openBindFor(AMS-принтер, null)» (universal-ячейка 1.7.8) — какие варианты реально
//     предлагает диалог. Смонтирована ДОСЛОВНАЯ shipped-подпись слота (external/«Слот N»): у живого
//     AMS-принтера предлагаются ТОЛЬКО его AMS-слоты «Слот 1..4» (external-варианта НЕТ ВООБЩЕ),
//     payload = выбранный числовой index; риска «визуально выбрал внешнюю, а записалось slot 0» нет —
//     index 0 подписан честно «Слот 1». У принтера БЕЗ живых слотов bindSlots = fallback
//     [{index:0, external:true}] («Внешняя катушка», слот 0) — прямая внешняя привязка. ═══
{
  const SLOT_MARKUP_FULL = '<div v-if="bindSlots.length > 1" class="fm-inv-field"><div class="fm-inv-slots"><button v-for="sl in bindSlots" :key="sl.index" class="fm-inv-slot" :class="{active: bind.slot===bindSlotIndex(sl)}" @click.stop="selectBindSlot(bindPrinterObj, bindSlotIndex(sl))"><span class="fm-inv-slot-n">{{ bindSlotName(sl) }}</span></button></div></div>';
  netCalls.length = 0;
  // живой AMS-принтер, состояние как после openBindFor(p, null): printer_id задан, slot = -1
  const root = mount(makeBind(ams4, 'spoolQ', SLOT_MARKUP_FULL));
  const btns = slotButtons(root);
  const labels = btns.map((b) => b.textContent.trim());
  clickEl(btns[0]); await nextTick();                       // выбрать первый вариант («Слот 1», index 0)
  clickEl(applyButton(root)); await nextTick(); await nextTick();
  const req = netCalls[netCalls.length - 1];
  check('T10a. живой AMS: варианты = ТОЛЬКО AMS-слоты ' + JSON.stringify(labels) + '; «Внешн…» среди них НЕТ; первый вариант подписан «Слот 1» и шлёт ams_slot=0 (лоток AMS, подмены под external нет)',
    labels.length === 4 && labels.join(',') === 'Слот 1,Слот 2,Слот 3,Слот 4'
    && labels.every((t) => !t.includes('Внешн'))
    && req && req.body.ams_slot === 0 && req.body.printer_id === 'PRN_A');
  // принтер БЕЗ живых слотов: fallback-вариант ровно один — внешняя катушка (index 0)
  const appE = createApp(makeBind({ printer_id: 'PRN_E', printer_name: 'K1', has_ams: false, slots: [] }, 'spoolQ', SLOT_MARKUP_FULL));
  const rootE = new DElement('div'); const vmE = appE.mount(rootE);
  const fb = vmE.$.setupState.bindSlots;
  check('T10b. принтер без живых слотов: bindSlots = [{index:0, external:true}] — единственный честный вариант «Внешняя катушка» (блок выбора скрыт: вариантов < 2)',
    fb.length === 1 && fb[0].index === 0 && fb[0].external === true && slotButtons(rootE).length === 0);
  check('T10c. мост: shipped InventoryPanel.js подписывает варианты той же функцией (external / «Слот N» / метка принтера «Слот T1B»)',
    PANEL.includes("{{ bindSlotName(sl) }}")
    && PANEL.includes("const bindSlotName")
    && PANEL.includes("L('Внешняя катушка', 'External spool')")
    && PANEL.includes("L('Слот ', 'Slot ') + sl.label")
    && PANEL.includes("L('Слот', 'Slot') + ' ' + (Number(sl.index) + 1)"));
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: runtime — реальный клик по AMS-слоту выбирает слот и активирует кнопку (Vue mount + DOM-события)'));
process.exit(fail ? 1 : 0);
