// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Edge/Chromium layout-тест: поиск во вкладках «В работе» и «На складе» — ЕДИНЫЙ layout-контракт (item 6).
// Рендерит ОБЕ toolbar в одинаковой ширины контейнерах (как .fm-inv-body в приложении) с ДОСЛОВНЫМ CARD_CSS
// модуля + ядровыми .fm-inv-toolbar/.fm-inv-search/.fm-inv-btn (web/app.css) + переменными темы и через
// getBoundingClientRect измеряет ОБА поля поиска. Проверяет: одинаковый правый край (right) и одинаковая
// ширина (width) с отклонением ≤1px; overflowX=0; левая зона — действия (у «На складе»), у «В работе» слева
// пусто, но поиск всё равно справа; удалённые кнопки не оставили пустых зон (нет .fm-inv-stat/.fm-inv-spacer).
// dark/light × 1366/1550/1920. Запуск: node tools/test_inventory_search_layout.mjs (0=ок).
// Alpha 2.835: транспорт переведён со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs).
// Смысл проверок не изменён — та же страница-стенд, те же измерения, то же выражение разбора;
// отсутствие браузера/результата больше НЕ пропуск, а красная проверка с точной причиной.
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

const ENGINE = findEngine();

const CARD_CSS_TEXT = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); return new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))().join('\n'); })();
const cssVar = (block, name) => { const m = new RegExp(name.replace(/[-]/g, '[-]') + ':\\s*([^;}]+)[;}]').exec(block); return m ? m[1].trim() : ''; };
const _blockAround = (idx) => APP_CSS.slice(APP_CSS.lastIndexOf('{', idx) + 1, APP_CSS.indexOf('}', idx));
const _dIdx = APP_CSS.indexOf('--fm-surface-raised:');
const _lIdx = APP_CSS.indexOf('--fm-surface-raised:', _dIdx + 10);
const darkRoot = _blockAround(_dIdx), lightRoot = _blockAround(_lIdx);
const VARS = (block, fb) => ['--fm-surface-raised', '--fm-surface-card', '--fm-surface-control', '--fm-surface-deep', '--fm-border-soft', '--fm-border', '--fm-border-strong', '--fm-text-primary', '--fm-text-secondary', '--fm-text-subtle', '--fm-accent', '--fm-accent-rgb', '--fm-black-rgb']
  .map((v) => v + ':' + (cssVar(block, v) || cssVar(fb, v) || '#888')).join(';');
const coreRule = (sel) => { const m = (new RegExp(sel.replace(/[.]/g, '\\.') + '\\{[^}]*\\}')).exec(APP_CSS); return m ? m[0] : ''; };

// РЕАЛЬНАЯ разметка toolbar (стрип Vue-директив): та же структура классов/margin-left:auto, что в шаблоне.
const SEARCH = '<input class="fm-inv-search" style="margin-left:auto" placeholder="Поиск: материал, цвет…">';
const WORK_TB = '<div class="fm-inv-toolbar">' + SEARCH + '</div>';
const STOCK_TB = '<div class="fm-inv-toolbar"><button class="fm-inv-btn primary"><span>Добавить катушку</span></button><button class="fm-inv-btn"><span>Выбрать</span></button>' + SEARCH + '</div>';

