// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { providerCandidates, sourceCostClass } from './camera-providers.js';

export const RETRY_DELAYS = Object.freeze([2000, 5000, 15000, 30000, 60000, 120000, 300000]);
// Alpha 2.875: пока принтер НА СВЯЗИ, пауза между попытками не уходит выше 30 секунд.
// Прежняя лестница доходила до пяти минут, и камера, сорвавшаяся в начале, могла ждать
// четверть часа — ровно это владелец и наблюдал на K2 24.08.2026. Длинные паузы остаются
// для принтеров не на связи: молотить в пустоту незачем.
export const RETRY_DELAY_CAP_ONLINE_MS = 30000;

function nowIso(now) { try { return new Date(now).toISOString(); } catch (_) { return ''; } }

export class CameraSession {
  constructor(source, options = {}) {
    this.source = source;
    this.env = options.env || globalThis;
    this.makeCandidates = options.providerCandidates || providerCandidates;
    this.onChange = options.onChange || (() => {});
    this.onReconnectStorm = options.onReconnectStorm || (() => {});
    this.onFailure = options.onFailure || (() => {});
    this.onRetryReady = options.onRetryReady || (() => {});
    this.host = null;
    this.provider = null;
    this.candidates = [];
    this.candidateIndex = 0;
    this.retryAttempt = 0;
    this.retryTimer = null;
    this.stableTimer = null;
    this.generation = 0;
    this.desiredLive = false;
    this.disposed = false;
    this.visibilitySuspended = false;
    this.resumeAfterVisibility = false;
    this.visibilityResumePending = false;
    this.visibilityResumeRetryAvailable = false;
    // The registry remains reusable in isolation; CameraWallPanel immediately
    // applies fail-closed WS availability before its first Governor reconcile.
    this.printerAvailability = 'online';
    this.view = {
      id: source.id,
      state: 'idle',
      transport: '',
      fallback: false,
      lastFrame: '',
      frameAt: '',
      snapshotAt: '',
      freshness: '',
      error: '',
      reconnectAt: 0,
      retryReady: false,
      failureCount: 0,
      suspension: '',
      costClass: sourceCostClass(source),
      printerAvailability: this.printerAvailability,
    };
  }

  get isSnapshot() { return this.source.sourceKind === 'ip' && this.source.mode === 'snapshot'; }
  setHost(host) { this.host = host || null; }

  emit(patch = {}) {
    Object.assign(this.view, patch);
    this.onChange(this.snapshot());
  }

  snapshot() {
    return {
      ...this.view,
      activeTransport: !!this.provider,
      desiredLive: this.desiredLive,
      snapshotRequest: this.isSnapshot && !!this.provider,
    };
  }

  start() {
    if (this.isSnapshot) return this.refreshSnapshot();
    if (this.disposed) return false;
    if (this.source.sourceKind === 'printer' && this.printerAvailability !== 'online') return false;
    this.desiredLive = true;
    this.cancelRetryTimer();
    this.emit({ retryReady: false, reconnectAt: 0 });
    if (!this.host) { this.desiredLive = false; this.emit({ state: 'idle', error: '' }); return false; }
    if (this.provider || this.view.state === 'connecting') return true;
    this.candidates = this.makeCandidates(this.source, this.env);
    this.candidateIndex = 0;
    const visibilityReconnect = this.visibilityResumePending;
    this.visibilityResumePending = false;
    this.openCandidate(visibilityReconnect || this.view.failureCount > 0);
    return true;
  }

  openCandidate(isReconnect) {
    if (!this.desiredLive || this.disposed || !this.host) return;
    const candidate = this.candidates[this.candidateIndex];
    if (!candidate) { this.scheduleRetry(new Error('no_camera_provider')); return; }
    const generation = ++this.generation;
    this.closeTransport(false);
    let provider;
    try { provider = candidate.create(); } catch (error) { this.handleError(error, generation, null); return; }
    this.provider = provider;
    this.emit({
      state: isReconnect ? 'reconnecting' : 'connecting',
      transport: candidate.label,
      fallback: !!candidate.fallback,
      freshness: '',
      error: '',
      retryReady: false,
      reconnectAt: 0,
      suspension: this.visibilityResumeRetryAvailable ? 'visibility' : '',
    });
    const callbacks = {
      onLive: (meta = {}) => {
        if (generation !== this.generation || provider !== this.provider || this.disposed) return;
        this.visibilityResumeRetryAvailable = false;
        this.emit({ state: 'live', error: '', freshness: meta.freshness || '', retryReady: false, reconnectAt: 0, failureCount: 0, suspension: '' });
        if (this.stableTimer != null) this.env.clearTimeout(this.stableTimer);
        this.stableTimer = this.env.setTimeout(() => {
          if (provider !== this.provider || this.view.state !== 'live') return;
          this.retryAttempt = 0;
          this.emit({ failureCount: 0 });
        }, 20000);
      },
      onError: (error) => this.handleError(error, generation, provider),
    };
    try {
      const result = provider.open(this.host, callbacks);
      if (result && result.catch) result.catch((error) => this.handleError(error, generation, provider));
    } catch (error) { this.handleError(error, generation, provider); }
  }

