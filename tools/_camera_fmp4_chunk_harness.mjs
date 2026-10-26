// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Alpha 2.885 — стенд «резать поток где угодно».
//
// Запуск: node _camera_fmp4_chunk_harness.mjs <file:///…/useCameraFmp4.js> <файл base64> <режим>
//   режим: all               — весь поток одним куском (эталон)
//          size:N            — куски ровно по N байт
//          offsets:a,b,c     — резать в указанных местах
//
// Подставные здесь только MediaSource, SourceBuffer, fetch и видеоэлемент — того, чего в Node
// нет физически. Разбор потока делает НАСТОЯЩИЙ код проигрывателя. Стенд записывает, ЧТО
// именно ушло в приёмник видео: тип первой коробки, длину и контрольную сумму каждого куска.
// Сравнение этих записей между режимами и есть доказательство, что место разреза ни на что
// не влияет.
import fs from 'fs';

const playerUrl = process.argv[2];
const b64Path = process.argv[3];
const mode = process.argv[4] || 'all';
const { createFmp4Player } = await import(playerUrl);

const buf = new Uint8Array(Buffer.from(fs.readFileSync(b64Path, 'utf8').trim(), 'base64'));

function chunksFor(mode) {
  if (mode === 'all') return [buf];
  if (mode.startsWith('size:')) {
    const n = Math.max(1, parseInt(mode.slice(5), 10));
    const out = [];
    for (let i = 0; i < buf.length; i += n) out.push(buf.slice(i, Math.min(buf.length, i + n)));
    return out;
  }
  if (mode.startsWith('offsets:')) {
    const cuts = mode.slice(8).split(',').map(Number).filter((x) => x > 0 && x < buf.length);
    cuts.sort((a, b) => a - b);
    const out = [];
    let prev = 0;
    for (const c of cuts) { out.push(buf.slice(prev, c)); prev = c; }
    out.push(buf.slice(prev));
    return out.filter((c) => c.length);
  }
  throw new Error('неизвестный режим: ' + mode);
}

const appends = [];
// Приёмник видео обязан вести себя как настоящий: после каждой порции он сообщает updateend,
// и только тогда проигрыватель отдаёт следующую. Без этого стенд мерил бы не разбор потока,
// а скорость опустошения очереди.
const listeners = [];
const sb = {
  updating: false, mode: '', remove() {}, buffered: { length: 0 },
  addEventListener(name, cb) { if (name === 'updateend') listeners.push(cb); },
  appendBuffer(chunk) {
    const u = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk);
    let sum = 0;
    for (let i = 0; i < u.length; i++) sum = (sum + u[i] * (i % 7 + 1)) >>> 0;
    const type = u.length >= 8
      ? String.fromCharCode(u[4], u[5], u[6], u[7]) : '????';
    appends.push({ type, len: u.length, sum });
    for (const cb of listeners.slice()) cb();
  },
};
function FakeMS() { this.readyState = 'open'; }
FakeMS.isTypeSupported = () => true;
FakeMS.prototype.addEventListener = function (n, cb) { if (n === 'sourceopen') cb(); };
FakeMS.prototype.addSourceBuffer = () => sb;
FakeMS.prototype.endOfStream = () => {};

const chunks = chunksFor(mode);
let step = 0;
const reader = {
  read() {
    if (step < chunks.length) return Promise.resolve({ done: false, value: chunks[step++] });
    return Promise.resolve({ done: true, value: null });
  },
};
const env = {
  MediaSource: FakeMS,
  fetch: () => Promise.resolve({ ok: true, status: 200, body: { getReader: () => reader } }),
  setInterval: () => 1, clearInterval: () => {},
  setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: (id) => clearTimeout(id),
  AbortController: function () { this.signal = {}; this.abort = () => {}; },
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} },
};
const video = {
  muted: false, src: '', currentTime: 0, playbackRate: 1, paused: false,
  play: () => Promise.resolve(), removeAttribute() {}, load() {},
};

const p = createFmp4Player({ env });
await p.start(video, 'http://printer.invalid/camera.mp4');
console.log('@@' + JSON.stringify({
  mode, chunks: chunks.length, appends,
  fragments: p.state.fragments, err: p.state.lastError || '',
}) + '@@');
