// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
//  useCameraFmp4 — показ камеры БЕЗ ПЕРЕКОДИРОВАНИЯ (Alpha 2.870, этап 1).
//
//  ЗАЧЕМ. Прежний путь отдаёт MJPEG: сервер перекодирует H.264 с принтера в поток
//  картинок. Измерено 23.08.2026 (ffmpeg -benchmark, ролик 1920x1080, 20 с):
//  перекодирование в MJPEG 15 к/с — 7,89 с процессорного времени, 30 к/с — 10,97 с,
//  ремукс без перекодирования — 0,03 с. Здесь браузер получает исходный H.264 во
//  фрагментированном MP4 и декодирует его видеокартой: сервер почти не тратит процессор.
//
//  КАК. MediaSource Extensions: маршрут /api/printer/<id>/camera.mp4 отдаёт «шапку»
//  (ftyp+moov), затем фрагменты (moof+mdat). Шапку кладём в SourceBuffer первой,
//  дальше — фрагменты по мере прихода.
//
//  ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО: имени принтера, кодов доступа и любых адресов принтера —
//  только идентификатор и наш собственный маршрут.
// ============================================================================

// Строка кодека обязана совпадать с реальным потоком, иначе браузер молча откажется
// принимать данные. Берём её ИЗ САМОГО ПОТОКА (коробка avcC внутри moov), а не угадываем:
// у разных камер профиль и уровень разные.
function codecFromInit(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let i = 0; i + 8 <= bytes.length; i++) {
    if (bytes[i] === 0x61 && bytes[i + 1] === 0x76 && bytes[i + 2] === 0x63 && bytes[i + 3] === 0x43) {
      // avcC: версия, профиль, совместимость, уровень
      const p = i + 4;
      if (p + 4 > bytes.length) break;
      const hex = (v) => v.toString(16).padStart(2, '0');
      return 'avc1.' + hex(dv.getUint8(p + 1)) + hex(dv.getUint8(p + 2)) + hex(dv.getUint8(p + 3));
    }
  }
  return '';
}

// Отделяет «шапку» от фрагментов ровно так же, как это делает сервер: по целым коробкам MP4.
// Резать поток произвольно нельзя — браузер не примет обрывок.
function splitBoxes(buf) {
  const out = [];
  let off = 0;
  while (off + 8 <= buf.length) {
    const dv = new DataView(buf.buffer, buf.byteOffset + off, Math.min(16, buf.length - off));
    let size = dv.getUint32(0);
    let head = 8;
    if (size === 1) {
      if (off + 16 > buf.length) break;
      size = Number(dv.getBigUint64(8));
      head = 16;
    }
    if (size < head || off + size > buf.length) break;
    const type = String.fromCharCode(buf[off + 4], buf[off + 5], buf[off + 6], buf[off + 7]);
    out.push({ type, start: off, end: off + size });
    off += size;
  }
  return { boxes: out, consumed: off };
}

// Запас видео (Alpha 2.877). Порции приходят каждые 200 мс, но сеть не идеальна: если играть
// вплотную к последнему кадру, любая задержка означает, что играть нечего — и картинка встаёт.
// Держим запас чуть больше секунды и правим его МЯГКО. Числа подобраны от шага порции:
// запас в шесть порций, ускорение только при отставании вдвое больше запаса.
const TARGET_LATENCY = 1.2;   // сколько секунд видео держим в запасе
const MAX_LATENCY = 5.0;      // больше этого — не догоняем, а перепрыгиваем
const KEEP_BUFFER = 12;       // сколько секунд прошлого держим в памяти
// Перерыв приёма: порции идут каждые 200 мс, поэтому секунда тишины — это уже провал связи,
// а не разброс. Считаем ИМЕННО приход данных, до всякого показа: если провал виден здесь,
// к отрисовке он отношения не имеет.
const STREAM_GAP_MS = 1000;
// Сколько ждём первый байт из сокета, прежде чем уйти на запасной путь HTTP.
const WS_FIRST_DATA_MS = 8000;

