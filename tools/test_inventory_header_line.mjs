// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// DISCRIMINATING layout-тест в РЕАЛЬНОМ Edge/Chromium: серая линия под sticky-заголовками «В работе».
// Строит статическую разметку таблицы (шапка .fm-inv-prow.fm-inv-prow-h + первая секция .fm-inv-psec) с
// ДОСЛОВНЫМ CARD_CSS модуля и переменными темы ядра; в headless-браузере через getComputedStyle и
// elementsFromPoint (в вырезах над скруглёнными углами) ОДНОЗНАЧНО определяет владельца линии и проверяет фикс:
//   • computed border-bottom ШАПКИ = 0 (линия убрана); box-shadow шапки = none;
//   • строки данных .fm-inv-prow сохраняют border-bottom 1px (источник = базовый .fm-inv-prow, а НЕ .fm-inv-prow-h);
//   • верхний контур секции (border-top 1px) и border-radius:12px сохранены;
//   • в вырезах над левым/правым радиусом первой секции нет border/тени, рисующей линию;
//   • sticky/top:0/z-index/непрозрачный фон целы; overflowX=0; после scrollTop>0 строки не просвечивают.
// Первая секция проверяется для External / AMS / Empty; dark/light; 1366/1550/1920; scroll 0 и >0.
// Запуск: node tools/test_inventory_header_line.mjs   (0 = пройдено)
// Alpha 2.835: транспорт переведён со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs).
// Стенд, набор из 20 сценариев и все пороги сохранены дословно; недоступный браузер или не
// вернувшийся результат теперь КРАСНЫЕ (раньше 21 пропуск скрывал 20 реальных проверок геометрии).
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';
import { findEngine, measure, browserProblems } from './_edge_cdp_lib.mjs';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const APP_CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8', 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

const ENGINE = findEngine();

// ─── извлечение CARD_CSS модуля + тем ядра из app.css (как в sections_runtime) ───
const CARD_CSS_TEXT = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); return new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))().join('\n'); })();
const cssVar = (block, name) => { const m = new RegExp(name.replace(/[-]/g, '[-]') + ':\\s*([^;}]+)[;}]').exec(block); return m ? m[1].trim() : ''; };
const _blockAround = (idx) => APP_CSS.slice(APP_CSS.lastIndexOf('{', idx) + 1, APP_CSS.indexOf('}', idx));
const _dIdx = APP_CSS.indexOf('--fm-surface-raised:');
const _lIdx = APP_CSS.indexOf('--fm-surface-raised:', _dIdx + 10);
const darkRoot = _blockAround(_dIdx), lightRoot = _blockAround(_lIdx);
const VARS = (block, fb) => ['--fm-surface-raised', '--fm-surface-card', '--fm-border-soft', '--fm-border-strong', '--fm-border', '--fm-text-primary', '--fm-text-secondary', '--fm-text-subtle', '--fm-accent-rgb', '--fm-black-rgb', '--fm-accent', '--fm-success']
  .map((v) => v + ':' + (cssVar(block, v) || cssVar(fb, v) || '#888')).join(';');
const coreRule = (sel) => (new RegExp(sel.replace(/[.]/g, '\\.') + '\\{[^}]*\\}')).exec(APP_CSS)[0];

// статические строки таблицы (структурно валидные для .fm-inv-prow grid: 6 детей)
const cells6 = (inner) => '<div>' + (inner || '') + '</div><div></div><div></div><div></div><div></div><div></div>';
const HEADER = '<div class="fm-inv-prow fm-inv-prow-h"><span>Принтер</span><span>Катушка</span><span>AMS слоты</span><span class="fm-inv-prem">Остаток</span><span class="fm-inv-pfc">Прогноз</span><span></span></div>';
const section = (title) => '<div class="fm-inv-psec"><div class="fm-inv-psec-h"><span class="fm-inv-psec-t">' + title + '</span><span class="fm-inv-psec-c">1 принт.</span></div>'
  + '<div class="fm-inv-prow">' + cells6('Принтер X') + '</div><div class="fm-inv-prow">' + cells6('Принтер Y') + '</div></div>';
const SECTIONS = { ext: 'Внешняя подача', ams: 'Системы AMS', empty: 'Без катушки' };

