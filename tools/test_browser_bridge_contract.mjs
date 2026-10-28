// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
//  Alpha 2.840 — КОНТРАКТ МОСТА «тест ↔ настоящий браузер» (_edge_cdp_lib.mjs).
//
//  ЗАЧЕМ. Браузерный release gate 2.835 доказывал свои несущие свойства КОСВЕННО:
//  чтобы убедиться, что мост не вернулся к сломанному `--dump-dom` и что таймаут
//  команды CDP не проглатывается, приходилось ломать мост и ждать, пока покраснеет
//  большой харнесс геометрии. Каждая такая проверка стоила ~6 минут реального
//  браузера, потому что отказ моста наступал по таймауту (30 c) и повторялся
//  второй попыткой на каждом из шести сценариев.
//
//  Здесь те же свойства проверяются НАПРЯМУЮ и за секунды. Это не ослабление:
//  проверяется ровно тот же семантический контракт, только там, где он живёт, —
//  в самом мосте, а не в далёком следствии.
//
//  ЧТО ЗАКРЫВАЕТ (каждый пункт — реальный класс дефекта):
//   B1  мост или харнесс снова передаёт `--dump-dom` (Edge 150 отдаёт пустой
//       документ, и ~48 браузерных проверок молча превращаются в пропуски);
//   B2  таймаут команды CDP отдаёт пустой ответ вместо ошибки — харнесс получает
//       «результат», которого не было, и зеленеет впустую;
//   B3  отсутствие движка рендера трактуется как «нечего проверять» вместо отказа;
//   B4  временный профиль и процессы движка остаются после прогона.
//
//  ПРОПУСКОВ НЕТ. Если движок не найден — это КРАСНЫЙ результат с причиной, а не SKIP.
//
//  Оверлей: FM_BRIDGE_SCAN и FM_BRIDGE_LIB позволяют проверить КОПИЮ оснастки во
//  временной папке, не трогая файлы репозитория (этим пользуется mutation proof).
//
//  Запуск:  node tools/test_browser_bridge_contract.mjs      (0 = всё пройдено)
// ============================================================================
import { existsSync, readdirSync, readFileSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCAN = process.env.FM_BRIDGE_SCAN || HERE;
const LIBPATH = process.env.FM_BRIDGE_LIB || join(HERE, '_edge_cdp_lib.mjs');
const SENTINEL = 'BROWSER_BRIDGE_CONTRACT_SENTINEL_2_840';

let fail = 0;
const check = (name, ok, extra) => {
  if (ok) console.log('PASS — ' + name);
  else { fail++; console.log('FAIL — ' + name + (extra ? ' | ' + String(extra).slice(0, 200) : '')); }
  return ok;
};

console.log('=== Alpha 2.840: контракт моста «тест ↔ браузер» ===');
console.log('МЕТКА ОСНАСТКИ: ' + SENTINEL);

// ── B1. `--dump-dom` не передаётся НИГДЕ (статически, за миллисекунды) ──────────────────────
// Ищем только БОЕВЫЕ вхождения: строка-аргумент в кавычках. Упоминания в комментариях —
// это история («почему мы ушли от --dump-dom»), и запрещать их бессмысленно.
// Комментарии отсекаются ОБА вида: и `//`, и строки блочного `/* ... */`. Без этого проверка
// ловит собственную историческую прозу («почему мы ушли от --dump-dom») и краснеет впустую.
// Кавычки только одинарные и двойные: аргумент передаётся строкой, а не шаблонным литералом.
const offenders = [];
for (const f of readdirSync(SCAN).filter((n) => n.endsWith('.mjs'))) {
  const src = readFileSync(join(SCAN, f), 'utf8');
  src.split('\n').forEach((line, i) => {
    const t = line.trim();
    if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;
    const code = line.split('//')[0];
    if (/['"]--dump-dom['"]/.test(code)) offenders.push(f + ':' + (i + 1));
  });
}
check('B1. ни мост, ни один харнесс не передаёт --dump-dom как аргумент', offenders.length === 0, offenders);

const { openStage, findEngine, readPort } = await import(pathToFileURL(LIBPATH).href);

// Windows может держать DevToolsActivePort открытым во время записи. Исполняем
// тот же читатель, что запускает браузер; подменено только чтение файла ОС.
let portReads = 0;
let recoveredPort = null;
let portError = '';
try {
  recoveredPort = await readPort('FIXTURE_PROFILE', null, 2000, () => {
    portReads++;
    if (portReads <= 2) throw Object.assign(new Error('fixture locked'), { code: 'EBUSY' });
    if (portReads === 3) throw Object.assign(new Error('fixture not created'), { code: 'ENOENT' });
    if (portReads === 4) return '543'; // запись строки ещё не закончена
    if (portReads === 5) return '65536\n'; // неверный номер не даёт ложную готовность
    return '54321\n/devtools/browser/FIXTURE';
  });
} catch (e) { portError = String(e); }
check('B9. временная блокировка и неполная запись порта пережидаются до настоящего результата',
  recoveredPort === 54321 && portReads === 6, portError || { recoveredPort, portReads });

let busyError = '';
const busyStarted = Date.now();
try {
  await readPort('FIXTURE_PROFILE', null, 150, () => {
    throw Object.assign(new Error('fixture always locked'), { code: 'EBUSY' });
  });
} catch (e) { busyError = String(e); }
check('B10. постоянная блокировка даёт ограниченный по времени отказ с причиной',
  /DevToolsActivePort/.test(busyError) && /EBUSY/.test(busyError) && Date.now() - busyStarted < 1500, busyError);

const denied = Object.assign(new Error('fixture denied'), { code: 'EACCES' });
let deniedError;
try { await readPort('FIXTURE_PROFILE', null, 2000, () => { throw denied; }); }
catch (e) { deniedError = e; }
check('B11. постоянный отказ доступа не маскируется под ожидание браузера', deniedError === denied);

// ── B3. Нет движка -> ОТКАЗ с причиной, а не «нечего проверять» ─────────────────────────────
// Удалить Edge с машины нельзя, а подсунуть несуществующий путь недостаточно: findEngine при
// негодном `explicit` МОЛЧА берёт следующий установленный движок. Поэтому проверяем на КОПИИ
// моста во временной папке, где список движков пуст, — файлы репозитория не трогаются.
const b3dir = join(tmpdir(), 'fm-bridge-noengine-' + process.pid);
mkdirSync(b3dir, { recursive: true });
const b3lib = join(b3dir, '_edge_cdp_lib.mjs');
{
  const src = readFileSync(LIBPATH, 'utf8');
  const anchor = 'for (const p of [explicit, ...ENGINES]) {';
  check('B3a. в мосте найдена точка выбора движка (иначе проверка ниже была бы пустой)',
    src.split(anchor).length === 2, anchor);
  writeFileSync(b3lib, src.replace(anchor, 'for (const p of []) {'), 'utf8');
}
let b3 = 'исключения не было';
try {
  const noEngine = await import(pathToFileURL(b3lib).href);
  await noEngine.openStage({ url: 'about:blank' });
  b3 = null;
} catch (e) { b3 = String((e && e.message) || e); }
check('B3. отсутствующий движок даёт отказ с причиной (а не пропуск)',
  !!b3 && /движок/i.test(b3), b3);
try { rmSync(b3dir, { recursive: true, force: true }); } catch { /* временная папка */ }

// ── Живой движок: он обязан быть, иначе весь браузерный gate недоказуем ─────────────────────
const ENGINE = findEngine();
if (!check('B0. движок рендера установлен (без него браузерные проверки невозможны)', !!ENGINE)) {
  console.log('\nFAIL: движок рендера не найден — браузерный контракт НЕ проверен');
  process.exit(1);
}

const tmp = join(tmpdir(), 'fm-bridge-contract-' + process.pid);
mkdirSync(tmp, { recursive: true });
const page = join(tmp, 'stand.html');
writeFileSync(page, '<!doctype html><html><body><div id="__res">ok</div></body></html>', 'utf8');

const stage = await openStage({ url: pathToFileURL(page).href, engine: ENGINE, width: 800, height: 600 });
const profile = stage.profile;
try {
  // ── B2. Таймаут команды CDP -> ОТКЛОНЕНИЕ, а не пустой ответ ─────────────────────────────
  // Заведомо долгая команда с коротким окном: результат обязан быть ошибкой, а не «{}».
  let b2 = 'команда вернулась без ошибки';
  try {
    const r = await stage.send('Runtime.evaluate',
      { expression: 'new Promise(function (r) { setTimeout(r, 4000); })', awaitPromise: true }, 300);
    b2 = 'вернулось ' + JSON.stringify(r).slice(0, 80);
  } catch (e) { b2 = String((e && e.message) || e); }
  check('B2. таймаут команды CDP отклоняется с причиной, а не отдаёт пустой результат',
    /CDP timeout/.test(b2), b2);

  // ── Мост в норме делает то, ради чего существует ─────────────────────────────────────────
  const dom = await stage.outerHTML();
  check('B5. документ снимается по протоколу (не из stdout)', /id="__res"/.test(dom || ''),
    (dom || '').slice(0, 60));
  check('B6. диагностика консоли и Vue собирается', Array.isArray(stage.consoleErrors)
    && Array.isArray(stage.consoleWarnings));
  check('B7. движок поднят на СВОЁМ временном профиле, а не на пользовательском',
    profile.includes('fm-cdp-') || profile.includes('fm-bridge'), profile);
} finally {
  await stage.close();
}

// ── B4. После закрытия не остаётся ни профиля, ни процессов этого профиля ───────────────────
check('B4. временный профиль удалён после прогона', !existsSync(profile), profile);

const { execFileSync } = await import('node:child_process');
let alive = '0';
try {
  alive = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '(Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\' OR Name=\'chrome.exe\'" | ' +
    'Where-Object { $_.CommandLine -and $_.CommandLine.Contains(' + JSON.stringify(profile) + ') } | ' +
    'Measure-Object).Count'], { encoding: 'utf8', timeout: 60000 }).trim();
} catch { alive = 'не проверено'; }
check('B8. процессов этого профиля не осталось', alive === '0', alive);

try { rmSync(tmp, { recursive: true, force: true }); } catch { /* временная папка */ }

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено')
  : 'PASS: контракт моста соблюдён — без --dump-dom, таймаут отклоняется, движок обязателен, профиль и процессы убраны'));
process.exit(fail ? 1 : 0);