export function createFmp4Player(options = {}) {
  const env = options.env || globalThis;
  const MS = env.MediaSource || env.WebKitMediaSource;

  const state = {
    supported: !!(MS && env.fetch && typeof MS.isTypeSupported === 'function'),
    running: false,
    fragments: 0,
    bytes: 0,
    lastError: '',
    streamGaps: 0,      // сколько раз данные от принтера пропадали дольше секунды
    maxGapMs: 0,        // самый долгий такой перерыв
    stallJumps: 0,      // сколько раз вставал показ при наличии данных
    transport: '',      // 'ws' или 'http' — чем реально приехало видео
  };

  let controller = null;
  let mediaSource = null;
  let sourceBuffer = null;
  let videoEl = null;
  let objectUrl = '';
  let pending = [];          // очередь: SourceBuffer принимает по одному куску за раз
  let carry = new Uint8Array(0);
  let initSent = false;
  let stallTimer = null;
  let sock = null;
  let liveSaid = false;
  let backlogSaid = false;
  let onStatus = options.onStatus || (() => {});
  const nowMs = options.now || (() => Date.now());
  let lastFragAt = 0;

  // Отметить приход порции. Первую не считаем: до неё перерыв — это ожидание подключения.
  function noteArrival() {
    const t = nowMs();
    if (lastFragAt) {
      const gap = t - lastFragAt;
      if (gap > state.maxGapMs) state.maxGapMs = gap;
      if (gap >= STREAM_GAP_MS) {
        state.streamGaps += 1;
        say('gap', { ms: gap, gaps: state.streamGaps });
      }
    }
    lastFragAt = t;
  }

  function say(kind, detail) {
    try { onStatus(kind, detail || {}); } catch (_) {}
  }

  // Alpha 2.879. ЗАЧЕМ ВООБЩЕ СОКЕТ. Измерено 25.08.2026 на этой машине: браузер держит к
  // ОДНОМУ адресу ровно ШЕСТЬ длинных ответов HTTP/1.1. Двенадцать одинаковых потоков дали
  // такую картину: потоки 0-5 получили первый байт сразу, потоки 6-11 не получили НИЧЕГО и
  // висели. Двенадцать WebSocket к тому же адресу открылись все за 0,2 секунды. Отсюда и
  // жалоба «загружаются шесть камер, остальные подключаются». Данные те же самые — меняется
  // только способ доставки; HTTP остаётся запасным путём.
  function wsUrlFrom(httpUrl) {
    try {
      const base = (env.location && env.location.href) || undefined;
      const u = new env.URL(httpUrl, base);
      u.protocol = (u.protocol === 'https:') ? 'wss:' : 'ws:';
      u.pathname = u.pathname.replace(/camera\.mp4$/, 'camera.ws');
      return u.pathname.endsWith('camera.ws') ? u.toString() : '';
    } catch (_) { return ''; }
  }

  // Возвращает true, если по сокету пришли данные (сколько-то), и false, если он не открылся
  // или закрылся, не отдав ни байта: тогда зовущий уходит на запасной путь.
  function streamOverWs(wsUrl) {
    return new Promise((resolve) => {
      let s0 = null;
      try { s0 = new env.WebSocket(wsUrl); } catch (_) { resolve(false); return; }
      sock = s0;
      try { s0.binaryType = 'arraybuffer'; } catch (_) {}
      let got = 0;
      let settled = false;
      const done = (v) => { if (!settled) { settled = true; resolve(v); } };
      const guard = env.setTimeout(() => {
        if (!got) { try { s0.close(); } catch (_) {} done(false); }
      }, WS_FIRST_DATA_MS);
      s0.onmessage = (ev) => {
        if (!state.running) return;
        got += 1;
        if (got === 1) {
          state.transport = 'ws';
          try { env.clearTimeout(guard); } catch (_) {}
        }
        try { onData(new Uint8Array(ev.data)); } catch (_) {}
      };
      s0.onerror = () => { if (!got) done(false); };
      s0.onclose = () => {
        try { env.clearTimeout(guard); } catch (_) {}
        done(got > 0);
      };
    });
  }

  function pump() {
    if (!sourceBuffer || sourceBuffer.updating || !pending.length) return;
    const chunk = pending.shift();
    try {
      sourceBuffer.appendBuffer(chunk);
    } catch (e) {
      // QuotaExceededError: буфер переполнен — чистим прошлое и пробуем снова.
      if (e && e.name === 'QuotaExceededError') {
        trim(true);
        pending.unshift(chunk);
      } else {
        state.lastError = String((e && e.name) || e);
        say('error', { reason: state.lastError });
      }
    }
  }

  // Живое видео не должно копить память и отставать: держим в буфере несколько секунд
  // и подтягиваем воспроизведение к концу, если браузер отстал (после сворачивания окна).
  function trim(force) {
    if (!sourceBuffer || sourceBuffer.updating || !videoEl) return;
    const b = sourceBuffer.buffered;
    if (!b.length) return;
    const end = b.end(b.length - 1);
    const start = b.start(0);
    const keep = force ? 3 : KEEP_BUFFER;
    if (end - start > keep) {
      try { sourceBuffer.remove(start, end - keep); } catch (_) {}
    }
    // Alpha 2.877: держим ЗАПАС, а не гонимся за краем.
    //   отстали сильно (больше MAX_LATENCY) — перепрыгиваем, но НЕ на край, а на запас;
    //   отстали умеренно — чуть ускоряемся (5 %, глазу незаметно);
    //   запас кончается — чуть замедляемся, чтобы он восстановился;
    //   иначе — обычная скорость.
    //  Alpha 2.879: пороги подтянуты к цели. Прежние (ускорять при отставании больше 2,4 с,
    //  замедлять при запасе меньше 0,6 с) означали, что в полосе 0,6-2,4 с скорость ровно 1,
    //  и запас спокойно оседал на нижнем краю — 0,6 с вместо заявленных 1,2 с. Теперь запас
    //  ниже цели подтягивается вверх, а выше полутора целей — плавно тратится.
    const lag = end - (videoEl.currentTime || 0);
    let rate = 1;
    if (lag > MAX_LATENCY || lag < 0) {
      try { videoEl.currentTime = Math.max(0, end - TARGET_LATENCY); } catch (_) {}
    } else if (lag > TARGET_LATENCY * 1.6) {
      rate = 1.05;
    } else if (lag < TARGET_LATENCY * 0.9) {
      rate = 0.97;
    }
    if (videoEl.playbackRate !== rate) {
      try { videoEl.playbackRate = rate; } catch (_) {}
    }
  }

  // Alpha 2.876: сторож застревания. Даже в режиме sequence браузер может встать: пакет
  // потерялся, вкладка была свёрнута, декодер споткнулся. Признак застревания — время
  // воспроизведения не двигается, ХОТЯ впереди есть данные. Тогда перешагиваем вперёд, а не
  // ждём молча: замерший кадр выглядит как «камера умерла», хотя поток идёт.
  let lastSeenTime = -1;
  let stuckTicks = 0;
  function watchStall() {
    if (!videoEl || !sourceBuffer) return;
    const b = sourceBuffer.buffered;
    if (!b.length) return;
    const end = b.end(b.length - 1);
    const cur = videoEl.currentTime || 0;
    if (videoEl.paused) { try { videoEl.play().catch(() => {}); } catch (_) {} }
    const moved = Math.abs(cur - lastSeenTime) > 0.02;
    lastSeenTime = cur;
    // Пока впереди меньше запаса, «стояние» — это нормальное накопление, а не застревание.
    //  Alpha 2.879: порог опущен до трети цели — при прежней половине сторож был выключен
    //  ровно в той полосе, где проигрыватель и живёт, и застревание некому было заметить.
    if (moved || end - cur < TARGET_LATENCY * 0.35) { stuckTicks = 0; return; }
    stuckTicks += 1;
    if (stuckTicks < 2) return;                 // одна секунда без движения — ещё не беда
    stuckTicks = 0;
    // Ищем ближайший кусок буфера ПОСЛЕ текущего времени: если между ними дыра, перешагиваем.
    // Прыгаем НЕ на край, а на запас: прыжок вплотную к последнему кадру гарантирует,
    // что через мгновение играть снова будет нечего, и застревание повторится.
    let target = Math.max(0, end - TARGET_LATENCY);
    for (let i = 0; i < b.length; i++) {
      if (b.start(i) > cur) { target = b.start(i) + 0.01; break; }
    }
    try { videoEl.currentTime = Math.max(0, target); } catch (_) {}
    state.stallJumps = (state.stallJumps || 0) + 1;
    say('stall', { at: cur, to: target, jumps: state.stallJumps });
  }

  //  Alpha 2.885. РАЗБОР ПОТОКА — КОНЕЧНЫЙ АВТОМАТ, А НЕ «ЧТО ПРИШЛО, ТО И РАЗОБРАЛИ».
  //  Сеть режет поток где угодно: коробка MP4 может прийти половиной, а может — три штуки в
  //  одном куске. Окончательно разобранным считается ТОЛЬКО то, что дошло целиком:
  //    * шапка — от начала до конца `moov` (одного `ftyp` мало: без `moov` нет ни кодека,
  //      ни описания дорожки, и браузер такой приёмник не примет);
  //    * фрагмент — от `moof` до конца ЕГО `mdat`.
  //  Всё, что не дошло, остаётся в `carry` и ждёт следующего куска. Ни один байт не теряется.
  const CARRY_LIMIT = 8 * 1024 * 1024;   // защита от бесконечного накопления при битом потоке

  function onData(buf) {
    const merged = new Uint8Array(carry.length + buf.length);
    merged.set(carry, 0);
    merged.set(buf, carry.length);
    state.bytes += buf.length;
    const { boxes } = splitBoxes(merged);
    let keep = 0;              // сколько байт разобрано ОКОНЧАТЕЛЬНО
    let i = 0;

    if (!initSent) {
      //  Ждём `moov` целиком. Пока его нет — копим, ничего не решая.
      const moovIdx = boxes.findIndex((b) => b.type === 'moov');
      if (moovIdx < 0) {
        carry = merged;
        if (carry.length > CARRY_LIMIT && !state.lastError) {
          state.lastError = 'init_not_found';
          say('error', { reason: state.lastError, bytes: carry.length });
        }
        return;
      }
      const init = merged.slice(0, boxes[moovIdx].end);
      const codec = codecFromInit(init);
      const mime = 'video/mp4; codecs="' + (codec || 'avc1.640028') + '"';
      if (!MS.isTypeSupported(mime)) {
        state.lastError = 'codec_unsupported';
        say('error', { reason: state.lastError, mime });
        return;
      }
      try {
        sourceBuffer = mediaSource.addSourceBuffer(mime);
        // Alpha 2.876. ЗДЕСЬ БЫЛА ПРИЧИНА ФРИЗОВ У КАМЕР BAMBU.
        //  'segments' — режим по умолчанию: браузер раскладывает куски по МЕТКАМ ВРЕМЕНИ из
        //  самого потока. У RTSP-камер метки бывают неровными и немонотонными, и тогда на
        //  ленте воспроизведения появляются дыры: видео доходит до дыры и ВСТАЁТ, пока она не
        //  закроется. Именно так выглядит «0 кадров в секунду при живой картинке».
        //  'sequence' — куски укладываются подряд, в порядке добавления, БЕЗ дыр (документация
        //  Chrome для MSE). Оговорка про рассинхронизацию дорожек к нам не относится: звука в
        //  потоке нет вовсе (-an), дорожка одна.
        //  K2 идёт через WebRTC, у него своя буферизация — поэтому он и не фризил никогда.
        sourceBuffer.mode = 'sequence';
      } catch (e) {
        state.lastError = String((e && e.name) || e);
        say('error', { reason: state.lastError, mime });
        return;
      }
      sourceBuffer.addEventListener('updateend', () => { trim(false); pump(); });
      pending.push(init);
      initSent = true;
      keep = boxes[moovIdx].end;
      i = moovIdx + 1;
      say('init', { mime });
    }

    //  Фрагменты: только полными парами `moof` + его `mdat`.
    let got = 0;
    for (; i < boxes.length; i++) {
      if (boxes[i].type !== 'moof') {
        //  Служебные коробки между фрагментами (например, `styp` или `free`) не теряем и не
        //  показываем: просто отмечаем разобранными.
        keep = boxes[i].end;
        continue;
      }
      const mdat = boxes[i + 1];
      if (!mdat) break;                      // `mdat` ещё не пришёл — `moof` ОСТАЁТСЯ в carry
      if (mdat.type !== 'mdat') { keep = boxes[i].end; continue; }
      pending.push(merged.slice(boxes[i].start, mdat.end));
      state.fragments += 1;
      got += 1;
      keep = mdat.end;
      i += 1;
    }
    carry = merged.slice(keep);
    if (carry.length > CARRY_LIMIT) {
      //  Столько неразобранного бывает только при испорченном потоке: начинаем заново с
      //  ближайшего целого фрагмента, а не тянем мусор дальше.
      carry = new Uint8Array(0);
      state.resyncs = (state.resyncs || 0) + 1;
      say('resync', { reason: 'carry_overflow' });
    }
    if (got) noteArrival();
    // Alpha 2.879: отставание очереди — это ПРЕДУПРЕЖДЕНИЕ, а не смерть потока. Раньше здесь
    // объявлялась ошибка, а стена трактует любую ошибку как фатальную и гасит плитку — то
    // есть исправная камера выключалась из-за кратковременной заминки браузера. Гасим только
    // при явно безнадёжном отставании (200 порций — это 40 секунд).
    if (pending.length > 60 && !backlogSaid) {
      backlogSaid = true;
      say('backlog', { pending: pending.length });
    }
    if (pending.length > 200 && !state.lastError) {
      state.lastError = 'append_backlog';
      say('error', { reason: state.lastError, pending: pending.length });
    }
    pump();
    noteLive();
  }

  // Alpha 2.879. ЗДЕСЬ БЫЛ ДЕФЕКТ, И ОН ПОКАЗЫВАЛ РАБОЧУЮ КАМЕРУ КАК СЛОМАННУЮ.
  // Сообщение «пошло видео» отправлялось строкой `if (state.fragments === 1)` в самом конце
  // разбора. Но когда шапка и первая порция приходят ОДНИМ куском (обычное дело, а по
  // WebSocket — почти всегда), разбор шапки заканчивался раньше, оператором return, и до
  // этой строки дело не доходило вовсе. Дальше счётчик уже больше единицы, и условие не
  // срабатывало никогда: картинка идёт, а стена через 15 секунд пишет «камера не прислала
  // кадр» и уходит на переподключение. Теперь говорим один раз при первой же порции.
  function noteLive() {
    if (!liveSaid && state.fragments > 0) {
      liveSaid = true;
      say('live', {});
    }
  }

  async function start(video, url) {
    stop();
    if (!state.supported) { say('error', { reason: 'mse_unsupported' }); return false; }
    videoEl = video;
    state.running = true;
    state.fragments = 0;
    state.bytes = 0;
    state.lastError = '';
    state.streamGaps = 0;
    state.maxGapMs = 0;
    state.stallJumps = 0;
    lastFragAt = 0;
    liveSaid = false;
    backlogSaid = false;
    initSent = false;
    carry = new Uint8Array(0);
    pending = [];
    mediaSource = new MS();
    objectUrl = env.URL.createObjectURL(mediaSource);
    video.src = objectUrl;
    video.muted = true;
    await new Promise((resolve) => {
      mediaSource.addEventListener('sourceopen', resolve, { once: true });
    });
    lastSeenTime = -1;
    stuckTicks = 0;
    stallTimer = env.setInterval(watchStall, 500);
    // Сначала сокет: он не занимает место в шестёрке HTTP-соединений браузера.
    const wsu = (env.WebSocket && env.URL) ? wsUrlFrom(url) : '';
    if (wsu) {
      const okWs = await streamOverWs(wsu);
      if (okWs) return true;
      if (!state.running) return false;
      // Сокет не отдал ни байта: сервер старый, сокет закрыт правилами доступа или это не
      // Bambu. Идём прежним путём — там придёт понятный ответ (409/404) или само видео.
      say('fallback', { reason: 'ws_no_data' });
    }
    state.transport = 'http';
    controller = new env.AbortController();
    try {
      const resp = await env.fetch(url, { signal: controller.signal, cache: 'no-store' });
      if (!resp.ok || !resp.body) {
        state.lastError = 'http_' + resp.status;
        say('error', { reason: state.lastError });
        return false;
      }
      const reader = resp.body.getReader();
      while (state.running) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value && value.length) onData(value);
      }
    } catch (e) {
      if (state.running) {
        state.lastError = String((e && e.name) || e);
        say('error', { reason: state.lastError });
      }
      return false;
    }
    return true;
  }

  function stop() {
    state.running = false;
    if (sock) { try { sock.close(); } catch (_) {} sock = null; }
    if (stallTimer != null) { try { env.clearInterval(stallTimer); } catch (_) {} stallTimer = null; }
    if (controller) { try { controller.abort(); } catch (_) {} controller = null; }
    if (sourceBuffer && mediaSource && mediaSource.readyState === 'open') {
      try { mediaSource.endOfStream(); } catch (_) {}
    }
    sourceBuffer = null;
    mediaSource = null;
    pending = [];
    carry = new Uint8Array(0);
    initSent = false;
    if (objectUrl) { try { env.URL.revokeObjectURL(objectUrl); } catch (_) {} objectUrl = ''; }
    if (videoEl) { try { videoEl.removeAttribute('src'); videoEl.load(); } catch (_) {} }
    videoEl = null;
  }

  return { state, start, stop, _internals: { codecFromInit, splitBoxes } };
}

export { codecFromInit, splitBoxes };
