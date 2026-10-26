// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
const SAFE_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';

function captureImage(env, image) {
  try {
    if (!image || !image.naturalWidth || !image.naturalHeight) return '';
    const canvas = env.document.createElement('canvas');
    const scale = Math.min(1, 1280 / image.naturalWidth);
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.78);
  } catch (_) { return ''; }
}

export class CoreMjpegProvider {
  constructor(url, env = globalThis) {
    this.url = url;
    this.env = env;
    this.image = null;
    this.timer = null;
    this.framePoll = null;
    this.closed = true;
  }

  open(host, callbacks = {}) {
    this.close();
    this.closed = false;
    const image = this.env.document.createElement('img');
    this.image = image;
    image.alt = '';
    image.decoding = 'async';
    image.draggable = false;
    let liveSent = false;
    const onLoad = () => {
      if (this.closed || liveSent) return;
      liveSent = true;
      if (this.timer != null) { this.env.clearTimeout(this.timer); this.timer = null; }
      if (this.framePoll != null) { this.env.clearInterval(this.framePoll); this.framePoll = null; }
      // Browser <img> confirms the first decoded frame, but exposes no reliable
      // per-frame counter after that. Do not claim continuous freshness.
      if (callbacks.onLive) callbacks.onLive({ freshness: 'first-frame-only' });
    };
    const onError = () => { if (!this.closed && callbacks.onError) callbacks.onError(new Error('mjpeg_stream_failed')); };
    image.addEventListener('load', onLoad);
    image.addEventListener('error', onError);
    this._removeListeners = () => { image.removeEventListener('load', onLoad); image.removeEventListener('error', onError); };
    if (host && host.replaceChildren) host.replaceChildren(image);
    image.src = this.url;
    // У бесконечного MJPEG браузер может не прислать load до закрытия HTTP response.
    // naturalWidth появляется после первого декодированного кадра и честно доказывает LIVE.
    this.framePoll = this.env.setInterval(() => { if (!this.closed && image.naturalWidth > 0) onLoad(); }, 200);
    this.timer = this.env.setTimeout(() => {
      if (!this.closed && !liveSent && callbacks.onError) callbacks.onError(new Error('first_frame_timeout'));
    }, 15000);
  }

  captureFrame() { return captureImage(this.env, this.image); }

  close() {
    if (this.closed && !this.image) return;
    this.closed = true;
    if (this.timer != null) { this.env.clearTimeout(this.timer); this.timer = null; }
    if (this.framePoll != null) { this.env.clearInterval(this.framePoll); this.framePoll = null; }
    const image = this.image;
    this.image = null;
    try { if (this._removeListeners) this._removeListeners(); } catch (_) {}
    this._removeListeners = null;
    if (image) {
      try { image.src = SAFE_PLACEHOLDER; image.removeAttribute('src'); image.remove(); } catch (_) {}
    }
  }
}
