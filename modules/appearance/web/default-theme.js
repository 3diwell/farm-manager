// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { addExtensionDefaults } from "./theme-extensions.js";
import { DASHBOARD_DEFAULTS } from './dashboard-settings.js';
export const THEME_SCHEMA_VERSION = 14;

const DEFAULT_THEME = {
  dashboard: { ...DASHBOARD_DEFAULTS },
  schemaVersion: THEME_SCHEMA_VERSION,
  meta: {
    name: 'Стандартное оформление',
    nameEn: 'Standard appearance',
    author: '3DIWELL',
    description: 'Базовая палитра оформления Farm Manager.',
    descriptionEn: 'Base appearance palette for Farm Manager.'
  },
  dark: {
    accent: '#4da6ff',
    surfaceDeep: '#0e0e10',
    surfaceBase: '#18181b',
    surfaceRaised: '#202023',
    surfaceCard: '#27272a',
    surfaceControl: '#303030',
    borderSoft: '#2e2e2e',
    border: '#3f3f46',
    borderStrong: '#52525b',
    textPrimary: '#e5e7eb',
    textSecondary: '#d1d5db',
    textMuted: '#9ca3af',
    textSubtle: '#6b7280',
    success: '#22c55e',
    warning: '#fbbf24',
    danger: '#f87171',
    headerSurface: '#26282a',
    headerAction: '#171918',
    headerBorder: '#5b5b5b'
  },
  light: {
    accent: '#4da6ff',
    surfaceDeep: '#e7e9ec',
    surfaceBase: '#f3f4f6',
    surfaceRaised: '#fafbfc',
    surfaceCard: '#ffffff',
    surfaceControl: '#ffffff',
    borderSoft: '#e9ebef',
    border: '#d4d8de',
    borderStrong: '#b4bac4',
    textPrimary: '#1f2329',
    textSecondary: '#3a4048',
    textMuted: '#697079',
    textSubtle: '#9aa1ac',
    success: '#15a34a',
    warning: '#b45309',
    danger: '#e11d2e',
    headerSurface: '#26282a',
    headerAction: '#171918',
    headerBorder: '#5b5b5b'
  },
  typography: {
    font: 'system',
    textScale: 1.28,
    customFontName: '',
    customFontFormat: '',
    customFontDataUrl: ''
  },
  shape: {
    radiusScale: 1,
    borderWidth: 1,
    shadowIntensity: 1,
    surfaceOpacity: 1
  },
  interface: {
    density: 'normal',
    reduceMotion: false,
    performanceMode: 'balanced',
    highContrast: false
  },
  effects: {
    secondaryAccent: '#8b5cf6',
    glowStrength: 0.45,
    haloStrength: 0.28,
    panelMaterial: 'solid',
    edgeLighting: 'active',
    panelTopHighlight: true,
    hoverLift: false,
    shimmerProgress: false,
    backgroundPattern: 'none',
    patternOpacity: 0.04,
    ambientStrength: 0.12,
    tableStyle: 'clean',
    statusStyle: 'text-dot',
    cornerStyle: 'rounded',
    inactiveDesaturation: 0,
    edgeDirection: 'full',
    panelDepth: 0.35,
    progressStyle: 'flat',
    controlStyle: 'clean',
    focusGlowStrength: 0.35,
    matteStrength: 0.28,
    glossStrength: 0.18,
    panelAiriness: 0.22,
    animatedBackground: 'off',
    backgroundAnimationStyle: 'flow',
    backgroundMixedStyle: 'flow',
    backgroundFlowUseThemeColors: true,
    backgroundFlowPrimary: '#4da6ff',
    backgroundFlowSecondary: '#8b5cf6',
    backgroundFlowSpeed: 0.32,
    backgroundFlowOpacity: 0.16,
    backgroundFlowBlur: 0.58,
    backgroundFlowScale: 0.52,
    backgroundStreamCount: 12,
    backgroundFlowMix: 1,
    backgroundStreamsMix: 1,
    hoverGlintPrinters: true,
    hoverGlintProjects: true,
    hoverGlintIntensity: 1,
    hoverGlintDuration: 6.2,
    microAccentIntensity: 0.22
  },
  paletteEffects: { separate: false, darkBrightness: .16, lightBrightness: .16, darkOpacity: 1, lightOpacity: 1, darkGlow: .45, lightGlow: .45, darkHalo: .28, lightHalo: .28 },
  background: {
    mode: 'default',
    imageDataUrl: '',
    overlay: '#000000',
    overlayOpacity: 0.18,
    blurPx: 0
  }
};

addExtensionDefaults(DEFAULT_THEME);
export default DEFAULT_THEME;