const buildPage = (theme) => `<!doctype html><html><head><meta charset="utf-8"><style>
:root{${theme === 'dark' ? VARS(darkRoot, darkRoot) : VARS(lightRoot, darkRoot)}}
html,body{margin:0;background:${theme === 'dark' ? '#141416' : '#eef1f4'};font:13px system-ui}
${coreRule('.fm-inv-body')}
${coreRule('.fm-inv-toolbar')}
${coreRule('.fm-inv-btn')}
${coreRule('.fm-inv-search')}
${coreRule('.fm-inv-spacer')}
${coreRule('.fm-inv-stat')}
${CARD_CSS_TEXT}
.pane{width:100%;box-sizing:border-box}
</style></head><body>
<div class="fm-inv-body pane" id="work"><div class="fm-inv-tabpane">${WORK_TB}</div></div>
<div class="fm-inv-body pane" id="stock"><div class="fm-inv-tabpane">${STOCK_TB}</div></div>
<pre id="__res"></pre>
<script type="module">
try {
  const w = document.querySelector('#work'), s = document.querySelector('#stock');
  const ws = w.querySelector('.fm-inv-search'), ss = s.querySelector('.fm-inv-search');
  const wr = ws.getBoundingClientRect(), sr = ss.getBoundingClientRect();
  const ox = (el) => el.scrollWidth - el.clientWidth;
  const res = { theme:'${theme}',
    wRight: Math.round(wr.right*10)/10, sRight: Math.round(sr.right*10)/10,
    wWidth: Math.round(wr.width*10)/10, sWidth: Math.round(sr.width*10)/10,
    rightDelta: Math.round(Math.abs(wr.right - sr.right)*10)/10,
    widthDelta: Math.round(Math.abs(wr.width - sr.width)*10)/10,
    overflowX: Math.max(ox(w), ox(s), document.documentElement.scrollWidth - document.documentElement.clientWidth),
    // поиск действительно у ПРАВОГО края своей панели (right у padding-края контейнера)
    wRightGap: Math.round((w.getBoundingClientRect().right - wr.right)*10)/10,
    sRightGap: Math.round((s.getBoundingClientRect().right - sr.right)*10)/10,
    stat: document.querySelectorAll('.fm-inv-stat').length, spacer: document.querySelectorAll('.fm-inv-spacer').length };
  document.getElementById('__res').textContent = '@@RES@@' + JSON.stringify(res) + '@@END@@';
} catch(e){ document.getElementById('__res').textContent = '@@RES@@' + JSON.stringify({err:String(e&&e.message||e)}) + '@@END@@'; }
</scr`+`ipt></body></html>`;

check('SL0. движок рендера для браузерных измерений найден (без него проверки геометрии невозможны)', !!ENGINE);
if (ENGINE) {
  const tmp = join(tmpdir(), 'fm-inv-sl-' + process.pid); mkdirSync(tmp, { recursive: true });
  let ran = 0;
  for (const theme of ['dark', 'light']) for (const w of [1366, 1550, 1920]) {
    const pg = join(tmp, `sl-${theme}-${w}.html`); writeFileSync(pg, buildPage(theme), 'utf8');
    let out = null, err = '';
    try {
      out = await measure({ url: pathToFileURL(pg).href, width: w, height: 900, engine: ENGINE });
    } catch (e) { err = String((e && e.message) || e); }
    if (!out) { check(`SL. ${theme}/${w}: стенд выполнен в реальном браузере`, false); console.log('   причина: ' + err); continue; }
    const r = out.res;
    check(`SL. ${theme}/${w}: страница без ошибок JS/консоли/Vue`, !r.err && browserProblems(out).length === 0);
    if (r.err) { console.log('   [page error] ' + r.err); }
    if (browserProblems(out).length) console.log('   ' + browserProblems(out).join('\n   '));
    ran++;
    const ok = r.rightDelta <= 1 && r.widthDelta <= 1 && r.overflowX <= 0
      && r.wRightGap <= 21 && Math.abs(r.wRightGap - r.sRightGap) <= 1   // оба у правого края (padding 20px), одинаково
      && r.stat === 0 && r.spacer === 0;                                 // удалённые счётчик/spacer не оставили зон
    check(`SL. ${theme}/${w}: поиск справа одинаково — right Δ${r.rightDelta}px (work ${r.wRight}/stock ${r.sRight}), width Δ${r.widthDelta}px (${r.wWidth}/${r.sWidth}), overflowX=${r.overflowX}, правый отступ work=${r.wRightGap}/stock=${r.sRightGap}px, stat/spacer=${r.stat}/${r.spacer}`, ok);
  }
  check('SL. все 6 сценариев (dark/light × 1366/1550/1920) реально исполнены в браузере', ran === 6);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: единый layout поиска — «В работе» и «На складе» держат поиск справа с одинаковыми right/width (Δ≤1px), overflowX=0, без остаточных зон (реальный Edge через CDP, 0 пропусков)'));
process.exit(fail ? 1 : 0);
