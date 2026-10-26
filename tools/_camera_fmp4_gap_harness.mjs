// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Alpha 2.877 — стенд для счёта перерывов приёма БЕЗ браузера и БЕЗ принтера.
//
// Запуск:  node _camera_fmp4_gap_harness.mjs <file:///…/useCameraFmp4.js> <файл с base64 потока>
//
// Подставные здесь только MediaSource, SourceBuffer, fetch и видеоэлемент — то, чего в Node
// нет физически. Разбор коробок MP4 и счёт перерывов выполняет НАСТОЯЩИЙ код проигрывателя
// на НАСТОЯЩИХ байтах ffmpeg. Часы подменены: между двумя порциями проходит две секунды —
// ровно то, что владелец видит как провал связи.
import fs from 'fs';

const playerUrl = process.argv[2];
const b64Path = process.argv[3];
const { createFmp4Player, splitBoxes } = await import(playerUrl);

const buf = new Uint8Array(Buffer.from(fs.readFileSync(b64Path, 'utf8').trim(), 'base64'));
const { boxes } = splitBoxes(buf);
const first = boxes.findIndex((b) => b.type === 'moof');
if (first < 0 || !boxes[first + 3]) {
  console.log('@@' + JSON.stringify({ error: 'stream_too_short', boxes: boxes.length }) + '@@');
  process.exit(0);
}
const chunk1 = buf.slice(0, boxes[first + 2].start);                    // шапка + одна порция
const chunk2 = buf.slice(boxes[first + 2].start, boxes[first + 3].end); // ещё одна порция

let t = 1000;
let wsSeen = '';
const sb = {
  updating: false, mode: '', addEventListener() {}, appendBuffer() {},
  remove() {}, buffered: { length: 0 },
};
function FakeMS() { this.readyState = 'open'; }
FakeMS.isTypeSupported = () => true;
FakeMS.prototype.addEventListener = function (n, cb) { if (n === 'sourceopen') cb(); };
FakeMS.prototype.addSourceBuffer = () => sb;
FakeMS.prototype.endOfStream = () => {};

let step = 0;
const reader = {
  read() {
    step += 1;
    if (step === 1) return Promise.resolve({ done: false, value: chunk1 });
    if (step === 2) { t += 2000; return Promise.resolve({ done: false, value: chunk2 }); }
    return Promise.resolve({ done: true, value: null });
  },
};
const env = {
  MediaSource: FakeMS,
  fetch: () => Promise.resolve({ ok: true, status: 200, body: { getReader: () => reader } }),
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id),
  AbortController: function () { this.signal = {}; this.abort = () => {}; },
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} },
};

// Alpha 2.879. Второй способ доставки — WebSocket. Здесь он подставной, но данные ИДУТ ТЕ ЖЕ
// и разбирает их настоящий проигрыватель: проверяем, что новый путь действительно работает и
// что адрес сокета выводится из адреса маршрута (иначе модуль пришлось бы переделывать).
if (process.argv[4] === 'ws') {
  const RealURL = URL;
  env.URL = Object.assign(function (u, base) { return new RealURL(u, base); },
                          { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} });
  env.location = { href: 'http://127.0.0.1:8000/' };
  env.WebSocket = function (u) {
    wsSeen = u;
    const self = this;
    setTimeout(() => {
      self.onmessage({ data: chunk1.buffer.slice(chunk1.byteOffset, chunk1.byteOffset + chunk1.byteLength) });
      t += 2000;
      self.onmessage({ data: chunk2.buffer.slice(chunk2.byteOffset, chunk2.byteOffset + chunk2.byteLength) });
      self.onclose();
    }, 0);
    this.close = () => {};
  };
}

const video = {
  muted: false, src: '', currentTime: 0, playbackRate: 1, paused: false,
  play: () => Promise.resolve(), removeAttribute() {}, load() {},
};

const p = createFmp4Player({ env, now: () => t });
await p.start(video, 'http://printer.invalid/camera.mp4');
console.log('@@' + JSON.stringify({
  gaps: p.state.streamGaps, max: p.state.maxGapMs, stalls: p.state.stallJumps,
  frags: p.state.fragments, mode: sb.mode, transport: p.state.transport, wsUrl: wsSeen,
}) + '@@');
