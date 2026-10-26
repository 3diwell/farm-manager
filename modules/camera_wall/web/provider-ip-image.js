// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
const SAFE_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';

function cacheBusted(url, stamp) {
  const parsed = new URL(url);
  parsed.searchParams.set('_cw', String(stamp));
  return parsed.href;
}

export class IpImageProvider {
  constructor(source, env = globalThis) {
    this.source = source;
    this.env = env;
    this.image = null;
    this.refreshTimer = null;
    this.timeoutTimer = null;
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
      if (this.closed) return;
      if (this.source.mode === 'mjpeg' && liveSent) return;
      liveSent = true;
      if (this.timeoutTimer != null) { this.env.clearTimeout(this.timeoutTimer); this.timeoutTimer = null; }
      if (this.source.mode === 'mjpeg' && this.framePoll != null) { this.env.clearInterval(this.framePoll); this.framePoll = null; }
      if (callbacks.onLive) callbacks.onLive({
        snapshot: this.source.mode === 'snapshot',
        capturedAt: Date.now(),
        displayUrl: image.currentSrc || image.src || this.source.url,
        freshness: this.source.mode === 'mjpeg' ? 'first-frame-only' : 'snapshot-at',
      });
    };
    const onError = () => { if (!this.closed && callbacks.onError) callbacks.onError(new Error('ip_image_failed')); };
    image.addEventListener('load', onLoad);
    image.addEventListener('error', onError);
    this._removeListeners = () => { image.removeEventListener('load', onLoad); image.removeEventListener('error', onError); };
    if (host && host.replaceChildren) host.replaceChildren(image);
    const load = () => {
      if (this.closed) return;
      image.src = this.source.mode === 'snapshot' ? cacheBusted(this.source.url, Date.now()) : this.source.url;
      if (this.timeoutTimer != null) this.env.clearTimeout(this.timeoutTimer);
      this.timeoutTimer = this.env.setTimeout(() => { if (!this.closed && callbacks.onError) callbacks.onError(new Error('ip_first_frame_timeout')); }, 15000);
    };
    load();
    // Snapshot is intentionally one-shot. PerformanceGovernor owns the bounded
    // refresh queue, so 25 snapshots never occupy 25 permanent live slots.
    if (this.source.mode !== 'snapshot') this.framePoll = this.env.setInterval(() => { if (!this.closed && image.naturalWidth > 0) onLoad(); }, 200);
  }

  captureFrame() {
    try {
      if (!this.image || !this.image.naturalWidth || !this.image.naturalHeight) return '';
      const canvas = this.env.document.createElement('canvas');
      const scale = Math.min(1, 1280 / this.image.naturalWidth);
      canvas.width = Math.max(1, Math.round(this.image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(this.image.naturalHeight * scale));
      canvas.getContext('2d').drawImage(this.image, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.78);
    } catch (_) { return ''; }
  }

  close() {
    if (this.closed && !this.image) return;
    this.closed = true;
    if (this.refreshTimer != null) { this.env.clearInterval(this.refreshTimer); this.refreshTimer = null; }
    if (this.timeoutTimer != null) { this.env.clearTimeout(this.timeoutTimer); this.timeoutTimer = null; }
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
