// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
function captureVideo(env, video) {
  try {
    if (!video || !video.videoWidth || !video.videoHeight) return '';
    const canvas = env.document.createElement('canvas');
    const scale = Math.min(1, 1280 / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.78);
  } catch (_) { return ''; }
}

export const WEBRTC_DISCONNECT_GRACE_MS = 5000;

export class CoreWebRtcProvider {
  constructor(signalingUrl, env = globalThis) {
    this.url = signalingUrl;
    this.env = env;
    this.pc = null;
    this.video = null;
    this.abort = null;
    this.closed = true;
    this.gatherTimer = null;
    this.firstFrameTimer = null;
    this.disconnectTimer = null;
    this._finishGather = null;
  }

  async open(host, callbacks = {}) {
    this.close();
    this.closed = false;
    const video = this.env.document.createElement('video');
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.controls = false;
    this.video = video;
    if (host && host.replaceChildren) host.replaceChildren(video);
    // 16.10.2026 (R-062): только кандидаты локальной сети, как у Creality Print 7.3 (iceServers: []): камера в той
    // же сети, а обращения к STUN-серверу Google в интернете больше нет.
    const pc = new this.env.RTCPeerConnection({ iceServers: [] });
    this.pc = pc;
    this.abort = new this.env.AbortController();
    let liveSent = false;
    const signalLive = () => {
      if (this.closed || liveSent) return;
      liveSent = true;
      if (this.firstFrameTimer != null) { this.env.clearTimeout(this.firstFrameTimer); this.firstFrameTimer = null; }
      if (callbacks.onLive) callbacks.onLive();
    };
    const signalError = (message) => { if (!this.closed && callbacks.onError) callbacks.onError(new Error(message)); };
    video.addEventListener('playing', signalLive);
    video.addEventListener('loadeddata', signalLive);
    this._removeVideoListeners = () => { video.removeEventListener('playing', signalLive); video.removeEventListener('loadeddata', signalLive); };
    pc.ontrack = (event) => {
      if (this.closed) return;
      const stream = event.streams && event.streams[0] ? event.streams[0] : new this.env.MediaStream([event.track]);
      video.srcObject = stream;
      const play = video.play();
      if (play && play.catch) play.catch(() => {});
    };
    pc.onconnectionstatechange = () => this.handleConnectionState(pc, signalError);
    try {
      // sendrecv — так предлагают Creality Print 7.3, родная страница принтера и go2rtc (R-062).
      pc.addTransceiver('video', { direction: 'sendrecv' });
      await pc.setLocalDescription(await pc.createOffer());
      if (this.closed || pc !== this.pc) return;
      await new Promise((resolve) => {
        let finished = false;
        const finishGather = () => {
          if (finished) return;
          finished = true;
          if (this.gatherTimer != null) {
            this.env.clearTimeout(this.gatherTimer);
            this.gatherTimer = null;
          }
          pc.removeEventListener('icegatheringstatechange', done);
          if (this._finishGather === finishGather) this._finishGather = null;
          resolve();
        };
        const done = () => {
          if (pc.iceGatheringState !== 'complete') return;
          finishGather();
        };
        this._finishGather = finishGather;
        if (pc.iceGatheringState === 'complete') { finishGather(); return; }
        pc.addEventListener('icegatheringstatechange', done);
        this.gatherTimer = this.env.setTimeout(finishGather, 2000);
      });
      if (this.closed || pc !== this.pc) return;
      const response = await this.env.fetch(this.url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'offer', sdp: pc.localDescription.sdp }),
        signal: this.abort.signal,
      });
      if (!response.ok) throw new Error('signaling_http_' + response.status);
      const answer = await response.json();
      if (!answer || !answer.sdp) throw new Error('signaling_answer_missing');
      if (this.closed || pc !== this.pc) return;
      await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
      if (this.closed || pc !== this.pc) return;
      if (!liveSent) this.firstFrameTimer = this.env.setTimeout(() => signalError('webrtc_first_frame_timeout'), 15000);
    } catch (error) {
      if (!this.closed && error && error.name !== 'AbortError') signalError(error.message || 'webrtc_failed');
    }
  }

  captureFrame() { return captureVideo(this.env, this.video); }

  clearDisconnectTimer() {
    if (this.disconnectTimer != null) {
      this.env.clearTimeout(this.disconnectTimer);
      this.disconnectTimer = null;
    }
  }

  handleConnectionState(pc, signalError) {
    if (pc !== this.pc || this.closed) return;
    const state = pc.connectionState;
    if (state === 'failed') {
      this.clearDisconnectTimer();
      signalError('webrtc_connection_failed');
    } else if (state === 'disconnected' && this.disconnectTimer == null) {
      this.disconnectTimer = this.env.setTimeout(() => {
        this.disconnectTimer = null;
        if (pc === this.pc && !this.closed && pc.connectionState === 'disconnected') signalError('webrtc_disconnected_timeout');
      }, WEBRTC_DISCONNECT_GRACE_MS);
    } else if (state === 'connected' || state === 'completed') {
      this.clearDisconnectTimer();
    }
  }

  close() {
    if (this.closed && !this.pc && !this.video && this.gatherTimer == null && this.disconnectTimer == null && this._finishGather == null) return;
    this.closed = true;
    if (this._finishGather) this._finishGather();
    else if (this.gatherTimer != null) { this.env.clearTimeout(this.gatherTimer); this.gatherTimer = null; }
    if (this.firstFrameTimer != null) { this.env.clearTimeout(this.firstFrameTimer); this.firstFrameTimer = null; }
    this.clearDisconnectTimer();
    try { if (this.abort) this.abort.abort(); } catch (_) {}
    this.abort = null;
    const pc = this.pc;
    this.pc = null;
    if (pc) {
      try { pc.ontrack = null; pc.onconnectionstatechange = null; pc.close(); } catch (_) {}
    }
    const video = this.video;
    this.video = null;
    try { if (this._removeVideoListeners) this._removeVideoListeners(); } catch (_) {}
    this._removeVideoListeners = null;
    if (video) {
      try {
        const stream = video.srcObject;
        if (stream && stream.getTracks) stream.getTracks().forEach((track) => { try { track.stop(); } catch (_) {} });
        video.pause();
        video.srcObject = null;
        video.removeAttribute('src');
        video.load();
        video.remove();
      } catch (_) {}
    }
  }
}
