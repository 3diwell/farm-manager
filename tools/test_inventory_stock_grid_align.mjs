// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// LAYOUT-регрессия выравнивания секций свёрнутых material-card «Склад → На складе» — inventory 1.7.13.
// НЕ статический поиск: реальный Edge/Chromium рендерит список из ДОСЛОВНОЙ разметки + CARD_CSS модуля
// и реальных правил ядра, затем через getBoundingClientRect() сверяет X-границы секций (Запасы/Состояние/
// Действия) МЕЖДУ карточками. Разные объёмы текста/chips/массы/названий НЕ должны сдвигать границы.
// Fixture: PETG×38 (3 chips), PLA×1 (2 chips), TPU×1, длинное название материала, очень большая масса,
// одна карточка раскрыта. Viewport dark/light × 1366/1550/1920. Отклонение границ ≤1px, без h-overflow.
// Запуск: node tools/test_inventory_stock_grid_align.mjs
// Alpha 2.835: транспорт переведён со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs).
// Стенд, шесть сценариев (dark/light × 1366/1550/1920) и пороги (≤1px, без h-overflow) сохранены
// дословно; отсутствие браузера или результата теперь КРАСНОЕ, а не пропуск.
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';
import { findEngine, measure, browserProblems } from './_edge_cdp_lib.mjs';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const APP_CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ── извлечение функций/разметки/CSS ──
const ext = (n) => { const a = 'const ' + n + ' = '; const i = PANEL.indexOf(a); if (i < 0) throw new Error('not found ' + n); let d = 0, q = null, e = false; for (let k = i + a.length; k < PANEL.length; k++) { const c = PANEL[k]; if (e) { e = false; continue; } if (q) { if (c === '\\') e = true; else if (c === q) q = null; continue; } if (c === "'" || c === '"' || c === '`') { q = c; continue; } if ('([{'.includes(c)) d++; else if (')]}'.includes(c)) d--; else if (c === ';' && d === 0) return PANEL.slice(i, k + 1); } throw new Error('unbalanced ' + n); };
const NAMES = ['pct', '_dir', '_spoolMatch', '_fMatch', 'spoolById', 'isBound', '_gnum', '_gtxt', '_ghex', 'safeHex', '_matKey', '_variantKey', '_lowW', 'warehouseGroups', 'expandedMat', 'expandedVar', 'isMatOpen', 'isVarOpen', 'toggleMat', 'toggleVar', 'matStateChips', 'matVendorLine', 'variantLabel', 'variantSub', '_hashId', 'spoolIdent', 'isEmptySpool', 'visibleSpoolsOrdered', 'groupSelState', 'toggleGroupSel', 'toggleSpoolSel', 'onRowClick', 'selectAllVisible', 'invertVisible'];
const SRCS = NAMES.map(ext).join('\n');
const KEY = '<div v-else class="fm-inv-wlist">'; const ms = PANEL.indexOf(KEY); const mOpenEnd = PANEL.indexOf('>', ms) + 1;
const mRe = /<div\b|<\/div>/g; mRe.lastIndex = mOpenEnd; let mm, dep = 1, mClose = -1;
while ((mm = mRe.exec(PANEL))) { dep += (mm[0] === '</div>') ? -1 : 1; if (dep === 0) { mClose = mm.index; break; } }
const MARKUP = PANEL.slice(ms, mClose + 6).replace('v-else class="fm-inv-wlist"', 'v-if="true" class="fm-inv-wlist"');
const CARD_CSS = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); return new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))().join('\n'); })();
const _d = APP_CSS.indexOf('--fm-surface-raised:'); const _l = APP_CSS.indexOf('--fm-surface-raised:', _d + 10);
const blk = (idx) => APP_CSS.slice(APP_CSS.lastIndexOf('{', idx) + 1, APP_CSS.indexOf('}', idx));
const cv = (b, n) => { const m = new RegExp(n.replace(/-/g, '[-]') + ':\\s*([^;}]+)').exec(b); return m ? m[1].trim() : '#888'; };
const VARS = (b) => ['--fm-surface-raised', '--fm-surface-card', '--fm-surface-control', '--fm-border-soft', '--fm-border-strong', '--fm-border', '--fm-text-primary', '--fm-text-secondary', '--fm-text-subtle', '--fm-accent-rgb', '--fm-black-rgb', '--fm-accent', '--fm-danger'].map((v) => v + ':' + cv(b, v)).join(';');
const vueUrl = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;

