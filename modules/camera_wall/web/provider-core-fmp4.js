// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
//  Провайдер видеостены: камера БЕЗ ПЕРЕКОДИРОВАНИЯ (ядро 2.870+).
//
//  ЗАЧЕМ. Прежний провайдер брал MJPEG: сервер перекодировал H.264 в поток картинок
//  и тратил около 0,4 ядра НА КАЖДУЮ камеру. Отсюда и потолок в две камеры Bambu.
//  Здесь браузер получает исходный H.264 и декодирует его сам (обычно видеокартой),
//  а сервер только перекладывает фрагменты — измерено в 250 раз дешевле.
//
//  СОВМЕСТИМОСТЬ. Проигрыватель живёт в ядре (/assets/composables/useCameraFmp4.js) —
//  один на программу, чтобы не было двух разных реализаций. Если модуль поставили на
//  старое ядро, где этого файла нет, загрузка честно падает, и сеанс сам переходит на
//  запасной MJPEG: список кандидатов в camera-providers.js это предусматривает.
// ============================================================================

const PLAYER_URL = '/assets/composables/useCameraFmp4.js';
let playerModule = null;

async function loadPlayer() {
  if (playerModule) return playerModule;
  playerModule = await import(PLAYER_URL);
  return playerModule;
}

export class CoreFmp4Provider {
  constructor(url, env = globalThis) {
    this.url = url;
    this.env = env;
    this.video = null;
    this.player = null;
    this.closed = true;
    this.timer = null;
    this.rate = null;
  }

  open(host, callbacks = {}) {
    this.close();
    this.closed = false;
    const video = this.env.document.createElement('video');
    this.video = video;
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('playsinline', '');
    video.style.width = '100%';
    video.style.height = '100%';
    video.style.objectFit = 'contain';
    video.style.background = '#000';
    if (host && host.replaceChildren) host.replaceChildren(video);

    // Первый фрагмент — это и есть доказательство живого потока. Без него не заявляем LIVE:
    // пустой чёрный прямоугольник не должен выглядеть как работающая камера.
    let liveSent = false;
    const fail = (reason) => {
      if (this.closed) return;
      if (callbacks.onError) callbacks.onError(new Error(String(reason || 'fmp4_failed')));
    };

    return loadPlayer().then((mod) => {
      if (this.closed) return;
      this.player = mod.createFmp4Player({
        env: this.env,
        onStatus: (kind, detail) => {
          if (this.closed) return;
          if (kind === 'live' && !liveSent) {
            liveSent = true;
            if (this.timer != null) { this.env.clearTimeout(this.timer); this.timer = null; }
            if (callbacks.onLive) callbacks.onLive({ freshness: 'fragments' });
          } else if (kind === 'error') {
            fail((detail && detail.reason) || 'fmp4_failed');
          }
        },
      });
      this.timer = this.env.setTimeout(() => {
        if (!this.closed && !liveSent) fail('first_frame_timeout');
      }, 15000);
      // Измеренная частота кадров. Берём у браузера счётчик ДЕКОДИРОВАННЫХ кадров: он не зависит
      // ни от наших предположений, ни от ощущений. Раз в две секунды считаем прирост и отдаём
      // число наверх — плитка показывает его рядом с подписью пути.
      let prevFrames = -1;
      let prevAt = 0;
      this.rate = this.env.setInterval(() => {
        if (this.closed || !liveSent) return;
        const q = (video.getVideoPlaybackQuality && video.getVideoPlaybackQuality()) || null;
        const frames = q ? q.totalVideoFrames
          : (typeof video.webkitDecodedFrameCount === 'number' ? video.webkitDecodedFrameCount : -1);
        const at = Date.now();
        if (frames < 0) return;
        if (prevFrames >= 0 && at > prevAt) {
          const fps = (frames - prevFrames) * 1000 / (at - prevAt);
          if (fps >= 0 && callbacks.onLive) {
            // Вместе с к/с отдаём ДВА разных счётчика, чтобы владелец видел причину рывка,
            // а не гадал: g — данные от принтера не пришли вовремя (связь и камера),
            // s — данные были, а картинка стояла (это уже мы). Читать журнал не требуется.
            const st = (this.player && this.player.state) || {};
            let extra = '';
            if (st.streamGaps) extra += ';g:' + st.streamGaps;
            if (st.stallJumps) extra += ';s:' + st.stallJumps;
            callbacks.onLive({
              freshness: 'fps:' + (fps < 10 ? fps.toFixed(1) : String(Math.round(fps))) + extra,
            });
          }
        }
        prevFrames = frames;
        prevAt = at;
      }, 2000);
      return this.player.start(video, this.url).then((ok) => {
        if (!ok && !liveSent) fail('fmp4_stream_failed');
      });
    }).catch(() => fail('fmp4_player_unavailable'));
  }

  // Снимок последнего кадра — тем же способом, что и у остальных провайдеров:
  // рисуем текущий кадр видео в canvas.
  captureFrame() {
    try {
      const v = this.video;
      if (!v || !v.videoWidth || !v.videoHeight) return '';
      const canvas = this.env.document.createElement('canvas');
      const scale = Math.min(1, 1280 / v.videoWidth);
      canvas.width = Math.max(1, Math.round(v.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(v.videoHeight * scale));
      canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.78);
    } catch (_) { return ''; }
  }

  close() {
    if (this.closed && !this.video) return;
    this.closed = true;
    if (this.timer != null) { this.env.clearTimeout(this.timer); this.timer = null; }
    if (this.rate != null) { this.env.clearInterval(this.rate); this.rate = null; }
    const player = this.player;
    this.player = null;
    if (player) { try { player.stop(); } catch (_) {} }
    const video = this.video;
    this.video = null;
    if (video) {
      try { video.removeAttribute('src'); video.load(); video.remove(); } catch (_) {}
    }
  }
}
