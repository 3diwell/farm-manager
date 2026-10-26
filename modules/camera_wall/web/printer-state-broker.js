// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const BROKER_RECONNECT_DELAYS = Object.freeze([3000, 5000, 10000, 30000]);

function websocketUrl(locationRef) {
  const secure = locationRef && locationRef.protocol === 'https:';
  return `${secure ? 'wss:' : 'ws:'}//${locationRef && locationRef.host || ''}/ws`;
}

export class PrinterStateBroker {
  constructor(options = {}) {
    this.env = options.env || globalThis;
    this.WebSocket = options.WebSocket || this.env.WebSocket;
    this.fetch = options.fetch || (this.env.fetch && this.env.fetch.bind(this.env));
    this.onSnapshot = options.onSnapshot || (() => {});
    this.onStatus = options.onStatus || (() => {});
    this.reconnectDelays = options.reconnectDelays || BROKER_RECONNECT_DELAYS;
    this.socket = null;
    this.timer = null;
    this.running = false;
    this.authStopped = false;
    this.reconnectAttempt = 0;
    // 16.10.2026 (R-150): сколько раз подряд переподключились после 4401 при действующем входе.
    this.authRetries = 0;
    this.generation = 0;
  }

  start() {
    if (this.running) return false;
    this.running = true;
    if (!this.authStopped) this.connect();
    return true;
  }

  connect() {
    if (!this.running || this.authStopped || this.socket || !this.WebSocket) return false;
    let socket;
    try { socket = new this.WebSocket(websocketUrl(this.env.location)); }
    catch (_) { this.scheduleReconnect(); return false; }
    const generation = ++this.generation;
    this.socket = socket;
    socket.onopen = () => {
      if (generation !== this.generation || socket !== this.socket) return;
      this.reconnectAttempt = 0;
      this.onStatus('connected');
    };
    socket.onmessage = (event) => {
      if (generation !== this.generation || socket !== this.socket) return;
      try {
        const value = JSON.parse(String(event && event.data || ''));
        if (value && typeof value === 'object' && !Array.isArray(value)) { this.authRetries = 0; this.onSnapshot(value); }
      } catch (_) {}
    };
    socket.onerror = () => {};
    socket.onclose = (event) => this.handleClose(socket, generation, event);
    return true;
  }

  async handleClose(socket, generation, event) {
    if (generation !== this.generation || socket !== this.socket) return;
    this.socket = null;
    this.clearSocketHandlers(socket);
    if (!this.running) return;
    // 16.10.2026 (R-150): сервер теперь перепроверяет вход у открытых сокетов. Когда защиту включают,
    // сокет, открытый ещё без входа, закрывается кодом 4401 — хотя в этом браузере вход уже есть
    // (cookie общая с окном программы). Тогда переподключаемся, не больше трёх раз подряд;
    // 4403 и «вход нужен» по-прежнему останавливают стену.
    if (event && event.code === 4401 && this.authRetries < 3 && await this.isAuthenticated()) {
      if (!this.running || generation !== this.generation) return;
      this.authRetries += 1;
      this.onStatus('disconnected');
      this.scheduleReconnect();
      return;
    }
    if (event && (event.code === 4401 || event.code === 4403)) {
      this.authStopped = true;
      this.onStatus('auth-denied');
      return;
    }
    if (event && event.code === 1006 && await this.isAuthDenied()) {
      if (!this.running || generation !== this.generation) return;
      this.authStopped = true;
      this.onStatus('auth-denied');
      return;
    }
    if (!this.running || generation !== this.generation) return;
    this.onStatus('disconnected');
    this.scheduleReconnect();
  }

  async isAuthenticated() {
    if (!this.fetch) return false;
    try {
      const response = await this.fetch('/api/auth/status', { credentials: 'same-origin', cache: 'no-store' });
      if (!response || !response.ok) return false;
      const value = await response.json();
      return !!(value && value.enabled && value.authenticated);
    } catch (_) { return false; }
  }

  async isAuthDenied() {
    if (!this.fetch) return false;
    try {
      const response = await this.fetch('/api/auth/status', { credentials: 'same-origin', cache: 'no-store' });
      if (!response || !response.ok) return false;
      const value = await response.json();
      return !!(value && value.enabled && !value.authenticated);
    } catch (_) { return false; }
  }

  scheduleReconnect() {
    if (!this.running || this.authStopped || this.timer != null) return false;
    const index = Math.min(this.reconnectAttempt, this.reconnectDelays.length - 1);
    const delay = Number(this.reconnectDelays[index]);
    this.reconnectAttempt += 1;
    const generation = this.generation;
    this.timer = this.env.setTimeout(() => {
      this.timer = null;
      if (this.running && !this.authStopped && generation === this.generation) this.connect();
    }, delay);
    return true;
  }

  clearSocketHandlers(socket) {
    if (!socket) return;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
  }

  stop() {
    if (!this.running && !this.socket && this.timer == null) return false;
    this.running = false;
    this.generation += 1;
    if (this.timer != null) { this.env.clearTimeout(this.timer); this.timer = null; }
    const socket = this.socket;
    this.socket = null;
    this.clearSocketHandlers(socket);
    if (socket) { try { socket.close(1000, 'camera-wall-owner-release'); } catch (_) {} }
    this.onStatus('stopped');
    return true;
  }

  activeCount() { return this.socket ? 1 : 0; }
  reconnectTimerCount() { return this.timer == null ? 0 : 1; }
}