  handleError(error, generation, provider = this.provider) {
    if (generation !== this.generation || provider !== this.provider || !this.desiredLive || this.disposed) return;
    if (this.stableTimer) {
      this.env.clearTimeout(this.stableTimer);
      this.stableTimer = null;
    }
    const message = String((error && error.message) || 'camera_failed').slice(0, 160);
    const frame = this.captureFrame();
    this.closeTransport(true);
    if (frame) this.emit({ lastFrame: frame, frameAt: nowIso(Date.now()) });
    if (message === 'first_frame_timeout' && this.visibilityResumeRetryAvailable && this.view.costClass === 'expensive-server') {
      this.visibilityResumeRetryAvailable = false;
      this.candidateIndex = 0;
      this.emit({ state: 'reconnecting', error: message, retryReady: false, reconnectAt: 0, suspension: 'visibility' });
      this.retryTimer = this.env.setTimeout(() => {
        this.retryTimer = null;
        if (this.desiredLive && !this.disposed) this.openCandidate(true);
      }, 1500);
      return;
    }
    if (this.candidateIndex + 1 < this.candidates.length) {
      this.candidateIndex += 1;
      this.emit({ state: 'reconnecting', error: message, fallback: true, retryReady: false });
      this.retryTimer = this.env.setTimeout(() => {
        this.retryTimer = null;
        if (this.desiredLive && !this.disposed) this.openCandidate(true);
      }, 0);
      return;
    }
    this.onFailure(this.source.id, message);
    this.scheduleRetry(error);
  }

  scheduleRetry(error) {
    if (this.disposed) return;
    this.desiredLive = false;
    const message = String((error && error.message) || 'camera_failed').slice(0, 160);
    if (this.source.sourceKind === 'printer' && this.printerAvailability !== 'online') {
      this.setPrinterAvailability(this.printerAvailability);
      return;
    }
    const storm = this.retryAttempt >= RETRY_DELAYS.length;
    let delay = RETRY_DELAYS[Math.min(this.retryAttempt, RETRY_DELAYS.length - 1)];
    if (this.source.sourceKind !== 'printer' || this.printerAvailability === 'online') {
      delay = Math.min(delay, RETRY_DELAY_CAP_ONLINE_MS);
    }
    this.retryAttempt += 1;
    if (storm) this.onReconnectStorm(this.source.id);
    // Waiting backoff owns no provider and therefore reserves no Governor slot.
    // A camera failure while printer telemetry remains fresh is distinct from
    // printer OFFLINE and is never represented as pseudo-LIVE.
    this.emit({
      state: 'camera-unavailable',
      error: message,
      retryReady: false,
      reconnectAt: Date.now() + delay,
      failureCount: this.retryAttempt,
      suspension: '',
    });
    this.cancelRetryTimer();
    this.retryTimer = this.env.setTimeout(() => {
      this.retryTimer = null;
      if (this.disposed) return;
      if (this.source.sourceKind === 'printer' && this.printerAvailability !== 'online') return;
      this.emit({ state: 'camera-unavailable', retryReady: true, reconnectAt: 0 });
      this.onRetryReady(this.source.id);
    }, delay);
  }