// ── fixture: разный объём контента, но сетка должна быть общей ──
const sp = (id, o) => Object.assign({ id, filament_id: 'f', material: 'PETG', color_name: 'Чёрный', color_hex: '#111111', vendor_name: 'GEHR', weight_remaining_g: 1000, weight_total_g: 1000, diameter: 1.75, location_id: 'loc1', lot: '', label: '', status: 'in_stock', ams_printer_id: '', ams_slot: -1, created_at: '2026-07-01' }, o);
const LIST = [
  // PETG ×38: 36 полных + 1 открытая (50%) + 1 «мало» (80г) → 3 chips
  ...Array.from({ length: 36 }, (_, i) => sp('pf' + i)),
  sp('po1', { weight_remaining_g: 500 }),
  sp('pl1', { weight_remaining_g: 80 }),
  // PLA ×1: полная → chips «Полные 1 / Мало 0» = 2
  sp('la1', { material: 'PLA', filament_id: 'fpla', color_hex: '#e5484d', vendor_name: 'Bambu' }),
  // TPU ×1: открытая (60%) → chips «Открытые 1 / Мало 0» = 2
  sp('tu1', { material: 'TPU', filament_id: 'ftpu', color_hex: '#eee', vendor_name: 'Polymaker', weight_remaining_g: 600 }),
  // длинное название материала + ОЧЕНЬ большая масса
  sp('bg1', { material: 'СВЕРХ-ДЛИННОЕ-НАЗВАНИЕ-КОМПОЗИТНОГО-МАТЕРИАЛА-PA-CF-XL', filament_id: 'fbig', color_hex: '#333', vendor_name: 'Полимейкер-Индастриз', weight_remaining_g: 999999, weight_total_g: 1000000 }),
];

const page = (theme) => `<!doctype html><html><head><meta charset="utf-8"><style>
:root{${VARS(theme === 'dark' ? blk(_d) : blk(_l))}}
html,body{margin:0;background:${theme === 'dark' ? '#141416' : '#eef1f4'};font:13px system-ui}
.pad{max-width:1500px;margin:14px auto;padding:14px 18px;background:var(--fm-surface-base,var(--fm-surface-raised));border-radius:14px}
${CARD_CSS}
</style></head><body><div class="pad"><div id="app"></div></div>
<pre id="__res" style="position:fixed;left:0;bottom:0;font:10px monospace;color:#0f0;background:#000;z-index:99;white-space:pre"></pre>
<script type="module">
import { createApp, ref, reactive, computed } from '${vueUrl}';
const LIST = ${JSON.stringify(LIST)};
const app = createApp({ setup() {
  const L=(a)=>a; const spools=ref(LIST); const q=ref(''); const sortBy=ref('material'); const sortDir=ref('asc');
  const fMat=ref(''); const fVendor=ref(''); const fLoc=ref(''); const fLow=ref(false); const lowG=ref(100);
  const locName=(id)=>({loc1:'Основной склад'}[id]||id||'');
  const barColor=()=>'var(--fm-accent)'; const statusLabel=(k)=>({in_stock:'В наличии'}[k]||k);
  const spoolSvg=()=>'<svg viewBox="0 0 40 40" width="38" height="38"><circle cx="20" cy="20" r="16" fill="none" stroke="var(--fm-accent)" stroke-width="4"/></svg>';
  const openHist=()=>{}; const spoolMenu=()=>{}; const groupMenu=()=>{}; const flash=()=>{};
  const selMode=ref(false); const selected=reactive(new Set()); const lastClickedId=ref('');
  ${SRCS}
  return { L, spools, q, sortBy, sortDir, fMat, fVendor, fLoc, fLow, lowG, locName, barColor, statusLabel, spoolSvg, openHist, spoolMenu, groupMenu, selMode, selected, lastClickedId, ${NAMES.join(', ')} };
}, template: ${JSON.stringify('<div>' + MARKUP + '</div>')} });
const vm = app.mount('#app'); const S = vm.$.setupState;
S.toggleMat(S.warehouseGroups[0]);   // одна карточка раскрыта
requestAnimationFrame(() => requestAnimationFrame(() => {
  const cards = [...document.querySelectorAll('.fm-inv-mcard')];
  const rows = cards.map((c) => {
    const g = (sel) => { const el = c.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().left * 100) / 100 : null; };
    return { stock: g('.fm-inv-msec-stock'), state: g('.fm-inv-msec-state'), act: g('.fm-inv-msec-act') };
  });
  const dev = (key) => { const xs = rows.map((r) => r[key]).filter((v) => v != null); return xs.length ? (Math.max(...xs) - Math.min(...xs)) : -1; };
  document.getElementById('__res').textContent = '@@R@@' + JSON.stringify({
    cards: cards.length, devStock: dev('stock'), devState: dev('state'), devAct: dev('act'),
    xStock: rows.map((r) => r.stock), xAct: rows.map((r) => r.act),
    bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
  }) + '@@E@@';
  document.title = 'ready';
}));
</script></body></html>`;

