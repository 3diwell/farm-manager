#!/usr/bin/env node
// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
/*
============================================================================
3DIWELL Farm Manager — проверка сценария обучения интерфейсу

Этот файл ничего не меняет в приложении. Он только читает:
  - web/composables/tourSteps.js
  - web/app.js
  - web/index.html

Проверяет:
  - уникальность id шагов;
  - что короткий тур ссылается только на существующие шаги;
  - что scene/group/card входят в разрешённые значения;
  - что для каждой группы есть название раздела;
  - что селекторы подсветки можно найти в index.html;
  - что для title/text/more есть русский перевод в словаре RU.
============================================================================
*/

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webDir = path.resolve(__dirname, '..');
const appJsPath = path.join(webDir, 'app.js');
const indexHtmlPath = path.join(webDir, 'index.html');
const tourModulePath = path.join(webDir, 'composables', 'tourSteps.js');

const allowedScenes = new Set(['diag', 'print', 'load', 'project', 'attach', 'slice', 'reveal']);
const allowedGroups = new Set(['basics', 'settings', 'printers', 'projects', 'quick_tasks', 'alerts', 'finish']);
const allowedCards = new Set(['below', 'above', 'tr', 'br', 'tl', 'bl', 'left', 'right', 'top', 'bottom']);
const allowedViews = new Set(['grid', 'list']);

const errors = [];
const warnings = [];

function addError(message) {
  errors.push(message);
}

function addWarning(message) {
  warnings.push(message);
}

function readText(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch (err) {
    addError(`Не удалось прочитать файл: ${filePath}\n  ${err.message}`);
    return '';
  }
}

function findMatchingBrace(source, startIndex) {
  let depth = 0;
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let i = startIndex; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];

    if (lineComment) {
      if (ch === '\n' || ch === '\r') lineComment = false;
      continue;
    }

    if (blockComment) {
      if (ch === '*' && next === '/') {
        blockComment = false;
        i += 1;
      }
      continue;
    }

    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (ch === '\\') {
        escaped = true;
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }

    if (ch === '/' && next === '/') {
      lineComment = true;
      i += 1;
      continue;
    }

    if (ch === '/' && next === '*') {
      blockComment = true;
      i += 1;
      continue;
    }

    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
      continue;
    }

    if (ch === '{') depth += 1;
    if (ch === '}') {
      depth -= 1;
      if (depth === 0) return i;
    }
  }

  return -1;
}

function evaluateObjectLiteral(objectLiteral, sourceName) {
  try {
    return Function(`"use strict"; return (${objectLiteral});`)();
  } catch (err) {
    addError(`Не удалось разобрать JS-объект переводов из ${sourceName}\n  ${err.message}`);
    return {};
  }
}

function extractObjectAfterMarker(source, marker, fromIndex = 0) {
  const markerIndex = source.indexOf(marker, fromIndex);
  if (markerIndex < 0) return null;

  const start = source.indexOf('{', markerIndex);
  if (start < 0) return null;

  const end = findMatchingBrace(source, start);
  if (end < 0) return null;

  return { start, end, literal: source.slice(start, end + 1), nextIndex: end + 1 };
}

function extractRuDictionary(appJs) {
  const base = extractObjectAfterMarker(appJs, 'const RU =');
  const ru = {};

  if (!base) {
    addError('В web/app.js не найден словарь `const RU = {...}`.');
    return ru;
  }

  Object.assign(ru, evaluateObjectLiteral(base.literal, 'const RU'));

  let searchFrom = 0;
  while (true) {
    const block = extractObjectAfterMarker(appJs, 'Object.assign(RU', searchFrom);
    if (!block) break;
    Object.assign(ru, evaluateObjectLiteral(block.literal, 'Object.assign(RU, ...)'));
    searchFrom = block.nextIndex;
  }

  return ru;
}