  refreshSnapshot() {
    if (!this.isSnapshot || this.disposed || !this.host || this.provider) return false;
    if (this.view.reconnectAt && !this.view.retryReady) return false;
    this.cancelRetryTimer();
    this.candidates = this.makeCandidates(this.source, this.env);
    const candidate = this.candidates[0];
    if (!candidate) return false;
    const generation = ++this.generation;
    let provider;
    try { provider = candidate.create(); } catch (error) { this.onFailure(this.source.id, 'snapshot_provider_failed'); this.scheduleRetry(error); return false; }
    this.provider = provider;
    this.emit({ state: 'connecting', transport: candidate.label, fallback: false, freshness: '', error: '', retryReady: false, reconnectAt: 0 });
    const callbacks = {
      onLive: (meta = {}) => {
        if (generation !== this.generation || provider !== this.provider || this.disposed) return;
        const frame = this.captureFrame() || meta.displayUrl || this.source.url || '';
        const capturedAt = meta.capturedAt || Date.now();
        this.closeTransport(true);
        this.retryAttempt = 0;
        this.emit({
          state: frame ? 'frozen' : 'paused-performance',
          lastFrame: frame,
          frameAt: frame ? nowIso(capturedAt) : this.view.frameAt,
          snapshotAt: nowIso(capturedAt),
          freshness: 'snapshot-at',
          error: '',
          retryReady: false,
          failureCount: 0,
        });
      },
      onError: (error) => {
        if (generation !== this.generation || provider !== this.provider || this.disposed) return;
        this.closeTransport(true);
        this.onFailure(this.source.id, String((error && error.message) || 'snapshot_failed'));
        this.scheduleRetry(error);
      },
    };
    try {
      const result = provider.open(this.host, callbacks);
      if (result && result.catch) result.catch(callbacks.onError);
    } catch (error) { callbacks.onError(error); }
    return true;
  }

  manualReconnect() {
    if (this.disposed) return false;
    if (this.source.sourceKind === 'printer' && this.printerAvailability !== 'online') return false;
    this.desiredLive = false;
    this.cancelTimers();
    this.closeTransport(true);
    this.retryAttempt = 0;
    this.clearVisibilityResume();
    this.emit({ state: 'idle', error: '', retryReady: true, reconnectAt: 0, failureCount: 0, fallback: false, suspension: '' });
    return true;
  }

  captureFrame() {
    try { return this.provider && this.provider.captureFrame ? (this.provider.captureFrame() || '') : ''; } catch (_) { return ''; }
  }

  pausePerformance() {
    if (this.disposed) return;
    this.desiredLive = false;
    const frame = this.captureFrame();
    this.cancelTimers();
    this.closeTransport(false);
    this.clearVisibilityResume();
    const lastFrame = frame || this.view.lastFrame || '';
    this.emit({
      state: lastFrame ? 'frozen' : 'paused-performance',
      lastFrame,
      frameAt: frame ? nowIso(Date.now()) : this.view.frameAt,
      error: '',
      retryReady: false,
      reconnectAt: 0,
      suspension: '',
    });
  }

  suspendVisibility() {
    if (this.disposed || this.visibilitySuspended) return;
    this.visibilitySuspended = true;
    const activeState = this.view.state === 'connecting' || this.view.state === 'live' ||
      (this.view.state === 'reconnecting' && !this.view.reconnectAt);
    this.resumeAfterVisibility = !!this.provider || this.desiredLive || activeState;
    if (!this.resumeAfterVisibility) return;
    this.desiredLive = false;
    const frame = this.captureFrame();
    this.cancelTimers();
    this.closeTransport(true);
    const lastFrame = frame || this.view.lastFrame || '';
    this.emit({
      state: lastFrame ? 'frozen' : 'paused-performance',
      lastFrame,
      frameAt: frame ? nowIso(Date.now()) : this.view.frameAt,
      error: '',
      retryReady: false,
      reconnectAt: 0,
      suspension: 'visibility',
    });
  }

  prepareVisibilityResume() {
    if (!this.visibilitySuspended) return false;
    this.visibilitySuspended = false;
    if (!this.resumeAfterVisibility) return false;
    this.resumeAfterVisibility = false;
    this.visibilityResumePending = true;
    this.visibilityResumeRetryAvailable = this.view.costClass === 'expensive-server';
    this.cancelRetryTimer();
    this.emit({ error: '', retryReady: true, reconnectAt: 0, suspension: 'visibility' });
    return true;
  }

  clearVisibilityResume() {
    this.visibilitySuspended = false;
    this.resumeAfterVisibility = false;
    this.visibilityResumePending = false;
    this.visibilityResumeRetryAvailable = false;
  }