const ENGINE = findEngine();
check('A0. движок рендера для браузерных измерений найден (без него проверки геометрии невозможны)', !!ENGINE);
if (ENGINE) {
  const tmp = join(tmpdir(), 'fm-align-' + process.pid); mkdirSync(tmp, { recursive: true });
  // Снимки кладём во временную папку прогона (раньше — в _incoming/): рабочие каталоги проекта тесты
  // не трогают, а снимок нужен только для разбора упавшего сценария.
  const shots = join(tmp, 'shots'); mkdirSync(shots, { recursive: true });
  let ran = 0;
  for (const theme of ['dark', 'light']) {
    const pg = join(tmp, 'a-' + theme + '.html'); writeFileSync(pg, page(theme), 'utf8');
    for (const w of [1366, 1550, 1920]) {
      const shot = (w === 1550) ? join(shots, `inv_1713_align_${theme}.png`) : null;
      let out = null, why = '';
      try {
        out = await measure({ url: pathToFileURL(pg).href, width: w, height: 900, engine: ENGINE,
          marker: '@@R@@', endMarker: '@@E@@', shot: shot || undefined });
      } catch (e) { why = String((e && e.message) || e); }
      if (!out) { check(`layout ${theme} ${w}: стенд выполнен в реальном браузере`, false); console.log('   причина: ' + why); continue; }
      const probs = browserProblems(out);
      check(`layout ${theme} ${w}: страница без ошибок JS/консоли/Vue`, probs.length === 0);
      if (probs.length) console.log('   ' + probs.join('\n   '));
      const r = out.res;
      ran++;
      const ok = r.cards === 4 && r.devStock <= 1 && r.devState <= 1 && r.devAct <= 1 && r.bodyOverflow <= 0;
      check(`layout ${theme} ${w}: ${r.cards} карточек (4), отклонение границ Запасы=${r.devStock}px Состояние=${r.devState}px Действия=${r.devAct}px (≤1), h-overflow=${r.bodyOverflow}`, ok);
    }
  }
  check('A. все 6 сценариев (dark/light × 1366/1550/1920) реально исполнены в браузере', ran === 6);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: границы секций material-card синхронны между карточками (≤1px) во всех темах/разрешениях (реальный Edge через CDP, 0 пропусков)'));
process.exit(fail ? 1 : 0);
