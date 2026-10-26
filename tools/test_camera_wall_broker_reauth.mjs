// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Видеостена: после включения защиты вкладка, где вход уже есть, переподключается сама (16.10.2026, R-150).
// Сервер теперь перепроверяет вход у открытых сокетов и закрывает сокет без входа кодом 4401. Раньше
// стена считала любой 4401 окончательным и переставала показывать состояния принтеров до перезагрузки.
// Проверяется ИСПОЛНЕНИЕМ настоящего modules/camera_wall/web/printer-state-broker.js с поддельными
// WebSocket, fetch и таймером. Запуск: node tools/test_camera_wall_broker_reauth.mjs   (0 = пройдено)
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const { PrinterStateBroker } = await import(pathToFileURL(join(REPO, 'modules', 'camera_wall', 'web', 'printer-state-broker.js')).href);
let fail = 0;
const check = (name, cond, extra) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name + (!cond && extra !== undefined ? '  :: ' + JSON.stringify(extra) : '')); if (!cond) fail++; };

function makeEnv(auth) {
  const sockets = [];
  const timers = [];
  class FakeWS { constructor(url) { this.url = url; sockets.push(this); } close() {} }
  const env = {
    location: { protocol: 'http:', host: '127.0.0.1:8000' },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => {},
  };
  const fetch = async () => ({ ok: true, json: async () => auth.value });
  return { env, sockets, timers, FakeWS, fetch };
}

async function closeWith(broker, sockets, code) {
  const s = sockets[sockets.length - 1];
  await s.onclose({ code });
}

async function runTimers(timers) {
  while (timers.length) { const t = timers.shift(); t.fn(); }
}

// 1. Защиту включили, а в этом браузере вход уже есть: 4401 -> переподключение, не остановка.
{
  const auth = { value: { enabled: true, authenticated: true } };
  const E = makeEnv(auth);
  const statuses = [];
  const b = new PrinterStateBroker({ env: E.env, WebSocket: E.FakeWS, fetch: E.fetch, onStatus: (s) => statuses.push(s) });
  b.start();
  await closeWith(b, E.sockets, 4401);
  check('1. 4401 при действующем входе — стена переподключается, а не останавливается',
    !b.authStopped && !statuses.includes('auth-denied') && E.timers.length === 1, { statuses, stopped: b.authStopped });
  await runTimers(E.timers);
  check('1b. новое соединение открыто', E.sockets.length === 2, E.sockets.length);
  E.sockets[1].onmessage({ data: '{"p1": {"status": "IDLE"}}' });
  check('1c. после живого сообщения счётчик повторов сброшен', b.authRetries === 0, b.authRetries);
}

// 2. Четвёртый 4401 подряд без единого сообщения — остановка (не крутим переподключения вечно).
{
  const auth = { value: { enabled: true, authenticated: true } };
  const E = makeEnv(auth);
  const statuses = [];
  const b = new PrinterStateBroker({ env: E.env, WebSocket: E.FakeWS, fetch: E.fetch, onStatus: (s) => statuses.push(s) });
  b.start();
  for (let i = 0; i < 3; i++) { await closeWith(b, E.sockets, 4401); await runTimers(E.timers); }
  await closeWith(b, E.sockets, 4401);
  check('2. больше трёх раз подряд — стена останавливается с «вход нужен»', b.authStopped && statuses.includes('auth-denied'), statuses);
}

// 3. Входа нет: 4401 останавливает, как раньше.
{
  const auth = { value: { enabled: true, authenticated: false } };
  const E = makeEnv(auth);
  const statuses = [];
  const b = new PrinterStateBroker({ env: E.env, WebSocket: E.FakeWS, fetch: E.fetch, onStatus: (s) => statuses.push(s) });
  b.start();
  await closeWith(b, E.sockets, 4401);
  check('3. 4401 без входа — остановка, как раньше', b.authStopped && statuses.includes('auth-denied') && E.timers.length === 0, statuses);
}

// 4. 4403 (нет прав) — всегда остановка.
{
  const auth = { value: { enabled: true, authenticated: true } };
  const E = makeEnv(auth);
  const b = new PrinterStateBroker({ env: E.env, WebSocket: E.FakeWS, fetch: E.fetch });
  b.start();
  await closeWith(b, E.sockets, 4403);
  check('4. 4403 — остановка без повторов', b.authStopped && E.timers.length === 0);
}

console.log(fail ? `\nFAIL: ${fail}` : '\nPASS: видеостена переподключается после включения защиты, без бесконечных повторов');
process.exit(fail ? 1 : 0);
