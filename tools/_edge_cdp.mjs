// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Alpha 2.834/2.835 — CLI-обёртка моста «браузер -> отрендеренный DOM» поверх ЕДИНОЙ реализации CDP.
//
// ЗАЧЕМ. На ферменном ПК headless-движки перестали отдавать документ по --dump-dom (Edge 150:
// stdout пуст, rc=0), а отдельный GPU-процесс Chromium здесь падает фатально
// («GPU process isn't usable. Goodbye.») — поэтому браузер запускается с --in-process-gpu, а
// документ читается по CDP. Node выбран транспортом потому, что у него есть готовые fetch и
// WebSocket: свой клиент WS в Python на этой машине упирался в таймауты рукопожатия.
//
// Alpha 2.835: сама работа с протоколом вынесена в tools/_edge_cdp_lib.mjs — ОДНА реализация CDP
// на все харнессы (питоновские через этот CLI, узловые через прямой import). Добавлены:
//   * diagFile — ошибки консоли, предупреждения (в т.ч. «[Vue warn]»), необработанные исключения
//     и отказы промисов. Без них браузерные проверки не могли краснеть на ошибках страницы;
//   * НАСТОЯЩЕЕ изменение вьюпорта из сценария (window.__fmViewport -> Emulation), нужное для
//     проверок «после resize» — синтетический resize-эвент этого не даёт.
//
// Использование:
//   node tools/_edge_cdp.mjs <exe> <url> <profile> <w> <h> <settleMs> [extraArgsJSON] [evalFile] [shotFile] [diagFile]
// stdout: сам документ (outerHTML). Ошибка -> пустой stdout и код 1; харнесс решает, как реагировать.
// Никакой сети, кроме 127.0.0.1 к своему же браузеру; ни БД, ни DATA_DIR, ни принтеров.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { openStage } from './_edge_cdp_lib.mjs';

const [exe, url, profile, wRaw, hRaw, settleRaw, extraRaw, evalFile, shotFile, diagFile] = process.argv.slice(2);
const W = parseInt(wRaw || '1440', 10), H = parseInt(hRaw || '900', 10);
const SETTLE = Math.max(200, Math.min(20000, parseInt(settleRaw || '900', 10)));
let extra = [];
try { extra = extraRaw ? JSON.parse(extraRaw) : []; } catch { extra = []; }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let out = '';
let stage = null;
try {
  // Профиль создаёт библиотека; переданный путь используется как якорь имени, чтобы вызывающий
  // Python видел ту же временную папку и мог её убрать (контракт _edge_dom.render_dom сохранён).
  stage = await openStage({ url, width: W, height: H, extraArgs: extra, engine: exe, profileHint: profile });
  await sleep(SETTLE);                       // даём смонтироваться Vue и сработать таймерам
  // Сценарий отдаётся файлом, а не аргументом: в нём кавычки и переводы строк.
  if (evalFile && existsSync(evalFile)) {
    const code = readFileSync(evalFile, 'utf8');
    let done = false, seen = 0;
    const p = stage.evaluate(code, { awaitPromise: true, timeoutMs: 600000 })
      .then(() => { done = true; }, () => { done = true; });
    // Пока сценарий работает, обслуживаем его запросы на смену вьюпорта: только так проверка
    // «после resize» видит настоящий новый размер окна, а не подделанное событие.
    while (!done) {
      await sleep(150);
      let req = null;
      try { req = JSON.parse(await stage.evaluate('JSON.stringify(window.__fmViewport||null)') || 'null'); }
      catch { req = null; }
      if (req && req.seq && req.seq > seen) {
        seen = req.seq;
        try {
          await stage.send('Emulation.setDeviceMetricsOverride', {
            width: Math.round(req.w), height: Math.round(req.h),
            deviceScaleFactor: Number(req.dsf) || 1, mobile: false,
          });
        } catch { /* сценарий сам заметит по таймауту */ }
        try { await stage.evaluate('window.__fmViewportApplied=' + seen); } catch { /* страница ушла */ }
      }
    }
    await p;
    await sleep(500);
  }
  out = (await stage.outerHTML()) || '';
  if (shotFile) await stage.screenshot(shotFile);
  if (diagFile) {
    const diag = await stage.unhandled();
    writeFileSync(diagFile, JSON.stringify({
      consoleErrors: stage.consoleErrors, consoleWarnings: stage.consoleWarnings,
      pageErrors: stage.pageErrors, unhandled: (diag.unhandled || []).concat(diag.errors || []),
    }), 'utf8');
  }
} catch (e) {
  console.error('CDP bridge: ' + String((e && e.message) || e));
  if (diagFile) {
    try { writeFileSync(diagFile, JSON.stringify({ bridgeError: String((e && e.message) || e) }), 'utf8'); }
    catch { /* нечего сообщить */ }
  }
} finally {
  if (stage) { try { await stage.close(); } catch { /* закрытие уже сделано */ } }
}

if (out) { process.stdout.write(out); process.exit(0); }
process.exit(1);