const buildPage = (theme, firstTitle, scroll) => `<!doctype html><html><head><meta charset="utf-8"><style>
:root{${theme === 'dark' ? VARS(darkRoot, darkRoot) : VARS(lightRoot, darkRoot)}}
html,body{margin:0;background:${theme === 'dark' ? '#141416' : '#eef1f4'};font:13px system-ui}
${coreRule('.fm-inv-body')}
${CARD_CSS_TEXT}
.fm-inv-body{height:400px;overflow:auto}
</style></head><body>
<div class="fm-inv-body" id="sc"><div class="fm-inv-tabpane"><div class="fm-inv-ptable">${HEADER}${section(firstTitle)}${section('Системы AMS')}${section('Без катушки')}</div></div></div>
<pre id="__res" style="position:fixed;left:0;bottom:0;font:11px monospace;background:#000;color:#0f0;z-index:99;white-space:pre"></pre>
<script type="module">
// СИНХРОННОЕ измерение: разметка статическая и полностью свёрстана к концу <body>, поэтому rAF
// не нужен вовсе; getBoundingClientRect форсирует расчёт layout прямо здесь. Мост ждёт появления
// маркера результата в документе, так что гонки «прочитали раньше, чем посчитали» нет.
try {
  const sc=document.getElementById('sc');
  sc.scrollTop=${scroll}; void sc.offsetHeight;
  const hdr=document.querySelector('.fm-inv-prow-h');
  const rows=[...document.querySelectorAll('.fm-inv-prow')].filter(r=>r!==hdr);
  const sec=document.querySelector('.fm-inv-psec');
  const cs=getComputedStyle(hdr), rs=getComputedStyle(rows[0]), ss=getComputedStyle(sec);
  const hr=hdr.getBoundingClientRect(), sr=sec.getBoundingClientRect();
  const y=Math.round((hr.bottom+sr.top)/2);
  // вырезы над скруглёнными углами: чуть внутри левого и правого края секции, на уровне между шапкой и секцией
  const pts=[[Math.round((sr.left+sr.right)/2),y],[Math.round(sr.left+2),y],[Math.round(sr.right-2),y]];
  const notch=pts.map(([x,yy])=>{ const els=document.elementsFromPoint(x,yy)||[]; const t=els.find(e=>e&&e.classList&&e!==document.documentElement&&e!==document.body); if(!t) return 'none'; const c=getComputedStyle(t); return (t.className||t.tagName)+'|bb='+c.borderBottomWidth+'|bt='+c.borderTopWidth+'|bs='+(c.boxShadow==='none'?'0':'Y'); });
  // просвет над sticky-шапкой после прокрутки: строк над верхом шапки нет (top шапки у верха контейнера)
  const gap=Math.round((hr.top - sc.getBoundingClientRect().top)*10)/10;
  const res={ theme:'${theme}', first:'${firstTitle}', scroll:${scroll},
    hdrBB:cs.borderBottomWidth, hdrBS:(cs.boxShadow==='none'?'none':'Y'), hdrBT:cs.borderTopWidth,
    hdrPos:cs.position, hdrTop:cs.top, hdrZ:cs.zIndex, hdrBgAlpha:(cs.backgroundColor.startsWith('rgba(')&&!cs.backgroundColor.match(/, ?1\\)$/))?'transp':'opaque',
    rowBB:rs.borderBottomWidth, secBT:ss.borderTopWidth, secRadius:ss.borderTopLeftRadius,
    overflowX:sc.scrollWidth-sc.clientWidth, stickyGap:gap, notch };
  document.getElementById('__res').textContent='@@RES@@'+JSON.stringify(res)+'@@END@@';
  document.title='ready';
} catch(e){ document.getElementById('__res').textContent='@@RES@@'+JSON.stringify({err:String(e&&e.message||e)})+'@@END@@'; }
</scr`+`ipt></body></html>`;

