// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const MODULE_ID = 'appearance';
export const MODULE_VERSION = '0.17.7';
export const SAVED_THEMES_KEY = 'fm_appearance_collection_v1';
export const EDITOR_STATE_KEY = 'fm_appearance_editor_v1';
export const DRAFT_STORAGE_KEY = 'fm_appearance_draft_v7';
export const APPLIED_STORAGE_KEY = 'fm_appearance_applied_v7';
export const LEGACY_DRAFT_STORAGE_KEY = 'fm_appearance_draft_v5';
export const LEGACY_APPLIED_STORAGE_KEY = 'fm_appearance_applied_v5';
export const STYLE_ID = 'fm-appearance-theme-style';
export const AMBIENT_LAYER_ID = 'fm-appearance-ambient-layer';
export const HOVER_GLINT_CLASS = 'fm-appearance-hover-glint';
export const ROOT_ACTIVE_ATTR = 'data-fm-appearance-active';
export const ROOT_PREVIEW_ATTR = 'data-fm-appearance-preview';

export const FONT_OPTIONS = [
  { id: 'system', ru: 'Системный', en: 'System', css: '-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif' },
  { id: 'segoe', ru: 'Segoe UI', en: 'Segoe UI', css: '"Segoe UI",Arial,sans-serif' },
  { id: 'calibri', ru: 'Calibri', en: 'Calibri', css: 'Calibri,"Segoe UI",Arial,sans-serif' },
  { id: 'arial', ru: 'Arial', en: 'Arial', css: 'Arial,"Segoe UI",sans-serif' },
  { id: 'verdana', ru: 'Verdana', en: 'Verdana', css: 'Verdana,Geneva,sans-serif' },
  { id: 'custom', ru: 'Загруженный шрифт', en: 'Uploaded font', css: '"FMThemeCustom","Segoe UI",Arial,sans-serif' }
];

export const PALETTE_FIELDS = [
  ['accent', 'Основной цвет', 'Accent'],
  ['surfaceDeep', 'Фон приложения', 'App background'],
  ['surfaceBase', 'Основные панели', 'Main panels'],
  ['surfaceRaised', 'Приподнятые панели', 'Raised panels'],
  ['surfaceCard', 'Карточки', 'Cards'],
  ['surfaceControl', 'Поля и элементы', 'Controls'],
  ['borderSoft', 'Мягкие границы', 'Soft borders'],
  ['border', 'Основные границы', 'Borders'],
  ['borderStrong', 'Усиленные границы', 'Strong borders'],
  ['textPrimary', 'Основной текст', 'Primary text'],
  ['textSecondary', 'Вторичный текст', 'Secondary text'],
  ['textMuted', 'Приглушённый текст', 'Muted text'],
  ['textSubtle', 'Служебный текст', 'Subtle text'],
  ['success', 'Успех', 'Success'],
  ['warning', 'Предупреждение', 'Warning'],
  ['danger', 'Ошибка', 'Danger'],
  ['headerSurface', 'Фон шапки', 'Header surface'],
  ['headerAction', 'Кнопки шапки', 'Header controls'],
  ['headerBorder', 'Границы шапки', 'Header borders']
];

export const OLDER_APPLIED_STORAGE_KEY='fm_appearance_applied_v4';
export const OLDER_DRAFT_STORAGE_KEY='fm_appearance_draft_v4';

export const APPLIED_STORAGE_KEYS=[APPLIED_STORAGE_KEY,'fm_appearance_applied_v6',LEGACY_APPLIED_STORAGE_KEY,OLDER_APPLIED_STORAGE_KEY,'fm_appearance_applied_v3'];
export const DRAFT_STORAGE_KEYS=[DRAFT_STORAGE_KEY,'fm_appearance_draft_v6',LEGACY_DRAFT_STORAGE_KEY,OLDER_DRAFT_STORAGE_KEY,'fm_appearance_draft_v3'];
export function firstStored(keys){for(const key of keys){const raw=localStorage.getItem(key);if(raw!==null)return raw;}return null;}
