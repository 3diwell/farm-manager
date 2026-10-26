// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { CoreMjpegProvider } from './provider-core-mjpeg.js';
import { CoreFmp4Provider } from './provider-core-fmp4.js';
import { CoreWebRtcProvider } from './provider-core-webrtc.js';
import { IpImageProvider } from './provider-ip-image.js';
import { resolveCameraCapability } from './source-discovery.js';

export function isBambuTlsJpeg(source) {
  const serial = String((source && source.serial) || '').toUpperCase();
  return serial.startsWith('01P') || serial.startsWith('01S');
}

// Alpha 2.871: камеры Bambu перестали быть дорогими ДЛЯ СЕРВЕРА. Прежде каждая из них
// поднимала ffmpeg с полным перекодированием H.264 -> MJPEG (измерено ~0,4 ядра на камеру),
// и именно поэтому их разрешалось показывать только две. Теперь поток идёт как есть, сервер
// его лишь перекладывает, а декодирует браузер — цена для сервера сравнялась с остальными.
// Класс 'expensive-server' НЕ удалён: он остаётся для запасного пути с перекодированием и
// пригодится будущим источникам, которым сервер снова понадобится.
export function sourceCostClass(source) {
  return 'medium';
}

export function providerCandidates(source, env = globalThis) {
  if (source.sourceKind === 'ip') {
    return [{ key: source.mode, label: source.mode === 'snapshot' ? 'Snapshot' : 'MJPEG', create: () => new IpImageProvider(source, env) }];
  }
  const pid = encodeURIComponent(String(source.id));
  // 16.10.2026 (R-062, R-146): Creality на заводской прошивке — тот же путь, что у Klipper: WebRTC через
  // сигнализацию ядра (видео идёт по локальной сети, без STUN-сервера в интернете), затем MJPEG.
  if (source.type === 'klipper' || source.type === 'creality') {
    return [
      { key: 'webrtc-lan', label: 'WebRTC · LAN', create: () => new CoreWebRtcProvider(`/api/printer/${pid}/webrtc`, env) },
      { key: 'mjpeg-fallback', label: 'MJPEG fallback', fallback: true, create: () => new CoreMjpegProvider(`/api/printer/${pid}/camera`, env) },
    ];
  }
  // 12.10.2026: FlashForge — поток MJPEG стримера принтера через ядро (одно соединение на камеру).
  if (source.type === 'flashforge') {
    return [{ key: 'core-mjpeg', label: 'Core MJPEG', create: () => new CoreMjpegProvider(`/api/printer/${pid}/camera`, env) }];
  }
  // P1/P1S отдают не H.264, а собственный поток JPEG (~0,5 кадра в секунду) — перекладывать
  // там нечего, для них прежний путь и остаётся единственным.
  if (isBambuTlsJpeg(source)) {
    return [{ key: 'core-mjpeg', label: 'Core JPEG/MJPEG', create: () => new CoreMjpegProvider(`/api/printer/${pid}/camera`, env) }];
  }
  // X1/H2: сперва без перекодирования, и только если ядро старое или поток не пошёл — прежний путь.
  return [
    { key: 'core-fmp4', label: 'Core H.264 · no transcoding', create: () => new CoreFmp4Provider(`/api/printer/${pid}/camera.mp4`, env) },
    { key: 'core-mjpeg', label: 'Core MJPEG · FFmpeg', fallback: true, create: () => new CoreMjpegProvider(`/api/printer/${pid}/camera`, env) },
  ];
}

export function printerToSource(printer) {
  return {
    id: String(printer.id),
    sourceKind: 'printer',
    name: String(printer.name || printer.id),
    type: String(printer.type || '').toLowerCase(),
    model: String(printer.model || ''),
    modelKey: String(printer.model_key || ''),
    serial: String(printer.serial || ''),
    orderIdx: Number.isFinite(Number(printer.order_idx)) ? Number(printer.order_idx) : Number.MAX_SAFE_INTEGER,
    capability: resolveCameraCapability(printer),
    fit: 'contain',
  };
}

export function isSupportedPrinter(source) {
  if (!source || source.sourceKind !== 'printer') return false;
  if (source.capability) return source.capability === 'confirmed';
  return resolveCameraCapability({ type: source.type, model: source.model, model_key: source.modelKey }) === 'confirmed';
}
