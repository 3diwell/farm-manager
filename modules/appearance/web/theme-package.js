// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { MODULE_VERSION } from './theme-schema.js';
import { safeFileName, validateTheme } from './theme-validator.js';

const SOURCE_FILES = [
  'AppearancePanel.js', 'dashboard-settings.js', 'dashboard-cards.js',
  'theme-runtime.js', 'theme-extensions.js', 'glass-layer.js', 'detail-style.js', 'printer-progress.js',
  'default-theme.js',
  'theme-schema.js',
  'theme-validator.js',
  'compatibility.js',
  'theme-package.js',
  'editor-fields.js', 'editor-simple.js', 'editor-simple-template.js', 'iphone-theme.js',
  'editor-storage.js', 'theme-profiles.js', 'ambient-fields.js', 'ambient-renderer.js',
  'editor-components.js',
  'editor-layout.js', 'editor-unified-template.js', 'editor-unified-style.js',
  'editor-soft-style.js', 'editor-presets.js',
  'theme-preview.js',
  'editor-sample.js',
  'editor-template.js'
];

let CRC_TABLE = null;
function crcTable() {
  if (CRC_TABLE) return CRC_TABLE;
  CRC_TABLE = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    CRC_TABLE[n] = c >>> 0;
  }
  return CRC_TABLE;
}
function crc32(bytes) {
  const table = crcTable();
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) c = table[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function u16(value) { return new Uint8Array([value & 255, (value >>> 8) & 255]); }
function u32(value) { return new Uint8Array([value & 255, (value >>> 8) & 255, (value >>> 16) & 255, (value >>> 24) & 255]); }
function join(chunks) {
  const total = chunks.reduce((sum, x) => sum + x.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  chunks.forEach((x) => { out.set(x, offset); offset += x.length; });
  return out;
}
function dosDateTime(date) {
  const year = Math.max(1980, date.getFullYear());
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}
function makeZip(files) {
  const encoder = new TextEncoder();
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;
  const stamp = dosDateTime(new Date());

  files.forEach((file) => {
    const name = encoder.encode(file.path);
    const data = typeof file.data === 'string' ? encoder.encode(file.data) : file.data;
    const crc = crc32(data);
    const local = join([
      u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(stamp.time), u16(stamp.day),
      u32(crc), u32(data.length), u32(data.length), u16(name.length), u16(0), name, data
    ]);
    localChunks.push(local);
    const central = join([
      u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(stamp.time), u16(stamp.day),
      u32(crc), u32(data.length), u32(data.length), u16(name.length), u16(0), u16(0),
      u16(0), u16(0), u32(0), u32(offset), name
    ]);
    centralChunks.push(central);
    offset += local.length;
  });
  const central = join(centralChunks);
  return join([
    ...localChunks,
    central,
    u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length),
    u32(central.length), u32(offset), u16(0)
  ]);
}
async function readOwnSource(fileName) {
  const url = new URL(`./${fileName}`, import.meta.url);
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Cannot read ${fileName}: HTTP ${response.status}`);
  return response.text();
}
function moduleManifest() {
  return JSON.stringify({
    id: 'appearance',
    ru: 'Оформление и темы',
    en: 'Appearance and themes',
    version: MODULE_VERSION,
    icon: 'module',
    entry: 'web/AppearancePanel.js'
  }, null, 2) + '\n';
}

export async function buildThemePackage(theme) {
  const checked = validateTheme(theme);
  if (!checked.ok) throw new Error(`Theme validation failed: ${checked.errors.join(', ')}`);
  const files = [{ path: 'appearance/module.json', data: moduleManifest() }];
  const sources = await Promise.all(SOURCE_FILES.map(async (name) => [name, await readOwnSource(name)]));
  sources.forEach(([name, text]) => files.push({ path: `appearance/web/${name}`, data: text }));
  files.push({
    path: 'appearance/web/theme-preset.js',
    data: `// Экспортировано редактором тем Farm Manager. Произвольный CSS/JS отсутствует.\nexport default ${JSON.stringify(checked.theme, null, 2)};\n`
  });
  return makeZip(files);
}

export async function exportThemePackage(theme) {
  const bytes = await buildThemePackage(theme);
  const fileName = `3DIWELL_Theme_${safeFileName(theme && theme.meta && theme.meta.name)}.zip`;
  const blob = new Blob([bytes], { type: 'application/zip' });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  return fileName;
}