function selectorExistsInTemplate(selector, indexHtml) {
  if (!selector || typeof selector !== 'string') return false;

  const dataTourMatch = selector.match(/^\[data-tour=["']([^"']+)["']\]$/);
  if (dataTourMatch) {
    const value = dataTourMatch[1];
    return indexHtml.includes(`data-tour="${value}"`) || indexHtml.includes(`data-tour='${value}'`);
  }

  const idMatch = selector.match(/^#([A-Za-z0-9_-]+)$/);
  if (idMatch) {
    const value = idMatch[1];
    // В Vue-шаблоне демо-id часто задаются через :id="... 'tour-demo-...' ...",
    // поэтому достаточно найти сам id как строку в index.html.
    return indexHtml.includes(value);
  }

  // Для сложных CSS-селекторов делаем мягкую проверку: если селектор целиком
  // встречается в шаблоне, считаем его найденным. Иначе предупреждаем, а не падаем.
  return indexHtml.includes(selector);
}

function formatStep(step, index) {
  return `${index + 1}. ${step?.id || '(без id)'}`;
}

async function main() {
  const appJs = readText(appJsPath);
  const indexHtml = readText(indexHtmlPath);
  const ru = extractRuDictionary(appJs);

  let tourModule;
  try {
    tourModule = await import(pathToFileURL(tourModulePath).href + `?v=${Date.now()}`);
  } catch (err) {
    addError(`Не удалось импортировать ${tourModulePath}\n  ${err.message}`);
    tourModule = {};
  }

  const tourSteps = Array.isArray(tourModule.tourSteps) ? tourModule.tourSteps : [];
  const quickTourSteps = Array.isArray(tourModule.quickTourSteps) ? tourModule.quickTourSteps : [];
  const quickTourStepIds = Array.isArray(tourModule.quickTourStepIds) ? tourModule.quickTourStepIds : [];
  const tourGroupLabels = tourModule.tourGroupLabels && typeof tourModule.tourGroupLabels === 'object' ? tourModule.tourGroupLabels : {};
  const tourGroupOrder = Array.isArray(tourModule.tourGroupOrder) ? tourModule.tourGroupOrder : [];

  if (!tourSteps.length) addError('Полный тур `tourSteps` пустой или не экспортируется.');
  if (!quickTourSteps.length) addError('Короткий тур `quickTourSteps` пустой или не экспортируется.');
  if (!quickTourStepIds.length) addError('Список `quickTourStepIds` пустой или не экспортируется.');
  if (!Object.keys(tourGroupLabels).length) addError('Список названий разделов `tourGroupLabels` пустой или не экспортируется.');

  const ids = new Map();
  const fullIds = new Set();

  tourSteps.forEach((step, index) => {
    const label = formatStep(step, index);

    for (const field of ['id', 'group', 'sel', 'title', 'text']) {
      if (!step[field]) addError(`${label}: отсутствует обязательное поле \`${field}\`.`);
    }

    if (step.id) {
      if (ids.has(step.id)) {
        addError(`${label}: дублируется id \`${step.id}\` — уже был в шаге ${ids.get(step.id) + 1}.`);
      }
      ids.set(step.id, index);
      fullIds.add(step.id);
    }

    if (step.group && !allowedGroups.has(step.group)) {
      addError(`${label}: неизвестная группа \`${step.group}\`.`);
    }

    if (step.group && allowedGroups.has(step.group) && !tourGroupLabels[step.group]) {
      addError(`${label}: для группы \`${step.group}\` нет названия в tourGroupLabels.`);
    }

    if (step.scene && !allowedScenes.has(step.scene)) {
      addError(`${label}: неизвестная demo-сцена \`${step.scene}\`.`);
    }

    if (step.card && !allowedCards.has(step.card)) {
      addError(`${label}: неизвестная позиция карточки \`${step.card}\`.`);
    }

    if (step.view && !allowedViews.has(step.view)) {
      addError(`${label}: неизвестный режим вида принтеров \`${step.view}\`.`);
    }

    if (step.sel && !selectorExistsInTemplate(step.sel, indexHtml)) {
      addError(`${label}: селектор \`${step.sel}\` не найден в web/index.html.`);
    }

    for (const key of ['title', 'text', 'more']) {
      const value = step[key];
      if (value && ru[value] === undefined) {
        addError(`${label}: нет русского перевода для ${key}: \`${value}\`.`);
      }
    }
  });

  quickTourStepIds.forEach((id, index) => {
    if (!fullIds.has(id)) {
      addError(`quickTourStepIds[${index}]: id \`${id}\` отсутствует в полном туре.`);
    }
  });

  const quickExportIds = quickTourSteps.map((step) => step?.id).filter(Boolean);
  const expectedQuickIds = quickTourStepIds.filter((id) => fullIds.has(id));
  if (quickExportIds.join('|') !== expectedQuickIds.join('|')) {
    addError('Экспорт `quickTourSteps` не совпадает с порядком `quickTourStepIds`.');
  }

  const sceneUsage = new Map();
  const groupUsage = new Map();
  for (const step of tourSteps) {
    if (step.scene) sceneUsage.set(step.scene, (sceneUsage.get(step.scene) || 0) + 1);
    if (step.group) groupUsage.set(step.group, (groupUsage.get(step.group) || 0) + 1);
  }

  for (const requiredGroup of ['basics', 'printers', 'projects', 'quick_tasks', 'finish']) {
    if (!groupUsage.has(requiredGroup)) {
      addWarning(`В полном туре нет шагов группы \`${requiredGroup}\`.`);
    }
  }

  for (const group of Object.keys(tourGroupLabels)) {
    if (!allowedGroups.has(group)) addError(`tourGroupLabels: неизвестная группа \`${group}\`.`);
    if (ru[tourGroupLabels[group]] === undefined) addError(`tourGroupLabels: нет русского перевода названия раздела \`${tourGroupLabels[group]}\`.`);
  }

  for (const group of tourGroupOrder) {
    if (!tourGroupLabels[group]) addWarning(`tourGroupOrder: группа \`${group}\` есть в порядке, но отсутствует в tourGroupLabels.`);
  }

  console.log('3DIWELL Farm Manager — проверка обучения');
  console.log('------------------------------------------------');
  console.log(`Полный тур: ${tourSteps.length} шагов`);
  console.log(`Короткий тур: ${quickTourSteps.length} шагов`);
  console.log(`Переводов RU загружено: ${Object.keys(ru).length}`);
  console.log('Группы:', [...groupUsage.entries()].map(([k, v]) => `${k}=${v}`).join(', ') || 'нет');
  console.log('Демо-сцены:', [...sceneUsage.entries()].map(([k, v]) => `${k}=${v}`).join(', ') || 'нет');
  console.log('Названия разделов:', Object.keys(tourGroupLabels).length);

  if (warnings.length) {
    console.log('\nПредупреждения:');
    warnings.forEach((message) => console.log(`  [WARN] ${message}`));
  }

  if (errors.length) {
    console.log('\nОшибки:');
    errors.forEach((message) => console.log(`  [ERROR] ${message}`));
    console.log('\nРезультат: обучение требует исправления.');
    process.exitCode = 1;
    return;
  }

  console.log('\nРезультат: OK. Обучение прошло автоматическую проверку.');
}

main().catch((err) => {
  console.error('Критическая ошибка проверки обучения:');
  console.error(err);
  process.exitCode = 1;
});