  setPrinterAvailability(value, message = '') {
    if (this.source.sourceKind !== 'printer' || this.disposed) return false;
    const next = value === 'online' || value === 'offline' ? value : 'unknown';
    const previous = this.printerAvailability;
    if (previous === next) {
      if (next !== 'online' && (this.provider || this.retryTimer != null || this.desiredLive)) {
        this.desiredLive = false;
        this.cancelTimers();
        this.closeTransport(true);
      }
      return false;
    }
    this.printerAvailability = next;
    if (next === 'online') {
      this.retryAttempt = 0;
      this.cancelTimers();
      this.emit({ state: 'idle', error: '', retryReady: true, reconnectAt: 0, failureCount: 0, printerAvailability: next, suspension: '' });
      return true;
    }
    this.desiredLive = false;
    const frame = this.captureFrame();
    this.cancelTimers();
    this.closeTransport(true);
    this.clearVisibilityResume();
    this.emit({
      state: next === 'offline' ? 'printer-offline' : 'printer-unknown',
      lastFrame: frame || this.view.lastFrame || '',
      frameAt: frame ? nowIso(Date.now()) : this.view.frameAt,
      error: String(message || ''),
      retryReady: false,
      reconnectAt: 0,
      printerAvailability: next,
      suspension: '',
    });
    return true;
  }

  markOffline(message) { return this.setPrinterAvailability('offline', message); }

  cancelRetryTimer() {
    if (this.retryTimer != null) { this.env.clearTimeout(this.retryTimer); this.retryTimer = null; }
  }

  cancelTimers() {
    this.cancelRetryTimer();
    if (this.stableTimer != null) { this.env.clearTimeout(this.stableTimer); this.stableTimer = null; }
  }

  closeTransport(invalidate = true) {
    if (invalidate) this.generation += 1;
    const provider = this.provider;
    this.provider = null;
    if (provider) { try { provider.close(); } catch (_) {} }
    if (this.host && this.host.replaceChildren) { try { this.host.replaceChildren(); } catch (_) {} }
  }

  close() {
    this.desiredLive = false;
    this.cancelTimers();
    this.closeTransport(true);
    this.clearVisibilityResume();
    this.emit({
      state: 'idle', transport: '', fallback: false, lastFrame: '', frameAt: '', snapshotAt: '',
      freshness: '', error: '', reconnectAt: 0, retryReady: false, failureCount: 0, suspension: '',
    });
  }

  dispose() { if (this.disposed) return; this.close(); this.disposed = true; this.host = null; }
}

export class SessionRegistry {
  constructor(options = {}) {
    this.env = options.env || globalThis;
    this.providerCandidates = options.providerCandidates || providerCandidates;
    this.onChange = options.onChange || (() => {});
    this.onReconnectStorm = options.onReconnectStorm || (() => {});
    this.onFailure = options.onFailure || (() => {});
    this.onRetryReady = options.onRetryReady || (() => {});
    this.sessions = new Map();
  }

  add(source) {
    if (this.sessions.has(source.id)) return this.sessions.get(source.id);
    const session = new CameraSession(source, {
      env: this.env,
      providerCandidates: this.providerCandidates,
      onReconnectStorm: this.onReconnectStorm,
      onFailure: this.onFailure,
      onRetryReady: this.onRetryReady,
      onChange: () => this.onChange(this.snapshot()),
    });
    this.sessions.set(source.id, session);
    this.onChange(this.snapshot());
    return session;
  }

  setHost(id, host) { const session = this.sessions.get(id); if (session) session.setHost(host); }
  start(id) { const session = this.sessions.get(id); return session ? session.start() : false; }
  refreshSnapshot(id) { const session = this.sessions.get(id); return session ? session.refreshSnapshot() : false; }
  manualReconnect(id) { const session = this.sessions.get(id); return session ? session.manualReconnect() : false; }
  pause(id) { const session = this.sessions.get(id); if (session) session.pausePerformance(); }
  pauseAll() { for (const session of this.sessions.values()) session.pausePerformance(); }
  suspendVisibility() { for (const session of this.sessions.values()) session.suspendVisibility(); }
  prepareVisibilityResume() { for (const session of this.sessions.values()) session.prepareVisibilityResume(); }
  setPrinterAvailability(id, value, message = '') { const session = this.sessions.get(id); return session ? session.setPrinterAvailability(value, message) : false; }

  remove(id) {
    const session = this.sessions.get(id);
    if (!session) return;
    session.dispose();
    this.sessions.delete(id);
    this.onChange(this.snapshot());
  }

  closeAll() {
    for (const session of this.sessions.values()) session.close();
    this.onChange(this.snapshot());
  }

  activeCount() { let count = 0; for (const session of this.sessions.values()) if (session.provider) count += 1; return count; }
  snapshotRefreshActiveCount() { let count = 0; for (const session of this.sessions.values()) if (session.isSnapshot && session.provider) count += 1; return count; }
  snapshot() { const out = {}; for (const [id, session] of this.sessions) out[id] = session.snapshot(); return out; }
}