check('HL0. движок рендера для браузерных измерений найден (без него проверки геометрии невозможны)', !!ENGINE);
if (ENGINE) {
  const tmp = join(tmpdir(), 'fm-inv-hl-' + process.pid); mkdirSync(tmp, { recursive: true });
  const run = async (pg, w) => {
    let out = null, err = '';
    try { out = await measure({ url: pathToFileURL(pg).href, width: w, height: 900, engine: ENGINE }); }
    catch (e) { err = String((e && e.message) || e); }
    if (!out) return { r: null, why: err, probs: [] };
    const probs = browserProblems(out);
    return { r: out.res, why: out.res && out.res.err ? out.res.err : '', probs };
  };
  const CASES = [];
  // полный матрикс тема × ширина × scroll на AMS-first (типовая первая секция)
  for (const theme of ['dark', 'light']) for (const w of [1366, 1550, 1920]) for (const scroll of [0, 300]) CASES.push([theme, 'ams', w, scroll]);
  // первая секция External / Empty — на нескольких комбинациях (контур/скругление у всех типов одинаковы)
  for (const first of ['ext', 'empty']) for (const theme of ['dark', 'light']) for (const w of [1366, 1920]) CASES.push([theme, first, w, 0]);
  let ran = 0;
  for (const [theme, first, w, scroll] of CASES) {
    const pg = join(tmp, `hl-${theme}-${first}-${w}-${scroll}.html`);
    writeFileSync(pg, buildPage(theme, SECTIONS[first], scroll), 'utf8');
    const { r, why, probs } = await run(pg, w);
    if (!r || r.err) {
      check(`HL. ${theme}/${first}/${w}/scroll${scroll}: стенд выполнен в реальном браузере`, false);
      console.log('   причина: ' + (why || 'результат не получен'));
      continue;
    }
    check(`HL. ${theme}/${first}/${w}/scroll${scroll}: страница без ошибок JS/консоли/Vue`, probs.length === 0);
    if (probs.length) console.log('   ' + probs.join('\n   '));
    ran++;
    const notchClean = r.notch.every((n) => n.includes('bb=0px') || n.startsWith('none') || (!n.includes('fm-inv-prow-h') && !n.includes('|bs=Y')));
    // sticky-прижим осмыслен только после прокрутки (scroll>0): при scroll0 шапка на естественном
    // отступе контейнера (.fm-inv-body padding:20px) — это не «просвет», а исходное положение.
    const stickyOk = scroll > 0 ? (r.stickyGap <= 1.5) : true;
    const ok = r.hdrBB === '0px' && r.hdrBS === 'none'
      && r.rowBB === '1px'                       // источник .fm-inv-prow цел на СТРОКАХ (доказывает: линия была именно этим классом на шапке)
      && r.secBT === '1px' && r.secRadius === '12px'   // контур+радиус секции сохранены
      && r.hdrPos === 'sticky' && r.hdrTop === '0px' && r.hdrZ === '7' && r.hdrBgAlpha === 'opaque'
      && r.overflowX <= 0 && stickyOk
      && notchClean;
    check(`HL. ${theme}/${first === 'ext' ? 'External' : first === 'ams' ? 'AMS' : 'Empty'}/${w}/scroll${scroll}: шапка border-bottom=${r.hdrBB} (=0) box-shadow=${r.hdrBS}; строки .fm-inv-prow bb=${r.rowBB} (=1px); секция border-top=${r.secBT} radius=${r.secRadius}; sticky ${r.hdrPos}/${r.hdrTop}/z${r.hdrZ}/${r.hdrBgAlpha}${scroll > 0 ? '/gap' + r.stickyGap : ''}; overflowX=${r.overflowX}; вырезы чисты`, ok);
    if (!ok) console.log('   notch:', JSON.stringify(r.notch), 'stickyGap:', r.stickyGap);
  }
  // Ожидаемое число сценариев задано ЯВНО (20), а не длиной списка: иначе выпавший сценарий
  // «согласовался» бы сам с собой и пропажа проверки осталась бы незамеченной.
  check('HL. все 20 сценариев (External/AMS/Empty × dark/light × ширины × scroll) реально исполнены в браузере',
    ran === 20 && CASES.length === 20);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : ('PASS: серая линия под sticky-заголовками убрана — border-bottom шапки=0 (источник: базовый .fm-inv-prow, отменён на .fm-inv-prow-h); строки и контур секции целы; вырезы над углами чисты; External/AMS/Empty × dark/light × scroll0/300 (реальный Edge через CDP, 0 пропусков)')));
process.exit(fail ? 1 : 0);
